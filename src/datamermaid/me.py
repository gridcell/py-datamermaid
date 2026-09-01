"""The signed-in user's MERMAID profile."""

from __future__ import annotations

from typing import Any

from .client import MermaidClient, client_context
from .exceptions import MermaidAPIError

__all__ = ["get_me"]


def get_me(
    *,
    client: MermaidClient | None = None,
    token: str | None = None,
) -> dict[str, Any]:
    """Get the profile of the signed-in user.

    Requires a login.  The token comes from ``token``, from the
    ``MERMAID_API_TOKEN`` environment variable, or from the cache written by
    :func:`datamermaid.authenticate`.

    Unlike most MERMAID endpoints, ``me/`` answers with a single object rather
    than a paginated list, so the response is returned as a dict rather than a
    data frame.

    Examples
    --------
    >>> import datamermaid
    >>> datamermaid.get_me()  # doctest: +SKIP
    """
    with client_context(client, token) as api:
        payload = api.get_one("me", require_auth=True)

    if not isinstance(payload, dict):
        raise MermaidAPIError(
            status_code=200,
            reason=f"expected an object from me/, got {type(payload).__name__}",
            url=api.url_for("me"),
        )
    return payload
