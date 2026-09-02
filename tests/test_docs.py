"""Keep the README, the example script and the documentation site honest.

The README's migration table and ``get_project_data()`` matrix are parsed here
and compared with the package, so a function renamed or a method added without
updating the docs fails the suite.  ``examples/quickstart.py`` is executed
end-to-end against its mock transport.  ``CHANGELOG.md`` is checked for an
``[Unreleased]`` section and one for the current ``__version__``.

The MkDocs site in ``docs/`` gets the same treatment, minus anything that would
need mkdocs installed: ``mkdocs.yml`` and the pages under ``docs/`` are read as
text, so these run under the plain ``dev`` extra.  ``mkdocs build --strict`` is
what actually renders them, in .github/workflows/docs.yml.
"""

from __future__ import annotations

import importlib
import re
import runpy
from pathlib import Path

import pytest

import datamermaid

ROOT = Path(__file__).resolve().parents[1]
README = ROOT / "README.md"
CHANGELOG = ROOT / "CHANGELOG.md"
QUICKSTART = ROOT / "examples" / "quickstart.py"
DOCS = ROOT / "docs"
MKDOCS_YML = ROOT / "mkdocs.yml"
PACKAGE = ROOT / "src" / "datamermaid"

#: mermaidr's exports, from its NAMESPACE, that have a datamermaid counterpart:
#: all of them, since ``%>%`` is not a function to port.
PORTED_MERMAIDR_FUNCTIONS = {
    "mermaid_auth",
    "mermaid_token",
    "mermaid_get_me",
    "mermaid_get_projects",
    "mermaid_search_projects",
    "mermaid_get_my_projects",
    "mermaid_search_my_projects",
    "mermaid_set_default_project",
    "mermaid_get_default_project",
    "mermaid_get_project_endpoint",
    "mermaid_get_project_sites",
    "mermaid_get_project_managements",
    "mermaid_get_project_data",
    "mermaid_get_endpoint",
    "mermaid_get_sites",
    "mermaid_get_managements",
    "mermaid_get_reference",
    "mermaid_get_summary_sampleevents",
    "mermaid_countries",
    "mermaid_get_classification_labelmappings",
    "mermaid_import_get_template_and_options",
    "mermaid_import_check_options",
    "mermaid_import_project_data",
    "mermaid_import_bulk_validate",
    "mermaid_import_bulk_submit",
    "mermaid_import_bulk_edit",
    "mermaid_get_gfcr_report",
}


def _section(markdown: str, heading: str) -> str:
    """Return the body of the ``## heading`` section, up to the next ``## ``."""
    match = re.search(rf"^## {re.escape(heading)}\n(.*?)(?=^## |\Z)", markdown, re.S | re.M)
    assert match, f"README has no section '## {heading}'"
    return match.group(1)


def _table_rows(section: str) -> list[list[str]]:
    """Parse the cells of every body row of the first pipe table in ``section``."""
    rows = []
    for line in section.splitlines():
        if not line.startswith("|"):
            continue
        cells = [cell.strip() for cell in line.strip().strip("|").split("|")]
        if all(cell in {"---", ""} for cell in cells):
            continue  # the separator row
        rows.append(cells)
    assert rows, "no table found"
    return rows[1:]  # drop the header row


@pytest.fixture(scope="module")
def readme() -> str:
    return README.read_text()


@pytest.fixture(scope="module")
def migration_rows(readme) -> dict[str, str]:
    """mermaidr function name -> the datamermaid name it maps to."""
    rows = _table_rows(_section(readme, "Migrating from mermaidr"))
    mapping = {}
    for cells in rows:
        r_name = re.fullmatch(r"`(mermaid_\w+)\(\)`", cells[0])
        py_name = re.fullmatch(r"`datamermaid\.(\w+)\(\)`", cells[1])
        assert r_name, f"unexpected mermaidr cell: {cells[0]!r}"
        assert py_name, f"unexpected datamermaid cell: {cells[1]!r}"
        mapping[r_name.group(1)] = py_name.group(1)
    return mapping


