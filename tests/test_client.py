"""Tests for :class:`datamermaid.MermaidClient`."""

from __future__ import annotations

import httpx
import pytest
import respx

from datamermaid import auth
from datamermaid.client import DEFAULT_BASE_URL, MermaidClient
from datamermaid.exceptions import AuthenticationError, MermaidAPIError

PROJECTS_URL = DEFAULT_BASE_URL + "projects/"


def page(results, next_url=None):
    return {"count": len(results), "next": next_url, "previous": None, "results": results}


@respx.mock
def test_get_does_not_send_authorization_by_default():
    route = respx.get(PROJECTS_URL).mock(return_value=httpx.Response(200, json=page([])))

    with MermaidClient() as client:
        client.get("projects/")

    assert "authorization" not in route.calls.last.request.headers


@respx.mock
def test_get_sends_the_bearer_token_when_auth_is_required(monkeypatch):
    monkeypatch.setenv(auth.TOKEN_ENV_VAR, "env-token")
    route = respx.get(DEFAULT_BASE_URL + "me/").mock(return_value=httpx.Response(200, json={}))

    with MermaidClient() as client:
        client.get("me/", require_auth=True)

    assert route.calls.last.request.headers["authorization"] == "Bearer env-token"


@respx.mock
def test_explicit_token_beats_the_environment(monkeypatch):
    monkeypatch.setenv(auth.TOKEN_ENV_VAR, "env-token")
    route = respx.get(DEFAULT_BASE_URL + "me/").mock(return_value=httpx.Response(200, json={}))

    with MermaidClient(token="explicit-token") as client:
        client.get("me/", require_auth=True)

    assert route.calls.last.request.headers["authorization"] == "Bearer explicit-token"


def test_missing_token_raises_an_actionable_error():
    with MermaidClient() as client, pytest.raises(AuthenticationError) as excinfo:
        client.get("me/", require_auth=True)

    message = str(excinfo.value)
    assert "datamermaid.authenticate()" in message
    assert auth.TOKEN_ENV_VAR in message


@respx.mock
def test_401_with_a_cached_token_clears_the_cache(write_cached_token, token_cache_path):
    write_cached_token("cached-token")
    respx.get(DEFAULT_BASE_URL + "me/").mock(return_value=httpx.Response(401, json={}))

    with MermaidClient() as client, pytest.raises(AuthenticationError) as excinfo:
        client.get("me/", require_auth=True)

    assert "authenticate()" in str(excinfo.value)
    assert not token_cache_path.exists()


@respx.mock
def test_403_does_not_discard_a_working_token(write_cached_token, token_cache_path):
    """A 403 means "not allowed", not "bad token", so the cache survives."""
    write_cached_token("cached-token")
    respx.get(DEFAULT_BASE_URL + "me/").mock(return_value=httpx.Response(403, json={}))

    with MermaidClient() as client, pytest.raises(AuthenticationError, match="may not have access"):
        client.get("me/", require_auth=True)

    assert token_cache_path.exists()


@respx.mock
def test_401_with_an_env_token_does_not_touch_the_cache(
    monkeypatch, write_cached_token, token_cache_path
):
    write_cached_token("cached-token")
    monkeypatch.setenv(auth.TOKEN_ENV_VAR, "env-token")
    respx.get(DEFAULT_BASE_URL + "me/").mock(return_value=httpx.Response(401, json={}))

    with MermaidClient() as client, pytest.raises(AuthenticationError) as excinfo:
        client.get("me/", require_auth=True)

    assert auth.TOKEN_ENV_VAR in str(excinfo.value)
    assert token_cache_path.exists()


@respx.mock
def test_401_with_an_explicit_token_mentions_the_client():
    respx.get(DEFAULT_BASE_URL + "me/").mock(return_value=httpx.Response(401, json={}))

    with MermaidClient(token="explicit") as client, pytest.raises(AuthenticationError) as excinfo:
        client.get("me/", require_auth=True)

    assert "MermaidClient" in str(excinfo.value)


@respx.mock
def test_401_on_an_unauthenticated_request_is_an_api_error():
    respx.get(PROJECTS_URL).mock(return_value=httpx.Response(401, text="nope"))

    with MermaidClient() as client, pytest.raises(MermaidAPIError) as excinfo:
        client.get("projects/")

    assert excinfo.value.status_code == 401


@respx.mock
def test_server_errors_are_reported_with_the_status_and_body():
    respx.get(PROJECTS_URL).mock(return_value=httpx.Response(500, text="boom"))

    with MermaidClient() as client, pytest.raises(MermaidAPIError) as excinfo:
        client.get("projects/")

    assert "HTTP 500" in str(excinfo.value)
    assert "boom" in str(excinfo.value)


@respx.mock
def test_non_json_responses_are_reported():
    respx.get(PROJECTS_URL).mock(return_value=httpx.Response(200, text="<html/>"))

    with MermaidClient() as client, pytest.raises(MermaidAPIError, match="non-JSON"):
        client.get("projects/")


@respx.mock
def test_get_records_follows_pagination():
    second = PROJECTS_URL + "?page=2"
    route = respx.get(PROJECTS_URL).mock(
        side_effect=[
            httpx.Response(200, json=page([{"id": 1}], next_url=second)),
            httpx.Response(200, json=page([{"id": 2}])),
        ]
    )

    with MermaidClient() as client:
        records = client.get_records("projects/")

    assert [record["id"] for record in records] == [1, 2]
    assert str(route.calls.last.request.url) == second


@respx.mock
def test_get_records_stops_once_the_limit_is_reached():
    route = respx.get(PROJECTS_URL).mock(
        return_value=httpx.Response(
            200, json=page([{"id": 1}, {"id": 2}, {"id": 3}], next_url=PROJECTS_URL + "?page=2")
        )
    )

    with MermaidClient() as client:
        records = client.get_records("projects/", limit=2)

    assert [record["id"] for record in records] == [1, 2]
    assert route.call_count == 1


@respx.mock
def test_get_records_accepts_a_bare_list_response():
    respx.get(DEFAULT_BASE_URL + "things/").mock(return_value=httpx.Response(200, json=[{"id": 1}]))

    with MermaidClient() as client:
        assert client.get_records("things/") == [{"id": 1}]


@respx.mock
def test_get_records_rejects_an_unexpected_shape():
    respx.get(DEFAULT_BASE_URL + "things/").mock(return_value=httpx.Response(200, json="nope"))

    with MermaidClient() as client, pytest.raises(MermaidAPIError, match="Unexpected response"):
        client.get_records("things/")


def test_base_url_always_ends_in_a_slash():
    with MermaidClient(base_url="https://example.org/v1") as client:
        assert client.base_url == "https://example.org/v1/"
