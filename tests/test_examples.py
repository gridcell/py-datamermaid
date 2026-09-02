"""Keep ``examples/`` honest without running it.

The example scripts talk to the real API, so the suite cannot execute them
(``examples/quickstart.py`` is the exception, and ``test_docs.py`` runs it).
What can be checked offline is that they still compile and that every
``datamermaid`` name they use is one the package actually exports -- which is
the realistic way examples rot, a function renamed underneath them.  The index
in ``examples/README.md`` is checked against the directory for the same reason.

The other thing checked here is the import guard: every example wraps its
third-party imports in ``try``/``except ImportError`` and hands the failure to
``examples/_preflight.py``, so someone running a script against an interpreter
that has no ``datamermaid`` (or a half-installed ``httpx``) gets one actionable
sentence rather than a traceback from inside a dependency.  That helper is
exercised directly, since no test can run an example in a broken environment.
"""

from __future__ import annotations

import ast
import importlib.util
import re
import sys
from pathlib import Path
from types import ModuleType

import pytest

import datamermaid

ROOT = Path(__file__).resolve().parents[1]
EXAMPLES = ROOT / "examples"

#: The examples proper.  ``_``-prefixed files are helpers the examples import,
#: not examples themselves, so they are held to none of the rules below.
EXAMPLE_SCRIPTS = sorted(path for path in EXAMPLES.glob("*.py") if not path.name.startswith("_"))
EXAMPLE_FILES = sorted(EXAMPLES.glob("*.py"))

#: Imports an example must not make unguarded: the ones that fail when the
#: package is missing from the interpreter running the script.
GUARDED_PACKAGES = frozenset({"datamermaid", "httpx", "pandas"})

#: A function the examples index claims exists, e.g. ``` `get_projects()` ```.
BACKTICKED_CALL = re.compile(r"`(\w+)\(\)`")


@pytest.fixture(scope="module")
def preflight():
    """``examples/_preflight.py``, loaded by path rather than via ``sys.path``."""
    spec = importlib.util.spec_from_file_location("_preflight", EXAMPLES / "_preflight.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


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


@pytest.mark.parametrize("path", EXAMPLE_FILES, ids=lambda path: path.name)
def test_example_compiles(path: Path):
    """Helpers included: a broken ``_preflight.py`` would break every example."""
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


def _import_guard(tree: ast.Module) -> ast.Try | None:
    """The module-level ``try``/``except ImportError`` an example wraps its imports in."""
    for node in tree.body:
        if not isinstance(node, ast.Try):
            continue
        caught = [handler.type for handler in node.handlers]
        if any(isinstance(name, ast.Name) and name.id == "ImportError" for name in caught):
            return node
    return None


def _imported_packages(nodes: list[ast.stmt]) -> set[str]:
    """Top-level package names imported anywhere under ``nodes``."""
    packages = set()
    for parent in nodes:
        for node in ast.walk(parent):
            if isinstance(node, ast.Import):
                packages.update(alias.name.split(".")[0] for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
                packages.add(node.module.split(".")[0])
    return packages


@pytest.mark.parametrize("path", EXAMPLE_SCRIPTS, ids=lambda path: path.name)
def test_example_explains_a_missing_install(path: Path):
    """Nothing an example needs may be imported without the ``_preflight`` guard.

    An unguarded ``import datamermaid`` is what turns "the package is not
    installed for this interpreter" into a traceback from inside httpx.
    """
    tree = ast.parse(path.read_text(), str(path))

    unguarded = _imported_packages(
        [node for node in tree.body if isinstance(node, ast.Import | ast.ImportFrom)]
    )
    assert not GUARDED_PACKAGES & unguarded, (
        f"{path.name} imports {sorted(GUARDED_PACKAGES & unguarded)} outside a "
        "try/except ImportError, so a missing install would raise a raw traceback"
    )

    guard = _import_guard(tree)
    assert guard is not None, f"{path.name} has no try/except ImportError around its imports"
    assert "datamermaid" in _imported_packages(guard.body), (
        f"{path.name} does not import datamermaid inside its import guard"
    )
    assert "missing_dependency" in ast.dump(ast.Module(body=guard.handlers, type_ignores=[])), (
        f"{path.name} catches ImportError without calling _preflight.missing_dependency"
    )


def test_preflight_reports_a_package_that_is_not_installed(preflight):
    """The plain case: nothing to import, so say what to install and where."""
    try:
        import definitely_not_a_module  # noqa: F401
    except ImportError as exc:
        message = str(preflight.missing_dependency(exc))

    assert "definitely_not_a_module is not installed" in message
    assert sys.executable in message
    assert f"{sys.executable} -m pip install datamermaid" in message


def test_preflight_reports_a_package_whose_own_dependency_is_missing(preflight, tmp_path):
    """The reported case: httpx installed, ``idna`` missing -- a reinstall, not an install."""
    package = tmp_path / "halfinstalled"
    package.mkdir()
    (package / "__init__.py").write_text("from . import _urls\n")
    (package / "_urls.py").write_text("import not_a_real_idna\n")

    sys.path.insert(0, str(tmp_path))
    try:
        import halfinstalled  # noqa: F401
    except ImportError as exc:
        message = str(preflight.missing_dependency(exc))
    finally:
        sys.path.remove(str(tmp_path))
        sys.modules.pop("halfinstalled", None)

    # The package that is broken is named, not just the module it could not find.
    assert "halfinstalled is installed for this interpreter" in message
    assert "not_a_real_idna, which is missing" in message
    assert f"{sys.executable} -m pip install --force-reinstall halfinstalled" in message


def test_preflight_needs_only_the_standard_library():
    """It reports broken installs, so it must not depend on anything installable."""
    tree = ast.parse((EXAMPLES / "_preflight.py").read_text())
    assert _imported_packages(tree.body) == {"__future__", "sys"}


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
