"""Tests for token resolution, the token cache, and the OAuth helpers."""

from __future__ import annotations

import base64
import hashlib
import json
import socket
import stat
import threading
import time
import urllib.parse

import httpx
import pytest
import respx

from datamermaid import auth
from datamermaid.exceptions import AuthenticationError

# --------------------------------------------------------------------------- #
# Precedence
# --------------------------------------------------------------------------- #


def test_env_var_takes_precedence_over_cache(monkeypatch, write_cached_token):
    write_cached_token("cached-token")
    monkeypatch.setenv(auth.TOKEN_ENV_VAR, "env-token")

    assert auth.get_token() == "env-token"
    assert auth.resolve_token().source == "env"


def test_env_var_is_used_without_a_browser(monkeypatch):
    monkeypatch.setenv(auth.TOKEN_ENV_VAR, "env-token")
    monkeypatch.setattr(auth, "_run_browser_flow", _explode)

    assert auth.authenticate() == "env-token"


def test_env_var_is_stripped_and_blank_is_ignored(monkeypatch, write_cached_token):
    monkeypatch.setenv(auth.TOKEN_ENV_VAR, "  padded-token\n")
    assert auth.get_token() == "padded-token"

    monkeypatch.setenv(auth.TOKEN_ENV_VAR, "   ")
    write_cached_token("cached-token")
    assert auth.get_token() == "cached-token"


def test_explicit_token_wins_over_everything(monkeypatch, write_cached_token):
    monkeypatch.setenv(auth.TOKEN_ENV_VAR, "env-token")
    write_cached_token("cached-token")

    resolved = auth.resolve_token("explicit-token")
    assert (resolved.access_token, resolved.source) == ("explicit-token", "explicit")


def test_get_token_is_none_when_nothing_is_available():
    assert auth.get_token() is None
    assert auth.resolve_token() is None


# --------------------------------------------------------------------------- #
# Cache
# --------------------------------------------------------------------------- #


def test_cache_path_honours_xdg_config_home(monkeypatch, tmp_path):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "xdg"))
    assert auth._cache_path() == tmp_path / "xdg" / "datamermaid" / "token.json"


def test_cache_path_defaults_to_dot_config(monkeypatch, tmp_path):
    monkeypatch.delenv("XDG_CONFIG_HOME", raising=False)
    monkeypatch.setattr(auth.Path, "home", classmethod(lambda cls: tmp_path))
    assert auth._cache_path() == tmp_path / ".config" / "datamermaid" / "token.json"


def test_write_cache_is_owner_only_and_readable(token_cache_path):
    expires_at = time.time() + 600
    auth._write_cache("secret-token", expires_at)

    assert json.loads(token_cache_path.read_text()) == {
        "access_token": "secret-token",
        "expires_at": expires_at,
    }
    assert stat.S_IMODE(token_cache_path.stat().st_mode) == 0o600
    assert auth.read_cached_token() == "secret-token"


def test_expired_cache_is_not_reused(write_cached_token):
    write_cached_token("stale-token", ttl=-1)
    assert auth.read_cached_token() is None
    assert auth.get_token() is None


def test_cache_expiring_within_the_skew_window_is_treated_as_expired(write_cached_token):
    write_cached_token("nearly-stale", ttl=auth.EXPIRY_SKEW_SECONDS / 2)
    assert auth.read_cached_token() is None


def test_is_expired_boundaries():
    now = 1_000.0
    assert auth._is_expired(None, now=now)
    assert auth._is_expired(now + auth.EXPIRY_SKEW_SECONDS - 1, now=now)
    assert not auth._is_expired(now + auth.EXPIRY_SKEW_SECONDS + 1, now=now)


@pytest.mark.parametrize(
    "contents",
    ["not json at all", "[]", '{"access_token": "x"}', '{"expires_at": 1}'],
)
def test_corrupt_cache_is_ignored(token_cache_path, contents):
    token_cache_path.parent.mkdir(parents=True, exist_ok=True)
    token_cache_path.write_text(contents)
    assert auth.read_cached_token() is None


