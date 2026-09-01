"""Survey data for MERMAID projects.

Ports mermaidr's ``mermaid_get_project_data``.  A survey ``method`` and an
aggregation ``data`` level together name a CSV endpoint underneath a project::

    projects/{project_id}/{method_slug}/{data_slug}/csv

:func:`construct_endpoints` builds that mapping for every method MERMAID
publishes and is pure, so it can be checked without touching the network.
:func:`get_project_data` fetches the resulting endpoints with a bearer token and
parses each response with :func:`pandas.read_csv`.

Every method and level can be fetched.  Bleaching observations are the one
combination that spans two endpoints, so they come back as two named frames --
see :data:`OBSERVATION_KEYS`.

Projects are named the same way as for the other project endpoints -- see
:mod:`datamermaid.project_endpoints`, which owns the coercion and the default
project.
"""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any

import pandas as pd

from .client import MermaidClient, check_limit, client_context
from .project_endpoints import ProjectLike, _resolve_project

__all__ = [
    "DATA_LEVELS",
    "METHODS",
    "OBSERVATION_KEYS",
    "PROJECT_COLUMN",
    "construct_endpoints",
    "get_project_data",
]

#: Method name -> the path segment MERMAID uses for it.  Mirrors the ``switch``
#: in mermaidr's ``construct_endpoint``.
METHOD_SLUGS: dict[str, str] = {
    "fishbelt": "beltfishes",
    "benthiclit": "benthiclits",
    "benthicpit": "benthicpits",
    "benthicpqt": "benthicpqts",
    "habitatcomplexity": "habitatcomplexities",
    "bleaching": "bleachingqcs",
    "macroinvertebrate": "beltinverts",
}

#: Aggregation level -> path segment.  ``observations`` is method-dependent and
#: is resolved by :func:`_observation_slugs` instead.
DATA_SLUGS: dict[str, str | None] = {
    "observations": None,
    "sampleunits": "sampleunits",
    "sampleevents": "sampleevents",
}

#: Methods whose observation endpoint is not ``obstransect{method_slug}``.
#: Bleaching splits its observations across two endpoints.
OBSERVATION_OVERRIDES: dict[str, tuple[str, ...]] = {
    "bleaching": ("obscoloniesbleacheds", "obsquadratbenthicpercents"),
    "habitatcomplexity": ("obshabitatcomplexities",),
}

#: Valid ``method`` values, in the order they are returned.
METHODS: tuple[str, ...] = tuple(METHOD_SLUGS)

#: Valid ``data`` values, in the order they are returned.
DATA_LEVELS: tuple[str, ...] = tuple(DATA_SLUGS)

#: Endpoint segment -> the key its frame gets when an aggregation level spans
#: more than one endpoint.  Only bleaching observations do, and mermaidr names
#: the two halves the same way.
OBSERVATION_KEYS: dict[str, str] = {
    "obscoloniesbleacheds": "colonies_bleached",
    "obsquadratbenthicpercents": "percent_cover",
}

#: Column added to identify the project when several are requested at once.
#: MERMAID's own CSVs already carry a ``project`` column holding the project
#: *name*, so the identifier gets its own column rather than colliding with it.
PROJECT_COLUMN = "project_id"

#: One aggregation level's result: a frame, or -- for bleaching observations --
#: one frame per endpoint, keyed by :data:`OBSERVATION_KEYS`.
LevelData = pd.DataFrame | dict[str, pd.DataFrame]

#: What :func:`get_project_data` returns: a single level's data when one method
#: and one level were asked for, otherwise ``{method: {data: LevelData}}``.
ProjectData = LevelData | dict[str, dict[str, LevelData]]


def _choices(valid: Iterable[str]) -> str:
    return ", ".join(f'"{value}"' for value in valid)


