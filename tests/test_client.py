"""Tests for the HTTP core: pagination, limits, headers and error mapping."""

from __future__ import annotations

import httpx
import pytest
import respx

from conftest import PROJECTS_URL, page, projects, query_of
from datamermaid.auth import TOKEN_ENV_VAR
from datamermaid.client import (
    API_BASE_URL,
    DEFAULT_PAGE_SIZE,
    USER_AGENT,
    MermaidClient,
    check_limit,
    client_context,
    default_client,
    set_default_client,
)
from datamermaid.exceptions import AuthenticationError, MermaidAPIError, MermaidError


class TestCheckLimit:
    def test_none_passes_through(self):
        assert check_limit(None) is None

    @pytest.mark.parametrize("value", [1, 5, 5000, 10_000])
    def test_positive_integers_are_accepted(self, value):
        assert check_limit(value) == value

    def test_integral_floats_are_coerced(self):
        result = check_limit(5.0)
        assert result == 5
        assert isinstance(result, int)

    @pytest.mark.parametrize(
        "value",
        [0, -1, 2.5, -0.5, "x", "5", True, False, float("inf"), float("nan"), [3]],
    )
    def test_invalid_values_raise(self, value):
        with pytest.raises(ValueError, match="positive integer"):
            check_limit(value)

    def test_invalid_limit_raises_before_any_request(self, client):
        with respx.mock:
            route = respx.get(PROJECTS_URL).mock(return_value=httpx.Response(200, json=page([])))
            with pytest.raises(ValueError):
                client.get("projects", limit=0)
            assert not route.called


class TestPagination:
    @respx.mock
    def test_follows_next_until_exhausted(self, client):
        page_two = PROJECTS_URL + "?limit=5000&offset=2"
        page_three = PROJECTS_URL + "?limit=5000&offset=4"
        respx.get(PROJECTS_URL, params={"offset": "2"}).mock(
            return_value=httpx.Response(
                200, json=page(projects(2, 2), next_url=page_three, count=5)
            )
        )
        respx.get(PROJECTS_URL, params={"offset": "4"}).mock(
            return_value=httpx.Response(200, json=page(projects(1, 4), count=5))
        )
        respx.get(PROJECTS_URL).mock(
            return_value=httpx.Response(200, json=page(projects(2, 0), next_url=page_two, count=5))
        )

        records = client.get("projects")

        assert [r["id"] for r in records] == [f"project-{i}" for i in range(5)]

    @respx.mock
    def test_stops_at_limit_without_fetching_extra_pages(self, client):
        page_two = PROJECTS_URL + "?limit=3&offset=3"
        second = respx.get(PROJECTS_URL, params={"offset": "3"}).mock(
            return_value=httpx.Response(200, json=page(projects(3, 3), count=9))
        )
        respx.get(PROJECTS_URL).mock(
            return_value=httpx.Response(200, json=page(projects(3, 0), next_url=page_two, count=9))
        )

        records = client.get("projects", limit=3)

        assert len(records) == 3
        assert not second.called, "should not page past the limit"

    @respx.mock
    def test_truncates_an_overlong_final_page(self, client):
        respx.get(PROJECTS_URL).mock(
            return_value=httpx.Response(200, json=page(projects(10), count=10))
        )

        records = client.get("projects", limit=4)

        assert [r["id"] for r in records] == [f"project-{i}" for i in range(4)]

    @respx.mock
    def test_empty_results(self, client):
        respx.get(PROJECTS_URL).mock(return_value=httpx.Response(200, json=page([])))

        assert client.get("projects") == []

    @respx.mock
    def test_unpaginated_object_response_is_returned_as_one_record(self, client):
        respx.get(PROJECTS_URL).mock(return_value=httpx.Response(200, json={"id": "me"}))

        assert client.get("projects") == [{"id": "me"}]

    @respx.mock
    def test_bare_list_response_is_returned_as_records(self, client):
        respx.get(PROJECTS_URL).mock(return_value=httpx.Response(200, json=[{"id": "a"}]))

        assert client.get("projects") == [{"id": "a"}]