def test_missing_cache_is_ignored(token_cache_path):
    assert not token_cache_path.exists()
    assert auth.read_cached_token() is None


def test_clear_cached_token_removes_the_file(token_cache_path, write_cached_token):
    write_cached_token()
    assert token_cache_path.exists()

    auth.clear_cached_token()

    assert not token_cache_path.exists()
    auth.clear_cached_token()  # a second call is a no-op


def test_authenticate_reuses_a_valid_cached_token(monkeypatch, write_cached_token):
    write_cached_token("cached-token")
    monkeypatch.setattr(auth, "_run_browser_flow", _explode)

    assert auth.authenticate() == "cached-token"


def test_authenticate_new_user_clears_the_cache_and_signs_in_again(
    monkeypatch, token_cache_path, write_cached_token
):
    write_cached_token("cached-token")
    seen = {}

    def fake_flow(*, timeout, client=None):
        seen["cache_present"] = token_cache_path.exists()
        return "fresh-token", time.time() + 3600

    monkeypatch.setattr(auth, "_run_browser_flow", fake_flow)

    assert auth.authenticate(new_user=True) == "fresh-token"
    assert seen["cache_present"] is False
    assert auth.read_cached_token() == "fresh-token"


def test_authenticate_caches_the_new_token(monkeypatch, token_cache_path):
    expires_at = time.time() + 3600
    monkeypatch.setattr(auth, "_run_browser_flow", lambda **kwargs: ("fresh-token", expires_at))

    assert auth.authenticate() == "fresh-token"
    assert json.loads(token_cache_path.read_text())["expires_at"] == expires_at


def test_authenticate_can_use_the_device_code_flow(monkeypatch):
    monkeypatch.setattr(auth, "_run_browser_flow", _explode)
    monkeypatch.setattr(
        auth, "_run_device_code_flow", lambda **kwargs: ("device-token", time.time() + 60)
    )

    assert auth.authenticate(use_device_code=True) == "device-token"


def _explode(*args, **kwargs):
    raise AssertionError("the interactive browser flow should not have been started")


# --------------------------------------------------------------------------- #
# PKCE and request payloads
# --------------------------------------------------------------------------- #


def test_pkce_pair_is_a_valid_s256_challenge():
    verifier, challenge = auth._pkce_pair()

    expected = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest())
    assert challenge == expected.decode().rstrip("=")
    assert "=" not in verifier and "=" not in challenge
    assert 43 <= len(verifier) <= 128
    assert auth._pkce_pair()[0] != verifier  # a fresh verifier every time


def test_authorize_url_carries_pkce_and_audience():
    url = auth._authorize_url(
        redirect_uri="http://localhost:1410/", code_challenge="chal", state="st4te"
    )
    parsed = urllib.parse.urlparse(url)
    query = dict(urllib.parse.parse_qsl(parsed.query))

    assert f"{parsed.scheme}://{parsed.netloc}{parsed.path}" == auth.AUTHORIZE_URL
    assert query == {
        "response_type": "code",
        "client_id": auth.CLIENT_ID,
        "redirect_uri": "http://localhost:1410/",
        "audience": auth.AUDIENCE,
        "scope": auth.SCOPE,
        "state": "st4te",
        "code_challenge": "chal",
        "code_challenge_method": "S256",
    }


def test_token_request_payload_is_a_pkce_code_exchange():
    payload = auth._token_request_payload(
        code="the-code", code_verifier="the-verifier", redirect_uri="http://localhost:1410/"
    )

    assert payload == {
        "grant_type": "authorization_code",
        "client_id": auth.CLIENT_ID,
        "code": "the-code",
        "code_verifier": "the-verifier",
        "redirect_uri": "http://localhost:1410/",
        "audience": auth.AUDIENCE,
    }
    assert "client_secret" not in payload


