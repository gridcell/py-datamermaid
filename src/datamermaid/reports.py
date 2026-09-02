"""Generated MERMAID reports.

Ports mermaidr's ``mermaid_get_gfcr_report``.  Unlike the rest of the package
this is neither a paginated ``GET`` nor a per-project CSV: a report is
*requested* with a ``POST`` describing what to build, and MERMAID answers with
a ZIP archive holding one Excel workbook.

API contract, read from mermaidr's ``master``::

    POST reports/  {"report_type": "gfcr", "project_ids": [...], "background": "false"}
    -> 200, body is a ZIP archive containing exactly one .xlsx

``background: "false"`` is what makes the archive come back in the response
rather than by email, so the whole thing is one request.

:func:`get_gfcr_report` returns one :class:`~pandas.DataFrame` per worksheet,
keyed by sheet name -- the dict standing in for the named list of tibbles
mermaidr returns.  Reading a workbook needs ``openpyxl``, which is not a
runtime dependency of this package: it is imported inside the function and its
absence is reported as an :class:`ImportError` naming the ``datamermaid[excel]``
extra.

Projects are named the same way as for every other project function -- see
:mod:`datamermaid.project_endpoints`, which owns the coercion and the default
project.
"""

from __future__ import annotations

import io
import os
import zipfile
from pathlib import Path
from typing import Any

import pandas as pd

from .client import MermaidClient, client_context
from .exceptions import MermaidError
from .project_endpoints import ProjectLike, _resolve_project

__all__ = [
    "GFCR_REPORT_TYPE",
    "REPORTS_ENDPOINT",
    "SAVE_SUFFIXES",
    "get_gfcr_report",
]

#: Endpoint every generated report is requested from.
REPORTS_ENDPOINT = "reports"

#: The ``report_type`` MERMAID knows the GFCR report by.
GFCR_REPORT_TYPE = "gfcr"

#: Extensions ``save=`` accepts, matched case-insensitively.  The archive always
#: holds an ``.xlsx``; ``.xls`` is allowed because mermaidr accepts it too.
SAVE_SUFFIXES = (".xlsx", ".xls")

_MISSING_OPENPYXL = (
    "Reading a MERMAID report needs openpyxl, which is not installed. "
    'Install it with `pip install "datamermaid[excel]"` (or `pip install openpyxl`).'
)


def _check_save_path(save: str | os.PathLike[str] | None) -> Path | None:
    """Validate ``save`` before anything is requested; ``None`` passes through."""
    if save is None:
        return None

    path = Path(os.fspath(save))
    if path.suffix.lower() not in SAVE_SUFFIXES:
        allowed = " or ".join(f"`{suffix}`" for suffix in SAVE_SUFFIXES)
        raise ValueError(f"`save` must name a file ending in {allowed}. Got {path.name!r}.")

    parent = path.parent
    if not parent.is_dir():
        # Checked here rather than at write time: generating a report is slow
        # and the download is not worth throwing away over a typo in the path.
        raise ValueError(f"`save` names a directory that does not exist: {str(parent)!r}.")
    return path


def _workbook_from_zip(content: bytes) -> bytes:
    """Pull the single ``.xlsx`` out of the archive MERMAID answered with.

    mermaidr inspects the ``content-encoding`` header to decide whether it got
    an archive; the payload itself is the more reliable witness, so it is what
    is checked here.
    """
    buffer = io.BytesIO(content)
    if not zipfile.is_zipfile(buffer):
        raise MermaidError(
            "The MERMAID reports endpoint did not return a ZIP archive "
            f"({len(content)} bytes). The report could not be read."
        )

    with zipfile.ZipFile(buffer) as archive:
        names = [
            name
            for name in archive.namelist()
            if not name.endswith("/") and name.lower().endswith(".xlsx")
        ]
        if len(names) != 1:
            raise MermaidError(
                "Expected exactly one .xlsx file in the archive the MERMAID "
                f"reports endpoint returned, found {len(names)}: "
                f"{sorted(archive.namelist())}."
            )
        return archive.read(names[0])


