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
from .exceptions import MermaidAPIError, MermaidError
from .projects import get_projects

__version__ = "0.1.0"

__all__ = [
    "API_BASE_URL",
    "DEFAULT_PAGE_SIZE",
    "MermaidAPIError",
    "MermaidClient",
    "MermaidError",
    "__version__",
    "default_client",
    "get_projects",
    "set_default_client",
]
