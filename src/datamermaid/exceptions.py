"""Exceptions raised by :mod:`datamermaid`."""

from __future__ import annotations

__all__ = [
    "MermaidError",
    "MermaidAPIError",
    "AuthenticationError",
]


class MermaidError(Exception):
    """Base class for every error raised by this package."""


class MermaidAPIError(MermaidError):
    """The MERMAID API returned an unsuccessful HTTP response."""

    def __init__(self, message: str, *, status_code: int | None = None, url: str | None = None):
        super().__init__(message)
        self.status_code = status_code
        self.url = url


class AuthenticationError(MermaidError):
    """No usable access token is available, or the API rejected the one we sent."""