def test_device_payloads():
    assert auth._device_code_payload() == {
        "client_id": auth.CLIENT_ID,
        "audience": auth.AUDIENCE,
        "scope": auth.SCOPE,
    }
    assert auth._device_token_payload("dev-code") == {
        "grant_type": auth.DEVICE_CODE_GRANT,
        "client_id": auth.CLIENT_ID,
        "device_code": "dev-code",
    }


def test_parse_token_response_computes_absolute_expiry():
    token, expires_at = auth._parse_token_response(
        {"access_token": "abc", "expires_in": 120}, now=1_000.0
    )
    assert (token, expires_at) == ("abc", 1_120.0)


def test_parse_token_response_falls_back_to_the_default_lifetime():
    _, expires_at = auth._parse_token_response({"access_token": "abc"}, now=0.0)
    assert expires_at == auth.DEFAULT_EXPIRES_IN


def test_parse_token_response_without_a_token_is_an_error():
    with pytest.raises(AuthenticationError, match="did not return an access token"):
        auth._parse_token_response({"error": "invalid_grant"})


# --------------------------------------------------------------------------- #
# Token endpoint
# --------------------------------------------------------------------------- #


@respx.mock
def test_exchange_code_posts_the_payload_and_returns_the_token():
    route = respx.post(auth.TOKEN_URL).mock(
        return_value=httpx.Response(200, json={"access_token": "issued", "expires_in": 3600})
    )

    token, expires_at = auth._exchange_code(
        code="the-code",
        code_verifier="the-verifier",
        redirect_uri="http://localhost:1410/",
        now=0.0,
    )

    assert (token, expires_at) == ("issued", 3600.0)
    sent = dict(urllib.parse.parse_qsl(route.calls.last.request.content.decode()))
    assert sent == auth._token_request_payload(
        code="the-code", code_verifier="the-verifier", redirect_uri="http://localhost:1410/"
    )


@respx.mock
def test_exchange_code_surfaces_the_auth0_error_description():
    respx.post(auth.TOKEN_URL).mock(
        return_value=httpx.Response(
            403,
            json={"error": "invalid_grant", "error_description": "Invalid authorization code"},
        )
    )

    with pytest.raises(AuthenticationError, match="Invalid authorization code"):
        auth._exchange_code(code="c", code_verifier="v", redirect_uri="http://localhost/")


@respx.mock
def test_poll_device_token_waits_for_approval():
    respx.post(auth.TOKEN_URL).mock(
        side_effect=[
            httpx.Response(403, json={"error": "authorization_pending"}),
            httpx.Response(429, json={"error": "slow_down"}),
            httpx.Response(200, json={"access_token": "device-token", "expires_in": 60}),
        ]
    )
    slept: list[float] = []

    body = auth._poll_device_token(
        device_code="dev-code",
        interval=5,
        deadline=100.0,
        sleep=slept.append,
        monotonic=lambda: 0.0,
    )

    assert body["access_token"] == "device-token"
    assert slept == [5, 10]  # slow_down backs the interval off


@respx.mock
def test_poll_device_token_stops_on_a_real_error():
    respx.post(auth.TOKEN_URL).mock(
        return_value=httpx.Response(403, json={"error_description": "User denied access"})
    )

    with pytest.raises(AuthenticationError, match="User denied access"):
        auth._poll_device_token(
            device_code="dev-code",
            interval=0,
            deadline=100.0,
            sleep=lambda _: None,
            monotonic=lambda: 0.0,
        )


def test_poll_device_token_gives_up_at_the_deadline():
    with pytest.raises(AuthenticationError, match="Timed out"):
        auth._poll_device_token(
            device_code="dev-code", interval=0, deadline=0.0, monotonic=lambda: 1.0
        )


