"""A Python client for the MERMAID coral reef monitoring API.

A port of the R package `mermaidr <https://github.com/data-mermaid/mermaidr>`_.
Each ``mermaid_*`` function has a ``datamermaid`` equivalent without the
prefix -- see the migration table in the README.  Tabular results are
:class:`pandas.DataFrame` objects.

The workflow mirrors mermaidr's: sign in, find projects, pull their data.

>>> import datamermaid
>>> datamermaid.authenticate()  # doctest: +SKIP
>>> projects = datamermaid.get_my_projects()  # doctest: +SKIP
>>> fish = datamermaid.get_project_data(projects, "fishbelt", "sampleevents")  # doctest: +SKIP

Public endpoints need no login:

>>> datamermaid.get_projects(limit=5)  # doctest: +SKIP
>>> datamermaid.get_reference("fishfamilies")  # doctest: +SKIP

Endpoints that need a login read a token from the ``MERMAID_API_TOKEN``
environment variable or from the cache written by :func:`authenticate`; see
:mod:`datamermaid.auth`.

Modules
-------
:mod:`datamermaid.auth`
    Sign-in and the token cache.
:mod:`datamermaid.client`
    :class:`MermaidClient`, the HTTP layer every function goes through.
:mod:`datamermaid.projects`
    Listing and searching projects.
:mod:`datamermaid.project_endpoints`
    Project-scoped endpoints (sites, managements) and the default project.
:mod:`datamermaid.project_data`
    Survey data by method and aggregation level.
:mod:`datamermaid.endpoints`
    Global, unauthenticated endpoints and reference tables.
:mod:`datamermaid.import_`
    The write path: templates, checks, ingest and bulk actions.
:mod:`datamermaid.reports`
    Generated reports (GFCR), returned as a dict of frames.
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
from .endpoints import (
    CLASSIFICATION_PROVIDERS,
    KNOWN_ENDPOINTS,
    REFERENCE_ENDPOINTS,
    countries,
    get_choices,
    get_classification_labelmappings,
    get_endpoint,
    get_managements,
    get_reference,
    get_sites,
    get_summary_sampleevents,
)
from .exceptions import AuthenticationError, MermaidAPIError, MermaidError
from .import_ import (
    METHOD_ENDPOINTS,
    import_bulk_edit,
    import_bulk_submit,
    import_bulk_validate,
    import_check_options,
    import_get_template_and_options,
    import_project_data,
)
from .me import get_me
from .project_data import (
    DATA_LEVELS,
    METHODS,
    construct_endpoints,
    get_project_data,
)
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
from .reports import get_gfcr_report

__version__ = "0.2.0"

__all__ = [
    "API_BASE_URL",
    "CLASSIFICATION_PROVIDERS",
    "DATA_LEVELS",
    "DEFAULT_PAGE_SIZE",
    "DEFAULT_PROJECT_ENV_VAR",
    "KNOWN_ENDPOINTS",
    "METHODS",
    "METHOD_ENDPOINTS",
    "REFERENCE_ENDPOINTS",
    "TOKEN_ENV_VAR",
    "AuthenticationError",
    "MermaidAPIError",
    "MermaidClient",
    "MermaidError",
    "__version__",
    "as_project_ids",
    "authenticate",
    "clear_cached_token",
    "construct_endpoints",
    "countries",
    "default_client",
    "get_choices",
    "get_classification_labelmappings",
    "get_default_project",
    "get_endpoint",
    "get_gfcr_report",
    "get_managements",
    "get_me",
    "get_my_projects",
    "get_project_data",
    "get_project_endpoint",
    "get_project_managements",
    "get_project_sites",
    "get_projects",
    "get_reference",
    "get_sites",
    "get_summary_sampleevents",
    "get_token",
    "import_bulk_edit",
    "import_bulk_submit",
    "import_bulk_validate",
    "import_check_options",
    "import_get_template_and_options",
    "import_project_data",
    "search_my_projects",
    "search_projects",
    "set_default_client",
    "set_default_project",
]
