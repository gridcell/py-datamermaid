"""The MERMAID ``projects`` endpoint."""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any

import pandas as pd

from .client import MermaidClient, check_limit, client_context
from .utils import records_to_df

__all__ = [
    "PROJECT_COLUMNS",
    "PROJECT_STATUS_OPEN",
    "get_my_projects",
    "get_projects",
    "search_my_projects",
    "search_projects",
]

#: Status code for a real (non-test) project.  mermaidr filters on this
#: server-side to exclude test projects.
PROJECT_STATUS_OPEN = 90

#: Columns returned by :func:`get_projects`, in order.  Mirrors mermaidr's
#: ``projects_columns``.  Columns missing from the API response are skipped
#: rather than raising.
PROJECT_COLUMNS = (
    "id",
    "name",
    "countries",
    "num_sites",
    "num_active_sample_units",
    "num_sample_units",
    "tags",
    "project_admins",
    "suggested_citation",
    "bbox",
    "notes",
    "status",
    "data_policy_beltfish",
    "data_policy_benthiclit",
    "data_policy_benthicpit",
    "data_policy_benthicpqt",
    "data_policy_habitatcomplexity",
    "data_policy_bleachingqc",
    "data_policy_macroinvertebrate",
    "created_on",
    "updated_on",
)


def _as_strings(value: Any) -> list[str]:
    """Flatten a MERMAID field into a list of comparable strings.

    Fields such as ``countries`` and ``tags`` come back as lists, lists of
    ``{"id": ..., "name": ...}`` objects, or comma-separated strings depending
    on the endpoint.
    """
    if value is None:
        return []
    if isinstance(value, str):
        return [part.strip() for part in value.split(",") if part.strip()]
    if isinstance(value, dict):
        return _as_strings(value.get("name", value.get("id")))
    if isinstance(value, Iterable):
        return [item for entry in value for item in _as_strings(entry)]
    return [str(value)]


def _contains(haystack: str, needle: str) -> bool:
    return needle.casefold() in haystack.casefold()


def _matches_any(values: Iterable[str], needle: str) -> bool:
    return any(_contains(value, needle) for value in values)


def _filter_projects(
    records: Iterable[dict[str, Any]],
    *,
    name: str | None = None,
    country: str | None = None,
    tag: str | None = None,
) -> list[dict[str, Any]]:
    """Filter records by case-insensitive substring match, like mermaidr."""
    matched: list[dict[str, Any]] = []
    for record in records:
        if name is not None and not _contains(str(record.get("name") or ""), name):
            continue
        if country is not None:
            countries = _as_strings(record.get("countries", record.get("country")))
            if not _matches_any(countries, country):
                continue
        if tag is not None and not _matches_any(_as_strings(record.get("tags")), tag):
            continue
        matched.append(record)
    return matched


def _fetch_projects(
    *,
    require_auth: bool,
    include_test_projects: bool,
    name: str | None = None,
    country: str | None = None,
    tag: str | None = None,
    limit: int | None = None,
    client: MermaidClient | None = None,
    token: str | None = None,
) -> pd.DataFrame:
    """Fetch, filter, and tidy the ``projects`` endpoint.

    Name, country, and tag matching happens here rather than server-side, so a
    search has to read every project before ``limit`` can be applied.
    """
    # A search sends no limit of its own, so validate it before any request.
    limit = check_limit(limit)
    searching = any(value is not None for value in (name, country, tag))

    with client_context(client, token) as api:
        params: dict[str, object] = {}
        if not include_test_projects:
            params["status"] = PROJECT_STATUS_OPEN
        if not require_auth and api.token is None:
            # Unauthenticated callers only see their own projects without this.
            params["showall"] = "true"

        records = api.get(
            "projects",
            limit=None if searching else limit,
            params=params,
            require_auth=require_auth,
        )

    if searching:
        records = _filter_projects(records, name=name, country=country, tag=tag)
        if limit is not None:
            del records[limit:]

    return records_to_df(records, columns=PROJECT_COLUMNS)


