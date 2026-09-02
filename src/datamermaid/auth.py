"""Auth0 authentication for the MERMAID API.

The MERMAID API is protected by Auth0.  ``datamermaid`` obtains an access token
in one of three ways, in order of precedence:

1. the ``MERMAID_API_TOKEN`` environment variable (headless / CI use),
2. a non-expired token cached on disk from a previous sign-in,
3. an interactive sign-in through the browser (:func:`authenticate`).

The interactive flow is an OAuth2 Authorization Code grant with PKCE against the
public MERMAID Auth0 client -- there is no client secret.  When the loopback
redirect cannot be used (port unavailable, no browser, or Auth0 refusing the
callback URL) the flow falls back to the Device Authorization Grant, which only
requires the user to open a URL and type a code.
"""

from __future__ import annotations

import base64
import contextlib
import hashlib
import http.server
import json
import os
import secrets
import socket
import time
import urllib.parse
import webbrowser
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from pathlib import Path

import httpx

from .exceptions import AuthenticationError

__all__ = ["TOKEN_ENV_VAR", "authenticate", "clear_cached_token", "get_token"]

AUTH0_DOMAIN = "datamermaid.auth0.com"
AUTHORIZE_URL = f"https://{AUTH0_DOMAIN}/authorize"
TOKEN_URL = f"https://{AUTH0_DOMAIN}/oauth/token"
DEVICE_CODE_URL = f"https://{AUTH0_DOMAIN}/oauth/device/code"
CLIENT_ID = "6q1XvYG0n75ZaLbFko0gUV4xGud4uPyG"
AUDIENCE = "https://api.datamermaid.org"
SCOPE = "openid profile email"
DEVICE_CODE_GRANT = "urn:ietf:params:oauth:grant-type:device_code"

#: Environment variable checked before the cache and the browser flow.
TOKEN_ENV_VAR = "MERMAID_API_TOKEN"

#: ``mermaidr`` (and httr) use this port, so it is the one Auth0 is known to
#: allow as a callback for this client.  An ephemeral port is tried after it.
DEFAULT_REDIRECT_PORT = 1410

#: Tokens are treated as expired this many seconds before they really are, so a
#: request started just under the wire does not fail in flight.
EXPIRY_SKEW_SECONDS = 60.0

#: Auth0 access tokens for this client last about a day; used when the token
#: response omits ``expires_in``.
DEFAULT_EXPIRES_IN = 86400.0

#: How long to wait for the browser redirect before falling back.
BROWSER_TIMEOUT_SECONDS = 180.0

#: How long a single connection to the callback server may stay silent.  Browsers
#: routinely open speculative connections without sending a request; without this
#: one of them would block the single-threaded handler loop forever.
CALLBACK_SOCKET_TIMEOUT_SECONDS = 10.0

#: Keys whose values must never be echoed back in an error message.
_SECRET_RESPONSE_KEYS = frozenset(
    {"access_token", "id_token", "refresh_token", "device_code", "code", "token"}
)

HTTP_TIMEOUT_SECONDS = 30.0

_CALLBACK_PAGE = b"""<!doctype html>
<html><head><title>MERMAID</title></head>
<body style="font-family: sans-serif; padding: 3rem">
<h1>Signed in to MERMAID</h1>
<p>You can close this tab and return to Python.</p>
</body></html>
"""


@dataclass(frozen=True)
class ResolvedToken:
    """An access token together with where it came from."""

    access_token: str
    #: One of ``"explicit"``, ``"env"`` or ``"cache"``.
    source: str

    @property
    def from_cache(self) -> bool:
        return self.source == "cache"


class _BrowserFlowUnavailable(Exception):
    """Internal signal that the loopback flow cannot be completed."""


# --------------------------------------------------------------------------- #
# Token cache
# --------------------------------------------------------------------------- #


def _cache_dir() -> Path:
    """Config directory for this package, honouring ``XDG_CONFIG_HOME``."""
    xdg = os.environ.get("XDG_CONFIG_HOME")
    base = Path(xdg).expanduser() if xdg else Path.home() / ".config"
    return base / "datamermaid"


