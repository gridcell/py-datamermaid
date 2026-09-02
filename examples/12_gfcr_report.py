"""The GFCR report: ask MERMAID for the workbook, save it, read the sheets.

:func:`datamermaid.get_gfcr_report` ports mermaidr's
``mermaid_get_gfcr_report()``.  It is the one call in the package that is
neither a paginated GET nor a per-project CSV: the Global Fund for Coral Reefs
report is an Excel workbook MERMAID *generates* on request, one worksheet per
indicator table, and the function asks for it, unpacks the archive it arrives
in, and hands back one :class:`~pandas.DataFrame` per sheet.

Reading a workbook needs ``openpyxl``, which is not a runtime dependency of
this package -- install the ``excel`` extra::

    python -m pip install 'datamermaid[excel]'   # or: -e '.[excel]'
    uv run --extra excel examples/12_gfcr_report.py

Needs: a network connection and a login for a project that reports to GFCR;
projects that do not have one produce a report with nothing in it, or none at
all.  Set ``MERMAID_EXAMPLE_PROJECT`` to that project's id; otherwise the first
of your own projects is used, which is unlikely to be the right one.
``MERMAID_EXAMPLE_GFCR_XLSX`` names where to save the workbook, and defaults to
a temporary directory.

Generating a report takes MERMAID a while -- a minute is normal -- so this
example makes exactly one request for one project.

Run it with::

    python examples/12_gfcr_report.py
"""

from __future__ import annotations

import os
import tempfile
from pathlib import Path

try:
    # openpyxl is imported here only so that a missing `excel` extra reports
    # itself like any other missing package, naming the interpreter and the
    # install.  `get_gfcr_report()` imports it lazily and says something
    # similar, but only once this script is already running.
    import openpyxl  # noqa: F401
    import pandas as pd

    import datamermaid
except ImportError as exc:  # explain what to install, instead of a deep traceback
    import sys

    # `python -P` and PYTHONSAFEPATH=1 keep this directory off sys.path, and the
    # helper below lives in it; without this the handler would fail in its turn.
    # `Path` is the standard library's, imported above, so it is always there.
    sys.path.insert(0, str(Path(__file__).parent))
    from _preflight import missing_dependency

    raise missing_dependency(exc, distribution="datamermaid[excel]") from None

#: Set this to a project id to run the example against a particular project.
PROJECT_ENV_VAR = "MERMAID_EXAMPLE_PROJECT"

#: Set this to save the workbook somewhere you can open it afterwards.
SAVE_ENV_VAR = "MERMAID_EXAMPLE_GFCR_XLSX"


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


def save_path(directory: str) -> Path:
    """Where to write the workbook: ``MERMAID_EXAMPLE_GFCR_XLSX``, or ``directory``.

    ``save=`` has to name an ``.xlsx`` (or ``.xls``) file in a directory that
    already exists, and says so before requesting anything -- a report is slow
    enough that it should not be thrown away over a typo in a path.
    """
    chosen = os.environ.get(SAVE_ENV_VAR, "").strip()
    return Path(chosen) if chosen else Path(directory) / "gfcr.xlsx"


def main() -> None:
    project = example_project()

    # The temporary directory only exists for as long as the workbook is being
    # read; set MERMAID_EXAMPLE_GFCR_XLSX to keep the file.
    with tempfile.TemporaryDirectory() as directory:
        destination = save_path(directory)
        print(f"Requesting the GFCR report for project {project}")
        print(f"Saving the workbook to {destination}")
        print("(MERMAID generates it on demand, so this takes a moment.)\n")

        try:
            # One call: POST the request, wait for the archive, unpack it, save
            # the workbook and parse every sheet.  `save=` is optional -- the
            # frames come back either way -- and the file it writes is the one
            # MERMAID generated, byte for byte.
            report = datamermaid.get_gfcr_report(project, save=destination)
        except datamermaid.MermaidAPIError as exc:
            raise SystemExit(
                f"MERMAID would not generate the report ({exc.status_code} {exc.reason}). "
                "The GFCR report is only available for projects enrolled in GFCR "
                f"reporting; set {PROJECT_ENV_VAR} to one of those."
            ) from None
        except datamermaid.MermaidError as exc:
            # Not an error status: the response was not the archive the
            # endpoint is documented to return.
            raise SystemExit(f"The report came back unreadable: {exc}") from None

        print(f"{len(report)} worksheets, {destination.stat().st_size / 1024:.0f} KiB on disk\n")

        # A dict, keyed by sheet name in workbook order -- this is what stands
        # in for the named list of tibbles mermaidr returns.
        for sheet, frame in report.items():
            print(f"{sheet}: {len(frame)} rows x {frame.shape[1]} columns")
        print()

        # Every value is an ordinary DataFrame, so a sheet is read like any
        # other frame.  Which sheets exist depends on what the project reports,
        # so pick the first non-empty one rather than naming one.
        filled = [(sheet, frame) for sheet, frame in report.items() if not frame.empty]
        if not filled:
            print("Every sheet is empty: the project has no GFCR indicator data yet.")
            return

        sheet, frame = filled[0]
        print(f"report[{sheet!r}] -- columns: {', '.join(map(str, frame.columns[:6]))}")
        show(frame.head(5), *frame.columns[:6])

    # Two things worth knowing about the file that just went away:
    #
    #   * several projects land in one report, as in mermaidr --
    #     get_gfcr_report(["00673bec-...", "2c0c9857-..."], save="gfcr.xlsx")
    #     -- and any shape as_project_ids() accepts works here too, including a
    #     frame of projects straight from get_my_projects();
    #   * save= is checked before the request and refuses anything that is not
    #     an .xlsx or .xls in a directory that already exists, so a slow
    #     download cannot be lost to a typo in a path.


if __name__ == "__main__":
    main()
