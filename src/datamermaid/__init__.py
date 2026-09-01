"""A Python client for the MERMAID coral reef monitoring API.

Example
-------
>>> import datamermaid
>>> datamermaid.get_projects(limit=5)  # doctest: +SKIP

Endpoints that need a login read a token from the ``MERMAID_API_TOKEN``
environment variable or from the cache written by :func:`authenticate`:

>>> datamermaid.authenticate()  # doctest: +SKIP
>>> datamermaid.get_my_projects()  # doctest: +SKIP
"""

from __future__ import annotations

from .auth import TOKEN_ENV_VAR, authenticate, clear_cached_token, get_token
from .client import (
    API_BASE_URL,
    DEFAULT_PAGE_SIZE,
    MermaidClient,
    default_client,
    set_default_client,
)
from .exceptions import AuthenticationError, MermaidAPIError, MermaidError
from .me import get_me
from .project_data import (
    DATA_LEVELS,
    METHODS,
    construct_endpoints,
    get_project_data,
)
from .projects import get_my_projects, get_projects, search_my_projects, search_projects

__version__ = "0.1.0"

__all__ = [
    "API_BASE_URL",
    "DATA_LEVELS",
    "DEFAULT_PAGE_SIZE",
    "METHODS",
    "TOKEN_ENV_VAR",
    "AuthenticationError",
    "MermaidAPIError",
    "MermaidClient",
    "MermaidError",
    "__version__",
    "authenticate",
    "clear_cached_token",
    "construct_endpoints",
    "default_client",
    "get_me",
    "get_my_projects",
    "get_project_data",
    "get_projects",
    "get_token",
    "search_my_projects",
    "search_projects",
    "set_default_client",
]