@respx.mock
def test_device_code_flow_prints_the_verification_url(capsys, monkeypatch):
    monkeypatch.setattr(auth.webbrowser, "open", lambda url: True)
    respx.post(auth.DEVICE_CODE_URL).mock(
        return_value=httpx.Response(
            200,
            json={
                "device_code": "dev-code",
                "user_code": "WXYZ-1234",
                "verification_uri_complete": "https://datamermaid.auth0.com/activate?code=WXYZ",
                "interval": 0,
                "expires_in": 600,
            },
        )
    )
    respx.post(auth.TOKEN_URL).mock(
        return_value=httpx.Response(200, json={"access_token": "device-token", "expires_in": 30})
    )

    token, expires_at = auth._run_device_code_flow(now=0.0)

    assert (token, expires_at) == ("device-token", 30.0)
    printed = capsys.readouterr().out
    assert "https://datamermaid.auth0.com/activate?code=WXYZ" in printed
    assert "WXYZ-1234" in printed


# --------------------------------------------------------------------------- #
# Loopback redirect server
# --------------------------------------------------------------------------- #


def test_callback_server_records_the_redirect_query():
    server = auth._bind_callback_server()
    try:
        assert server.callback_query is None
        url = f"http://127.0.0.1:{server.server_port}/?code=the-code&state=st4te"
        response = _request_in_background(server, url)
    finally:
        server.server_close()

    assert response.status_code == 200
    assert b"Signed in to MERMAID" in response.content
    assert server.callback_query == {"code": ["the-code"], "state": ["st4te"]}


def _request_in_background(server, url: str) -> httpx.Response:
    """Fire one request at ``server`` while it handles exactly one connection."""
    captured: list[httpx.Response] = []

    def call():
        captured.append(httpx.get(url, timeout=10))

    thread = threading.Thread(target=call)
    thread.start()
    server.handle_request()
    thread.join(timeout=10)
    return captured[0]


def test_callback_server_falls_back_to_an_ephemeral_port():
    import socket

    blocker = socket.socket()
    blocker.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    try:
        blocker.bind(("127.0.0.1", auth.DEFAULT_REDIRECT_PORT))
        blocker.listen(1)
    except OSError:  # pragma: no cover - depends on the sandbox
        blocker.close()
        pytest.skip("cannot occupy the default redirect port")

    try:
        server = auth._bind_callback_server()
        try:
            assert server.server_port != auth.DEFAULT_REDIRECT_PORT
        finally:
            server.server_close()
    finally:
        blocker.close()


# --------------------------------------------------------------------------- #
# Malformed Auth0 responses
# --------------------------------------------------------------------------- #


def test_parse_token_response_ignores_an_unusable_expires_in():
    _, expires_at = auth._parse_token_response(
        {"access_token": "abc", "expires_in": "soon"}, now=0.0
    )
    assert expires_at == auth.DEFAULT_EXPIRES_IN


@pytest.mark.parametrize(
    ("response", "expected"),
    [
        (httpx.Response(500, text="upstream exploded"), "upstream exploded"),
        (httpx.Response(500, text=""), "HTTP 500"),
        (httpx.Response(400, json=["nope"]), "nope"),
    ],
)
def test_auth0_error_falls_back_to_the_body(response, expected):
    assert expected in auth._auth0_error(response)


@respx.mock
def test_post_auth0_rejects_a_non_object_response():
    respx.post(auth.TOKEN_URL).mock(return_value=httpx.Response(200, json=["surprise"]))

    with pytest.raises(AuthenticationError, match="Unexpected response"):
        auth._post_auth0(auth.TOKEN_URL, {})


@respx.mock
def test_a_supplied_http_client_is_reused_and_left_open():
    respx.post(auth.TOKEN_URL).mock(
        return_value=httpx.Response(200, json={"access_token": "issued"})
    )

    with httpx.Client() as http:
        auth._exchange_code(code="c", code_verifier="v", redirect_uri="/", client=http)
        assert not http.is_closed