def get_projects(
    limit: int | None = None,
    include_test_projects: bool = False,
    *,
    client: MermaidClient | None = None,
) -> pd.DataFrame:
    """Get MERMAID projects.

    Parameters
    ----------
    limit:
        Maximum number of projects to return.  ``None`` (the default) returns
        every project, paginating as needed.
    include_test_projects:
        Whether to include test projects.  Defaults to ``False``, which filters
        the request to projects with status
        :data:`PROJECT_STATUS_OPEN` server-side.
    client:
        Client to issue the request with.  Defaults to the process-wide client.

    Returns
    -------
    pandas.DataFrame
        One row per project, with the columns in :data:`PROJECT_COLUMNS` that
        the API returned.

    Examples
    --------
    >>> import datamermaid
    >>> datamermaid.get_projects(limit=5)  # doctest: +SKIP
    """
    return _fetch_projects(
        require_auth=False,
        include_test_projects=include_test_projects,
        limit=limit,
        client=client,
    )


def search_projects(
    name: str | None = None,
    country: str | None = None,
    tag: str | None = None,
    limit: int | None = None,
    include_test_projects: bool = False,
    *,
    client: MermaidClient | None = None,
) -> pd.DataFrame:
    """Get public MERMAID projects matching a name, country, or tag.

    Every argument is an optional case-insensitive substring match, applied
    after the projects are fetched (the API has no search parameter).  Omitting
    all three is the same as calling :func:`get_projects`.

    Parameters
    ----------
    name:
        Substring of the project name.
    country:
        Substring of any of the project's countries.
    tag:
        Substring of any of the project's tags.
    limit:
        Maximum number of matching projects to return.
    include_test_projects:
        Whether to include test projects.
    client:
        Client to issue the request with.  Defaults to the process-wide client.

    Returns
    -------
    pandas.DataFrame
        One row per matching project, with the columns in
        :data:`PROJECT_COLUMNS` that the API returned.

    Examples
    --------
    >>> import datamermaid
    >>> datamermaid.search_projects(country="Fiji")  # doctest: +SKIP
    """
    return _fetch_projects(
        require_auth=False,
        include_test_projects=include_test_projects,
        name=name,
        country=country,
        tag=tag,
        limit=limit,
        client=client,
    )


def get_my_projects(
    limit: int | None = None,
    include_test_projects: bool = False,
    *,
    client: MermaidClient | None = None,
    token: str | None = None,
) -> pd.DataFrame:
    """Get the MERMAID projects the signed-in user belongs to.

    Requires a login.  The token comes from ``token``, from the
    ``MERMAID_API_TOKEN`` environment variable, or from the cache written by
    :func:`datamermaid.authenticate`.

    Parameters
    ----------
    limit:
        Maximum number of projects to return.  ``None`` returns every project.
    include_test_projects:
        Whether to include test projects.
    client:
        Client to issue the request with.  Defaults to the process-wide client.
    token:
        Access token to use instead of the resolved one.

    Returns
    -------
    pandas.DataFrame
        One row per project, with the columns in :data:`PROJECT_COLUMNS` that
        the API returned.

    Examples
    --------
    >>> import datamermaid
    >>> datamermaid.get_my_projects()  # doctest: +SKIP
    """
    return _fetch_projects(
        require_auth=True,
        include_test_projects=include_test_projects,
        limit=limit,
        client=client,
        token=token,
    )


def search_my_projects(
    name: str | None = None,
    country: str | None = None,
    tag: str | None = None,
    limit: int | None = None,
    include_test_projects: bool = False,
    *,
    client: MermaidClient | None = None,
    token: str | None = None,
) -> pd.DataFrame:
    """Get the signed-in user's projects matching a name, country, or tag.

    The arguments match :func:`search_projects`; the request is authenticated
    like :func:`get_my_projects`.

    Returns
    -------
    pandas.DataFrame
        One row per matching project, with the columns in
        :data:`PROJECT_COLUMNS` that the API returned.

    Examples
    --------
    >>> import datamermaid
    >>> datamermaid.search_my_projects(tag="WCS")  # doctest: +SKIP
    """
    return _fetch_projects(
        require_auth=True,
        include_test_projects=include_test_projects,
        name=name,
        country=country,
        tag=tag,
        limit=limit,
        client=client,
        token=token,
    )
