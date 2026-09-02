"""Turn a missing or half-installed dependency into one actionable message.

Every example imports ``datamermaid``, and most import ``httpx`` or ``pandas``
as well.  When one of those is not installed for the interpreter running the
script -- or *is* installed but cannot be imported, because a dependency of its
own is missing -- Python raises ``ModuleNotFoundError`` from somewhere deep
inside the failing package, and the traceback says nothing about what to do::

    File ".../httpx/_urls.py", line 6, in <module>
        import idna
    ModuleNotFoundError: No module named 'idna'

So the examples wrap their third-party imports in ``try``/``except
ImportError`` and hand the exception to :func:`missing_dependency`, which
returns a ``SystemExit`` naming the interpreter, the module that is missing,
and the command that fixes it.  Raise it with ``from None`` so the message
replaces the traceback rather than following it::

    try:
        import datamermaid
    except ImportError as exc:
        from _preflight import missing_dependency

        raise missing_dependency(exc) from None

This module uses nothing outside the standard library and does no work when
imported, so it cannot itself be the thing that fails.  ``python
examples/<script>.py`` puts this directory on ``sys.path``, which is how the
examples find it; a script copied out of this directory should lose its
``except`` clause on the way out.
"""

from __future__ import annotations

import sys

__all__ = ["missing_dependency"]

#: The PyPI name to install.  ``httpx`` and ``pandas`` come with it, so a
#: missing one of those is fixed the same way as a missing ``datamermaid``.
DISTRIBUTION = "datamermaid"

#: Where the longer version of this advice lives, for the message to point at.
TROUBLESHOOTING = 'examples/README.md ("Troubleshooting")'

#: Frames that belong to the import machinery rather than to the package whose
#: import failed.
_IMPORT_MACHINERY = frozenset({"importlib", "runpy"})


def missing_dependency(error: ImportError) -> SystemExit:
    """Return a ``SystemExit`` explaining an import failure in an example.

    Distinguishes the two cases that look identical in a traceback: a package
    that is not installed at all, and a package that is installed but whose own
    dependencies are not -- the second needs a reinstall, not an install.

    Parameters
    ----------
    error : ImportError
        The exception raised by the example's import block.  ``ImportError``
        rather than ``ModuleNotFoundError`` so that a package which imports but
        does not export what the example asked for is covered too.

    Returns
    -------
    SystemExit
        Carrying the message.  Returned rather than raised so the call site
        reads ``raise missing_dependency(exc) from None``, which is what
        suppresses the original traceback.

    Examples
    --------
    >>> exc = ModuleNotFoundError("No module named 'datamermaid'", name="datamermaid")
    >>> print(missing_dependency(exc))  # doctest: +ELLIPSIS
    datamermaid is not installed for this interpreter.
    ...
    """
    missing = error.name or "the package this example needs"
    package = _importing_package(error)

    if isinstance(error, ModuleNotFoundError) and package in (None, missing):
        return SystemExit(_not_installed(missing))
    return SystemExit(_broken_install(package or missing, missing, error))


def _interpreter() -> str:
    """The running interpreter, the way a bug report should quote it."""
    version = ".".join(str(part) for part in sys.version_info[:3])
    return f"{sys.executable} (Python {version})"


def _importing_package(error: ImportError) -> str | None:
    """The top-level package whose import failed, when that is not the missing one.

    ``import httpx`` failing on ``idna`` leaves ``httpx``'s own modules on the
    traceback; the outermost of them names the package that is installed but
    unusable.  ``None`` when the traceback holds only the example's own frame,
    which is what a package that is simply absent looks like.
    """
    # The first frame ran the failing ``import`` statement, so it belongs to the
    # example, not to anything being imported.  Everything after it does.
    frame = error.__traceback__.tb_next if error.__traceback__ is not None else None
    while frame is not None:
        root = frame.tb_frame.f_globals.get("__name__", "").split(".")[0]
        if root and root not in _IMPORT_MACHINERY and not root.startswith("_frozen"):
            return root
        frame = frame.tb_next
    return None


def _not_installed(missing: str) -> str:
    """The package is absent: install it, into *this* interpreter."""
    return f"""\
{missing} is not installed for this interpreter.

    interpreter: {_interpreter()}
    missing:     {missing}

Install {DISTRIBUTION} for that interpreter -- it brings httpx and pandas with
it.  Spell it `python -m pip`, not a bare `pip`: a bare `pip` may install into
a different interpreter than the one that just failed, which is the usual
reason a package looks installed and still cannot be imported.

    {sys.executable} -m pip install {DISTRIBUTION}
    {sys.executable} -m pip install -e .    # from a checkout of this repository

More at {TROUBLESHOOTING}."""


def _broken_install(package: str, missing: str, error: ImportError) -> str:
    """The package is present but unusable: reinstall it with its dependencies."""
    return f"""\
{package} is installed for this interpreter but cannot be imported: it needs
{missing}, which is missing.

    interpreter: {_interpreter()}
    package:     {package}
    missing:     {missing}
    error:       {error}

That is a half-finished install of {package} rather than anything to do with
{DISTRIBUTION}.  Reinstall it, dependencies included:

    {sys.executable} -m pip install --force-reinstall {package}

A fresh virtual environment avoids the whole class of problem, since nothing
there is left over from an earlier install:

    {sys.executable} -m venv .venv
    .venv/bin/python -m pip install {DISTRIBUTION}    # .venv\\Scripts\\python.exe on Windows

More at {TROUBLESHOOTING}."""
