"""Exceptions raised by :mod:`datamermaid`."""

from __future__ import annotations

__all__ = ["MermaidError", "MermaidAPIError", "AuthenticationError"]


class MermaidError(Exception):
    """Base class for all errors raised by this package."""


class MermaidAPIError(MermaidError):
    """Raised when the MERMAID API returns an unsuccessful HTTP response.

    Mirrors ``check_errors`` in mermaidr, which surfaces the status code and
    the reason phrase of the failed request.
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
    """Raised when an endpoint requires a bearer token and none is available.

    Mirrors mermaidr's refusal to call an authenticated endpoint without
    credentials.  Raised before any HTTP request is made.
    """
