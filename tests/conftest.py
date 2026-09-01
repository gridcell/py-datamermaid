"""Shared fixtures.

Every test runs offline: all HTTP is mocked with respx, the token cache points
at a temporary directory, and ``MERMAID_API_TOKEN`` and the default-project
setting are cleared, so nothing touches a developer's real MERMAID credentials
or configuration.
"""

from __future__ import annotations

import os
import time
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse

import pytest

from datamermaid import auth, project_endpoints
from datamermaid.client import API_BASE_URL, MermaidClient

PROJECTS_URL = API_BASE_URL + "projects/"
ME_URL = API_BASE_URL + "me/"


@pytest.fixture(autouse=True)
def token_cache_path(tmp_path, monkeypatch):
    """Point the token cache at ``tmp_path`` and unset ``MERMAID_API_TOKEN``."""
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    monkeypatch.delenv(auth.TOKEN_ENV_VAR, raising=False)
    return tmp_path / "config" / "datamermaid" / "token.json"


@pytest.fixture
def write_cached_token(token_cache_path):
    """Write a token to the cache; expires an hour from now by default."""

    def _write(token: str = "cached-token", *, ttl: float = 3600.0) -> str:
        auth._write_cache(token, time.time() + ttl)
        return token

    return _write


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


FIXTURE_DIR = Path(__file__).parent / "fixtures"


def fixture_csv(name: str) -> str:
    """Read a checked-in CSV fixture, e.g. ``"fishbelt_observations"``."""
    return (FIXTURE_DIR / f"{name}.csv").read_text()


def project_csv_url(project_id: str, method_slug: str, data_slug: str) -> str:
    """Build the URL of a project's CSV endpoint for one method and level."""
    return f"{API_BASE_URL}projects/{project_id}/{method_slug}/{data_slug}/csv/"


def project_url(project_id: str, endpoint: str) -> str:
    """URL of a project-scoped endpoint, e.g. ``projects/p1/sites/``."""
    return f"{API_BASE_URL}projects/{project_id}/{endpoint.strip('/')}/"


def sites(n: int, start: int = 0) -> list[dict[str, Any]]:
    """Build ``n`` minimal project site records."""
    return [
        {
            "id": f"site-{i}",
            "name": f"Site {i}",
            "notes": "",
            "project": "project-from-payload",
            "country": "Fiji",
            "reef_type": "fringing",
            "reef_zone": "crest",
            "exposure": "exposed",
            "created_on": "2020-01-01T00:00:00Z",
            "updated_on": "2021-01-01T00:00:00Z",
        }
        for i in range(start, start + n)
    ]


def managements(n: int, start: int = 0) -> list[dict[str, Any]]:
    """Build ``n`` minimal project management-regime records."""
    return [
        {
            "id": f"management-{i}",
            "name": f"Management {i}",
            "name_secondary": "",
            "notes": "",
            "project": "project-from-payload",
            "est_year": 2000 + i,
            "no_take": True,
            "open_access": False,
            "parties": ["community"],
            "created_on": "2020-01-01T00:00:00Z",
            "updated_on": "2021-01-01T00:00:00Z",
        }
        for i in range(start, start + n)
    ]


@pytest.fixture(autouse=True)
def _no_default_project(monkeypatch):
    """Keep the default-project setting from leaking between tests.

    ``set_default_project`` writes ``os.environ`` itself, so the variable is
    snapshotted and restored here rather than left to ``monkeypatch.delenv``,
    which does not track keys that were absent to begin with.
    """
    monkeypatch.setattr(project_endpoints, "_default_project", None)
    env_var = project_endpoints.DEFAULT_PROJECT_ENV_VAR
    previous = os.environ.pop(env_var, None)
    yield
    os.environ.pop(env_var, None)
    if previous is not None:
        os.environ[env_var] = previous
