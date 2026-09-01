"""HTTP core for the MERMAID API.

:class:`MermaidClient` wraps an :class:`httpx.Client` and knows how to walk the
API's ``{count, next, previous, results}`` pagination envelope.  Endpoint
modules (see :mod:`datamermaid.projects`) stay thin: they pick a path, supply
query parameters, and hand the resulting records to
:func:`datamermaid.utils.records_to_df`.
"""

from __future__ import annotations

import contextlib
import numbers
import threading
from collections.abc import Iterator
from types import TracebackType
from typing import Any
from urllib.parse import urljoin

import httpx

from . import auth
from .exceptions import AuthenticationError, MermaidAPIError

__all__ = [
    "API_BASE_URL",
    "DEFAULT_PAGE_SIZE",
    "USER_AGENT",
    "MermaidClient",
    "check_limit",
    "client_context",
    "default_client",
    "set_default_client",
]

API_BASE_URL = "https://api.datamermaid.org/v1/"

#: The API caps ``?limit=`` at 5000 records per page.
DEFAULT_PAGE_SIZE = 5000

USER_AGENT = "https://github.com/gridcell/py-datamermaid"

DEFAULT_TIMEOUT = 60.0


def check_limit(limit: Any) -> int | None:
    """Validate a user-supplied ``limit``.

    Returns ``None`` (meaning "every record") or a positive :class:`int`.
    Anything else raises :class:`ValueError` before any HTTP call is made.
    Mirrors mermaidr's ``check_limit``.
    """
    if limit is None:
        return None

    # bool is a subclass of int, but ``get_projects(limit=True)`` is a mistake.
    if isinstance(limit, bool) or not isinstance(limit, numbers.Real):
        raise ValueError("`limit` must be None or a positive integer.")

    value = float(limit)
    if not value.is_integer() or value <= 0:
        raise ValueError("`limit` must be None or a positive integer.")

    return int(value)


