"""The write path: fill a fishbelt template, dry-run it, and only then import.

Ports mermaidr's ``importing_fishbelt`` vignette.  The workflow is four steps,
each of which has to succeed before the next is worth trying:

1. :func:`datamermaid.import_get_template_and_options` -- the empty CSV
   template for a survey method, plus what MERMAID will accept in each column.
2. :func:`datamermaid.import_check_options` -- compare your values against
   those and get the closest accepted one for anything that does not line up.
3. :func:`datamermaid.import_project_data` -- upload the records.  **Dry-runs
   by default**: MERMAID checks them and reports problems without saving.
4. :func:`datamermaid.import_bulk_validate` and
   :func:`datamermaid.import_bulk_submit` -- drive the imported records through
   Collect.

**This example writes nothing unless you ask it to.**  Steps 1-3 are read-only
(the dry run saves nothing), and that is where it stops.  Pass ``--submit`` and
it does step 3 for real and then step 4, which adds one made-up fishbelt
observation to the project and submits it -- so point it at a project you are
happy to have a stray record in.

Needs: a network connection and a login for a project you can *write* to.  Set
``MERMAID_EXAMPLE_PROJECT`` to a project id to use a specific one; otherwise
the first of your own projects is used.

Run it with::

    python examples/10_importing_data.py            # template, options, dry run
    python examples/10_importing_data.py --submit    # ... and import for real
"""

from __future__ import annotations

import argparse
import logging
import os
from datetime import date

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

#: The method imported here.  Every method works the same way -- only the
#: template's columns differ; `datamermaid.METHODS` lists them all.
METHOD = "fishbelt"


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


def heading(column: str) -> str:
    """Normalise a template heading: no trailing ``*``, no case, no padding.

    The headings are the API's, ``*`` and all (``"Sample date: Year *"``), so
    matching them loosely means a column MERMAID renames or marks required
    turns up as an unfilled column below rather than as a silently wrong CSV.
    """
    return column.removesuffix("*").strip().lower()


def sample_values(site: str, management: str, observer: str) -> dict[str, str]:
    """One made-up fishbelt observation, keyed by normalised template heading.

    Real data comes out of a filled-in copy of the template instead -- read it
    with ``pandas.read_csv()`` and hand the frame straight to
    :func:`datamermaid.import_project_data`.  Building the row here keeps the
    example to one file, and makes it plain which columns MERMAID insists on.

    The site, the management regime and the observer are the project's own,
    since those are the values it will accept; some of the rest are deliberately
    not quite right, so that step 2 has something to catch.
    """
    today = date.today()
    return {
        "site": site,
        "management": management,
        "sample date: year": str(today.year),
        "sample date: month": str(today.month),
        "sample date: day": str(today.day),
        "sample time": "10:00",
        "depth": "5",
        "transect number": "1",
        "transect length surveyed": "50",
        "width": "5 m",
        "fish size bin": "1",
        # A typo, on purpose: step 2 catches it and suggests "flat".
        "reef slope": "flatt",
        "visibility": "5-10m",
        "current": "low",
        "relative depth": "deep",
        "tide": "falling",
        "observer emails": observer,
        "fish name": "Chlorurus microrhinos",
        "size": "20",
        "count": "3",
        "notes": "added by examples/10_importing_data.py",
    }


def build_record(template: pd.DataFrame, values: dict[str, str]) -> pd.DataFrame:
    """A one-row frame with the *template's* columns, filled in from ``values``.

    Taking the columns from the template rather than from ``values`` is the
    point: the import is rejected outright when a column is missing, so the
    frame is built to match what MERMAID just said it expects.
    """
    row = {column: values.get(heading(column), "") for column in template.columns}
    return pd.DataFrame([row], columns=list(template.columns))


def unfilled_required(record: pd.DataFrame, options: dict[str, dict]) -> list[str]:
    """Required columns of ``record`` with nothing in them.

    MERMAID would reject the import for these, so they are worth naming before
    anything is sent -- and if one turns up it means the template has grown a
    column that ``sample_values()`` above does not know about.
    """
    return [
        column
        for column in record.columns
        if options.get(column, {}).get("required") and not record.at[0, column]
    ]


def fix_unmatched(record: pd.DataFrame, options: dict[str, dict]) -> None:
    """Replace values MERMAID would reject with the closest ones it accepts.

    Step 2 doing its job: :func:`datamermaid.import_check_options` reports the
    closest accepted value for anything that does not line up, so a typo -- or
    a made-up value, as here -- can be corrected before the import rather than
    coming back as an error afterwards.  Columns with no ``choices`` accept any
    value, and the report for one is empty.
    """
    for column in record.columns:
        if not options.get(column, {}).get("choices"):
            continue

        report = datamermaid.import_check_options(record, options, column)
        for row in report.itertuples():
            if not row.match:
                print(f"  {column}: {row.data_value!r} -> {row.closest_choice!r}")
                record[column] = record[column].replace(row.data_value, row.closest_choice)