def _cache_path() -> Path:
    return _cache_dir() / "token.json"


def _is_expired(expires_at: float | None, *, now: float | None = None) -> bool:
    if expires_at is None:
        return True
    now = time.time() if now is None else now
    return float(expires_at) - EXPIRY_SKEW_SECONDS <= now


def _read_cache() -> dict | None:
    path = _cache_path()
    try:
        with path.open(encoding="utf-8") as handle:
            data = json.load(handle)
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) else None


def read_cached_token(*, now: float | None = None) -> str | None:
    """Return the cached access token, or ``None`` if missing or expired."""
    data = _read_cache()
    if not data:
        return None
    token = data.get("access_token")
    if not token or not isinstance(token, str):
        return None
    try:
        expires_at = float(data["expires_at"])
    except (KeyError, TypeError, ValueError):
        return None
    if _is_expired(expires_at, now=now):
        return None
    return token


def _write_cache(access_token: str, expires_at: float) -> Path:
    """Store the token at :func:`_cache_path` with owner-only permissions."""
    path = _cache_path()
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    payload = json.dumps({"access_token": access_token, "expires_at": expires_at}, indent=2).encode(
        "utf-8"
    )
    tmp = path.with_name(path.name + ".tmp")
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    try:
        os.write(fd, payload)
    finally:
        os.close(fd)
    os.replace(tmp, path)
    return path


def clear_cached_token() -> None:
    """Delete the cached token, if any.

    The next :func:`authenticate` call then signs in afresh.  Only the on-disk
    cache is touched; a token in ``MERMAID_API_TOKEN`` keeps being used.

    Examples
    --------
    >>> import datamermaid
    >>> datamermaid.clear_cached_token()  # doctest: +SKIP
    >>> datamermaid.get_token() is None  # doctest: +SKIP
    True
    """
    with contextlib.suppress(OSError):
        _cache_path().unlink(missing_ok=True)


# --------------------------------------------------------------------------- #
# PKCE / request helpers
# --------------------------------------------------------------------------- #


