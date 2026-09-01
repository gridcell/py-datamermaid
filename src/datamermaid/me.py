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

    Parameters
    ----------
    client:
        Client to issue the request with.  Defaults to the process-wide client.
    token:
        Bearer token for this call only.  Mutually exclusive with ``client``.

    Returns
    -------
    dict
        The profile as MERMAID returns it: ``id``, ``first_name``,
        ``last_name``, ``email``, ``full_name``, ``projects`` and so on.

    Raises
    ------
    AuthenticationError
        If no access token can be resolved, or MERMAID rejects it.

    Examples
    --------
    >>> import datamermaid
    >>> me = datamermaid.get_me()  # doctest: +SKIP
    >>> me["full_name"]  # doctest: +SKIP
    'Ada Lovelace'
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
