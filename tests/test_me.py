"""Tests for :func:`datamermaid.get_me`."""

from __future__ import annotations

import httpx
import pytest
import respx

from datamermaid import auth, get_me
from datamermaid.client import DEFAULT_BASE_URL, MermaidClient
from datamermaid.exceptions import AuthenticationError, MermaidAPIError

ME_URL = DEFAULT_BASE_URL + "me/"
PROFILE = {"id": "abc", "first_name": "Ada", "last_name": "Lovelace", "email": "ada@example.org"}


@respx.mock
def test_get_me_returns_the_profile_object(monkeypatch):
    monkeypatch.setenv(auth.TOKEN_ENV_VAR, "env-token")
    route = respx.get(ME_URL).mock(return_value=httpx.Response(200, json=PROFILE))

    assert get_me() == PROFILE
    assert route.calls.last.request.headers["authorization"] == "Bearer env-token"


@respx.mock
def test_get_me_is_not_paginated(monkeypatch):
    """``me/`` returns a bare object, so it must not be unwrapped as a page."""
    monkeypatch.setenv(auth.TOKEN_ENV_VAR, "env-token")
    route = respx.get(ME_URL).mock(return_value=httpx.Response(200, json=PROFILE))

    profile = get_me()

    assert "results" not in profile
    assert route.call_count == 1
    assert "limit" not in dict(route.calls.last.request.url.params)


@respx.mock
def test_get_me_uses_the_cached_token(write_cached_token):
    write_cached_token("cached-token")
    route = respx.get(ME_URL).mock(return_value=httpx.Response(200, json=PROFILE))

    get_me()

    assert route.calls.last.request.headers["authorization"] == "Bearer cached-token"


@respx.mock
def test_get_me_reuses_a_supplied_client(monkeypatch):
    monkeypatch.setenv(auth.TOKEN_ENV_VAR, "env-token")
    respx.get(ME_URL).mock(return_value=httpx.Response(200, json=PROFILE))

    with MermaidClient() as client:
        assert get_me(client=client) == PROFILE
        assert get_me(client=client) == PROFILE  # the client is still usable


def test_get_me_without_a_token_raises():
    with pytest.raises(AuthenticationError, match="authenticate"):
        get_me()


@respx.mock
def test_get_me_with_a_rejected_token_clears_the_cache(write_cached_token, token_cache_path):
    write_cached_token("cached-token")
    respx.get(ME_URL).mock(return_value=httpx.Response(401, json={"detail": "expired"}))

    with pytest.raises(AuthenticationError, match="authenticate"):
        get_me()

    assert not token_cache_path.exists()


@respx.mock
def test_get_me_rejects_a_non_object_response(monkeypatch):
    monkeypatch.setenv(auth.TOKEN_ENV_VAR, "env-token")
    respx.get(ME_URL).mock(return_value=httpx.Response(200, json=[PROFILE]))

    with pytest.raises(MermaidAPIError, match="Expected an object"):
        get_me()