def _b64url(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def _pkce_pair() -> tuple[str, str]:
    """Return a ``(code_verifier, code_challenge)`` pair for PKCE S256."""
    verifier = _b64url(secrets.token_bytes(32))
    challenge = _b64url(hashlib.sha256(verifier.encode("ascii")).digest())
    return verifier, challenge


def _authorize_url(*, redirect_uri: str, code_challenge: str, state: str) -> str:
    params = {
        "response_type": "code",
        "client_id": CLIENT_ID,
        "redirect_uri": redirect_uri,
        "audience": AUDIENCE,
        "scope": SCOPE,
        "state": state,
        "code_challenge": code_challenge,
        "code_challenge_method": "S256",
    }
    return f"{AUTHORIZE_URL}?{urllib.parse.urlencode(params)}"


def _token_request_payload(*, code: str, code_verifier: str, redirect_uri: str) -> dict[str, str]:
    return {
        "grant_type": "authorization_code",
        "client_id": CLIENT_ID,
        "code": code,
        "code_verifier": code_verifier,
        "redirect_uri": redirect_uri,
        "audience": AUDIENCE,
    }


def _device_code_payload() -> dict[str, str]:
    return {"client_id": CLIENT_ID, "audience": AUDIENCE, "scope": SCOPE}


def _device_token_payload(device_code: str) -> dict[str, str]:
    return {
        "grant_type": DEVICE_CODE_GRANT,
        "client_id": CLIENT_ID,
        "device_code": device_code,
    }


def _redacted(payload: dict) -> dict:
    """Copy ``payload`` with any credential-bearing values masked.

    A response missing ``access_token`` can still carry an ``id_token`` or a
    refresh token, and this ends up in an exception message and the logs.
    """
    return {
        key: ("<redacted>" if key in _SECRET_RESPONSE_KEYS and value else value)
        for key, value in payload.items()
    }


def _parse_token_response(payload: dict, *, now: float | None = None) -> tuple[str, float]:
    """Turn an Auth0 token response into ``(access_token, expires_at)``."""
    token = payload.get("access_token")
    if not token:
        raise AuthenticationError(
            "Auth0 did not return an access token; the response was: "
            f"{json.dumps(_redacted(payload), default=str)}"
        )
    now = time.time() if now is None else now
    try:
        expires_in = float(payload.get("expires_in") or DEFAULT_EXPIRES_IN)
    except (TypeError, ValueError):
        expires_in = DEFAULT_EXPIRES_IN
    return token, now + expires_in


@contextlib.contextmanager
def _http_client(client: httpx.Client | None = None) -> Iterator[httpx.Client]:
    if client is not None:
        yield client
        return
    with httpx.Client(timeout=HTTP_TIMEOUT_SECONDS) as owned:
        yield owned


def _auth0_error(response: httpx.Response) -> str:
    with contextlib.suppress(ValueError):
        body = response.json()
        if isinstance(body, dict):
            description = body.get("error_description") or body.get("error")
            if description:
                return str(description)
    return response.text.strip() or f"HTTP {response.status_code}"


def _post_auth0(url: str, payload: dict[str, str], *, client: httpx.Client | None = None) -> dict:
    with _http_client(client) as http:
        response = http.post(url, data=payload)
    try:
        body = response.json()
    except ValueError:
        body = {}
    if response.status_code >= 400:
        raise AuthenticationError(f"Auth0 rejected the request: {_auth0_error(response)}")
    if not isinstance(body, dict):
        raise AuthenticationError(f"Unexpected response from {url}: {response.text!r}")
    return body


def _exchange_code(
    *,
    code: str,
    code_verifier: str,
    redirect_uri: str,
    client: httpx.Client | None = None,
    now: float | None = None,
) -> tuple[str, float]:
    payload = _token_request_payload(
        code=code, code_verifier=code_verifier, redirect_uri=redirect_uri
    )
    return _parse_token_response(_post_auth0(TOKEN_URL, payload, client=client), now=now)


# --------------------------------------------------------------------------- #
# Device authorization grant
# --------------------------------------------------------------------------- #


def _poll_device_token(
    *,
    device_code: str,
    interval: float,
    deadline: float,
    client: httpx.Client | None = None,
    sleep: Callable[[float], None] = time.sleep,
    monotonic: Callable[[], float] = time.monotonic,
) -> dict:
    """Poll the token endpoint until the user approves the device code."""
    payload = _device_token_payload(device_code)
    with _http_client(client) as http:
        while monotonic() < deadline:
            response = http.post(TOKEN_URL, data=payload)
            try:
                body = response.json()
            except ValueError:
                body = {}
            if response.status_code < 400:
                return body if isinstance(body, dict) else {}
            error = body.get("error") if isinstance(body, dict) else None
            if error == "slow_down":
                interval += 5
            elif error != "authorization_pending":
                raise AuthenticationError(f"Auth0 rejected the request: {_auth0_error(response)}")
            sleep(interval)
    raise AuthenticationError(
        "Timed out waiting for the sign-in to be approved. "
        "Call datamermaid.authenticate() to try again."
    )


def _run_device_code_flow(
    *,
    client: httpx.Client | None = None,
    now: float | None = None,
) -> tuple[str, float]:
    body = _post_auth0(DEVICE_CODE_URL, _device_code_payload(), client=client)
    verification_uri = body.get("verification_uri_complete") or body.get("verification_uri")
    print(
        "To sign in to MERMAID, open this page and enter the code below:\n"
        f"  {verification_uri}\n"
        f"  code: {body.get('user_code')}"
    )
    with contextlib.suppress(Exception):  # pragma: no cover - convenience only
        webbrowser.open(str(verification_uri))
    interval = float(body.get("interval") or 5)
    expires_in = float(body.get("expires_in") or 900)
    token_response = _poll_device_token(
        device_code=str(body.get("device_code")),
        interval=interval,
        deadline=time.monotonic() + expires_in,
        client=client,
    )
    return _parse_token_response(token_response, now=now)


# --------------------------------------------------------------------------- #
# Loopback (authorization code + PKCE) flow
# --------------------------------------------------------------------------- #


class _CallbackHandler(http.server.BaseHTTPRequestHandler):
    """Handler that records the query string of the OAuth redirect.

    The redirect port is fixed and well known, so unrelated local requests --
    a favicon fetch, a restored browser tab from an earlier attempt, a port
    probe -- do reach this server.  Only a request that actually looks like the
    Auth0 callback is recorded; everything else gets a 404 and the flow keeps
    waiting for the real one.
    """

    #: Applied to the connection socket by ``StreamRequestHandler.setup``, so a
    #: client that connects without sending a request cannot stall the loop.
    timeout = CALLBACK_SOCKET_TIMEOUT_SECONDS

    def do_GET(self) -> None:  # noqa: N802 - name mandated by BaseHTTPRequestHandler
        query = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
        if not ("code" in query or "error" in query):
            self.send_error(404)
            return
        self.server.callback_query = query  # type: ignore[attr-defined]
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(_CALLBACK_PAGE)))
        self.end_headers()
        self.wfile.write(_CALLBACK_PAGE)

    def log_message(self, *args: object) -> None:
        """Silence the default stderr access log."""