def _read_sheets(workbook: bytes) -> dict[str, pd.DataFrame]:
    """Parse every worksheet of ``workbook`` into a frame, keyed by sheet name."""
    sheets: dict[str, Any] = pd.read_excel(io.BytesIO(workbook), sheet_name=None, engine="openpyxl")
    # ``sheet_name=None`` gives a dict already; copy it so the returned mapping
    # is a plain dict whatever pandas hands back.
    return dict(sheets)


def get_gfcr_report(
    project: ProjectLike | None = None,
    save: str | os.PathLike[str] | None = None,
    *,
    client: MermaidClient | None = None,
    token: str | None = None,
) -> dict[str, pd.DataFrame]:
    """Get the GFCR report for one or more MERMAID projects.

    The Global Fund for Coral Reefs report is an Excel workbook MERMAID
    generates on request, one worksheet per indicator table.  Requires a
    login: the token comes from ``token``, from the ``MERMAID_API_TOKEN``
    environment variable, or from the cache written by
    :func:`datamermaid.authenticate`.

    Reading the workbook needs ``openpyxl``, an optional dependency; install it
    with ``pip install "datamermaid[excel]"``.

    Parameters
    ----------
    project:
        Project(s) to report on, in any shape :func:`datamermaid.as_project_ids`
        accepts.  ``None`` uses the default project (see
        :func:`datamermaid.set_default_project`).  Several projects are covered
        by a single report, as in mermaidr.
    save:
        Optional path to write the workbook to, ending in ``.xlsx`` or
        ``.xls``, in a directory that already exists.  The file is the one
        MERMAID generated, byte for byte; the parsed frames are returned
        either way.
    client:
        Client to issue the request with.  Defaults to the process-wide client.
    token:
        Access token to use instead of the resolved one.

    Returns
    -------
    dict[str, pandas.DataFrame]
        One frame per worksheet, keyed by sheet name, in workbook order.  This
        takes the place of the named list of tibbles mermaidr returns.

    Raises
    ------
    ValueError
        If ``save`` does not name an Excel file in a directory that exists, or
        if no project was given and no default is set.  Nothing is requested in
        either case.
    ImportError
        If ``openpyxl`` is not installed.  Raised before the request, since the
        workbook could not be read anyway.
    AuthenticationError
        If no access token can be resolved; no request is made.
    MermaidAPIError
        If MERMAID answers with an unsuccessful status.
    MermaidError
        If the response is not a ZIP archive, or does not hold exactly one
        ``.xlsx`` file.

    Examples
    --------
    >>> import datamermaid
    >>> report = datamermaid.get_gfcr_report("00673bec-...")  # doctest: +SKIP
    >>> sorted(report)  # doctest: +SKIP
    ['F1', 'F2', 'F3', ...]
    >>> report["F1"].head()  # doctest: +SKIP

    Several projects land in one report, and ``save=`` keeps the workbook:

    >>> datamermaid.get_gfcr_report(
    ...     ["00673bec-...", "2c0c9857-..."], save="gfcr.xlsx"
    ... )  # doctest: +SKIP
    """
    save_path = _check_save_path(save)
    project_ids = _resolve_project(project)

    try:
        import openpyxl  # noqa: F401  (pandas' engine; imported for the error message)
    except ImportError as exc:
        raise ImportError(_MISSING_OPENPYXL) from exc

    payload = {
        "report_type": GFCR_REPORT_TYPE,
        "project_ids": project_ids,
        # A string, not a bool: this is what mermaidr sends, and it is what
        # keeps the archive in the response instead of emailing it.
        "background": "false",
    }

    with client_context(client, token) as api:
        response = api.post(
            REPORTS_ENDPOINT,
            json=payload,
            # These endpoints answer with an archive, and `application/json`
            # -- the client default -- is not something the response can
            # satisfy.  Ask for anything, as get_csv() does for CSV.
            headers={"Accept": "*/*"},
            require_auth=True,
        )

    workbook = _workbook_from_zip(response.content)
    # Written before parsing: the download is the part that cannot be repeated
    # cheaply, so a caller who asked for the file gets it either way.
    if save_path is not None:
        save_path.write_bytes(workbook)

    return _read_sheets(workbook)
