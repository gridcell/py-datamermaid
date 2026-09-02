"""List MERMAID's public projects.  No login needed.

MERMAID's project list is open data, so :func:`datamermaid.get_projects` works
without a token.  This example shows the ``limit`` argument, the columns that
come back, and how list-valued fields such as ``countries`` and ``tags`` are
collapsed to comma-separated strings.

Needs: a network connection.  No MERMAID account.

Run it with::

    python examples/01_public_projects.py
"""

from __future__ import annotations

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


def show(frame: pd.DataFrame, *columns: str) -> None:
    """Print the requested columns of ``frame`` that the API actually returned."""
    present = [column for column in columns if column in frame.columns]
    print(frame[present].to_string(index=False))


def main() -> None:
    # `limit` caps the number of records; the client stops paginating once it
    # has that many, so this is one small request rather than a full download.
    projects = datamermaid.get_projects(limit=5)
    print(f"First {len(projects)} public projects:")
    show(projects, "id", "name", "countries", "num_sites")
    print()

    # `limit=None` (the default) walks every page.  MERMAID has a few thousand
    # projects, so this takes a moment.
    everything = datamermaid.get_projects()
    print(f"Every public project: {len(everything)} rows x {everything.shape[1]} columns")
    print("Columns:", ", ".join(everything.columns))
    print()

    # List-valued fields arrive as comma-separated strings, as in mermaidr: a
    # project spanning two countries shows "Fiji, Tonga", and `tags` collapses
    # a list of {id, name} objects down to the names.
    multi_country = everything[everything["countries"].str.contains(",", na=False)]
    print(f"Projects in more than one country: {len(multi_country)}")
    show(multi_country.head(3), "name", "countries", "tags")
    print()

    # Test projects are filtered out server-side unless you ask for them.
    with_tests = datamermaid.get_projects(include_test_projects=True)
    print(f"Including test projects: {len(with_tests)} (vs {len(everything)} without)")


if __name__ == "__main__":
    main()