def _resolve_choices(value: Any, valid: tuple[str, ...], argument: str) -> list[str]:
    """Normalise a ``method``/``data`` argument into a list of valid names.

    Accepts a single name, ``"all"``, or an iterable of either.  Mirrors
    mermaidr's ``check_project_data_inputs``: an unknown name raises
    :class:`ValueError` naming every option, before any request is made.
    """
    if value is None or isinstance(value, (str, bytes)):
        given: list[Any] = [value]
    elif isinstance(value, Iterable):
        given = list(value)
    else:
        given = [value]

    resolved: list[str] = []
    for item in given:
        if not isinstance(item, str):
            raise ValueError(
                f'`{argument}` must be one of {_choices(valid)} or "all", '
                f"not {type(item).__name__}."
            )
        names = list(valid) if item == "all" else [item]
        for name in names:
            if name not in valid:
                raise ValueError(
                    f'`{argument}` must be one of {_choices(valid)} or "all". Got "{name}".'
                )
            if name not in resolved:
                resolved.append(name)

    if not resolved:
        raise ValueError(f'`{argument}` must be one of {_choices(valid)} or "all".')

    # Keep the canonical order regardless of how the caller listed them.
    return [name for name in valid if name in resolved]


def _observation_slugs(method: str) -> tuple[str, ...]:
    """Return the observation endpoint segment(s) for ``method``."""
    override = OBSERVATION_OVERRIDES.get(method)
    if override is not None:
        return override
    return (f"obstransect{METHOD_SLUGS[method]}",)


def construct_endpoints(
    methods: Any = "all",
    datas: Any = "all",
) -> dict[str, dict[str, list[str]]]:
    """Map survey methods and aggregation levels onto MERMAID endpoint paths.

    Parameters
    ----------
    methods:
        A method name, ``"all"``, or an iterable of either.  Valid names are
        listed in :data:`METHODS`.
    datas:
        An aggregation level, ``"all"``, or an iterable of either.  Valid
        levels are listed in :data:`DATA_LEVELS`.

    Returns
    -------
    dict
        ``{method: {data: [path, ...]}}``, where each path is relative to a
        project (e.g. ``"beltfishes/obstransectbeltfishes"``).  The value is a
        list because bleaching observations live at two endpoints; every other
        combination yields exactly one.

    Examples
    --------
    >>> construct_endpoints("fishbelt", "observations")
    {'fishbelt': {'observations': ['beltfishes/obstransectbeltfishes']}}
    >>> construct_endpoints("bleaching", "observations")["bleaching"]["observations"]
    ['bleachingqcs/obscoloniesbleacheds', 'bleachingqcs/obsquadratbenthicpercents']
    """
    method_names = _resolve_choices(methods, METHODS, "method")
    data_names = _resolve_choices(datas, DATA_LEVELS, "data")

    endpoints: dict[str, dict[str, list[str]]] = {}
    for method in method_names:
        method_slug = METHOD_SLUGS[method]
        levels: dict[str, list[str]] = {}
        for data in data_names:
            slugs = _observation_slugs(method) if data == "observations" else (DATA_SLUGS[data],)
            levels[data] = [f"{method_slug}/{slug}" for slug in slugs]
        endpoints[method] = levels
    return endpoints


def _concat(frames: list[pd.DataFrame], project_ids: list[str]) -> pd.DataFrame:
    """Stack one frame per project, labelling the rows with the project id."""
    if len(frames) == 1:
        return frames[0]

    labelled = []
    for project_id, frame in zip(project_ids, frames, strict=True):
        frame = frame.copy()
        frame.insert(0, PROJECT_COLUMN, project_id)
        labelled.append(frame)
    return pd.concat(labelled, ignore_index=True)


def _by_endpoint(paths: list[str], frames: list[pd.DataFrame]) -> dict[str, pd.DataFrame]:
    """Name the frames of an aggregation level that spans several endpoints."""
    keyed: dict[str, pd.DataFrame] = {}
    for path, frame in zip(paths, frames, strict=True):
        slug = path.rsplit("/", 1)[-1]
        keyed[OBSERVATION_KEYS.get(slug, slug)] = frame
    return keyed


