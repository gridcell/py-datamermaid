"""HTTP client for the MERMAID API."""

from __future__ import annotations

import contextlib
from collections.abc import Iterator
from typing import Any
from urllib.parse import urljoin

import httpx

from . import auth
from .exceptions import AuthenticationError, MermaidAPIError

__all__ = ["MermaidClient", "client_context", "DEFAULT_BASE_URL"]

DEFAULT_BASE_URL = "https://api.datamermaid.org/v1/"
DEFAULT_TIMEOUT = 30.0
#: Page size requested from the API; the maximum it accepts is larger, but this
#: keeps individual responses a reasonable size.
DEFAULT_PAGE_SIZE = 1000
USER_AGENT = "py-datamermaid"


class MermaidClient:
    """Thin wrapper around :class:`httpx.Client` for the MERMAID API.

    Parameters
    ----------
    base_url:
        Root of the API, ending in a slash.
    token:
        Access token to use for authenticated endpoints.  When omitted, the
        token is resolved lazily through :mod:`datamermaid.auth` (environment
        variable, then the on-disk cache).
    timeout:
        Per-request timeout in seconds.
    transport:
        Optional :mod:`httpx` transport, mainly useful in tests.
    """

    def __init__(
        self,
        base_url: str = DEFAULT_BASE_URL,
        token: str | None = None,
        timeout: float = DEFAULT_TIMEOUT,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self.base_url = base_url if base_url.endswith("/") else base_url + "/"
        self.token = token
        self._http = httpx.Client(
            base_url=self.base_url,
            timeout=timeout,
            transport=transport,
            headers={"User-Agent": USER_AGENT, "Accept": "application/json"},
            follow_redirects=True,
        )

    # -- lifecycle ---------------------------------------------------------- #

    def close(self) -> None:
        self._http.close()

    def __enter__(self) -> MermaidClient:
        return self

    def __exit__(self, *exc_info: object) -> None:
        self.close()

    # -- requests ----------------------------------------------------------- #

    def _resolve_token(self) -> auth.ResolvedToken:
        resolved = auth.resolve_token(self.token)
        if resolved is None:
            raise AuthenticationError(
                "This endpoint requires a MERMAID login. Call datamermaid.authenticate() "
                f"to sign in, or set the {auth.TOKEN_ENV_VAR} environment variable."
            )
        return resolved

    def get(
        self,
        endpoint: str,
        params: dict[str, Any] | None = None,
        *,
        require_auth: bool = False,
    ) -> Any:
        """GET ``endpoint`` and return the decoded JSON body."""
        headers = {}
        resolved = None
        if require_auth:
            resolved = self._resolve_token()
            headers["Authorization"] = f"Bearer {resolved.access_token}"

        url = endpoint if endpoint.startswith("http") else urljoin(self.base_url, endpoint)
        response = self._http.get(url, params=params, headers=headers)

        if response.status_code in (401, 403) and resolved is not None:
            raise self._auth_failure(response, resolved)
        if response.status_code >= 400:
            raise MermaidAPIError(
                f"MERMAID API request to {url} failed with HTTP {response.status_code}: "
                f"{response.text.strip()[:500]}",
                status_code=response.status_code,
                url=url,
            )
        try:
            return response.json()
        except ValueError as exc:
            raise MermaidAPIError(
                f"MERMAID API returned a non-JSON response for {url}", url=url
            ) from exc

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

    def get_records(
        self,
        endpoint: str,
        params: dict[str, Any] | None = None,
        *,
        limit: int | None = None,
        require_auth: bool = False,
    ) -> list[dict[str, Any]]:
        """GET ``endpoint`` and return every record, following pagination.

        ``limit`` caps the number of records returned and stops paging early.
        """
        page_size = DEFAULT_PAGE_SIZE if limit is None else min(limit, DEFAULT_PAGE_SIZE)
        query: dict[str, Any] | None = {"limit": page_size, **(params or {})}

        records: list[dict[str, Any]] = []
        url = endpoint
        seen: set[str] = set()
        while url and url not in seen:
            seen.add(url)
            payload = self.get(url, params=query, require_auth=require_auth)
            if isinstance(payload, list):
                records.extend(payload)
                break
            if not isinstance(payload, dict):
                raise MermaidAPIError(f"Unexpected response shape for {url}: {type(payload)!r}")
            records.extend(payload.get("results") or [])
            if limit is not None and len(records) >= limit:
                break
            # ``next`` is an absolute URL that already carries the query string.
            url = payload.get("next") or ""
            query = None
        return records[:limit] if limit is not None else records


@contextlib.contextmanager
def client_context(
    client: MermaidClient | None = None, token: str | None = None
) -> Iterator[MermaidClient]:
    """Yield ``client``, or a temporary one that is closed on exit.

    ``token`` only applies to a client created here; a caller-supplied client
    keeps whatever token it was built with.
    """
    if client is not None:
        yield client
        return
    owned = MermaidClient(token=token)
    try:
        yield owned
    finally:
        owned.close()