class TestPageSize:
    @respx.mock
    def test_no_limit_requests_the_maximum_page_size(self, client):
        route = respx.get(PROJECTS_URL).mock(
            return_value=httpx.Response(200, json=page(projects(1)))
        )

        client.get("projects")

        assert query_of(route.calls.last.request)["limit"] == [str(DEFAULT_PAGE_SIZE)]

    @respx.mock
    def test_small_limit_requests_only_that_many(self, client):
        route = respx.get(PROJECTS_URL).mock(
            return_value=httpx.Response(200, json=page(projects(3)))
        )

        client.get("projects", limit=3)

        assert query_of(route.calls.last.request)["limit"] == ["3"]

    @respx.mock
    def test_page_size_never_exceeds_the_api_cap(self, client):
        route = respx.get(PROJECTS_URL).mock(
            return_value=httpx.Response(200, json=page(projects(1), count=20_000))
        )

        client.get("projects", limit=20_000)

        requested = int(query_of(route.calls.last.request)["limit"][0])
        assert requested == DEFAULT_PAGE_SIZE


class TestHeaders:
    @respx.mock
    def test_user_agent_points_at_this_repo(self, client):
        route = respx.get(PROJECTS_URL).mock(return_value=httpx.Response(200, json=page([])))

        client.get("projects")

        assert route.calls.last.request.headers["User-Agent"] == USER_AGENT

    @respx.mock
    def test_no_authorization_header_without_a_token(self, client):
        route = respx.get(PROJECTS_URL).mock(return_value=httpx.Response(200, json=page([])))

        client.get("projects")

        assert "Authorization" not in route.calls.last.request.headers

    @respx.mock
    def test_bearer_token_is_sent_when_set(self, auth_client):
        route = respx.get(PROJECTS_URL).mock(return_value=httpx.Response(200, json=page([])))

        auth_client.get("projects")

        assert route.calls.last.request.headers["Authorization"] == "Bearer secret-token"

    @respx.mock
    def test_headers_are_applied_to_followed_next_pages(self, auth_client):
        page_two = PROJECTS_URL + "?limit=5000&offset=1"
        second = respx.get(PROJECTS_URL, params={"offset": "1"}).mock(
            return_value=httpx.Response(200, json=page(projects(1, 1), count=2))
        )
        respx.get(PROJECTS_URL).mock(
            return_value=httpx.Response(200, json=page(projects(1), next_url=page_two, count=2))
        )

        auth_client.get("projects")

        assert second.calls.last.request.headers["Authorization"] == "Bearer secret-token"


class TestErrors:
    @pytest.mark.parametrize("status", [400, 401, 403, 404, 500, 503])
    @respx.mock
    def test_http_errors_map_to_mermaid_api_error(self, client, status):
        respx.get(PROJECTS_URL).mock(return_value=httpx.Response(status))

        with pytest.raises(MermaidAPIError) as excinfo:
            client.get("projects")

        error = excinfo.value
        assert error.status_code == status
        assert str(status) in str(error)
        assert isinstance(error, MermaidError)

    @respx.mock
    def test_error_carries_the_requested_url(self, client):
        respx.get(PROJECTS_URL).mock(return_value=httpx.Response(404))

        with pytest.raises(MermaidAPIError) as excinfo:
            client.get("projects")

        assert "projects" in excinfo.value.url

    @respx.mock
    def test_error_on_a_later_page_propagates(self, client):
        page_two = PROJECTS_URL + "?limit=5000&offset=1"
        respx.get(PROJECTS_URL, params={"offset": "1"}).mock(return_value=httpx.Response(500))
        respx.get(PROJECTS_URL).mock(
            return_value=httpx.Response(200, json=page(projects(1), next_url=page_two, count=2))
        )

        with pytest.raises(MermaidAPIError) as excinfo:
            client.get("projects")

        assert excinfo.value.status_code == 500


class TestClientLifecycle:
    def test_url_for_builds_a_versioned_path(self, client):
        assert client.url_for("projects") == "https://api.datamermaid.org/v1/projects/"
        assert client.url_for("/projects/") == "https://api.datamermaid.org/v1/projects/"

    def test_base_url_gains_a_trailing_slash(self):
        with MermaidClient(base_url="https://example.test/v1") as c:
            assert c.base_url == "https://example.test/v1/"

    def test_context_manager_closes_the_pool(self):
        with MermaidClient() as c:
            pass
        assert c._client.is_closed

    def test_repr_does_not_leak_the_token(self):
        with MermaidClient(token="secret-token") as c:
            assert "secret-token" not in repr(c)
            assert "authenticated=True" in repr(c)

    def test_default_client_is_reused(self):
        set_default_client(None)
        try:
            assert default_client() is default_client()
        finally:
            set_default_client(None)

    def test_default_client_can_be_replaced(self):
        replacement = MermaidClient(token="t")
        set_default_client(replacement)
        try:
            assert default_client() is replacement
        finally:
            set_default_client(None)
            replacement.close()


