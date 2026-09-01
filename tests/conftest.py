"""Shared fixtures.  Every test runs offline; all HTTP is mocked with respx."""

from __future__ import annotations

from typing import Any
from urllib.parse import parse_qs, urlparse

import pytest

from datamermaid.client import API_BASE_URL, MermaidClient

PROJECTS_URL = API_BASE_URL + "projects/"


@pytest.fixture
def client() -> MermaidClient:
    """An unauthenticated client, closed at the end of the test."""
    with MermaidClient() as c:
        yield c


@pytest.fixture
def auth_client() -> MermaidClient:
    """A client carrying a bearer token."""
    with MermaidClient(token="secret-token") as c:
        yield c


def page(
    results: list[dict[str, Any]],
    *,
    next_url: str | None = None,
    count: int | None = None,
) -> dict[str, Any]:
    """Build a MERMAID pagination envelope."""
    return {
        "count": count if count is not None else len(results),
        "next": next_url,
        "previous": None,
        "results": results,
    }


def query_of(request) -> dict[str, list[str]]:
    """Parse the query string of a captured httpx request."""
    return parse_qs(urlparse(str(request.url)).query)


def projects(n: int, start: int = 0) -> list[dict[str, Any]]:
    """Build ``n`` minimal project records."""
    return [
        {
            "id": f"project-{i}",
            "name": f"Project {i}",
            "countries": ["Fiji"],
            "num_sites": i,
            "tags": [{"id": "t1", "name": "WCS"}],
            "notes": "",
            "status": 90,
            "data_policy_beltfish": "public summary",
            "created_on": "2020-01-01T00:00:00Z",
            "updated_on": "2021-01-01T00:00:00Z",
        }
        for i in range(start, start + n)
    ]
