"""Project-scoped MERMAID endpoints (``projects/{project_id}/{endpoint}/``).

Every endpoint here is authenticated: the API only returns a project's sites,
managements and data to members of that project, so a token is required.  It is
resolved the same way as everywhere else in the package -- an explicit
``token``, then ``MERMAID_API_TOKEN``, then the cache written by
:func:`datamermaid.authenticate` -- and :class:`AuthenticationError` is raised
before any request when none is available.

The functions accept a project in whatever shape the caller happens to have:
an id, several ids, a single project record, or the
:class:`~pandas.DataFrame` returned by :func:`datamermaid.get_projects`.
:func:`as_project_ids` does that coercion, mirroring mermaidr's ``as_id`` and
``check_id_in_df``.  A default project can be set once with
:func:`set_default_project` and then omitted from every call, as in mermaidr's
``mermaid_set_default_project``.
"""

from __future__ import annotations

import os
import threading
from collections.abc import Iterable, Mapping, Sequence
from contextlib import contextmanager
from typing import Any

import pandas as pd

from .client import MermaidClient, check_limit, client_context
from .utils import records_to_df

__all__ = [
    "DEFAULT_PROJECT_ENV_VAR",
    "MANAGEMENT_COLUMNS",
    "PROJECT_COLUMN",
    "SITE_COLUMNS",
    "as_project_ids",
    "get_default_project",
    "get_project_endpoint",
    "get_project_managements",
    "get_project_sites",
    "set_default_project",
]

#: Environment variable holding the default project id(s), comma separated.
#: Read by :func:`get_default_project` and written by
#: :func:`set_default_project`, so a default survives into subprocesses.
DEFAULT_PROJECT_ENV_VAR = "MERMAID_DEFAULT_PROJECT"

#: Name of the column identifying which project a row was fetched for.
PROJECT_COLUMN = "project"

#: Columns returned by :func:`get_project_sites`, in order.  As everywhere in
#: this package, requested columns the API did not return are skipped.
SITE_COLUMNS = (
    "id",
    "name",
    "notes",
    "country",
    "reef_type",
    "reef_zone",
    "exposure",
    "location",
    "predecessor",
    "created_on",
    "updated_on",
)

#: Columns returned by :func:`get_project_managements`, in order.
MANAGEMENT_COLUMNS = (
    "id",
    "name",
    "name_secondary",
    "notes",
    "est_year",
    "size",
    "parties",
    "compliance",
    "open_access",
    "no_take",
    "access_restriction",
    "periodic_closure",
    "size_limits",
    "gear_restriction",
    "species_restriction",
    "predecessor",
    "created_on",
    "updated_on",
)

#: Anything :func:`as_project_ids` accepts.
ProjectLike = str | Mapping[str, Any] | pd.DataFrame | Iterable[Any]

_ACCEPTED_SHAPES = (
    "a project id, an iterable of ids, a project record (dict with an `id` "
    "key), or a data frame with an `id` column (e.g. the output of "
    "`get_projects()`)"
)


def as_project_ids(project: ProjectLike) -> list[str]:
    """Coerce ``project`` into a list of project ids.

    Accepts an id, an iterable of ids, a mapping with an ``id`` key, a
    :class:`~pandas.DataFrame` or :class:`~pandas.Series` carrying ids, and any
    nesting of those.  Duplicates are dropped, keeping first-seen order.

    Raises
    ------
    ValueError
        If ``project`` holds no usable id — including a frame without an ``id``
        column and an empty input, both of which are caller mistakes rather
        than requests for zero projects — or if an id contains ``/``, which
        would rewrite the request path.
    """
    ids = _collect_ids(project)
    if not ids:
        raise ValueError(f"`project` contains no project id; pass {_ACCEPTED_SHAPES}.")

    # dict.fromkeys de-duplicates while preserving insertion order.
    return list(dict.fromkeys(ids))


