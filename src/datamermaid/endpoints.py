"""Global MERMAID endpoints that need no login.

Everything here is served from the API root (``sites/``, ``fishspecies/``,
``choices/``, ...) and is public, so no token is resolved or sent: an
unauthenticated request returns the same public data whether or not the caller
happens to be signed in.  Project-scoped data lives in
:mod:`datamermaid.project_endpoints` instead.

:func:`get_endpoint` is the generic getter the named functions delegate to, so
pagination and ``limit`` handling live in one place.  It mirrors mermaidr's
``mermaid_get_endpoint``; the named functions mirror ``mermaid_get_sites``,
``mermaid_get_managements``, ``mermaid_get_reference``,
``mermaid_get_summary_sampleevents``, ``get_choices`` and
``mermaid_countries``.
"""

from __future__ import annotations

import warnings
from collections.abc import Sequence
from typing import Any

import pandas as pd

from .client import MermaidClient, check_limit, client_context
from .exceptions import MermaidError
from .project_endpoints import MANAGEMENT_COLUMNS, PROJECT_COLUMN, SITE_COLUMNS
from .utils import records_to_df

__all__ = [
    "KNOWN_ENDPOINTS",
    "REFERENCE_ENDPOINTS",
    "countries",
    "get_choices",
    "get_endpoint",
    "get_managements",
    "get_reference",
    "get_sites",
    "get_summary_sampleevents",
]

#: Reference tables :func:`get_reference` accepts, in mermaidr's order.
REFERENCE_ENDPOINTS = (
    "fishfamilies",
    "fishgenera",
    "fishspecies",
    "benthicattributes",
    "fishgroupings",
)

#: Global endpoints known to answer a plain paginated GET.  :func:`get_endpoint`
#: accepts any string, but warns about one not listed here since a typo would
#: otherwise surface only as an HTTP 404.
KNOWN_ENDPOINTS = frozenset(
    {
        "benthicattributes",
        "choices",
        "fishfamilies",
        "fishgenera",
        "fishgroupings",
        "fishsizes",
        "fishspecies",
        "managements",
        "projects",
        "projecttags",
        "sites",
        "summarysampleevents",
    }
)

#: Name of the choice set :func:`countries` reads.
_COUNTRIES_CHOICE = "countries"


def get_endpoint(
    endpoint: str,
    limit: int | None = None,
    *,
    client: MermaidClient | None = None,
    columns: Sequence[str] | None = None,
    **filters: Any,
) -> pd.DataFrame:
    """Get any global MERMAID endpoint as a :class:`~pandas.DataFrame`.

    This is the escape hatch for endpoints without a dedicated function.  It
    paginates like every other getter and needs no login.

    Parameters
    ----------
    endpoint:
        Endpoint name relative to the API root, e.g. ``"fishsizes"``.  Names
        outside :data:`KNOWN_ENDPOINTS` are still requested, with a
        :class:`UserWarning`, so a new endpoint can be reached before this
        package learns about it.
    limit:
        Maximum number of records to return.  ``None`` (the default) returns
        every record, paginating as needed.
    client:
        Client to issue the request with.  Defaults to the process-wide client.
    columns:
        Columns to keep, in order.  ``None`` keeps everything the API returned.
    **filters:
        Extra query parameters, passed through to the API unchanged.
        ``None`` values are dropped.

    Returns
    -------
    pandas.DataFrame
        One row per record.  List-valued fields are collapsed to
        comma-separated strings, as everywhere in this package; use
        :func:`get_choices` for ``choices/``, whose nested payload is better
        served as a dict of frames.

    Examples
    --------
    >>> import datamermaid
    >>> datamermaid.get_endpoint("fishsizes", limit=10)  # doctest: +SKIP
    """
    limit = check_limit(limit)

    name = endpoint.strip("/")
    if not name:
        raise ValueError("`endpoint` must not be empty.")
    if name not in KNOWN_ENDPOINTS:
        warnings.warn(
            f"`{name}` is not a known MERMAID endpoint; requesting it anyway. "
            f"Known endpoints: {', '.join(sorted(KNOWN_ENDPOINTS))}.",
            UserWarning,
            stacklevel=2,
        )

    params = {key: value for key, value in filters.items() if value is not None}

    with client_context(client) as api:
        records = api.get(name, limit=limit, params=params, require_auth=False)

    return records_to_df(records, columns=columns)


def get_sites(
    limit: int | None = None,
    *,
    client: MermaidClient | None = None,
) -> pd.DataFrame:
    """Get every public MERMAID site.

    Parameters
    ----------
    limit:
        Maximum number of sites to return.  ``None`` returns every site.
    client:
        Client to issue the request with.  Defaults to the process-wide client.

    Returns
    -------
    pandas.DataFrame
        One row per site, laid out like :func:`datamermaid.get_project_sites`:
        a leading ``project`` column followed by
        :data:`~datamermaid.project_endpoints.SITE_COLUMNS`.

    Examples
    --------
    >>> import datamermaid
    >>> datamermaid.get_sites(limit=5)  # doctest: +SKIP
    """
    return get_endpoint("sites", limit, client=client, columns=(PROJECT_COLUMN, *SITE_COLUMNS))


