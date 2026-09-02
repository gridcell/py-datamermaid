"""Keep the port honest from the R side: mermaidr's surface, checked here.

``tests/test_docs.py`` checks the README's migration table against
``datamermaid.__all__``.  This file checks the other end of that table -- the R
package -- against the same package, so that drift in mermaidr surfaces as a
failure naming the R function that has no Python counterpart, rather than as a
silent gap.  Two snapshots do the work: the ``mermaid_*`` functions mermaidr's
NAMESPACE exports, and the reference tables ``mermaid_get_reference()`` accepts.

Updating for a new mermaidr release is a one-file edit: add the export to
``MERMAIDR_EXPORTS`` with the ``datamermaid`` name it maps to, or ``None`` while
the port is still to be written, which keeps the suite red until it is, and
move the snapshot date along.

Nothing here needs the network, and nothing here parses the README: the parsing
lives in ``test_docs.py``, whose snapshot is imported below rather than copied.
"""

from __future__ import annotations

import datamermaid
from test_docs import PORTED_MERMAIDR_FUNCTIONS

#: Every function mermaidr exports, mapped to the ``datamermaid`` name that
#: ports it, or ``None`` for one with no port yet.
#:
#: Snapshot of https://github.com/data-mermaid/mermaidr/blob/main/NAMESPACE
#: taken 2026-09: 27 ``mermaid_*`` functions, listed in NAMESPACE's own
#: alphabetical order so the file diffs against this table by eye.  The `%>%`
#: re-export is deliberately out of scope -- pandas method chaining replaces
#: it, so it is not a function to port and does not appear here.
MERMAIDR_EXPORTS: dict[str, str | None] = {
    "mermaid_auth": "authenticate",
    "mermaid_countries": "countries",
    "mermaid_get_classification_labelmappings": "get_classification_labelmappings",
    "mermaid_get_default_project": "get_default_project",
    "mermaid_get_endpoint": "get_endpoint",
    "mermaid_get_gfcr_report": "get_gfcr_report",
    "mermaid_get_managements": "get_managements",
    "mermaid_get_me": "get_me",
    "mermaid_get_my_projects": "get_my_projects",
    "mermaid_get_project_data": "get_project_data",
    "mermaid_get_project_endpoint": "get_project_endpoint",
    "mermaid_get_project_managements": "get_project_managements",
    "mermaid_get_project_sites": "get_project_sites",
    "mermaid_get_projects": "get_projects",
    "mermaid_get_reference": "get_reference",
    "mermaid_get_sites": "get_sites",
    "mermaid_get_summary_sampleevents": "get_summary_sampleevents",
    "mermaid_import_bulk_edit": "import_bulk_edit",
    "mermaid_import_bulk_submit": "import_bulk_submit",
    "mermaid_import_bulk_validate": "import_bulk_validate",
    "mermaid_import_check_options": "import_check_options",
    "mermaid_import_get_template_and_options": "import_get_template_and_options",
    "mermaid_import_project_data": "import_project_data",
    "mermaid_search_my_projects": "search_my_projects",
    "mermaid_search_projects": "search_projects",
    "mermaid_set_default_project": "set_default_project",
    "mermaid_token": "get_token",
}

#: The reference tables ``mermaid_get_reference()`` accepts, in the order its
#: ``reference`` argument lists them.  Snapshot of
#: https://github.com/data-mermaid/mermaidr/blob/main/R/mermaid_get_reference.R
#: taken 2026-09.
MERMAIDR_REFERENCE_TABLES = (
    "fishfamilies",
    "fishgenera",
    "fishspecies",
    "benthicattributes",
    "fishgroupings",
    "invertattributes",
    "invertspecies",
)

