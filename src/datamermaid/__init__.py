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
from .project_endpoints import (
    DEFAULT_PROJECT_ENV_VAR,
    as_project_ids,
    get_default_project,
    get_project_endpoint,
    get_project_managements,
    get_project_sites,
    set_default_project,
)
from .projects import get_my_projects, get_projects, search_my_projects, search_projects

__version__ = "0.1.0"

__all__ = [
    "API_BASE_URL",
    "DEFAULT_PAGE_SIZE",
    "DEFAULT_PROJECT_ENV_VAR",
    "TOKEN_ENV_VAR",
    "AuthenticationError",
    "MermaidAPIError",
    "MermaidClient",
    "MermaidError",
    "__version__",
    "as_project_ids",
    "authenticate",
    "clear_cached_token",
    "default_client",
    "get_default_project",
    "get_me",
    "get_my_projects",
    "get_project_endpoint",
    "get_project_managements",
    "get_project_sites",
    "get_projects",
    "get_token",
    "search_my_projects",
    "search_projects",
    "set_default_client",
    "set_default_project",
]