@respx.mock
def test_browser_flow_exchanges_the_redirected_code(monkeypatch):
    """Drive the real loopback flow with a stand-in for the browser."""
    respx.route(host="localhost").pass_through()
    respx.post(auth.TOKEN_URL).mock(
        return_value=httpx.Response(200, json={"access_token": "issued", "expires_in": 3600})
    )
    visited: list[str] = []

    def fake_browser(url: str) -> bool:
        visited.append(url)
        query = dict(urllib.parse.parse_qsl(urllib.parse.urlparse(url).query))
        threading.Thread(
            target=httpx.get,
            args=(query["redirect_uri"],),
            kwargs={"params": {"code": "the-code", "state": query["state"]}, "timeout": 10},
        ).start()
        return True

    monkeypatch.setattr(auth.webbrowser, "open", fake_browser)

    token, expires_at = auth._run_browser_flow(timeout=10)

    assert token == "issued"
    assert expires_at > time.time()
    assert visited and visited[0].startswith(auth.AUTHORIZE_URL)
    sent = dict(urllib.parse.parse_qsl(respx.calls.last.request.content.decode()))
    assert sent["code"] == "the-code"
    assert sent["grant_type"] == "authorization_code"
    # The verifier must be the pre-image of the challenge that was sent to Auth0.
    challenge = dict(urllib.parse.parse_qsl(urllib.parse.urlparse(visited[0]).query))[
        "code_challenge"
    ]
    digest = hashlib.sha256(sent["code_verifier"].encode()).digest()
    assert challenge == base64.urlsafe_b64encode(digest).decode().rstrip("=")


@respx.mock
def test_browser_flow_rejects_a_mismatched_state(monkeypatch):
    respx.route(host="localhost").pass_through()

    def fake_browser(url: str) -> bool:
        query = dict(urllib.parse.parse_qsl(urllib.parse.urlparse(url).query))
        threading.Thread(
            target=httpx.get,
            args=(query["redirect_uri"],),
            kwargs={"params": {"code": "the-code", "state": "forged"}, "timeout": 10},
        ).start()
        return True

    monkeypatch.setattr(auth.webbrowser, "open", fake_browser)

    with pytest.raises(AuthenticationError, match="state mismatch"):
        auth._run_browser_flow(timeout=10)


def test_browser_flow_falls_back_when_auth0_returns_an_error(monkeypatch):
    def fake_browser(url: str) -> bool:
        query = dict(urllib.parse.parse_qsl(urllib.parse.urlparse(url).query))
        threading.Thread(
            target=httpx.get,
            args=(query["redirect_uri"],),
            kwargs={
                "params": {"error": "access_denied", "error_description": "Callback not allowed"},
                "timeout": 10,
            },
        ).start()
        return True

    monkeypatch.setattr(auth.webbrowser, "open", fake_browser)

    with pytest.raises(auth._BrowserFlowUnavailable, match="Callback not allowed"):
        auth._run_browser_flow(timeout=10)


def test_authenticate_falls_back_to_the_device_code_flow(monkeypatch, capsys):
    def unavailable(**kwargs):
        raise auth._BrowserFlowUnavailable("no browser here")

    monkeypatch.setattr(auth, "_run_browser_flow", unavailable)
    monkeypatch.setattr(
        auth, "_run_device_code_flow", lambda **kwargs: ("device-token", time.time() + 3600)
    )

    assert auth.authenticate() == "device-token"
    assert "no browser here" in capsys.readouterr().out
    assert auth.read_cached_token() == "device-token"


def test_callback_server_ignores_requests_that_are_not_the_redirect():
    """A stray local request must not be mistaken for the OAuth callback."""
    server = auth._bind_callback_server()
    base = f"http://localhost:{server.server_port}/"
    try:
        stray = _request_in_background(server, base + "favicon.ico")
        assert stray.status_code == 404
        assert server.callback_query is None

        real = _request_in_background(server, base + "?code=the-code&state=st4te")
        assert real.status_code == 200
        assert server.callback_query == {"code": ["the-code"], "state": ["st4te"]}
    finally:
        server.server_close()


def test_callback_server_records_an_error_redirect():
    server = auth._bind_callback_server()
    try:
        url = f"http://localhost:{server.server_port}/?error=access_denied"
        assert _request_in_background(server, url).status_code == 200
        assert server.callback_query == {"error": ["access_denied"]}
    finally:
        server.server_close()


