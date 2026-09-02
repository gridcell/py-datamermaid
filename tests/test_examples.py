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

``examples/09_marimo_notebook.py`` is a marimo notebook, which is a Python file
and so is held to all of the above -- plus the parts of the notebook format
that an ordinary-looking edit would break: the top-level ``import marimo`` that
marimo needs in order to save the file, and the rule that a cell runs in its own
namespace and therefore cannot read a module-level name.  marimo is an extra, so
none of this may import it.
"""

from __future__ import annotations

import ast
import doctest
import importlib.util
import os
import re
import subprocess
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

#: The marimo notebooks among the examples.  A notebook is a Python file, so it
#: is held to every rule above as well -- and to the ones below, which are the
#: parts of the notebook format that a well-meaning edit would quietly break.
MARIMO_NOTEBOOKS = sorted(path for path in EXAMPLE_SCRIPTS if "marimo.App(" in path.read_text())

#: An extra an example tells the reader to install, e.g. ``datamermaid[notebook]``.
NAMED_EXTRA = re.compile(r"""distribution=["']datamermaid\[(\w+)\]["']""")


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
    handlers = ast.unparse(ast.Module(body=guard.handlers, type_ignores=[]))
    assert "missing_dependency" in handlers, (
        f"{path.name} catches ImportError without calling _preflight.missing_dependency"
    )
    assert "sys.path" in handlers, (
        f"{path.name} imports _preflight without putting its directory on sys.path, "
        "so the handler itself would fail under `python -P` / PYTHONSAFEPATH=1"
    )


def test_example_reports_a_broken_install_even_with_a_safe_path(tmp_path):
    """End to end: the reported failure, run the way the reporter ran it.

    ``PYTHONSAFEPATH=1`` (equivalently ``python -P``) keeps the script's own
    directory off ``sys.path``, which is where ``_preflight`` lives -- the guard
    has to put it back or it fails in place of the error it exists to explain.
    The environment variable rather than the flag because ``-P`` only exists
    from Python 3.11 and the supported floor is 3.10, where it is an unknown
    option; there the variable is ignored and the test still checks the message.
    """
    httpx = tmp_path / "httpx"
    httpx.mkdir()
    (httpx / "__init__.py").write_text("from . import _urls\n")
    (httpx / "_urls.py").write_text("import not_a_real_idna\n")

    result = subprocess.run(
        [sys.executable, str(EXAMPLES / "quickstart.py")],
        capture_output=True,
        text=True,
        env={**os.environ, "PYTHONPATH": str(tmp_path), "PYTHONSAFEPATH": "1"},
    )

    assert result.returncode == 1, result.stdout
    assert "No module named '_preflight'" not in result.stderr
    assert "httpx is installed for this interpreter but cannot be imported" in result.stderr
    assert "not_a_real_idna, which is missing" in result.stderr
    # The message replaces the traceback rather than trailing it.
    assert "Traceback" not in result.stderr


def test_preflight_reports_a_package_that_is_not_installed(preflight):
    """The plain case: nothing to import, so say what to install and where."""
    try:
        import definitely_not_a_module  # noqa: F401
    except ImportError as exc:
        message = str(preflight.missing_dependency(exc))
    else:
        pytest.fail("definitely_not_a_module imported; the test needs a name that cannot")

    assert "definitely_not_a_module is not installed" in message
    assert sys.executable in message
    assert f"{sys.executable} -m pip install datamermaid" in message
    assert "uv sync" in message, "the message offers pip but not the uv equivalent"


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
    else:
        pytest.fail("halfinstalled imported; it is built here to fail")
    finally:
        sys.path.remove(str(tmp_path))
        sys.modules.pop("halfinstalled", None)

    # The package that is broken is named, not just the module it could not find.
    assert "halfinstalled is installed for this interpreter" in message
    assert "not_a_real_idna, which is missing" in message
    assert f"{sys.executable} -m pip install --force-reinstall halfinstalled" in message
    assert "uv sync" in message, "the message offers pip but not the uv equivalent"


def test_preflight_offers_uv_wherever_it_offers_an_install(preflight):
    """Both install messages name uv, and name it the same way.

    The whole class of failure these messages describe is an example running
    against a different environment than the one the package went into, which
    is what ``uv run`` removes; the README says so, so the messages have to
    agree with it.
    """
    messages = [
        preflight._not_installed("httpx"),
        preflight._broken_install("httpx", "idna", ImportError("No module named 'idna'")),
    ]
    for message in messages:
        assert preflight._UV_ALTERNATIVE in message
        assert "uv run examples/" in message
        # The uv path is the alternative, not the headline: pip comes first.
        assert message.index("-m pip install") < message.index("uv sync")
        assert message.rindex("uv sync") < message.index(preflight.TROUBLESHOOTING)


def test_preflight_reports_a_name_a_different_version_does_not_have(preflight):
    """An ImportError that is not a missing module: an upgrade, not a reinstall.

    This is what an example run against an older release of the package looks
    like -- ``from datamermaid import <name it does not export>``.  Saying that
    datamermaid "needs datamermaid, which is missing" would be nonsense.
    """
    try:
        from datamermaid import NOT_A_REAL_NAME  # noqa: F401
    except ImportError as exc:
        message = str(preflight.missing_dependency(exc))
    else:
        pytest.fail("datamermaid exports NOT_A_REAL_NAME; pick a name it does not")

    assert message.startswith("datamermaid is installed for this interpreter, but importing it")
    assert "which is missing" not in message
    assert "half-finished install" not in message
    assert "cannot import name 'NOT_A_REAL_NAME'" in message
    assert f"{sys.executable} -m pip install --upgrade datamermaid" in message


def test_preflight_reports_an_import_error_that_names_no_module(preflight, tmp_path):
    """The other non-ModuleNotFoundError: a package at odds with a compiled one."""
    package = tmp_path / "mismatched"
    package.mkdir()
    (package / "__init__.py").write_text("from . import _core\n")
    (package / "_core.py").write_text(
        'raise ImportError("numpy.dtype size changed, may indicate binary incompatibility")\n'
    )

    sys.path.insert(0, str(tmp_path))
    try:
        import mismatched  # noqa: F401
    except ImportError as exc:
        assert exc.name is None, "the point of this case is an ImportError with no module name"
        message = str(preflight.missing_dependency(exc))
    else:
        pytest.fail("mismatched imported; it is built here to fail")
    finally:
        sys.path.remove(str(tmp_path))
        sys.modules.pop("mismatched", None)

    # The package is named from the traceback, never described as needing itself.
    assert message.startswith("mismatched is installed for this interpreter")
    assert "which is missing" not in message
    assert "binary incompatibility" in message


def test_preflight_reports_a_broken_install_of_datamermaid_itself(preflight, monkeypatch):
    """The same case, but the half-installed package is ``datamermaid``.

    ``--doctest-modules`` collects ``src/datamermaid`` and ``tests``, never
    ``examples/``, so nothing else would notice the message telling the reader
    that a broken ``datamermaid`` has nothing to do with ``datamermaid``.
    """
    error = ModuleNotFoundError("No module named 'pandas'", name="pandas")
    monkeypatch.setattr(preflight, "_importing_package", lambda exc: preflight.DISTRIBUTION)

    message = str(preflight.missing_dependency(error))

    assert "rather than anything to do" not in message
    assert "half-finished install of datamermaid itself" in message
    assert f"{sys.executable} -m pip install --force-reinstall datamermaid" in message


def test_preflight_names_the_extra_the_example_needs(preflight):
    """An example needing more than the package itself gets that install named.

    The marimo notebook is the case: ``pip install datamermaid`` would leave it
    exactly as broken, so every command in the message carries the extra --
    quoted, since a bare ``datamermaid[notebook]`` is a glob in zsh.
    """
    error = ModuleNotFoundError("No module named 'marimo'", name="marimo")

    message = str(preflight.missing_dependency(error, distribution="datamermaid[notebook]"))

    assert message.startswith("marimo is not installed for this interpreter.")
    assert f"{sys.executable} -m pip install 'datamermaid[notebook]'" in message
    assert f"{sys.executable} -m pip install -e '.[notebook]'" in message
    # `uv run` syncs first, so it has to be told about the extra as well.
    assert "uv sync --extra notebook" in message
    assert "uv run --extra notebook examples/" in message
    # The plain message's aside about what datamermaid brings with it would be
    # an incomplete list here, so it is dropped rather than left wrong.
    assert "httpx and pandas" not in message


def test_preflight_extra_leaves_the_package_name_alone(preflight):
    """The extra is for installing, not for diagnosing: no `datamermaid[notebook]` imports."""
    error = ImportError("No module named 'psutil'")

    message = preflight._broken_install(
        "marimo", "psutil", error, distribution="datamermaid[notebook]"
    )

    assert "half-finished install of marimo rather than anything to do" in message
    assert "with datamermaid." in message, "the diagnosis names the package, extras and all"
    assert f"{sys.executable} -m pip install --force-reinstall marimo" in message
    # The install advice, unlike the diagnosis, does carry the extra.
    assert "-m pip install 'datamermaid[notebook]'" in message


def test_preflight_doctests_run(preflight):
    """``testpaths`` excludes ``examples/``, so collect its doctests by hand."""
    results = doctest.testmod(preflight, optionflags=doctest.ELLIPSIS, verbose=False)
    assert results.attempted, "no doctests found in examples/_preflight.py"
    assert not results.failed


def test_preflight_needs_only_the_standard_library():
    """It reports broken installs, so it must not depend on anything installable."""
    tree = ast.parse((EXAMPLES / "_preflight.py").read_text())
    assert _imported_packages(tree.body) <= set(sys.stdlib_module_names)


def _cells(tree: ast.Module) -> list[ast.FunctionDef]:
    """The ``@app.cell``-decorated functions of a marimo notebook, in file order."""
    return [
        node
        for node in tree.body
        if isinstance(node, ast.FunctionDef)
        and any(
            isinstance(decorator, ast.Attribute)
            and decorator.attr == "cell"
            and isinstance(decorator.value, ast.Name)
            and decorator.value.id == "app"
            for decorator in node.decorator_list
        )
    ]


def _bound(nodes: list[ast.stmt]) -> set[str]:
    """Every name bound anywhere under ``nodes`` -- imported, assigned or defined."""
    names = set()
    for parent in nodes:
        for node in ast.walk(parent):
            if isinstance(node, ast.Name) and isinstance(node.ctx, ast.Store):
                names.add(node.id)
            elif isinstance(node, ast.Import | ast.ImportFrom):
                names.update((alias.asname or alias.name).split(".")[0] for alias in node.names)
            elif isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef):
                names.add(node.name)
    return names


