"""Tests for the authenticated project endpoints."""

from __future__ import annotations

import httpx
import pytest
import respx

from datamermaid import auth, get_my_projects, search_my_projects
from datamermaid.client import DEFAULT_BASE_URL
from datamermaid.exceptions import AuthenticationError

PROJECTS_URL = DEFAULT_BASE_URL + "projects/"

MY_PROJECTS = [
    {
        "id": "1",
        "name": "Kubulau Reefs",
        "countries": ["Fiji"],
        "tags": [{"name": "WCS Fiji"}, {"name": "Reef Check"}],
        "status": 90,
    },
    {
        "id": "2",
        "name": "Karimunjawa Monitoring",
        "countries": ["Indonesia"],
        "tags": [{"name": "WCS Indonesia"}],
        "status": 90,
    },
    {"id": "3", "name": "Sandbox test", "countries": ["Fiji"], "tags": [], "status": 80},
]


def page(results, next_url=None):
    return {"count": len(results), "next": next_url, "previous": None, "results": results}


@pytest.fixture
def projects_route():
    with respx.mock:
        yield respx.get(PROJECTS_URL).mock(return_value=httpx.Response(200, json=page(MY_PROJECTS)))


def test_get_my_projects_sends_the_token_and_omits_showall(monkeypatch, projects_route):
    monkeypatch.setenv(auth.TOKEN_ENV_VAR, "env-token")

    projects = get_my_projects()

    request = projects_route.calls.last.request
    assert request.headers["authorization"] == "Bearer env-token"
    assert "showall" not in request.url.params
    assert [project["id"] for project in projects] == ["1", "2"]


def test_get_my_projects_uses_the_cached_token(write_cached_token, projects_route):
    write_cached_token("cached-token")

    get_my_projects()

    assert projects_route.calls.last.request.headers["authorization"] == "Bearer cached-token"


def test_get_my_projects_accepts_an_explicit_token(projects_route):
    get_my_projects(token="explicit-token")

    assert projects_route.calls.last.request.headers["authorization"] == "Bearer explicit-token"


def test_get_my_projects_can_include_test_projects(monkeypatch, projects_route):
    monkeypatch.setenv(auth.TOKEN_ENV_VAR, "env-token")

    assert len(get_my_projects(include_test_projects=True)) == 3


def test_get_my_projects_respects_limit(monkeypatch, projects_route):
    monkeypatch.setenv(auth.TOKEN_ENV_VAR, "env-token")

    assert [project["id"] for project in get_my_projects(limit=1)] == ["1"]


def test_get_my_projects_without_a_token_raises():
    with pytest.raises(AuthenticationError, match="authenticate"):
        get_my_projects()


@respx.mock
def test_rejected_token_clears_the_cache(write_cached_token, token_cache_path):
    write_cached_token("cached-token")
    respx.get(PROJECTS_URL).mock(return_value=httpx.Response(401, json={"detail": "expired"}))

    with pytest.raises(AuthenticationError) as excinfo:
        get_my_projects()

    assert "datamermaid.authenticate()" in str(excinfo.value)
    assert not token_cache_path.exists()


def test_search_my_projects_filters_by_name(monkeypatch, projects_route):
    monkeypatch.setenv(auth.TOKEN_ENV_VAR, "env-token")

    assert [p["id"] for p in search_my_projects(name="karimunjawa")] == ["2"]


def test_search_my_projects_filters_by_country(monkeypatch, projects_route):
    monkeypatch.setenv(auth.TOKEN_ENV_VAR, "env-token")

    assert [p["id"] for p in search_my_projects(country="Fiji")] == ["1"]


def test_search_my_projects_filters_by_tag(monkeypatch, projects_route):
    monkeypatch.setenv(auth.TOKEN_ENV_VAR, "env-token")

    assert [p["id"] for p in search_my_projects(tag="reef check")] == ["1"]
    assert [p["id"] for p in search_my_projects(tag="WCS")] == ["1", "2"]


def test_search_my_projects_combines_filters(monkeypatch, projects_route):
    monkeypatch.setenv(auth.TOKEN_ENV_VAR, "env-token")

    assert search_my_projects(name="Kubulau", country="Indonesia") == []
    assert [p["id"] for p in search_my_projects(name="Kubulau", tag="WCS")] == ["1"]


def test_search_my_projects_sends_the_token(monkeypatch, projects_route):
    monkeypatch.setenv(auth.TOKEN_ENV_VAR, "env-token")

    search_my_projects(name="Kubulau")

    request = projects_route.calls.last.request
    assert request.headers["authorization"] == "Bearer env-token"
    assert "showall" not in request.url.params
