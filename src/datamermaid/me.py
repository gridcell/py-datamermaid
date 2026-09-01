"""The signed-in user's MERMAID profile."""

from __future__ import annotations

from typing import Any

from .client import MermaidClient, client_context
from .exceptions import MermaidAPIError

__all__ = ["get_me"]

ME_ENDPOINT = "me/"


def get_me(
    *,
    client: MermaidClient | None = None,
    token: str | None = None,
) -> dict[str, Any]:
    """Return the profile of the signed-in user.

    Unlike most MERMAID endpoints, ``me/`` returns a single object rather than a
    paginated list, so the response is returned as-is.
    """
    with client_context(client, token) as api:
        payload = api.get(ME_ENDPOINT, require_auth=True)
    if not isinstance(payload, dict):
        raise MermaidAPIError(f"Expected an object from {ME_ENDPOINT}, got {type(payload)!r}")
    return payload