def _loaded(nodes: list[ast.stmt]) -> set[str]:
    """Every name read anywhere under ``nodes``."""
    return {
        node.id
        for parent in nodes
        for node in ast.walk(parent)
        if isinstance(node, ast.Name) and isinstance(node.ctx, ast.Load)
    }


def test_there_is_a_marimo_notebook():
    assert MARIMO_NOTEBOOKS, "examples/ has no marimo notebook"


@pytest.mark.parametrize("path", MARIMO_NOTEBOOKS, ids=lambda path: path.name)
def test_notebook_is_shaped_like_a_marimo_notebook(path: Path):
    """The structure marimo looks for when it loads the file, and `python` when it runs it.

    marimo is an extra, so the suite cannot open the notebook to find out; what
    it can check is that the file still declares an ``app``, still hangs its
    cells off it, and still runs them under the main guard.
    """
    source = path.read_text()
    tree = ast.parse(source, str(path))

    # `import marimo`, unindented: marimo's own file handling splits the file on
    # exactly that line to find the header it preserves across a save, and
    # raises rather than saving when the file has no such line.
    assert re.search(r"^import marimo$", source, flags=re.MULTILINE), (
        f"{path.name} has no top-level `import marimo`, which marimo needs to save it"
    )

    assigned = [
        node
        for node in tree.body
        if isinstance(node, ast.Assign)
        and any(isinstance(target, ast.Name) and target.id == "app" for target in node.targets)
    ]
    assert assigned, f"{path.name} never assigns `app = marimo.App(...)`"

    assert _cells(tree), f"{path.name} has no @app.cell functions"
    assert "app.run()" in source, f"{path.name} never runs its cells"


