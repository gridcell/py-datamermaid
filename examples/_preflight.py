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

An example that needs something outside ``datamermaid``'s own dependencies --
``examples/09_marimo_notebook.py`` needs marimo -- passes the extra that
provides it, so the command in the message covers either failure::

    raise missing_dependency(exc, distribution="datamermaid[notebook]") from None

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
#: An example that needs more than the package itself -- the marimo notebook
#: needs marimo -- passes ``distribution="datamermaid[<extra>]"`` instead, so
#: the message names an install that covers what *it* imports.
DISTRIBUTION = "datamermaid"

#: Where the longer version of this advice lives, for the message to point at.
TROUBLESHOOTING = 'examples/README.md ("Troubleshooting")'

#: The way out that does not involve choosing an interpreter at all.  Every
#: message here exists because the example ran against one environment while
#: the package went into another; `uv run` builds the environment and runs the
#: script in it, so the two cannot disagree.  ``{extra}`` carries the extra an
#: example needs, since `uv run` syncs before it runs and would otherwise
#: uninstall it again.
_UV_TEMPLATE = """\
Or, from a checkout of this repository, hand the whole question to uv
(<https://docs.astral.sh/uv/>) -- it resolves, installs and runs in one step,
against an interpreter it fetches itself if it has to:

    uv sync{extra}
    uv run{extra} examples/<script>.py"""

#: The plain-``datamermaid`` rendering of the above, which is what all but one
#: example needs.
_UV_ALTERNATIVE = _UV_TEMPLATE.format(extra="")

#: Frames that belong to the import machinery rather than to the package whose
#: import failed.
_IMPORT_MACHINERY = frozenset({"importlib", "runpy"})


def _extras(distribution: str) -> str:
    """The extras named by ``datamermaid[notebook]``, ``""`` when there are none."""
    return distribution.partition("[")[2].removesuffix("]")


def _package_name(distribution: str) -> str:
    """``datamermaid[notebook]`` -> ``datamermaid``: what is importable, not installable."""
    return distribution.partition("[")[0]


def _installable(distribution: str) -> str:
    """The distribution as a shell word.  Extras need quoting; zsh globs ``[]``."""
    return f"'{distribution}'" if _extras(distribution) else distribution


def _editable(distribution: str) -> str:
    """The same install from a checkout of this repository, extras included."""
    extras = _extras(distribution)
    return f"-e '.[{extras}]'" if extras else "-e ."


def _uv_alternative(distribution: str) -> str:
    """:data:`_UV_TEMPLATE` with whatever extra the example needs kept installed."""
    extras = _extras(distribution)
    return _UV_TEMPLATE.format(extra=f" --extra {extras}" if extras else "")


def missing_dependency(error: ImportError, *, distribution: str = DISTRIBUTION) -> SystemExit:
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
    distribution : str, optional
        What to tell the reader to install, ``"datamermaid"`` by default.  An
        example that imports something outside the package's own dependencies
        passes the extra that provides it -- ``"datamermaid[notebook]"`` for
        the marimo notebook -- so that one install fixes either failure.

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
    >>> exc = ModuleNotFoundError("No module named 'marimo'", name="marimo")
    >>> print(missing_dependency(exc, distribution="datamermaid[notebook]"))  # doctest: +ELLIPSIS
    marimo is not installed for this interpreter.
    ...
        ... -m pip install 'datamermaid[notebook]'
    ...
    """
    package = _importing_package(error)

    if not isinstance(error, ModuleNotFoundError):
        # Nothing is missing: the import got far enough to fail on what it
        # found, e.g. `from datamermaid import <name a different version has>`.
        return SystemExit(_import_failed(package or error.name, error, distribution=distribution))

    missing = error.name or "the package this example needs"
    if package in (None, missing):
        return SystemExit(_not_installed(missing, distribution=distribution))
    return SystemExit(_broken_install(package, missing, error, distribution=distribution))


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


def _not_installed(missing: str, *, distribution: str = DISTRIBUTION) -> str:
    """The package is absent: install it, into *this* interpreter."""
    # The extras case names marimo, or whatever else an example needs, so
    # "httpx and pandas" would be an incomplete list rather than a helpful one.
    brings = " -- it brings httpx and pandas with it" if distribution == DISTRIBUTION else ""
    install = _installable(distribution)
    editable = _editable(distribution)
    return f"""\
{missing} is not installed for this interpreter.

    interpreter: {_interpreter()}
    missing:     {missing}

Install {install} for that interpreter{brings}.
Spell it `python -m pip`, not a bare `pip`: a bare `pip` may install into a
different interpreter than the one that just failed, which is the usual reason
a package looks installed and still cannot be imported.

    {sys.executable} -m pip install {install}
    {sys.executable} -m pip install {editable}    # from a checkout of this repository

{_uv_alternative(distribution)}

More at {TROUBLESHOOTING}."""


def _broken_install(
    package: str, missing: str, error: ImportError, *, distribution: str = DISTRIBUTION
) -> str:
    """The package is present but unusable: reinstall it with its dependencies."""
    install = _installable(distribution)
    diagnosis = (
        f"That is a half-finished install of {_package_name(distribution)} itself: it is\n"
        f"there, but {missing} -- which it depends on -- is not."
        if package == _package_name(distribution)
        else (
            f"That is a half-finished install of {package} rather than anything to do\n"
            f"with {_package_name(distribution)}."
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
    .venv/bin/python -m pip install {install}    # .venv\\Scripts\\python.exe on Windows

{_uv_alternative(distribution)}

More at {TROUBLESHOOTING}."""


def _import_failed(
    package: str | None, error: ImportError, *, distribution: str = DISTRIBUTION
) -> str:
    """The import failed on something other than a missing module.

    Two ways that happens: the package is a different release than the example
    expects and does not have the name it asked for, or the package disagrees
    with a compiled dependency.  The first wants an upgrade, the second a
    matched pair -- neither wants the reinstall :func:`_broken_install`
    recommends, so the error itself is quoted and both are named.
    """
    subject = package or "A package this example needs"
    target = package or _package_name(distribution)
    ours = target == _package_name(distribution)
    # Upgrading the package this repository ships means the distribution, extras
    # and all; upgrading anything else means just that package.
    upgrade = _installable(distribution) if ours else target
    checkout = (
        f"\n    {sys.executable} -m pip install {_editable(distribution)}"
        "    # from a checkout of this repository"
        if ours
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
    {sys.executable} -m pip install --upgrade {upgrade}{checkout}

If instead it mentions a compiled extension or a binary incompatibility, two
installed packages disagree with each other; reinstall {target} together with
whatever the error names.

More at {TROUBLESHOOTING}."""
