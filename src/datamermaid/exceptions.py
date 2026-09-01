"""Exceptions raised by :mod:`datamermaid`."""

from __future__ import annotations

__all__ = ["AuthenticationError", "MermaidAPIError", "MermaidError"]


class MermaidError(Exception):
    """Base class for all errors raised by this package.

    Catch this to handle any failure the package itself reports -- an HTTP
    error (:class:`MermaidAPIError`) or a missing or rejected login
    (:class:`AuthenticationError`).  Argument mistakes such as an unknown
    survey method raise the built-in :class:`ValueError` instead.

    Examples
    --------
    >>> import datamermaid
    >>> try:
    ...     datamermaid.get_my_projects()
    ... except datamermaid.MermaidError as exc:
    ...     print(exc)  # doctest: +SKIP
    """


class MermaidAPIError(MermaidError):
    """Raised when the MERMAID API returns an unsuccessful HTTP response.

    Mirrors ``check_errors`` in mermaidr, which surfaces the status code and
    the reason phrase of the failed request.

    Attributes
    ----------
    status_code:
        HTTP status of the failed response, e.g. ``404``.
    reason:
        Reason phrase of the response, e.g. ``"Not Found"``.
    url:
        URL that was requested, when known.

    Examples
    --------
    >>> import datamermaid
    >>> try:
    ...     datamermaid.get_project_sites("not-a-project")
    ... except datamermaid.MermaidAPIError as exc:
    ...     exc.status_code  # doctest: +SKIP
    404
    """

    def __init__(self, status_code: int, reason: str = "", url: str | None = None) -> None:
        self.status_code = status_code
        self.reason = reason
        self.url = url

        message = f"MERMAID API request failed: ({status_code}) {reason}".rstrip()
        if url:
            message = f"{message} [{url}]"
        super().__init__(message)


class AuthenticationError(MermaidError):
    """No usable access token is available, or the API rejected the one we sent.

    When a token cannot be found at all, this is raised before any HTTP
    request is made, mirroring mermaidr's refusal to call an authenticated
    endpoint without credentials.  The message says how to obtain a token:
    call :func:`datamermaid.authenticate`, or set ``MERMAID_API_TOKEN``.

    Examples
    --------
    >>> import datamermaid
    >>> datamermaid.clear_cached_token()  # doctest: +SKIP
    >>> datamermaid.get_me()  # doctest: +SKIP
    Traceback (most recent call last):
        ...
    datamermaid.exceptions.AuthenticationError: ...
    """
