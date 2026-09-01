"""Access to MERMAID projects."""

from __future__ import annotations

import contextlib
from collections.abc import Iterable
from typing import Any

from .client import DEFAULT_PAGE_SIZE, MermaidClient, client_context

__all__ = [
    "get_projects",
    "search_projects",
    "get_my_projects",
    "search_my_projects",
]

PROJECTS_ENDPOINT = "projects/"

#: MERMAID marks test projects with this status code.
TEST_PROJECT_STATUS = 80

Project = dict[str, Any]


def _as_strings(value: Any) -> list[str]:
    """Flatten a MERMAID field into a list of comparable strings.

    Fields such as ``countries`` and ``tags`` come back as lists, lists of
    objects, or comma-separated strings depending on the endpoint.
    """
    if value is None:
        return []
    if isinstance(value, str):
        return [part.strip() for part in value.split(",") if part.strip()]
    if isinstance(value, dict):
        return _as_strings(value.get("name"))
    if isinstance(value, Iterable):
        return [item for entry in value for item in _as_strings(entry)]
    return [str(value)]


def _contains(haystack: str, needle: str) -> bool:
    return needle.casefold() in haystack.casefold()


def _matches_any(values: Iterable[str], needle: str) -> bool:
    return any(_contains(value, needle) for value in values)


def _is_test_project(project: Project) -> bool:
    status = project.get("status")
    return status == TEST_PROJECT_STATUS or str(status).casefold() == "test"


def _filter_projects(
    projects: Iterable[Project],
    *,
    name: str | None = None,
    country: str | None = None,
    tag: str | None = None,
) -> list[Project]:
    """Filter projects by case-insensitive substring match, like ``mermaidr``."""
    matched = []
    for project in projects:
        if name is not None and not _contains(str(project.get("name") or ""), name):
            continue
        if country is not None:
            countries = _as_strings(project.get("countries") or project.get("country"))
            if not _matches_any(countries, country):
                continue
        if tag is not None and not _matches_any(_as_strings(project.get("tags")), tag):
            continue
        matched.append(project)
    return matched


def _take_projects(
    records: Iterable[Project], *, include_test_projects: bool, limit: int | None
) -> list[Project]:
    """Collect up to ``limit`` records, skipping test projects as they arrive."""
    kept: list[Project] = []
    for record in records:
        if not include_test_projects and _is_test_project(record):
            continue
        kept.append(record)
        if limit is not None and len(kept) >= limit:
            break
    return kept


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
) -> list[Project]:
    searching = any(x is not None for x in (name, country, tag))
    params: dict[str, Any] = {}
    if not require_auth:
        # Unauthenticated callers must ask for the full public project list.
        params["showall"] = "true"

    # Name/country/tag matching happens here, so every project has to be fetched
    # before the limit can be applied.  Dropping test projects is local too, but
    # there the pages can simply be read until enough records have been kept.
    page_size = DEFAULT_PAGE_SIZE
    if limit is not None and not searching:
        page_size = max(1, min(limit, DEFAULT_PAGE_SIZE))

    with client_context(client, token) as api:
        pages = api.iter_records(
            PROJECTS_ENDPOINT, params=params, page_size=page_size, require_auth=require_auth
        )
        with contextlib.closing(pages):
            if not searching:
                return _take_projects(
                    pages, include_test_projects=include_test_projects, limit=limit
                )
            records = _take_projects(pages, include_test_projects=include_test_projects, limit=None)

    records = _filter_projects(records, name=name, country=country, tag=tag)
    return records[:limit] if limit is not None else records


def get_projects(
    include_test_projects: bool = False,
    limit: int | None = None,
    *,
    client: MermaidClient | None = None,
) -> list[Project]:
    """Return every public MERMAID project.

    No login is required; the request asks the API for all projects rather than
    only the caller's own (see :func:`get_my_projects` for those).
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
    include_test_projects: bool = False,
    limit: int | None = None,
    *,
    client: MermaidClient | None = None,
) -> list[Project]:
    """Return public projects whose name, country, or tags match the query."""
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
    include_test_projects: bool = False,
    limit: int | None = None,
    *,
    client: MermaidClient | None = None,
    token: str | None = None,
) -> list[Project]:
    """Return the projects the signed-in user belongs to.

    Requires a login: the token is taken from ``token``, the ``MERMAID_API_TOKEN``
    environment variable, or the cache written by
    :func:`datamermaid.authenticate`.
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
    include_test_projects: bool = False,
    limit: int | None = None,
    *,
    client: MermaidClient | None = None,
    token: str | None = None,
) -> list[Project]:
    """Return the signed-in user's projects matching name, country, or tags."""
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