@pytest.mark.parametrize("path", MARIMO_NOTEBOOKS, ids=lambda path: path.name)
def test_notebook_cells_do_not_read_module_globals(path: Path):
    """A cell runs in its own namespace, so a module-level import does not reach it.

    Nothing in the file makes that visible -- ``import datamermaid`` at the top
    and ``datamermaid.get_me()`` in a cell looks fine and raises ``NameError``
    when run.  Every name a cell uses has to be a parameter of the cell or bound
    inside it.
    """
    tree = ast.parse(path.read_text(), str(path))
    globals_ = _bound([node for node in tree.body if not isinstance(node, ast.FunctionDef)])

    for cell in _cells(tree):
        available = {argument.arg for argument in cell.args.args} | _bound(cell.body)
        leaked = sorted((_loaded(cell.body) & globals_) - available)
        assert not leaked, (
            f"{path.name}: cell {cell.name}() reads {leaked} from module scope, "
            "which a marimo cell cannot see"
        )


@pytest.mark.parametrize("path", EXAMPLE_SCRIPTS, ids=lambda path: path.name)
def test_example_only_names_extras_that_exist(path: Path):
    """An example that tells the reader to install an extra must name a real one."""
    declared = (ROOT / "pyproject.toml").read_text()
    for extra in NAMED_EXTRA.findall(path.read_text()):
        assert re.search(rf"^{extra} = \[", declared, flags=re.MULTILINE), (
            f"{path.name} points at datamermaid[{extra}], which pyproject.toml does not define"
        )


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
