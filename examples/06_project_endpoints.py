"""Project-scoped endpoints: sites, management regimes, and the default project.

Anything under ``projects/{id}/`` is reached the same way: pass a project and
get a DataFrame back.  A "project" can be an id, a list of ids, a project
record, or a whole frame of projects -- several projects are fetched in turn
and stacked, with a leading ``project`` column saying where each row came from.

Setting a default project once lets you leave the argument out entirely.

Needs: a network connection and a login.  Set ``MERMAID_EXAMPLE_PROJECT`` to a
project id to use a specific one; otherwise the first of your own projects is
used.

Run it with::

    python examples/06_project_endpoints.py
"""

from __future__ import annotations

import os

try:
    import pandas as pd

    import datamermaid
except ImportError as exc:  # explain what to install, instead of a deep traceback
    import sys
    from pathlib import Path

    # `python -P` and PYTHONSAFEPATH=1 keep this directory off sys.path, and the
    # helper below lives in it; without this the handler would fail in its turn.
    sys.path.insert(0, str(Path(__file__).parent))
    from _preflight import missing_dependency

    raise missing_dependency(exc) from None

#: Set this to a project id to run the example against a particular project.
PROJECT_ENV_VAR = "MERMAID_EXAMPLE_PROJECT"


def show(frame: pd.DataFrame, *columns: str) -> None:
    """Print the requested columns of ``frame`` that the API actually returned."""
    present = [column for column in columns if column in frame.columns]
    print(frame[present].to_string(index=False))


def example_project() -> str:
    """Return a project id to demonstrate with, rather than hardcoding a UUID."""
    chosen = os.environ.get(PROJECT_ENV_VAR, "").strip()
    if chosen:
        return chosen

    if datamermaid.get_token() is None:
        raise SystemExit(
            "No MERMAID token found. Run `python examples/03_authenticate.py` "
            f"first, set MERMAID_API_TOKEN, or name a project in {PROJECT_ENV_VAR}."
        )

    mine = datamermaid.get_my_projects(limit=1)
    if mine.empty:
        raise SystemExit(f"No projects on this account; set {PROJECT_ENV_VAR} to one you can read.")
    return str(mine["id"].iloc[0])


def main() -> None:
    project = example_project()
    print(f"Using project {project}\n")

    # `as_project_ids` is the coercion every project function runs on its
    # argument.  It is exported so a project argument can be validated up
    # front; a shape it cannot read raises ValueError before any request.
    print("as_project_ids accepts several shapes:")
    print("  a bare id         ->", datamermaid.as_project_ids(project))
    print("  a record          ->", datamermaid.as_project_ids({"id": project, "name": "Reef"}))
    print("  a list, de-duped  ->", datamermaid.as_project_ids([project, project]))
    print()

    sites = datamermaid.get_project_sites(project)
    print(f"{len(sites)} sites:")
    show(sites.head(5), "project", "name", "reef_type", "reef_zone", "exposure")
    print()

    managements = datamermaid.get_project_managements(project)
    print(f"{len(managements)} management regimes:")
    show(managements.head(5), "project", "name", "est_year", "no_take", "open_access")
    print()

    # The generic getter reaches any projects/{id}/{endpoint}/ path, including
    # ones without a dedicated function.  `limit` is per project, `columns`
    # picks and orders the columns, and any other keyword (say country="Fiji")
    # is passed through to the API as a query parameter.
    first_sites = datamermaid.get_project_endpoint(
        project,
        "sites",
        limit=3,
        columns=("name", "country", "reef_type"),
    )
    print("get_project_endpoint(..., 'sites', limit=3):")
    show(first_sites, *first_sites.columns)
    print()

    # Set a default and the project argument becomes optional.  The ids are
    # also exported to MERMAID_DEFAULT_PROJECT so subprocesses inherit it.
    datamermaid.set_default_project(project)
    print("Default project:", datamermaid.get_default_project())
    print("Sites, with no project argument:", len(datamermaid.get_project_sites()))

    # Clear it again so nothing leaks into the rest of the session.
    datamermaid.set_default_project(None)
    print("Default project after clearing:", datamermaid.get_default_project())


if __name__ == "__main__":
    main()