def test_callback_handler_bounds_a_silent_connection():
    """Set so a connection that never sends a request cannot stall the loop."""
    assert auth._CallbackHandler.timeout == auth.CALLBACK_SOCKET_TIMEOUT_SECONDS


def _addrinfo(*addresses):
    return [(family, socket.SOCK_STREAM, 6, "", (host, 0)) for family, host in addresses]


def test_loopback_address_prefers_ipv4(monkeypatch):
    monkeypatch.setattr(
        auth.socket,
        "getaddrinfo",
        lambda *a, **k: _addrinfo((socket.AF_INET6, "::1"), (socket.AF_INET, "127.0.0.1")),
    )
    assert auth._loopback_address() == (socket.AF_INET, "127.0.0.1")


def test_loopback_address_uses_ipv6_when_localhost_is_ipv6_only(monkeypatch):
    monkeypatch.setattr(
        auth.socket, "getaddrinfo", lambda *a, **k: _addrinfo((socket.AF_INET6, "::1"))
    )
    assert auth._loopback_address() == (socket.AF_INET6, "::1")


def test_loopback_address_falls_back_when_localhost_does_not_resolve(monkeypatch):
    monkeypatch.setattr(auth.socket, "getaddrinfo", lambda *a, **k: [])
    assert auth._loopback_address() == (socket.AF_INET, "127.0.0.1")


def test_callback_server_is_reachable_over_ipv6_localhost(monkeypatch):
    monkeypatch.setattr(auth, "_loopback_address", lambda: (socket.AF_INET6, "::1"))
    try:
        server = auth._bind_callback_server()
    except OSError:  # pragma: no cover - depends on the sandbox
        pytest.skip("no IPv6 loopback available")

    try:
        assert server.socket.family == socket.AF_INET6
        url = f"http://localhost:{server.server_port}/?code=the-code&state=st4te"
        assert _request_in_background(server, url).status_code == 200
    finally:
        server.server_close()


@respx.mock
def test_browser_flow_ignores_a_stray_request_before_the_redirect(monkeypatch):
    """A favicon fetch or an old tab must not abort the wait for the callback."""
    respx.route(host="localhost").pass_through()
    respx.post(auth.TOKEN_URL).mock(
        return_value=httpx.Response(200, json={"access_token": "issued", "expires_in": 3600})
    )

    def fake_browser(url: str) -> bool:
        query = dict(urllib.parse.parse_qsl(urllib.parse.urlparse(url).query))
        redirect = query["redirect_uri"]

        def visit():
            httpx.get(redirect + "favicon.ico", timeout=10)
            httpx.get(redirect, params={"code": "the-code", "state": query["state"]}, timeout=10)

        threading.Thread(target=visit).start()
        return True

    monkeypatch.setattr(auth.webbrowser, "open", fake_browser)

    token, _ = auth._run_browser_flow(timeout=10)

    assert token == "issued"


def test_browser_flow_gives_up_at_once_when_no_browser_can_be_opened(monkeypatch):
    """``webbrowser.open`` returns False instead of raising on headless hosts."""
    monkeypatch.setattr(auth.webbrowser, "open", lambda url: False)
    started = time.monotonic()

    with pytest.raises(auth._BrowserFlowUnavailable, match="no usable browser"):
        auth._run_browser_flow(timeout=60)

    assert time.monotonic() - started < 5


def test_parse_token_response_redacts_credentials_from_the_error(capsys):
    payload = {
        "id_token": "secret-jwt",
        "refresh_token": "secret-refresh",
        "error": "invalid_scope",
        "error_description": "the audience is wrong",
    }

    with pytest.raises(AuthenticationError) as excinfo:
        auth._parse_token_response(payload)

    message = str(excinfo.value)
    assert "secret-jwt" not in message
    assert "secret-refresh" not in message
    assert "<redacted>" in message
    assert "the audience is wrong" in message
    assert payload["id_token"] == "secret-jwt"  # the response itself is untouched