class TestRequireAuth:
    """``require_auth`` resolves a token lazily, per request."""

    @respx.mock
    def test_token_is_resolved_from_the_environment(self, client, monkeypatch):
        monkeypatch.setenv(TOKEN_ENV_VAR, "env-token")
        route = respx.get(PROJECTS_URL).mock(return_value=httpx.Response(200, json=page([])))

        client.get("projects", require_auth=True)

        assert route.calls.last.request.headers["Authorization"] == "Bearer env-token"

    @respx.mock
    def test_an_explicit_token_wins_over_the_environment(self, auth_client, monkeypatch):
        monkeypatch.setenv(TOKEN_ENV_VAR, "env-token")
        route = respx.get(PROJECTS_URL).mock(return_value=httpx.Response(200, json=page([])))

        auth_client.get("projects", require_auth=True)

        assert route.calls.last.request.headers["Authorization"] == "Bearer secret-token"

    @respx.mock
    def test_the_token_is_sent_on_followed_next_pages(self, client, monkeypatch):
        monkeypatch.setenv(TOKEN_ENV_VAR, "env-token")
        page_two = PROJECTS_URL + "?limit=5000&offset=1"
        second = respx.get(PROJECTS_URL, params={"offset": "1"}).mock(
            return_value=httpx.Response(200, json=page(projects(1, 1), count=2))
        )
        respx.get(PROJECTS_URL).mock(
            return_value=httpx.Response(200, json=page(projects(1), next_url=page_two, count=2))
        )

        client.get("projects", require_auth=True)

        assert second.calls.last.request.headers["Authorization"] == "Bearer env-token"

    def test_no_token_raises_before_any_request(self, client):
        with respx.mock:
            route = respx.get(PROJECTS_URL).mock(return_value=httpx.Response(200, json=page([])))
            with pytest.raises(AuthenticationError, match="authenticate"):
                client.get("projects", require_auth=True)
            assert not route.called

    @respx.mock
    def test_unauthenticated_requests_send_no_token(self, client, monkeypatch):
        """An endpoint that needs no login must not send one that happens to exist."""
        monkeypatch.setenv(TOKEN_ENV_VAR, "env-token")
        route = respx.get(PROJECTS_URL).mock(return_value=httpx.Response(200, json=page([])))

        client.get("projects")

        assert "Authorization" not in route.calls.last.request.headers

    @respx.mock
    def test_a_401_on_an_unauthenticated_request_stays_an_api_error(self, client):
        respx.get(PROJECTS_URL).mock(return_value=httpx.Response(401))

        with pytest.raises(MermaidAPIError):
            client.get("projects")


class TestGetOne:
    @respx.mock
    def test_returns_the_object_unwrapped(self, client):
        respx.get(API_BASE_URL + "me/").mock(return_value=httpx.Response(200, json={"id": "abc"}))

        assert client.get_one("me") == {"id": "abc"}

    @respx.mock
    def test_no_pagination_parameters_are_sent(self, client):
        route = respx.get(API_BASE_URL + "me/").mock(
            return_value=httpx.Response(200, json={"id": "abc"})
        )

        client.get_one("me")

        assert query_of(route.calls.last.request) == {}

    @respx.mock
    def test_errors_map_to_mermaid_api_error(self, client):
        respx.get(API_BASE_URL + "me/").mock(return_value=httpx.Response(404))

        with pytest.raises(MermaidAPIError):
            client.get_one("me")


class TestClientContext:
    def test_a_supplied_client_is_yielded_and_left_open(self, client):
        with client_context(client) as api:
            assert api is client
        assert not client._client.is_closed

    def test_a_token_builds_a_client_that_is_closed_on_exit(self):
        with client_context(token="t") as api:
            assert api.token == "t"
        assert api._client.is_closed

    def test_without_arguments_it_yields_the_default_client(self, client):
        set_default_client(client)
        try:
            with client_context() as api:
                assert api is client
        finally:
            set_default_client(None)
