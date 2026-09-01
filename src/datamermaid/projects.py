"""The MERMAID ``projects`` endpoint."""

from __future__ import annotations

import pandas as pd

from .client import MermaidClient, default_client
from .utils import records_to_df

__all__ = ["PROJECT_COLUMNS", "PROJECT_STATUS_OPEN", "get_projects"]

#: Status code for a real (non-test) project.  mermaidr filters on this
#: server-side to exclude test projects.
PROJECT_STATUS_OPEN = 90

#: Columns returned by :func:`get_projects`, in order.  Mirrors mermaidr's
#: ``projects_columns``.  Columns missing from the API response are skipped
#: rather than raising.
PROJECT_COLUMNS = (
    "id",
    "name",
    "countries",
    "num_sites",
    "num_active_sample_units",
    "num_sample_units",
    "tags",
    "project_admins",
    "suggested_citation",
    "bbox",
    "notes",
    "status",
    "data_policy_beltfish",
    "data_policy_benthiclit",
    "data_policy_benthicpit",
    "data_policy_benthicpqt",
    "data_policy_habitatcomplexity",
    "data_policy_bleachingqc",
    "data_policy_macroinvertebrate",
    "created_on",
    "updated_on",
)


def get_projects(
    limit: int | None = None,
    include_test_projects: bool = False,
    *,
    client: MermaidClient | None = None,
) -> pd.DataFrame:
    """Get MERMAID projects.

    Parameters
    ----------
    limit:
        Maximum number of projects to return.  ``None`` (the default) returns
        every project, paginating as needed.
    include_test_projects:
        Whether to include test projects.  Defaults to ``False``, which filters
        the request to projects with status
        :data:`PROJECT_STATUS_OPEN` server-side.
    client:
        Client to issue the request with.  Defaults to the process-wide client.

    Returns
    -------
    pandas.DataFrame
        One row per project, with the columns in :data:`PROJECT_COLUMNS` that
        the API returned.

    Examples
    --------
    >>> import datamermaid
    >>> datamermaid.get_projects(limit=5)  # doctest: +SKIP
    """
    client = client if client is not None else default_client()

    params: dict[str, object] = {}
    if not include_test_projects:
        params["status"] = PROJECT_STATUS_OPEN
    if client.token is None:
        # Unauthenticated callers only see their own projects without this.
        params["showall"] = "true"

    records = client.get("projects", limit=limit, params=params)
    return records_to_df(records, columns=PROJECT_COLUMNS)