class MermaidClient:
    """A client for the MERMAID API.

    Parameters
    ----------
    token:
        Optional bearer token.  When set it is sent as an ``Authorization``
        header.  When omitted, requests to endpoints that need a login resolve
        a token lazily through :mod:`datamermaid.auth` (the
        ``MERMAID_API_TOKEN`` environment variable, then the on-disk cache
        written by :func:`datamermaid.authenticate`).
    base_url:
        API root, including the version segment and a trailing slash.
    timeout:
        Per-request timeout in seconds.
    transport:
        Optional :class:`httpx.BaseTransport`, mostly useful for testing.
    """

    def __init__(
        self,
        token: str | None = None,
        *,
        base_url: str = API_BASE_URL,
        timeout: float = DEFAULT_TIMEOUT,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self.token = token
        self.base_url = base_url if base_url.endswith("/") else base_url + "/"

        headers = {"User-Agent": USER_AGENT, "Accept": "application/json"}
        if token:
            headers["Authorization"] = f"Bearer {token}"

        self._client = httpx.Client(
            headers=headers,
            timeout=timeout,
            transport=transport if transport is not None else httpx.HTTPTransport(retries=2),
        )

    # -- request plumbing --------------------------------------------------

    def url_for(self, endpoint: str) -> str:
        """Return the absolute URL for ``endpoint`` (e.g. ``"projects"``)."""
        return urljoin(self.base_url, endpoint.strip("/") + "/")

    def _resolve_token(self) -> auth.ResolvedToken:
        """Return the token to send, or explain how to obtain one."""
        resolved = auth.resolve_token(self.token)
        if resolved is None:
            raise AuthenticationError(
                "This endpoint requires a MERMAID login. Call datamermaid.authenticate() "
                f"to sign in, or set the {auth.TOKEN_ENV_VAR} environment variable."
            )
        return resolved

    @staticmethod
    def _auth_failure(
        response: httpx.Response, resolved: auth.ResolvedToken
    ) -> AuthenticationError:
        """Build the error for a refused request, invalidating the cache if needed.

        Only 401 means the token itself was refused; a 403 can simply mean the
        signed-in user lacks access to that record, so the cache is left alone.
        """
        if response.status_code != 401:
            return AuthenticationError(
                f"HTTP {response.status_code} from {response.url}. The MERMAID API accepted "
                "your login but refused this request; your account may not have access to it."
            )
        if resolved.from_cache:
            auth.clear_cached_token()
            advice = (
                "Your saved MERMAID login has been rejected and was removed. "
                "Call datamermaid.authenticate() to sign in again."
            )
        elif resolved.source == "env":
            advice = (
                f"The token in {auth.TOKEN_ENV_VAR} was rejected by the MERMAID API. "
                "Set a current token, or unset it and call datamermaid.authenticate()."
            )
        else:
            advice = (
                "The token passed to MermaidClient was rejected by the MERMAID API. "
                "Call datamermaid.authenticate() to obtain a current one."
            )
        return AuthenticationError(f"HTTP {response.status_code} from {response.url}. {advice}")

    def _get_json(
        self,
        url: str,
        params: dict[str, Any] | None = None,
        *,
        resolved: auth.ResolvedToken | None = None,
    ) -> Any:
        headers = {"Authorization": f"Bearer {resolved.access_token}"} if resolved else None
        response = self._client.get(url, params=params, headers=headers)
        if resolved is not None and response.status_code in (401, 403):
            raise self._auth_failure(response, resolved)
        if response.is_error:
            raise MermaidAPIError(
                status_code=response.status_code,
                reason=response.reason_phrase,
                url=str(response.request.url),
            )
        return response.json()

    def get_one(
        self,
        endpoint: str,
        *,
        params: dict[str, Any] | None = None,
        require_auth: bool = False,
    ) -> Any:
        """Fetch ``endpoint`` as a single object, without paginating.

        A few endpoints (``me/``, for one) answer with a bare object rather
        than the usual ``{count, next, previous, results}`` envelope.
        """
        resolved = self._resolve_token() if require_auth else None
        return self._get_json(self.url_for(endpoint), params=params, resolved=resolved)

    def get(
        self,
        endpoint: str,
        *,
        limit: int | None = None,
        params: dict[str, Any] | None = None,
        require_auth: bool = False,
    ) -> list[dict[str, Any]]:
        """Fetch every record from ``endpoint``, following pagination.

        Pages are requested at ``min(limit, 5000)`` records each.  Subsequent
        pages are fetched from the absolute ``next`` URL the API returns, so
        offsets never have to be recomputed here.  Paging stops once ``next``
        is null or ``limit`` records have been collected; the result is then
        truncated to exactly ``limit``.

        ``require_auth`` resolves an access token before the first request and
        sends it as a bearer token on every page.
        """
        limit = check_limit(limit)
        resolved = self._resolve_token() if require_auth else None

        query: dict[str, Any] | None = dict(params or {})
        query["limit"] = DEFAULT_PAGE_SIZE if limit is None else min(limit, DEFAULT_PAGE_SIZE)

        url: str | None = self.url_for(endpoint)
        records: list[dict[str, Any]] = []

        while url is not None:
            payload = self._get_json(url, params=query, resolved=resolved)
            # ``next`` is absolute and carries its own query string.
            query = None

            if isinstance(payload, list):
                records.extend(payload)
                break
            if not isinstance(payload, dict) or "results" not in payload:
                # Not a paginated envelope (e.g. a single object); return as-is.
                records.append(payload)
                break

            records.extend(payload["results"] or [])

            if limit is not None and len(records) >= limit:
                break
            url = payload.get("next")

        if limit is not None:
            del records[limit:]
        return records

    # -- lifecycle ---------------------------------------------------------

    def close(self) -> None:
        """Close the underlying HTTP connection pool."""
        self._client.close()

    def __enter__(self) -> MermaidClient:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        self.close()

    def __repr__(self) -> str:
        return f"MermaidClient(base_url={self.base_url!r}, authenticated={bool(self.token)})"


_default_client: MermaidClient | None = None
_default_client_lock = threading.Lock()


def default_client() -> MermaidClient:
    """Return the process-wide client used by the module-level functions."""
    global _default_client
    with _default_client_lock:
        if _default_client is None:
            _default_client = MermaidClient()
        return _default_client


def set_default_client(client: MermaidClient | None) -> None:
    """Replace the process-wide client; pass ``None`` to reset it."""
    global _default_client
    with _default_client_lock:
        _default_client = client


@contextlib.contextmanager
def client_context(
    client: MermaidClient | None = None,
    token: str | None = None,
) -> Iterator[MermaidClient]:
    """Yield the client an endpoint function should use.

    A caller-supplied ``client`` is used as it is.  A ``token`` builds a
    throwaway client that is closed on exit.  With neither, the process-wide
    client is used; it resolves a token lazily when an endpoint needs one.
    """
    if client is not None:
        yield client
        return
    if token is None:
        yield default_client()
        return
    owned = MermaidClient(token=token)
    try:
        yield owned
    finally:
        owned.close()