def get_project_data(
    project: ProjectLike | None = None,
    method: Any = "fishbelt",
    data: Any = "observations",
    limit: int | None = None,
    covariates: bool = False,
    *,
    client: MermaidClient | None = None,
    token: str | None = None,
) -> ProjectData:
    """Get survey data for one or more MERMAID projects.

    Requires a login.  The token comes from ``token``, from the
    ``MERMAID_API_TOKEN`` environment variable, or from the cache written by
    :func:`datamermaid.authenticate`.

    Parameters
    ----------
    project:
        Project(s) to query, in any shape :func:`datamermaid.as_project_ids`
        accepts.  ``None`` uses the default project (see
        :func:`datamermaid.set_default_project`).  Several projects are fetched
        in turn and stacked, with a leading :data:`PROJECT_COLUMN` column naming
        the project each row came from.
    method:
        Survey method: one of :data:`METHODS`, ``"all"``, or a list of those.
    data:
        Aggregation level: one of :data:`DATA_LEVELS`, ``"all"``, or a list of
        those.
    limit:
        Maximum number of rows to return per project.  ``None`` returns every
        row.  These endpoints are not paginated, so the limit is applied by
        truncating the parsed frame.
    covariates:
        Whether to request the site covariates MERMAID derives (``geomorphic
        zone``, ``benthic habitat`` and friends) alongside the survey data.
    client:
        Client to issue the request with.  Defaults to the process-wide client.
    token:
        Access token to use instead of the resolved one.

    Returns
    -------
    pandas.DataFrame or dict
        A single frame when exactly one method and one aggregation level are
        requested.  Otherwise a nested dict, ``{method: {data: DataFrame}}``,
        keyed in the order of :data:`METHODS` and :data:`DATA_LEVELS`.

        Bleaching observations are the exception: they live at two endpoints,
        so that level's value is a ``{"colonies_bleached": DataFrame,
        "percent_cover": DataFrame}`` dict -- the same split mermaidr returns
        as a named list.  It takes the place of a frame wherever one would
        otherwise sit, including inside the nested dict.

    Raises
    ------
    ValueError
        If ``method``, ``data``, or ``limit`` is invalid, or if no project was
        given and no default is set.  Nothing is requested in that case.

    Examples
    --------
    >>> import datamermaid
    >>> datamermaid.get_project_data("abc-123", "fishbelt", "sampleevents")  # doctest: +SKIP
    >>> everything = datamermaid.get_project_data("abc-123", data="all")  # doctest: +SKIP
    >>> everything["fishbelt"]["observations"]  # doctest: +SKIP

    Bleaching observations come back as two frames:

    >>> bleaching = datamermaid.get_project_data(
    ...     "abc-123", "bleaching", "observations"
    ... )  # doctest: +SKIP
    >>> bleaching["colonies_bleached"]  # doctest: +SKIP
    >>> bleaching["percent_cover"]  # doctest: +SKIP
    """
    limit = check_limit(limit)
    endpoints = construct_endpoints(method, data)
    project_ids = _resolve_project(project)

    params = {"covariates": "true"} if covariates else None

    results: dict[str, dict[str, LevelData]] = {}
    with client_context(client, token) as api:
        for method_name, levels in endpoints.items():
            results[method_name] = {}
            for data_name, paths in levels.items():
                frames: list[pd.DataFrame] = []
                for path in paths:
                    per_project = [
                        _fetch(api, project_id, path, params=params, limit=limit)
                        for project_id in project_ids
                    ]
                    frames.append(_concat(per_project, project_ids))
                results[method_name][data_name] = (
                    frames[0] if len(frames) == 1 else _by_endpoint(paths, frames)
                )

    only_method = next(iter(results))
    if len(results) == 1 and len(results[only_method]) == 1:
        return next(iter(results[only_method].values()))
    return results


def _fetch(
    api: MermaidClient,
    project_id: str,
    path: str,
    *,
    params: dict[str, Any] | None,
    limit: int | None,
) -> pd.DataFrame:
    """Fetch and parse one project's CSV for one endpoint."""
    df = api.get_csv(f"projects/{project_id}/{path}/csv", params=params)
    if limit is not None and len(df) > limit:
        df = df.head(limit).reset_index(drop=True)
    return df