def _collect_ids(project: Any) -> list[str]:
    """Recursively pull ids out of ``project``; ``[]`` when there are none."""
    if isinstance(project, pd.DataFrame):
        if "id" not in project.columns:
            raise ValueError(
                "`project` data frame has no `id` column; pass a frame from "
                "`get_projects()` or the project id itself."
            )
        return _collect_ids(list(project["id"]))

    if isinstance(project, str):
        stripped = project.strip()
        if not stripped:
            return []
        if "/" in stripped:
            # Ids are interpolated into `projects/{id}/{endpoint}/`, so a slash
            # would silently rewrite the request path.
            raise ValueError(f"`{stripped}` is not a valid project id: ids cannot contain `/`.")
        return [stripped]

    if isinstance(project, Mapping):
        if "id" not in project:
            raise ValueError("`project` record has no `id` key.")
        return _collect_ids(project["id"])

    if project is None or isinstance(project, (bytes, bytearray)):
        raise ValueError(f"`project` must be {_ACCEPTED_SHAPES}, not {type(project).__name__}.")

    if isinstance(project, Iterable):
        ids: list[str] = []
        for item in project:
            if item is None or (isinstance(item, float) and pd.isna(item)):
                continue  # Skip missing ids rather than sending "nan" upstream.
            ids.extend(_collect_ids(item))
        return ids

    raise ValueError(f"`project` must be {_ACCEPTED_SHAPES}, not {type(project).__name__}.")


# -- default project -------------------------------------------------------

_default_project: list[str] | None = None
_default_project_lock = threading.Lock()


def set_default_project(project: ProjectLike | None) -> None:
    """Set the project used when a project function is called without one.

    The ids are also written to :data:`DEFAULT_PROJECT_ENV_VAR` so that
    subprocesses inherit the default.  Pass ``None`` to clear both.
    """
    global _default_project

    if project is None:
        with _default_project_lock:
            _default_project = None
            os.environ.pop(DEFAULT_PROJECT_ENV_VAR, None)
        return

    ids = as_project_ids(project)
    with _default_project_lock:
        _default_project = ids
        os.environ[DEFAULT_PROJECT_ENV_VAR] = ",".join(ids)


def get_default_project() -> list[str] | None:
    """Return the default project ids, or ``None`` if no default is set.

    A default set in this process wins over
    :data:`DEFAULT_PROJECT_ENV_VAR`, which is used as a fallback so the
    variable can be exported before the interpreter starts.
    """
    with _default_project_lock:
        if _default_project is not None:
            return list(_default_project)

    raw = os.environ.get(DEFAULT_PROJECT_ENV_VAR)
    if not raw:
        return None

    ids = [part.strip() for part in raw.split(",") if part.strip()]
    return ids or None


def _resolve_project(project: ProjectLike | None) -> list[str]:
    """Return ids for ``project``, falling back to the default project."""
    if project is not None:
        return as_project_ids(project)

    default = get_default_project()
    if default:
        # Re-validate: a default read from the environment has not been through
        # `as_project_ids`.
        return as_project_ids(default)

    raise ValueError(
        "No project given and no default project set. Pass `project=`, or call "
        f"`set_default_project()` (or set ${DEFAULT_PROJECT_ENV_VAR})."
    )


# -- requests --------------------------------------------------------------


@contextmanager
def _authenticated_client(client: MermaidClient | None, token: str | None):
    """Yield the client to use for a project request.

    Every project id in a call is served by the same client, so one connection
    pool covers the whole request.  The token itself is resolved per request by
    :mod:`datamermaid.auth`, so a client built here needs none of its own.
    """
    if client is not None and token is not None:
        raise ValueError("Pass either `client` or `token`, not both.")
    with client_context(client, token) as api:
        yield api