def test_migration_table_covers_every_ported_function(migration_rows):
    assert set(migration_rows) == PORTED_MERMAIDR_FUNCTIONS


def test_migration_table_names_resolve_and_are_exported(migration_rows):
    for py_name in migration_rows.values():
        assert py_name in datamermaid.__all__, py_name
        assert callable(getattr(datamermaid, py_name)), py_name


def test_migration_table_has_no_duplicate_targets(migration_rows):
    targets = list(migration_rows.values())
    assert len(targets) == len(set(targets))


def test_every_readme_datamermaid_name_exists(readme):
    """Any ``datamermaid.<name>`` mentioned anywhere in the README must exist."""
    names = set(re.findall(r"datamermaid\.([A-Za-z_]\w*)", readme))
    names -= {"auth", "org"}  # module path in prose, and datamermaid.org URLs
    missing = sorted(name for name in names if not hasattr(datamermaid, name))
    assert not missing, missing


def test_all_exports_exist():
    for name in datamermaid.__all__:
        assert hasattr(datamermaid, name), name


def test_project_data_matrix_matches_construct_endpoints(readme):
    rows = _table_rows(_section(readme, "Project data"))

    endpoints = datamermaid.construct_endpoints()
    documented = {}
    for cells in rows:
        method = cells[0].strip("`")
        documented[method] = {
            level: re.findall(r"`([^`]+)`", cell)
            for level, cell in zip(datamermaid.DATA_LEVELS, cells[1:], strict=True)
        }

    assert list(documented) == list(datamermaid.METHODS)
    assert documented == endpoints


def test_project_data_matrix_header_lists_data_levels(readme):
    section = _section(readme, "Project data")
    header = next(line for line in section.splitlines() if line.startswith("| `method`"))
    levels = re.findall(r"`(\w+)`", header)[1:]
    assert tuple(levels) == datamermaid.DATA_LEVELS


def test_quickstart_runs_offline(capsys):
    runpy.run_path(str(QUICKSTART), run_name="__main__")

    out = capsys.readouterr().out
    assert "Signed in as Ada Lovelace" in out
    assert "fishbelt/sampleevents: 2 rows" in out
    assert "beltfishes/obstransectbeltfishes" in out

    # The script must leave no process-wide state behind for other tests.
    assert datamermaid.get_default_project() is None


def test_changelog_has_unreleased_and_the_current_version():
    """A version bump without a changelog section for it fails the suite."""
    changelog = CHANGELOG.read_text()
    headings = re.findall(r"^## \[([^\]]+)\]", changelog, re.M)

    assert "Unreleased" in headings, "CHANGELOG.md has no '## [Unreleased]' section"
    assert datamermaid.__version__ in headings, (
        f"CHANGELOG.md has no section for version {datamermaid.__version__}: {headings}"
    )


def test_readme_links_the_changelog(readme):
    assert "CHANGELOG.md" in readme


# --- The MkDocs site -------------------------------------------------------
#
# mkdocs is in the `docs` extra rather than `dev`, so nothing below imports it
# or PyYAML: mkdocs.yml is read with a line-oriented parser that only has to
# understand the two shapes this file uses (`- Title: path.md` under `nav:` and
# `paths: [src]`).  The real validation is `mkdocs build --strict`, which CI
# runs; these tests are the drift guard the offline suite can afford.

#: Modules under ``src/datamermaid/`` with no page of their own.  ``__init__``
#: is rendered on ``docs/api/index.md`` instead, with ``members: false``.
UNDOCUMENTED_MODULES = {"__init__"}


@pytest.fixture(scope="module")
def mkdocs_yml() -> str:
    return MKDOCS_YML.read_text()


