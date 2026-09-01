"""Python client for the MERMAID coral reef monitoring API."""

from __future__ import annotations

from .auth import TOKEN_ENV_VAR, authenticate, clear_cached_token, get_token
from .client import DEFAULT_BASE_URL, MermaidClient
from .exceptions import AuthenticationError, MermaidAPIError, MermaidError
from .me import get_me
from .projects import get_my_projects, get_projects, search_my_projects, search_projects

__version__ = "0.1.0"

__all__ = [
    "DEFAULT_BASE_URL",
    "TOKEN_ENV_VAR",
    "AuthenticationError",
    "MermaidAPIError",
    "MermaidClient",
    "MermaidError",
    "__version__",
    "authenticate",
    "clear_cached_token",
    "get_me",
    "get_my_projects",
    "get_projects",
    "get_token",
    "search_my_projects",
    "search_projects",
]
