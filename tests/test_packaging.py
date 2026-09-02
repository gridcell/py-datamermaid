"""Keep the release metadata in ``pyproject.toml`` and the package agreeing.

The version is spelled twice -- ``[project] version`` for the build backend and
``datamermaid.__version__`` for anyone who imports the package -- because
hatchling reads a static version and nothing in the source tree reads the
metadata back.  Two places is one more than ideal, so the drift is guarded here
rather than left to a release-day diff: bump one and the suite fails until the
other follows.  ``tests/test_docs.py`` covers the third obligation, a
``CHANGELOG.md`` section for whatever ``__version__`` says.

``pyproject.toml`` is read with regular expressions rather than ``tomllib``:
the oldest interpreter in the matrix is 3.10, which does not have it, and the
three fields below are simple enough not to need a parser.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

import datamermaid

ROOT = Path(__file__).resolve().parents[1]
PYPROJECT = ROOT / "pyproject.toml"

#: What a released-enough-to-use package claims.  Bumping this is a deliberate
#: act -- ``3 - Alpha`` means "expect breakage", ``4 - Beta`` means the public
#: surface is settled -- so the value is asserted rather than pattern-matched.
DEVELOPMENT_STATUS = "Development Status :: 4 - Beta"


@pytest.fixture(scope="module")
def pyproject() -> str:
    return PYPROJECT.read_text()


@pytest.fixture(scope="module")
def project_version(pyproject) -> str:
    """The ``version = "..."`` of the ``[project]`` table."""
    table = re.search(r"^\[project\]\n(.*?)(?=^\[|\Z)", pyproject, re.S | re.M)
    assert table, "pyproject.toml has no [project] table"
    match = re.search(r'^version = "([^"]+)"$', table.group(1), re.M)
    assert match, "[project] declares no static version"
    return match.group(1)


def test_version_matches_the_package(project_version):
    assert project_version == datamermaid.__version__, (
        f"pyproject.toml says {project_version}, "
        f"src/datamermaid/__init__.py says {datamermaid.__version__}"
    )


def test_version_is_a_release_number(project_version):
    """No local or editable suffix should reach a build."""
    assert re.fullmatch(r"\d+\.\d+\.\d+(?:[ab]\d+|rc\d+)?", project_version), project_version


def test_development_status_classifier(pyproject):
    statuses = re.findall(r'"(Development Status :: [^"]+)"', pyproject)
    assert statuses == [DEVELOPMENT_STATUS], statuses


def test_version_is_exported():
    """``__version__`` is in ``__all__``; keep it importable by name."""
    assert "__version__" in datamermaid.__all__
    from datamermaid import __version__

    assert __version__ == datamermaid.__version__


def test_project_urls_include_the_changelog(pyproject):
    """PyPI renders these; a release with no changelog link is a worse release."""
    urls = re.search(r"^\[project\.urls\]\n(.*?)(?=^\[|\Z)", pyproject, re.S | re.M)
    assert urls, "pyproject.toml has no [project.urls] table"
    assert "CHANGELOG.md" in urls.group(1)
