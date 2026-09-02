"""Survey data: methods, aggregation levels, and the shapes they come back in.

:func:`datamermaid.get_project_data` is the main event.  Pick a survey method
(fishbelt, benthicpit, bleaching, ...) and an aggregation level (raw
``observations``, ``sampleunits``, or ``sampleevents``) and it returns that
CSV endpoint as a DataFrame.  Ask for several and you get a nested
``{method: {level: DataFrame}}`` dict instead.

Needs: a network connection and a login, except for the first section, which is
pure lookup and runs offline.  Set ``MERMAID_EXAMPLE_PROJECT`` to a project id
to use a specific one; otherwise the first of your own projects is used.

Run it with::

    python examples/07_project_data.py
"""

from __future__ import annotations

import json
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
    # What can be asked for.  Both are plain tuples, so they can be looped
    # over, and an unknown name raises ValueError before any request is made.
    print("Methods:", ", ".join(datamermaid.METHODS))
    print("Data levels:", ", ".join(datamermaid.DATA_LEVELS))
    print()

    # construct_endpoints() is the pure method x level -> URL path mapping the
    # fetching is built on.  It needs no login and no network, which makes it a
    # handy way to see what a call is about to request.
    print("Endpoints for fishbelt:")
    print(json.dumps(datamermaid.construct_endpoints("fishbelt"), indent=2))
    print()

    project = example_project()
    print(f"Using project {project}\n")

    # One method and one level: a single DataFrame, one row per observation.
    observations = datamermaid.get_project_data(project, "fishbelt", "observations")
    print(f"fishbelt/observations: {len(observations)} rows x {observations.shape[1]} columns")
    show(observations.head(5), "site", "sample_date", "fish_family", "size", "biomass_kgha")
    print()

    # `sampleevents` is the most aggregated level: one row per site and date.
    events = datamermaid.get_project_data(project, "fishbelt", "sampleevents")
    print(f"fishbelt/sampleevents: {len(events)} rows")
    show(events.head(5), "site", "sample_date", "biomass_kgha_avg")
    print()

    # Several levels (or several methods, or "all" of either) give a nested
    # dict keyed {method: {level: DataFrame}} -- in METHODS/DATA_LEVELS order.
    fishbelt = datamermaid.get_project_data(project, "fishbelt", data="all")
    for level, frame in fishbelt["fishbelt"].items():
        print(f"fishbelt/{level}: {len(frame)} rows x {frame.shape[1]} columns")
    print()

    # Every method is fetchable the same way; a project with no surveys of that
    # method simply returns an empty frame.
    benthic = datamermaid.get_project_data(project, "benthicpit", "sampleunits")
    print(f"benthicpit/sampleunits: {len(benthic)} rows")

    # Bleaching is the one exception to "a level is a frame": its observations
    # live at two endpoints, so that level is a dict of two frames instead.
    bleaching = datamermaid.get_project_data(project, "bleaching", "observations")
    for key, frame in bleaching.items():
        print(f"bleaching/observations[{key!r}]: {len(frame)} rows")
    print()

    # `covariates=True` asks MERMAID for the site covariates it derives
    # (geomorphic zone, benthic habitat, ...) alongside the survey data, and
    # `limit` caps the rows returned per project.
    with_covariates = datamermaid.get_project_data(
        project, "fishbelt", "sampleevents", limit=5, covariates=True
    )
    extra = [column for column in with_covariates.columns if column not in events.columns]
    print(f"covariates=True adds {len(extra)} columns: {', '.join(extra[:6])}")
    print()

    # Several projects at once: pass a list of ids or a frame of projects and
    # the rows are stacked, labelled by a leading `project_id` column.
    #
    #     mine = datamermaid.get_my_projects()
    #     everyone = datamermaid.get_project_data(mine, "fishbelt", "sampleevents")
    #     everyone.groupby("project_id").size()


if __name__ == "__main__":
    main()