def _loopback_address() -> tuple[int, str]:
    """Return the ``(family, host)`` to bind so ``localhost`` reaches us.

    The redirect URI has to say ``localhost`` (that is what Auth0 whitelists),
    but on some hosts that name resolves only to ``::1``, where a server bound
    to ``127.0.0.1`` would never be reached.  IPv4 is preferred when available
    because browsers fall back to it, and it keeps the well-known port check
    meaningful.
    """
    try:
        infos = socket.getaddrinfo("localhost", None, type=socket.SOCK_STREAM)
    except OSError:  # pragma: no cover - name resolution is always available
        infos = []
    candidates = [
        (int(family), str(sockaddr[0]))
        for family, _type, _proto, _canon, sockaddr in infos
        if family in (socket.AF_INET, socket.AF_INET6)
    ]
    for family, host in candidates:
        if family == socket.AF_INET:
            return family, host
    return candidates[0] if candidates else (int(socket.AF_INET), "127.0.0.1")


class _CallbackServer(http.server.HTTPServer):
    """Loopback HTTP server that holds the recorded OAuth callback query."""

    callback_query: dict[str, list[str]] | None = None


class _CallbackServerV6(_CallbackServer):
    """The same server for hosts where ``localhost`` is IPv6-only."""

    address_family = socket.AF_INET6


def _bind_callback_server() -> _CallbackServer:
    family, host = _loopback_address()
    server_class = _CallbackServerV6 if family == socket.AF_INET6 else _CallbackServer
    for port in (DEFAULT_REDIRECT_PORT, 0):
        try:
            server = server_class((host, port), _CallbackHandler)
        except OSError:
            continue
        server.callback_query = None
        return server
    raise _BrowserFlowUnavailable("could not listen for the sign-in redirect on localhost")


def _run_browser_flow(
    *,
    timeout: float = BROWSER_TIMEOUT_SECONDS,
    client: httpx.Client | None = None,
) -> tuple[str, float]:
    server = _bind_callback_server()
    try:
        redirect_uri = f"http://localhost:{server.server_port}/"
        code_verifier, code_challenge = _pkce_pair()
        state = secrets.token_urlsafe(16)
        url = _authorize_url(redirect_uri=redirect_uri, code_challenge=code_challenge, state=state)
        print(f"Opening your browser to sign in to MERMAID.\nIf it does not open, visit:\n  {url}")
        # ``open`` returns False (it does not raise) when no browser is
        # registered, e.g. on a headless machine; waiting out the timeout in
        # that case would only delay the device code fallback.
        try:
            opened = webbrowser.open(url)
        except webbrowser.Error:  # pragma: no cover - platform dependent
            opened = False
        if not opened:
            raise _BrowserFlowUnavailable("no usable browser was found")

        deadline = time.monotonic() + timeout
        query = None
        while query is None:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                break
            # Only bound the wait for the next connection; requests that are not
            # the callback (see _CallbackHandler) leave callback_query unset.
            server.timeout = remaining
            server.handle_request()
            query = getattr(server, "callback_query", None) or None
        if query is None:
            raise _BrowserFlowUnavailable("timed out waiting for the browser redirect")
        if "error" in query:
            raise _BrowserFlowUnavailable(query.get("error_description", query["error"])[0])
        if query.get("state", [None])[0] != state:
            raise AuthenticationError(
                "The sign-in response did not match the request (state mismatch); "
                "the redirect may have been tampered with."
            )
        code = query.get("code", [None])[0]
        if not code:
            raise _BrowserFlowUnavailable("the redirect did not contain an authorization code")
    finally:
        server.server_close()
    return _exchange_code(
        code=code, code_verifier=code_verifier, redirect_uri=redirect_uri, client=client
    )