#: Tables from :data:`MERMAIDR_REFERENCE_TABLES` this package knowingly does
#: not support yet, each with the issue that tracks it.  Empty: py-datamermaid-tyc
#: added ``invertattributes`` and ``invertspecies``, the last two missing, so
#: coverage is asserted outright.  A future gap belongs here rather than in a
#: weakened assertion, and the two tests below keep the set honest -- one that
#: every name in it is really a mermaidr table, one that every name in it is
#: really absent, so closing the gap forces the entry out again.
KNOWN_MISSING_REFERENCE_TABLES: frozenset[str] = frozenset()


def _ported() -> dict[str, str]:
    """The mapping, minus any export still waiting for a port."""
    return {r_name: py_name for r_name, py_name in MERMAIDR_EXPORTS.items() if py_name is not None}


def test_snapshot_holds_only_mermaid_prefixed_names():
    """A typo in an R name would otherwise pass as an unported export."""
    unexpected = sorted(name for name in MERMAIDR_EXPORTS if not name.startswith("mermaid_"))
    assert not unexpected, f"not mermaidr exports: {unexpected}"


def test_every_mermaidr_export_is_ported():
    unported = sorted(r_name for r_name, py_name in MERMAIDR_EXPORTS.items() if py_name is None)
    assert not unported, f"mermaidr exports with no datamermaid counterpart: {unported}"


def test_every_ported_name_is_exported():
    """The port has to be public: in ``__all__``, not merely importable."""
    missing = sorted(
        f"{r_name}() -> datamermaid.{py_name}()"
        for r_name, py_name in _ported().items()
        if py_name not in datamermaid.__all__
    )
    assert not missing, f"not in datamermaid.__all__: {missing}"


def test_every_ported_name_is_callable():
    missing = sorted(
        f"{r_name}() -> datamermaid.{py_name}()"
        for r_name, py_name in _ported().items()
        if not callable(getattr(datamermaid, py_name, None))
    )
    assert not missing, f"missing or not callable: {missing}"


def test_no_two_exports_share_a_port():
    """One Python function standing in for two R ones would hide a gap."""
    targets = list(_ported().values())
    duplicated = sorted({name for name in targets if targets.count(name) > 1})
    assert not duplicated, f"mapped from more than one mermaidr export: {duplicated}"


def test_snapshot_agrees_with_the_readme_snapshot():
    """This table and ``test_docs.py``'s must describe the same R package.

    ``test_docs.PORTED_MERMAIDR_FUNCTIONS`` is the set the README's migration
    table is held to; keeping the two equal means a mermaidr release cannot be
    recorded in one file and forgotten in the other.
    """
    assert set(_ported()) == PORTED_MERMAIDR_FUNCTIONS


def test_every_mermaidr_reference_table_is_supported():
    expected = set(MERMAIDR_REFERENCE_TABLES) - KNOWN_MISSING_REFERENCE_TABLES
    missing = sorted(expected - set(datamermaid.REFERENCE_ENDPOINTS))
    assert not missing, f"accepted by mermaid_get_reference(), not by get_reference(): {missing}"


def test_reference_endpoints_match_mermaidr():
    """Nothing extra, nothing reordered: ``REFERENCE_ENDPOINTS`` is mermaidr's."""
    expected = tuple(
        table for table in MERMAIDR_REFERENCE_TABLES if table not in KNOWN_MISSING_REFERENCE_TABLES
    )
    assert datamermaid.REFERENCE_ENDPOINTS == expected


def test_known_missing_reference_tables_are_mermaidr_tables():
    unexpected = sorted(KNOWN_MISSING_REFERENCE_TABLES - set(MERMAIDR_REFERENCE_TABLES))
    assert not unexpected, f"not tables mermaid_get_reference() accepts: {unexpected}"


def test_known_missing_reference_tables_are_really_missing():
    """A closed gap must be deleted from the set, not left excusing itself."""
    landed = sorted(KNOWN_MISSING_REFERENCE_TABLES & set(datamermaid.REFERENCE_ENDPOINTS))
    assert not landed, f"supported now, so drop from KNOWN_MISSING_REFERENCE_TABLES: {landed}"