def get_managements(
    limit: int | None = None,
    *,
    client: MermaidClient | None = None,
) -> pd.DataFrame:
    """Get every public MERMAID management regime.

    Parameters
    ----------
    limit:
        Maximum number of regimes to return.  ``None`` returns every regime.
    client:
        Client to issue the request with.  Defaults to the process-wide client.

    Returns
    -------
    pandas.DataFrame
        One row per regime, laid out like
        :func:`datamermaid.get_project_managements`: a leading ``project``
        column followed by
        :data:`~datamermaid.project_endpoints.MANAGEMENT_COLUMNS`.

    Examples
    --------
    >>> import datamermaid
    >>> datamermaid.get_managements(limit=5)  # doctest: +SKIP
    """
    return get_endpoint(
        "managements",
        limit,
        client=client,
        columns=(PROJECT_COLUMN, *MANAGEMENT_COLUMNS),
    )


def get_reference(
    reference: str,
    limit: int | None = None,
    *,
    client: MermaidClient | None = None,
) -> pd.DataFrame:
    """Get one of MERMAID's reference tables.

    Parameters
    ----------
    reference:
        Which table: one of :data:`REFERENCE_ENDPOINTS` (``"fishfamilies"``,
        ``"fishgenera"``, ``"fishspecies"``, ``"benthicattributes"`` or
        ``"fishgroupings"``).
    limit:
        Maximum number of records to return.  ``None`` returns the whole table.
    client:
        Client to issue the request with.  Defaults to the process-wide client.

    Returns
    -------
    pandas.DataFrame
        One row per record, with every field the API returned.  Related
        records (a species' genus, an attribute's parent) are left as ids;
        join against the other tables to resolve them.

    Raises
    ------
    ValueError
        If ``reference`` is not one of :data:`REFERENCE_ENDPOINTS`.

    Examples
    --------
    >>> import datamermaid
    >>> datamermaid.get_reference("fishfamilies")  # doctest: +SKIP
    """
    if reference not in REFERENCE_ENDPOINTS:
        options = ", ".join(f'"{name}"' for name in REFERENCE_ENDPOINTS)
        raise ValueError(f"`reference` must be one of {options}, not {reference!r}.")

    return get_endpoint(reference, limit, client=client)


def get_summary_sampleevents(
    limit: int | None = None,
    *,
    client: MermaidClient | None = None,
) -> pd.DataFrame:
    """Get the public summary of every MERMAID sample event.

    Each row aggregates the surveys done at one site on one date across every
    method, along with the project, site and management regime it belongs to.
    The endpoint is large; pass a ``limit`` to sample it.

    Parameters
    ----------
    limit:
        Maximum number of sample events to return.  ``None`` returns them all.
    client:
        Client to issue the request with.  Defaults to the process-wide client.

    Returns
    -------
    pandas.DataFrame
        One row per sample event, with every field the API returned.

    Examples
    --------
    >>> import datamermaid
    >>> datamermaid.get_summary_sampleevents(limit=100)  # doctest: +SKIP
    """
    return get_endpoint("summarysampleevents", limit, client=client)


def get_choices(*, client: MermaidClient | None = None) -> dict[str, pd.DataFrame]:
    """Get MERMAID's controlled vocabularies (reef types, countries, ...).

    ``choices/`` is the one global endpoint that is not paginated: it answers
    with a bare list of ``{"name": ..., "data": [...]}`` objects, one per
    vocabulary.  Each is returned as its own frame here, so
    ``get_choices()["reeftypes"]`` is a table of reef types.

    Parameters
    ----------
    client:
        Client to issue the request with.  Defaults to the process-wide client.

    Returns
    -------
    dict[str, pandas.DataFrame]
        Keyed by vocabulary name, in the order the API listed them.  Each frame
        has one row per allowed value, typically with ``id`` and ``name``
        columns plus whatever else the API attaches (``updated_on``, region
        ids, ...).

    Examples
    --------
    >>> import datamermaid
    >>> choices = datamermaid.get_choices()  # doctest: +SKIP
    >>> choices["reeftypes"]  # doctest: +SKIP
    """
    with client_context(client) as api:
        records = api.get("choices", require_auth=False)

    choices: dict[str, pd.DataFrame] = {}
    for record in records:
        if not isinstance(record, dict) or "name" not in record:
            raise MermaidError(
                "Unexpected `choices/` payload: expected a list of {name, data} objects, "
                f"got {type(record).__name__}."
            )
        choices[str(record["name"])] = records_to_df(record.get("data") or [])
    return choices


def countries(*, client: MermaidClient | None = None) -> list[str]:
    """Get the names of every country MERMAID knows about.

    Read from the ``countries`` vocabulary of :func:`get_choices`, like
    mermaidr's ``mermaid_countries()``.  Useful for finding the spelling
    :func:`datamermaid.search_projects` will match on.

    Parameters
    ----------
    client:
        Client to issue the request with.  Defaults to the process-wide client.

    Returns
    -------
    list[str]
        Country names, sorted alphabetically.

    Raises
    ------
    MermaidError
        If the API's choices no longer include a ``countries`` vocabulary with
        a ``name`` column.

    Examples
    --------
    >>> import datamermaid
    >>> datamermaid.countries()[:3]  # doctest: +SKIP
    ['Afghanistan', 'Albania', 'Algeria']
    """
    choices = get_choices(client=client)

    table = choices.get(_COUNTRIES_CHOICE)
    if table is None or "name" not in table.columns:
        available = ", ".join(choices) or "none"
        raise MermaidError(
            f"The MERMAID `choices/` endpoint returned no `{_COUNTRIES_CHOICE}` vocabulary "
            f"with a `name` column. Available vocabularies: {available}."
        )

    names = table["name"].dropna().astype(str)
    return sorted(names.tolist())