# --------------------------------------------------------------------------- #
# Public API
# --------------------------------------------------------------------------- #


def _env_token() -> str | None:
    token = os.environ.get(TOKEN_ENV_VAR)
    token = token.strip() if token else ""
    return token or None


def resolve_token(explicit_token: str | None = None) -> ResolvedToken | None:
    """Return the token to use, without ever prompting the user.

    Precedence is explicit argument, then :data:`TOKEN_ENV_VAR`, then the cache.
    """
    if explicit_token:
        return ResolvedToken(explicit_token, "explicit")
    env = _env_token()
    if env:
        return ResolvedToken(env, "env")
    cached = read_cached_token()
    if cached:
        return ResolvedToken(cached, "cache")
    return None


def get_token() -> str | None:
    """Return a usable access token from the environment or the cache.

    Mirrors mermaidr's ``mermaid_token()``, except that it never prompts:
    ``MERMAID_API_TOKEN`` is checked first, then the cache written by
    :func:`authenticate`.

    Returns
    -------
    str or None
        The bearer token, or ``None`` when the user has never signed in (or
        the cached token has expired); call :func:`authenticate` to obtain
        one interactively.

    Examples
    --------
    >>> import datamermaid
    >>> token = datamermaid.get_token() or datamermaid.authenticate()  # doctest: +SKIP
    """
    resolved = resolve_token()
    return resolved.access_token if resolved else None


def authenticate(
    new_user: bool = False,
    *,
    use_device_code: bool = False,
    timeout: float = BROWSER_TIMEOUT_SECONDS,
) -> str:
    """Sign in to MERMAID and return an access token.

    The token is cached in ``$XDG_CONFIG_HOME/datamermaid/token.json`` (by
    default ``~/.config/datamermaid/token.json``) so subsequent sessions do not
    need to sign in again until it expires, roughly a day later.

    Parameters
    ----------
    new_user:
        Clear the cached token first, so a different account can sign in.
    use_device_code:
        Skip the browser redirect and use the Device Authorization Grant, which
        only needs a URL and a code (useful over SSH).
    timeout:
        Seconds to wait for the browser redirect before falling back to the
        device code flow.

    Returns
    -------
    str
        The bearer token, which is also cached.  When ``MERMAID_API_TOKEN`` is
        set, or a non-expired token is cached, it is returned without any
        sign-in.

    Raises
    ------
    AuthenticationError
        If the sign-in does not complete, e.g. Auth0 rejects the request or
        the user never finishes the flow.

    Examples
    --------
    >>> import datamermaid
    >>> datamermaid.authenticate()  # opens a browser  # doctest: +SKIP
    >>> datamermaid.authenticate(use_device_code=True)  # over SSH  # doctest: +SKIP
    >>> datamermaid.authenticate(new_user=True)  # sign in as someone else  # doctest: +SKIP
    """
    if new_user:
        clear_cached_token()

    env = _env_token()
    if env:
        return env

    cached = read_cached_token()
    if cached:
        return cached

    if use_device_code:
        access_token, expires_at = _run_device_code_flow()
    else:
        try:
            access_token, expires_at = _run_browser_flow(timeout=timeout)
        except _BrowserFlowUnavailable as exc:
            print(f"Browser sign-in unavailable ({exc}); falling back to a device code.")
            access_token, expires_at = _run_device_code_flow()

    _write_cache(access_token, expires_at)
    return access_token
