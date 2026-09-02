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
returns a ``SystemExit`` naming the interpreter, what went wrong, and the
command that fixes it.  Raise it with ``from None`` so the message replaces the
traceback rather than following it::

    try:
        import datamermaid
    except ImportError as exc:
        import sys
        from pathlib import Path

        sys.path.insert(0, str(Path(__file__).parent))
        from _preflight import missing_dependency

        raise missing_dependency(exc) from None

Three things can go wrong, and they need three different fixes: the package is
absent (install it), the package is present but its own dependencies are not
(reinstall it), or the package imported and then refused the name the example
asked for (a version mismatch, so upgrade rather than reinstall).

This module uses nothing outside the standard library and does no work when
imported, so it cannot itself be the thing that fails.  ``python
examples/<script>.py`` puts this directory on ``sys.path``, which is normally
how the examples find it; the ``sys.path.insert`` above covers ``python -P``
and ``PYTHONSAFEPATH=1``, which do not.  A script copied out of this directory
should lose its ``except`` clause on the way out.
"""

from __future__ import annotations

import sys
from types import TracebackType

__all__ = ["missing_dependency"]

#: The PyPI name to install.  ``httpx`` and ``pandas`` come with it, so a
#: missing one of those is fixed the same way as a missing ``datamermaid``.
DISTRIBUTION = "datamermaid"

#: Where the longer version of this advice lives, for the message to point at.
TROUBLESHOOTING = 'examples/README.md ("Troubleshooting")'

#: The way out that does not involve choosing an interpreter at all.  Every
#: message here exists because the example ran against one environment while
#: the package went into another; `uv run` builds the environment and runs the
#: script in it, so the two cannot disagree.
_UV_ALTERNATIVE = """\
Or, from a checkout of this repository, hand the whole question to uv
(<https://docs.astral.sh/uv/>) -- it resolves, installs and runs in one step,
against an interpreter it fetches itself if it has to:

    uv sync
    uv run examples/<script>.py"""

#: Frames that belong to the import machinery rather than to the package whose
#: import failed.
_IMPORT_MACHINERY = frozenset({"importlib", "runpy"})


def missing_dependency(error: ImportError) -> SystemExit:
    """Return a ``SystemExit`` explaining an import failure in an example.

    Distinguishes the three cases that look alike in a traceback: a package
    that is not installed at all, a package that is installed but whose own
    dependencies are not, and a package that imports but does not provide the
    name the example asked for.  They need an install, a reinstall and an
    upgrade respectively, so the message says which.

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
    package = _importing_package(error)

    if not isinstance(error, ModuleNotFoundError):
        # Nothing is missing: the import got far enough to fail on what it
        # found, e.g. `from datamermaid import <name a different version has>`.
        return SystemExit(_import_failed(package or error.name, error))

    missing = error.name or "the package this example needs"
    if package in (None, missing):
        return SystemExit(_not_installed(missing))
    return SystemExit(_broken_install(package, missing, error))


def _interpreter() -> str:
    """The running interpreter, the way a bug report should quote it."""
    version = ".".join(str(part) for part in sys.version_info[:3])
    return f"{sys.executable} (Python {version})"


def _importing_package(error: ImportError) -> str | None:
    """The top-level package whose import failed, when that is not the missing one.

    ``import httpx`` failing on ``idna`` leaves ``httpx``'s own modules on the
    traceback; the outermost of them names the package that is installed but
    unusable.  ``None`` when the traceback holds only the example's own frame,
    which is what a package that is simply absent looks like -- and also what
    ``from datamermaid import <missing name>`` looks like, since the import
    machinery raises that one in the caller's frame.
    """
    frame = error.__traceback__
    if frame is None:
        return None
    # The first frame ran the failing ``import`` statement, so it belongs to the
    # example, not to anything being imported -- and neither does any later
    # frame in the same module, which is what ``exec`` of an import adds.
    caller = _root(frame)
    frame = frame.tb_next
    while frame is not None:
        root = _root(frame)
        if root and root != caller and root not in _IMPORT_MACHINERY:
            return root
        frame = frame.tb_next
    return None


def _root(frame: TracebackType) -> str:
    """The top-level package a traceback frame belongs to, ``""`` if it has none."""
    root = frame.tb_frame.f_globals.get("__name__", "").split(".")[0]
    return "" if root.startswith("_frozen") else root


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

{_UV_ALTERNATIVE}

More at {TROUBLESHOOTING}."""


def _broken_install(package: str, missing: str, error: ImportError) -> str:
    """The package is present but unusable: reinstall it with its dependencies."""
    diagnosis = (
        f"That is a half-finished install of {DISTRIBUTION} itself: it is there, but\n"
        f"{missing} -- which it depends on -- is not."
        if package == DISTRIBUTION
        else (
            f"That is a half-finished install of {package} rather than anything to do\n"
            f"with {DISTRIBUTION}."
        )
    )
    return f"""\
{package} is installed for this interpreter but cannot be imported: it needs
{missing}, which is missing.

    interpreter: {_interpreter()}
    package:     {package}
    missing:     {missing}
    error:       {error}

{diagnosis}  Reinstall it, dependencies included:

    {sys.executable} -m pip install --force-reinstall {package}

A fresh virtual environment avoids the whole class of problem, since nothing
there is left over from an earlier install:

    {sys.executable} -m venv .venv
    .venv/bin/python -m pip install {DISTRIBUTION}    # .venv\\Scripts\\python.exe on Windows

{_UV_ALTERNATIVE}

More at {TROUBLESHOOTING}."""


def _import_failed(package: str | None, error: ImportError) -> str:
    """The import failed on something other than a missing module.

    Two ways that happens: the package is a different release than the example
    expects and does not have the name it asked for, or the package disagrees
    with a compiled dependency.  The first wants an upgrade, the second a
    matched pair -- neither wants the reinstall :func:`_broken_install`
    recommends, so the error itself is quoted and both are named.
    """
    subject = package or "A package this example needs"
    target = package or DISTRIBUTION
    checkout = (
        f"\n    {sys.executable} -m pip install -e .    # from a checkout of this repository"
        if target == DISTRIBUTION
        else ""
    )
    return f"""\
{subject} is installed for this interpreter, but importing it failed anyway --
and not because anything is missing.

    interpreter: {_interpreter()}
    package:     {package or "not named by the error below"}
    error:       {error}

Read that error.  If it says a name cannot be imported, the installed {target}
is a different release than these examples, which are written against this
repository; upgrade it rather than reinstalling it:

    {sys.executable} -m pip show {target}
    {sys.executable} -m pip install --upgrade {target}{checkout}

If instead it mentions a compiled extension or a binary incompatibility, two
installed packages disagree with each other; reinstall {target} together with
whatever the error names.

More at {TROUBLESHOOTING}."""
