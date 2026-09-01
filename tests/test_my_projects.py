"""Tests for the authenticated project endpoints and the search filters."""

from __future__ import annotations

import httpx
import pytest
import respx

from conftest import PROJECTS_URL, page, query_of
from datamermaid import auth, get_my_projects, search_my_projects
from datamermaid.client import DEFAULT_PAGE_SIZE
from datamermaid.exceptions import AuthenticationError
from datamermaid.projects import PROJECT_STATUS_OPEN

MY_PROJECTS = [
    {
        "id": "1",
        "name": "Kubulau Reefs",
        "countries": ["Fiji"],
        "tags": [{"id": "a", "name": "WCS Fiji"}, {"id": "b", "name": "Reef Check"}],
        "status": PROJECT_STATUS_OPEN,
    },
    {
        "id": "2",
        "name": "Karimunjawa Monitoring",
        "countries": ["Indonesia"],
        "tags": [{"id": "c", "name": "WCS Indonesia"}],
        "status": PROJECT_STATUS_OPEN,
    },
]


@pytest.fixture
def projects_route():
    """The ``projects`` endpoint, answering with one page of MY_PROJECTS."""
    with respx.mock:
        yield respx.get(PROJECTS_URL).mock(return_value=httpx.Response(200, json=page(MY_PROJECTS)))


@pytest.fixture
def env_token(monkeypatch):
    monkeypatch.setenv(auth.TOKEN_ENV_VAR, "env-token")
    return "env-token"


class TestRequestShape:
    def test_sends_the_token_and_omits_showall(self, env_token, projects_route):
        df = get_my_projects()

        request = projects_route.calls.last.request
        assert request.headers["Authorization"] == "Bearer env-token"
        assert "showall" not in query_of(request)
        assert list(df["id"]) == ["1", "2"]

    def test_uses_the_cached_token(self, write_cached_token, projects_route):
        write_cached_token("cached-token")

        get_my_projects()

        assert projects_route.calls.last.request.headers["Authorization"] == "Bearer cached-token"

    def test_accepts_an_explicit_token(self, projects_route):
        get_my_projects(token="explicit-token")

        assert projects_route.calls.last.request.headers["Authorization"] == "Bearer explicit-token"

    def test_test_projects_are_filtered_out_by_default(self, env_token, projects_route):
        get_my_projects()

        assert query_of(projects_route.calls.last.request)["status"] == [str(PROJECT_STATUS_OPEN)]

    def test_status_filter_is_dropped_when_including_test_projects(self, env_token, projects_route):
        get_my_projects(include_test_projects=True)

        assert "status" not in query_of(projects_route.calls.last.request)

    def test_the_api_applies_the_limit(self, env_token, projects_route):
        df = get_my_projects(limit=1)

        assert list(df["id"]) == ["1"]
        assert query_of(projects_route.calls.last.request)["limit"] == ["1"]
        assert projects_route.call_count == 1

    def test_a_search_asks_for_full_pages(self, env_token, projects_route):
        """A filter is applied here, so ``limit`` must not shrink the request."""
        search_my_projects(name="Kubulau", limit=1)

        assert query_of(projects_route.calls.last.request)["limit"] == [str(DEFAULT_PAGE_SIZE)]

    def test_search_sends_the_token_and_omits_showall(self, env_token, projects_route):
        search_my_projects(name="Kubulau")

        request = projects_route.calls.last.request
        assert request.headers["Authorization"] == "Bearer env-token"
        assert "showall" not in query_of(request)

    def test_without_a_token_raises(self):
        with pytest.raises(AuthenticationError, match="authenticate"):
            get_my_projects()

    def test_no_request_is_made_without_a_token(self):
        with respx.mock:
            route = respx.get(PROJECTS_URL).mock(
                return_value=httpx.Response(200, json=page(MY_PROJECTS))
            )
            with pytest.raises(AuthenticationError):
                get_my_projects()
            assert not route.called


class TestRejectedToken:
    @respx.mock
    def test_a_rejected_cached_token_clears_the_cache(self, write_cached_token, token_cache_path):
        write_cached_token("cached-token")
        respx.get(PROJECTS_URL).mock(return_value=httpx.Response(401, json={"detail": "expired"}))

        with pytest.raises(AuthenticationError) as excinfo:
            get_my_projects()

        assert "datamermaid.authenticate()" in str(excinfo.value)
        assert not token_cache_path.exists()

    @respx.mock
    def test_a_rejected_env_token_names_the_variable(self, env_token):
        respx.get(PROJECTS_URL).mock(return_value=httpx.Response(401))

        with pytest.raises(AuthenticationError, match=auth.TOKEN_ENV_VAR):
            get_my_projects()

    @respx.mock
    def test_a_forbidden_request_keeps_the_cached_token(self, write_cached_token, token_cache_path):
        """403 means the account lacks access, not that the token is stale."""
        write_cached_token("cached-token")
        respx.get(PROJECTS_URL).mock(return_value=httpx.Response(403))

        with pytest.raises(AuthenticationError, match="may not have access"):
            get_my_projects()

        assert token_cache_path.exists()


class TestSearchFilters:
    def test_filters_by_name(self, env_token, projects_route):
        assert list(search_my_projects(name="karimunjawa")["id"]) == ["2"]

    def test_filters_by_country(self, env_token, projects_route):
        assert list(search_my_projects(country="Fiji")["id"]) == ["1"]

    def test_filters_by_tag(self, env_token, projects_route):
        assert list(search_my_projects(tag="reef check")["id"]) == ["1"]
        assert list(search_my_projects(tag="WCS")["id"]) == ["1", "2"]

    def test_combines_filters(self, env_token, projects_route):
        assert search_my_projects(name="Kubulau", country="Indonesia").empty
        assert list(search_my_projects(name="Kubulau", tag="WCS")["id"]) == ["1"]

    def test_limit_applies_after_filtering(self, env_token, projects_route):
        assert list(search_my_projects(tag="WCS", limit=1)["id"]) == ["1"]

    def test_no_filters_returns_everything(self, env_token, projects_route):
        assert list(search_my_projects()["id"]) == ["1", "2"]
