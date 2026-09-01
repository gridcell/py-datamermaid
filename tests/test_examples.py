"""Keep ``examples/`` honest without running it.

The example scripts talk to the real API, so the suite cannot execute them
(``examples/quickstart.py`` is the exception, and ``test_docs.py`` runs it).
What can be checked offline is that they still compile and that every
``datamermaid`` name they use is one the package actually exports -- which is
the realistic way examples rot, a function renamed underneath them.  The index
in ``examples/README.md`` is checked against the directory for the same reason.
"""

from __future__ import annotations

import ast
import re
from pathlib import Path
from types import ModuleType

import pytest

import datamermaid

ROOT = Path(__file__).resolve().parents[1]
EXAMPLES = ROOT / "examples"
EXAMPLE_SCRIPTS = sorted(EXAMPLES.glob("*.py"))

#: A function the examples index claims exists, e.g. ``` `get_projects()` ```.
BACKTICKED_CALL = re.compile(r"`(\w+)\(\)`")


def _aliases(tree: ast.Module) -> set[str]:
    """Names the module is bound to, e.g. ``dm`` for ``import datamermaid as dm``."""
    names = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name == "datamermaid":
                    names.add(alias.asname or alias.name)
    return names


def _referenced_names(tree: ast.Module) -> set[str]:
    """Every ``datamermaid.<name>`` and ``from datamermaid import <name>``."""
    aliases = _aliases(tree)
    names = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Attribute):
            if isinstance(node.value, ast.Name) and node.value.id in aliases:
                names.add(node.attr)
        elif isinstance(node, ast.ImportFrom) and node.module == "datamermaid":
            names.update(alias.name for alias in node.names)
    return names


def test_examples_directory_is_not_empty():
    assert EXAMPLE_SCRIPTS, "examples/ has no scripts"


@pytest.mark.parametrize("path", EXAMPLE_SCRIPTS, ids=lambda path: path.name)
def test_example_compiles(path: Path):
    compile(path.read_text(), str(path), "exec")


def _is_submodule(name: str) -> bool:
    """A submodule (``datamermaid.auth``) is fair game even though ``__all__`` omits it."""
    return isinstance(getattr(datamermaid, name, None), ModuleType)


@pytest.mark.parametrize("path", EXAMPLE_SCRIPTS, ids=lambda path: path.name)
def test_example_uses_only_public_api(path: Path):
    """Every datamermaid name an example uses must be exported by the package."""
    referenced = _referenced_names(ast.parse(path.read_text(), str(path)))
    assert referenced, f"{path.name} imports datamermaid but never uses it"

    exported = set(datamermaid.__all__)
    unknown = sorted(
        name for name in referenced if name not in exported and not _is_submodule(name)
    )
    assert not unknown, f"{path.name} uses names that are not exported: {unknown}"


@pytest.mark.parametrize("path", EXAMPLE_SCRIPTS, ids=lambda path: path.name)
def test_example_has_a_docstring_and_a_main_guard(path: Path):
    source = path.read_text()
    assert ast.get_docstring(ast.parse(source, str(path))), f"{path.name} has no module docstring"
    assert 'if __name__ == "__main__":' in source, f"{path.name} is not runnable on its own"


def test_examples_readme_indexes_every_script():
    index = (EXAMPLES / "README.md").read_text()
    missing = [path.name for path in EXAMPLE_SCRIPTS if f"({path.name})" not in index]
    assert not missing, f"examples/README.md does not link: {missing}"


def test_examples_readme_names_exist():
    """Any function the examples index names in backticks must exist."""
    index = (EXAMPLES / "README.md").read_text()
    names = set(BACKTICKED_CALL.findall(index))
    missing = sorted(name for name in names if not hasattr(datamermaid, name))
    assert not missing, missing


def test_main_readme_links_the_examples_directory():
    readme = (ROOT / "README.md").read_text()
    assert "examples/README.md" in readme
