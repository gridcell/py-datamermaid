"""HTTP core for the MERMAID API.

:class:`MermaidClient` wraps an :class:`httpx.Client` and knows how to walk the
API's ``{count, next, previous, results}`` pagination envelope.  Endpoint
modules (see :mod:`datamermaid.projects`) stay thin: they pick a path, supply
query parameters, and hand the resulting records to
:func:`datamermaid.utils.records_to_df`.
"""

from __future__ import annotations

import numbers
import threading
from types import TracebackType
from typing import Any
from urllib.parse import urljoin

import httpx

from .exceptions import MermaidAPIError

__all__ = [
    "API_BASE_URL",
    "DEFAULT_PAGE_SIZE",
    "USER_AGENT",
    "MermaidClient",
    "check_limit",
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
        header.  Acquiring a token is out of scope for this client.
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

    def _get_json(self, url: str, params: dict[str, Any] | None = None) -> Any:
        response = self._client.get(url, params=params)
        if response.is_error:
            raise MermaidAPIError(
                status_code=response.status_code,
                reason=response.reason_phrase,
                url=str(response.request.url),
            )
        return response.json()

    def get(
        self,
        endpoint: str,
        *,
        limit: int | None = None,
        params: dict[str, Any] | None = None,
    ) -> list[dict[str, Any]]:
        """Fetch every record from ``endpoint``, following pagination.

        Pages are requested at ``min(limit, 5000)`` records each.  Subsequent
        pages are fetched from the absolute ``next`` URL the API returns, so
        offsets never have to be recomputed here.  Paging stops once ``next``
        is null or ``limit`` records have been collected; the result is then
        truncated to exactly ``limit``.
        """
        limit = check_limit(limit)

        query: dict[str, Any] | None = dict(params or {})
        query["limit"] = DEFAULT_PAGE_SIZE if limit is None else min(limit, DEFAULT_PAGE_SIZE)

        url: str | None = self.url_for(endpoint)
        records: list[dict[str, Any]] = []

        while url is not None:
            payload = self._get_json(url, params=query)
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