def get_project_endpoint(
    project: ProjectLike | None,
    endpoint: str,
    limit: int | None = None,
    *,
    client: MermaidClient | None = None,
    token: str | None = None,
    columns: Sequence[str] | None = None,
    **filters: Any,
) -> pd.DataFrame:
    """Get ``projects/{project_id}/{endpoint}/`` for one or more projects.

    Parameters
    ----------
    project:
        Project(s) to query, in any shape :func:`as_project_ids` accepts.
        ``None`` uses the default project (see :func:`set_default_project`).
    endpoint:
        Project-scoped endpoint name, e.g. ``"sites"``.
    limit:
        Maximum number of records **per project**, matching mermaidr; the
        concatenated result can therefore hold up to
        ``limit * len(projects)`` rows.  ``None`` returns everything.
    client:
        Authenticated client to issue the requests with.  Defaults to the
        process-wide client.
    token:
        Bearer token to build a throwaway authenticated client from, as a
        shorthand for constructing a :class:`~datamermaid.MermaidClient`.
        Mutually exclusive with ``client``.  Omit it to use the token from
        ``MERMAID_API_TOKEN`` or from the cache written by
        :func:`datamermaid.authenticate`.
    columns:
        Columns to keep, in order.  ``None`` keeps everything the API returned.
    **filters:
        Extra query parameters, passed through to the API unchanged.
        ``None`` values are dropped.

    Returns
    -------
    pandas.DataFrame
        The records for every requested project, concatenated, with a leading
        :data:`PROJECT_COLUMN` column naming the project each row came from.

    Raises
    ------
    AuthenticationError
        If no access token can be resolved; no request is made.
    """
    limit = check_limit(limit)
    project_ids = _resolve_project(project)

    params = {key: value for key, value in filters.items() if value is not None}
    selected = None if columns is None else [c for c in columns if c != PROJECT_COLUMN]

    frames: list[pd.DataFrame] = []
    with _authenticated_client(client, token) as api:
        for project_id in project_ids:
            records = api.get(
                f"projects/{project_id}/{endpoint}",
                limit=limit,
                params=params,
                require_auth=True,
            )
            frame = records_to_df(records, columns=selected)
            # Records may carry their own `project` field; the id actually
            # requested is the one that identifies the row.
            if PROJECT_COLUMN in frame.columns:
                frame = frame.drop(columns=[PROJECT_COLUMN])
            frame.insert(0, PROJECT_COLUMN, project_id)
            frames.append(frame)

    return _concat(frames, columns=selected)


def _concat(frames: Sequence[pd.DataFrame], *, columns: Sequence[str] | None) -> pd.DataFrame:
    """Concatenate per-project frames, tolerating empty results."""
    populated = [frame for frame in frames if not frame.empty]

    if not populated:
        # Keep the requested schema visible even when nothing came back.
        return pd.DataFrame(columns=[PROJECT_COLUMN, *(columns or ())])
    if len(populated) == 1:
        result = populated[0]
    else:
        result = pd.concat(populated, ignore_index=True)

    if columns is not None:
        # Projects can return different field subsets, so concatenating orders
        # columns by first appearance; restore the requested order over every
        # column that showed up somewhere.
        present = [column for column in columns if column in result.columns]
        result = result[[PROJECT_COLUMN, *present]]

    return result


def get_project_sites(
    project: ProjectLike | None = None,
    limit: int | None = None,
    *,
    client: MermaidClient | None = None,
    token: str | None = None,
) -> pd.DataFrame:
    """Get the sites of one or more MERMAID projects.

    See :func:`get_project_endpoint` for the parameters; the columns are
    :data:`SITE_COLUMNS`, preceded by :data:`PROJECT_COLUMN`.

    Examples
    --------
    >>> import datamermaid
    >>> datamermaid.get_project_sites("00673bec-...", token="...")  # doctest: +SKIP
    """
    return get_project_endpoint(
        project,
        "sites",
        limit,
        client=client,
        token=token,
        columns=SITE_COLUMNS,
    )


def get_project_managements(
    project: ProjectLike | None = None,
    limit: int | None = None,
    *,
    client: MermaidClient | None = None,
    token: str | None = None,
) -> pd.DataFrame:
    """Get the management regimes of one or more MERMAID projects.

    See :func:`get_project_endpoint` for the parameters; the columns are
    :data:`MANAGEMENT_COLUMNS`, preceded by :data:`PROJECT_COLUMN`.
    """
    return get_project_endpoint(
        project,
        "managements",
        limit,
        client=client,
        token=token,
        columns=MANAGEMENT_COLUMNS,
    )