@pytest.fixture(scope="module")
def nav_pages(mkdocs_yml) -> list[str]:
    """Every ``docs/``-relative path the ``nav:`` block names, in order."""
    nav = re.search(r"^nav:\n((?:[ \t]+.*\n|\n)*)", mkdocs_yml, re.M)
    assert nav, "mkdocs.yml has no nav: block"
    pages = re.findall(r":\s*([\w./-]+\.md)\s*$", nav.group(1), re.M)
    assert pages, "nav: names no pages"
    return pages


def test_nav_pages_all_exist(nav_pages):
    missing = [page for page in nav_pages if not (DOCS / page).is_file()]
    assert not missing, f"mkdocs.yml nav names pages that do not exist: {missing}"


def test_every_docs_page_is_in_the_nav(nav_pages):
    """No orphan pages: `strict: true` only catches the other direction."""
    on_disk = sorted(path.relative_to(DOCS).as_posix() for path in DOCS.rglob("*.md"))
    assert on_disk == sorted(nav_pages)


def test_narrative_pages_include_the_readmes():
    """The prose has one home.  A copy here is a copy that drifts."""
    assert '--8<-- "README.md"' in (DOCS / "index.md").read_text()
    assert '--8<-- "examples/README.md"' in (DOCS / "examples.md").read_text()


def test_snippets_base_path_is_the_repository_root(mkdocs_yml):
    """Without this the README includes above resolve to nothing."""
    assert re.search(r"^\s*base_path:\s*\[\.\]\s*$", mkdocs_yml, re.M)


def test_mkdocstrings_looks_in_src(mkdocs_yml):
    assert re.search(r"^\s*paths:\s*\[src\]\s*$", mkdocs_yml, re.M)


def _api_targets() -> set[str]:
    """The dotted module names the ``docs/api/`` pages point mkdocstrings at."""
    targets = set()
    for path in (DOCS / "api").glob("*.md"):
        targets.update(re.findall(r"^::: ([\w.]+)\s*$", path.read_text(), re.M))
    return targets


def test_every_module_has_an_api_page():
    """A new module must get a page, or its docstrings never reach the site."""
    modules = {path.stem for path in PACKAGE.glob("*.py") if path.stem not in UNDOCUMENTED_MODULES}
    documented = {target.split(".", 1)[1] for target in _api_targets() if "." in target}
    assert modules <= documented, f"no docs/api page for: {sorted(modules - documented)}"


def test_api_targets_are_importable():
    """A `:::` pointing at a module that no longer exists fails the build."""
    for target in _api_targets():
        importlib.import_module(target)


def test_readme_links_the_documentation_site(readme):
    assert "https://gridcell.github.io/py-datamermaid/" in readme


def test_readme_links_are_not_repository_relative():
    """docs/index.md inlines the README, and a relative link would not survive.

    ``[text](examples/quickstart.py)`` resolves against the page it ends up on,
    which is the site root rather than the repository, so links out of these
    two files are spelled absolutely.
    """
    for path in (README, ROOT / "examples" / "README.md"):
        relative = re.findall(r"\]\((?!https?://|#|mailto:)([^)]+)\)", path.read_text())
        assert not relative, f"{path.name} has repo-relative links: {relative}"


def test_module_exports_are_reachable_from_their_api_page():
    """mkdocstrings renders each module's ``__all__``; the package's must fit.

    ``filters: public`` in mkdocs.yml means a name that ``datamermaid`` exports
    but its own module does not is absent from the site.
    """
    modules = [
        importlib.import_module(f"datamermaid.{path.stem}")
        for path in PACKAGE.glob("*.py")
        if path.stem not in UNDOCUMENTED_MODULES
    ]
    exported = {name for module in modules for name in getattr(module, "__all__", ())}
    unreachable = sorted(
        name for name in datamermaid.__all__ if name != "__version__" and name not in exported
    )
    assert not unreachable, f"in datamermaid.__all__ but no module's __all__: {unreachable}"