def main(submit: bool = False) -> None:
    # The import functions report their progress through the `datamermaid`
    # logger rather than printing, so turn logging on to see the commentary
    # mermaidr writes to the console.  `logging.basicConfig(level=logging.INFO)`
    # would do, at the cost of one line per request from httpx as well.
    logging.basicConfig(format="%(levelname)s %(message)s")
    logging.getLogger("datamermaid").setLevel(logging.INFO)

    project = example_project()
    print(f"Using project {project}\n")

    # == 1. The template and the field options ==
    #
    # Both are project-specific, because the sites and management regimes a
    # record may name are the project's own.
    template, options = datamermaid.import_get_template_and_options(project, METHOD)
    required = [column for column in template.columns if options.get(column, {}).get("required")]
    print(f"{METHOD} template: {len(template.columns)} columns, {len(required)} required")
    print("  required:", ", ".join(required))
    print("  optional:", ", ".join(column for column in template.columns if column not in required))
    print()

    # An options entry says whether the column is required, what it is for, and
    # -- for the columns that only take certain values -- which ones.
    with_choices = [column for column in template.columns if options.get(column, {}).get("choices")]
    for column in with_choices[:3]:
        entry = options[column]
        # The site and management columns list the project's own, so the lists
        # can be long; only the first few are worth printing.
        choices = entry["choices"]
        listed = ", ".join(choices[:8]) + (", ..." if len(choices) > 8 else "")
        print(f"options[{column!r}]")
        print(f"  help_text: {entry['help_text']}")
        print(f"  choices:   {listed} ({len(choices)})")
    print(f"({len(with_choices)} of {len(template.columns)} columns restrict their values)\n")

    # The record needs a site and a management regime that exist in *this*
    # project, and an observer MERMAID knows; all three are a request away.
    sites = datamermaid.get_project_sites(project, limit=1)
    managements = datamermaid.get_project_managements(project, limit=1)
    if sites.empty or managements.empty:
        raise SystemExit(
            "This project has no sites or no management regimes yet, so there is "
            "nothing a fishbelt record could refer to. Set "
            f"{PROJECT_ENV_VAR} to a project that has both."
        )

    record = build_record(
        template,
        sample_values(
            site=str(sites["name"].iloc[0]),
            management=str(managements["name"].iloc[0]),
            observer=str(datamermaid.get_me().get("email", "")),
        ),
    )
    print("The record to import:")
    show(record, *record.columns)
    print()

    unfilled = unfilled_required(record, options)
    if unfilled:
        print("Required columns this example did not fill in:", ", ".join(unfilled))
        print("(MERMAID will reject the import for those; the dry run below says so.)\n")

    # == 2. Check the values against the options ==
    #
    # One column at a time, by the name it has in the template.  The report has
    # one row per distinct value, with the closest accepted value and whether
    # it matched; non-matches come first.
    slope = next((column for column in template.columns if heading(column) == "reef slope"), None)
    if slope is not None:
        report = datamermaid.import_check_options(record, options, slope)
        print(f"import_check_options(record, options, {slope!r}):")
        print(report.to_string(index=False))
        print()

    print("Correcting the values MERMAID would not accept:")
    fix_unmatched(record, options)
    print()

    # == 3. Import -- as a dry run first ==
    #
    # `dryrun=True` is the default: MERMAID checks the records and reports what
    # is wrong with them without saving anything.  `None` back means it is
    # happy; a frame means it is not, one row per rejected record.
    problems = datamermaid.import_project_data(record, project, METHOD)
    if problems is None:
        print("Dry run: MERMAID accepted the record.\n")
    else:
        print(f"Dry run: MERMAID rejected {len(problems)} row(s):")
        print(problems.to_string(index=False))
        print()

    if not submit:
        print(
            "Stopping here: nothing has been written to MERMAID.\n"
            "Re-run with --submit to import the record for real, validate it and "
            "submit it:\n"
            "    python examples/10_importing_data.py --submit"
        )
        return

    if problems is not None:
        raise SystemExit(
            "Not importing: the dry run above found problems, and importing "
            "records MERMAID has already rejected only moves the errors into "
            "the project. Fix them and run again."
        )

    # Everything past here changes the project, which is why it is behind
    # --submit.  `dryrun=False` is the argument that turns the check into a
    # write; there is no prompt, so it is the only thing standing between a
    # script and a real import.
    print("Importing for real (--submit was passed):")
    datamermaid.import_project_data(record, project, METHOD, dryrun=False)

    # `clearexisting=True` would delete *every* existing fishbelt record in the
    # project before importing, which is why it needs `clearexisting_confirm=True`
    # as well and cannot be combined with a dry run. This example never passes it.

    # == 4. Validate and submit what was imported ==
    #
    # Validation only asks MERMAID to check the records it already holds, so it
    # needs no confirmation.
    print("\nimport_bulk_validate():")
    print(datamermaid.import_bulk_validate(project).to_string(index=False))

    # Submitting moves every cleanly validated record out of Collecting for the
    # whole project at once, so `confirm=True` is required.
    print("\nimport_bulk_submit(confirm=True):")
    print(datamermaid.import_bulk_submit(project, confirm=True).to_string(index=False))

    # The way back is `import_bulk_edit(project, "fishbelt", confirm=True)`,
    # which returns every submitted fishbelt record to Collecting for editing.
    # Also project-wide, also confirmed, and also not called here.
    print(
        "\nDone. The record is now submitted in MERMAID; delete it in Collect if "
        "it was only meant as a test."
    )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--submit",
        action="store_true",
        help="actually import the record, then validate and submit it (writes to MERMAID)",
    )
    return parser.parse_args()


if __name__ == "__main__":
    main(parse_args().submit)
