"""A Python client for the MERMAID coral reef monitoring API.

Example
-------
>>> import datamermaid
>>> datamermaid.get_projects(limit=5)  # doctest: +SKIP
"""

from __future__ import annotations

from .client import (
    API_BASE_URL,
    DEFAULT_PAGE_SIZE,
    MermaidClient,
    default_client,
    set_default_client,
)
from .exceptions import AuthenticationError, MermaidAPIError, MermaidError
from .project_endpoints import (
    DEFAULT_PROJECT_ENV_VAR,
    as_project_ids,
    get_default_project,
    get_project_endpoint,
    get_project_managements,
    get_project_sites,
    set_default_project,
)
from .projects import get_projects

__version__ = "0.1.0"

__all__ = [
    "API_BASE_URL",
    "DEFAULT_PAGE_SIZE",
    "DEFAULT_PROJECT_ENV_VAR",
    "AuthenticationError",
    "MermaidAPIError",
    "MermaidClient",
    "MermaidError",
    "__version__",
    "as_project_ids",
    "default_client",
    "get_default_project",
    "get_project_endpoint",
    "get_project_managements",
    "get_project_sites",
    "get_projects",
    "set_default_client",
    "set_default_project",
]
