"""Pushing data into MERMAID Collect.

Ports mermaidr's write path -- ``mermaid_import_get_template_and_options``,
``mermaid_import_check_options``, ``mermaid_import_project_data`` and the three
bulk actions.  The module is named ``import_`` because ``import`` is a keyword;
the public functions are re-exported from :mod:`datamermaid` under their plain
names.

The workflow is four steps, and each one has to succeed before the next is
worth trying:

1. :func:`import_get_template_and_options` fetches the empty CSV template for a
   survey method along with, per column, whether it is required and which
   values MERMAID will accept.
2. :func:`import_check_options` compares a column of your data against those
   accepted values and reports the closest match for anything that does not
   line up.
3. :func:`import_project_data` uploads the records.  It **dry-runs by default**:
   MERMAID checks the rows and reports problems without saving anything, and
   only an explicit ``dryrun=False`` writes.
4. :func:`import_bulk_validate`, :func:`import_bulk_submit` and
   :func:`import_bulk_edit` drive the records through Collect afterwards.

Every function that changes something upstream needs an argument the caller has
to type: ``dryrun=False`` to import, ``clearexisting_confirm=True`` to wipe a
method's existing records, and ``confirm=True`` to bulk submit or bulk edit.
Nothing here prompts, so the whole workflow runs unattended.

Progress is reported through the ``datamermaid`` logger rather than printed, so
call :func:`logging.basicConfig` at ``INFO`` to see the running commentary
mermaidr prints to the console.

API contract, read from mermaidr's ``master``:

============================  ==========================================================
Template                      ``GET  ingest_schema_csv/{method}/`` (CSV, unauthenticated)
Field options                 ``GET  projects/{id}/collectrecords/ingest_schema/{method}/``
Ingest                        ``POST projects/{id}/collectrecords/ingest/`` (multipart)
Validate / submit             ``POST projects/{id}/collectrecords/{validate,submit}/``
Edit                          ``PUT  projects/{id}/{methods_endpoint}/{record_id}/edit/``
============================  ==========================================================

``bleaching`` is spelled ``bleachingqc`` in the template and ingest paths.
"""

from __future__ import annotations

import io
import logging
from collections.abc import Iterable, Iterator, Mapping, Sequence
from pathlib import Path
from typing import Any

import httpx
import pandas as pd

from .client import OPTIONAL_AUTH, MermaidClient, client_context
from .exceptions import MermaidAPIError
from .project_data import METHODS
from .project_endpoints import ProjectLike, _resolve_project

__all__ = [
    "CHECK_COLUMNS",
    "METHOD_ENDPOINTS",
    "STATUS_COLUMNS",
    "import_bulk_edit",
    "import_bulk_submit",
    "import_bulk_validate",
    "import_check_options",
    "import_get_template_and_options",
    "import_project_data",
]

logger = logging.getLogger(__name__)

#: Method -> the project endpoint holding its *submitted* sample units, which
#: is what bulk edit moves back into Collecting.  Mirrors mermaidr's
#: ``methods_endpoint_names``.
METHOD_ENDPOINTS: dict[str, str] = {
    "fishbelt": "beltfishtransectmethods",
    "benthiclit": "benthiclittransectmethods",
    "benthicpit": "benthicpittransectmethods",
    "benthicpqt": "benthicphotoquadrattransectmethods",
    "habitatcomplexity": "habitatcomplexitytransectmethods",
    "bleaching": "bleachingquadratcollectionmethods",
    "macroinvertebrate": "beltinverttransectmethods",
}

#: Columns of the report :func:`import_check_options` returns.
CHECK_COLUMNS = ("data_value", "closest_choice", "match")

#: Columns of the summary the bulk actions return.
STATUS_COLUMNS = ("status", "n")

#: Statuses each bulk action can report, in the order they are summarised.
_ACTION_STATUSES: dict[str, tuple[str, ...]] = {
    "validate": ("error", "warning", "ok"),
    "submit": ("ok", "not_ok"),
    "edit": ("ok", "not_ok"),
}

#: Records per request.  Validation is batched; submitting and editing are not,
#: so that one bad record cannot take a whole batch down with it.
_BATCH_SIZES: dict[str, int] = {"validate": 3, "submit": 1, "edit": 1}

_ACTION_VERBS = {
    "validate": "validated",
    "submit": "submitted",
    "edit": "edited and moved back to Collecting",
}


# -- shared argument checking ----------------------------------------------


def _check_method(method: Any, *, argument: str = "method") -> str:
    """Return ``method`` if it names exactly one MERMAID survey method."""
    if not isinstance(method, str) or method not in METHODS:
        options = ", ".join(f'"{name}"' for name in METHODS)
        raise ValueError(f"`{argument}` must be one of {options}. Got {method!r}.")
    return method


def _wire_method(method: str) -> str:
    """Return the spelling the ingest endpoints use for ``method``."""
    return "bleachingqc" if method == "bleaching" else method


def _single_project(project: ProjectLike | None) -> str:
    """Return the one project id in ``project``, refusing several at once.

    The import endpoints write into a single project, so unlike the read side
    there is no sensible way to fan a call out; mermaidr's
    ``check_single_project`` refuses too.
    """
    project_ids = _resolve_project(project)
    if len(project_ids) > 1:
        raise ValueError(
            f"Importing works on one project at a time; got {len(project_ids)}: "
            f"{', '.join(project_ids)}."
        )
    return project_ids[0]


# -- template and field options --------------------------------------------


def _normalise_choices(raw: Any) -> list[str]:
    """Flatten the ``choices`` MERMAID returns into a list of strings.

    Choices come back as ``[{"value": "crest"}, ...]``, but MERMAID has used
    bare strings and ``{"name": ...}`` objects for some fields, so each shape
    is accepted rather than trusted.
    """
    if raw is None or isinstance(raw, (str, bytes)) or not isinstance(raw, Iterable):
        return []

    choices: list[str] = []
    for item in raw:
        if isinstance(item, Mapping):
            for key in ("value", "name", "label", "id"):
                if item.get(key) is not None:
                    choices.append(str(item[key]))
                    break
        elif item is not None:
            choices.append(str(item))
    return choices


def _clean_options(records: Any) -> dict[str, dict[str, Any]]:
    """Key the ingest schema by column label, as mermaidr's ``clean_import_options``.

    ``label`` is the column heading in the template, so it is what the caller
    has in their data and the natural key.  ``label`` and ``name`` drop out of
    each entry, and an empty ``choices`` list drops out too -- absent choices
    mean "any value is allowed", which is not the same as "no value is".
    """
    if isinstance(records, Mapping):
        # Not the documented shape, but tolerate a pagination envelope.
        records = records.get("results", [])
    if not isinstance(records, Sequence):
        raise MermaidAPIError(
            status_code=200,
            reason="The MERMAID ingest schema endpoint returned an unexpected payload.",
        )

    options: dict[str, dict[str, Any]] = {}
    for field in records:
        if not isinstance(field, Mapping):
            continue
        label = field.get("label") or field.get("name")
        if label is None:
            continue

        entry = {key: value for key, value in field.items() if key not in ("label", "name")}
        choices = _normalise_choices(entry.get("choices"))
        if choices:
            entry["choices"] = choices
        else:
            entry.pop("choices", None)
        options[str(label)] = entry
    return options


def import_get_template_and_options(
    project: ProjectLike | None = None,
    method: str = "fishbelt",
    *,
    client: MermaidClient | None = None,
    token: str | None = None,
) -> tuple[pd.DataFrame, dict[str, dict[str, Any]]]:
    """Get the import template and the field options for one survey method.

    Parameters
    ----------
    project:
        The project to import into, in any shape
        :func:`datamermaid.as_project_ids` accepts.  ``None`` uses the default
        project.  Exactly one project; the options are project-specific, since
        the sites and management regimes a record may name are its own.
    method:
        One of :data:`datamermaid.METHODS`.
    client, token:
        As elsewhere in the package; see
        :func:`datamermaid.get_project_endpoint`.

    Returns
    -------
    (pandas.DataFrame, dict)
        The template -- an empty frame whose columns are the headings MERMAID
        expects, with a trailing ``*`` on the required ones -- and the options,
        ``{column: {"required": bool, "help_text": str, "choices": [str]}}``.
        ``choices`` is absent for columns that accept any value.  mermaidr
        returns these as one list with the template under a ``"Template"`` key;
        a tuple keeps the two apart, since only the options are a mapping.

    Examples
    --------
    >>> import datamermaid
    >>> template, options = datamermaid.import_get_template_and_options(
    ...     "00673bec-...", "fishbelt"
    ... )  # doctest: +SKIP
    >>> list(template.columns)[:2]  # doctest: +SKIP
    ['Site *', 'Management *']
    >>> options["Reef slope"]["choices"]  # doctest: +SKIP
    ['crest', 'flat', 'slope', 'wall']
    """
    method = _check_method(method)
    project_id = _single_project(project)
    wire = _wire_method(method)

    with client_context(client, token) as api:
        # The template is the same for every project and mermaidr fetches it
        # unauthenticated; a token is still sent when one is to hand, in case
        # the endpoint ever stops being public.
        template = api.get_csv(f"ingest_schema_csv/{wire}", require_auth=OPTIONAL_AUTH)
        records = api.get_one(
            f"projects/{project_id}/collectrecords/ingest_schema/{wire}",
            require_auth=True,
        )

    return template, _clean_options(records)


# -- checking a column against its options ---------------------------------


def _edit_distance(a: str, b: str) -> int:
    """Levenshtein distance between ``a`` and ``b``, as R's ``adist``."""
    if a == b:
        return 0
    if not a:
        return len(b)
    if not b:
        return len(a)

    previous = list(range(len(b) + 1))
    for i, ch_a in enumerate(a, start=1):
        current = [i]
        for j, ch_b in enumerate(b, start=1):
            current.append(
                min(
                    previous[j] + 1,  # deletion
                    current[j - 1] + 1,  # insertion
                    previous[j - 1] + (ch_a != ch_b),  # substitution
                )
            )
        previous = current
    return previous[-1]


def _closest_choice(value: str, choices: Sequence[str], lowered: Sequence[str]) -> tuple[str, int]:
    """Return the choice closest to ``value``, and its distance.

    Comparison is case-insensitive, matching mermaidr.  Ties go to the choice
    MERMAID listed first, which is what ``dplyr::arrange`` -- a stable sort --
    gives there.
    """
    target = value.lower()
    best_index, best_distance = 0, None
    for index, choice in enumerate(lowered):
        # |len(a) - len(b)| is a lower bound on the edit distance, so a choice
        # that cannot beat the incumbent need not be scored.  Choice lists run
        # to thousands of entries for fields like `Fish name *`.
        if best_distance is not None and abs(len(choice) - len(target)) >= best_distance:
            continue
        distance = _edit_distance(target, choice)
        if best_distance is None or distance < best_distance:
            best_index, best_distance = index, distance
            if distance == 0:
                break
    return choices[best_index], (0 if best_distance is None else best_distance)


def _empty_check_report() -> pd.DataFrame:
    return pd.DataFrame(columns=list(CHECK_COLUMNS))


def import_check_options(
    data: pd.DataFrame,
    options: Mapping[str, Any],
    field: str,
) -> pd.DataFrame:
    """Check one column of ``data`` against the values MERMAID accepts for it.

    Parameters
    ----------
    data:
        The frame you are about to import.
    options:
        The options mapping from :func:`import_get_template_and_options`, for
        the same method.
    field:
        The column to check, named as it is in the template (including the
        trailing ``*`` on required columns).

    Returns
    -------
    pandas.DataFrame
        One row per distinct non-missing value in the column, with columns
        ``data_value``, ``closest_choice`` and ``match``.  Values that did not
        match come first, so problems are at the top.  The report is empty --
        and the reason is logged -- when there is nothing to check: the column
        accepts any value, or it is optional and entirely missing.  A required
        column containing missing values also yields an empty report, with a
        warning, because the import will be rejected before any value is
        looked at.

    Raises
    ------
    ValueError
        If ``field`` is not in ``options`` or not in ``data``, or if the entry
        for it carries no ``required`` flag (which means it did not come from
        :func:`import_get_template_and_options`).

    Examples
    --------
    >>> import pandas as pd, datamermaid
    >>> data = pd.DataFrame({"Reef slope": ["crest", "wal"]})
    >>> datamermaid.import_check_options(data, options, "Reef slope")  # doctest: +SKIP
      data_value closest_choice  match
    0        wal           wall  False
    1      crest          crest   True
    """
    if field == "Template":
        raise ValueError(
            "`Template` is not a field to check; the template is returned "
            "separately by `import_get_template_and_options()`."
        )
    if field not in options:
        available = ", ".join(options) or "(none)"
        raise ValueError(
            f"`{field}` does not exist in `options`. Possible options are: {available}"
        )
    if field not in data.columns:
        raise ValueError(f"`{field}` column does not exist in `data`.")

    field_options = options[field]
    if not isinstance(field_options, Mapping) or "required" not in field_options:
        raise ValueError(
            f'`required` is missing from `options["{field}"]`. Please pass the options '
            "returned by `import_get_template_and_options()`."
        )

    values = data[field].drop_duplicates()
    missing = values.isna()

    if field_options["required"]:
        if missing.any():
            logger.warning(
                "`%s` is required, but the data contains missing values. "
                "All values must be filled in.",
                field,
            )
            return _empty_check_report()
    elif missing.all():
        logger.info("All values of `%s` are missing, nothing to check.", field)
        return _empty_check_report()

    choices = field_options.get("choices")
    if not choices:
        logger.info("Any value is allowed for `%s`, nothing to check.", field)
        return _empty_check_report()

    lowered = [choice.lower() for choice in choices]
    rows = []
    for value in values[~missing]:
        text = str(value)
        closest, distance = _closest_choice(text, choices, lowered)
        rows.append({"data_value": text, "closest_choice": closest, "match": distance == 0})

    report = pd.DataFrame(rows, columns=list(CHECK_COLUMNS))
    if report["match"].all():
        logger.info("All values of `%s` match.", field)
    else:
        logger.warning("Some values of `%s` do not match; see the returned report.", field)

    # Non-matches first, input order preserved within each group.
    return report.sort_values("match", kind="stable").reset_index(drop=True)


# -- importing records -----------------------------------------------------


def _data_as_csv(data: pd.DataFrame | str | Path) -> bytes:
    """Serialise ``data`` to the CSV bytes MERMAID's ingest endpoint expects.

    Missing values are written as empty fields rather than ``NaN``/``NA``, as
    mermaidr's ``na = ""`` does -- MERMAID reads the literal text of each cell,
    so an ``NA`` would be ingested as the string "NA".  A path is re-read and
    re-written for the same reason, every column as text so that pandas'
    inference cannot blank out a site named "NA" or turn a code like "007"
    into 7.

    Frames go through pandas' nullable dtypes first: a column of whole numbers
    with a gap in it is otherwise float64, and would be uploaded as "3.0"
    where the user wrote 3.  Genuine floats are left alone.
    """
    if isinstance(data, pd.DataFrame):
        frame = data
    elif isinstance(data, (str, Path)):
        path = Path(data)
        if path.suffix.lower() != ".csv" or not path.is_file():
            raise ValueError("`data` must be a DataFrame or the path to an existing CSV file.")
        frame = pd.read_csv(path, dtype=str, keep_default_na=False)
    else:
        raise ValueError(
            "`data` must be a DataFrame or the path to an existing CSV file, "
            f"not {type(data).__name__}."
        )

    buffer = io.StringIO()
    frame.convert_dtypes().to_csv(buffer, index=False, na_rep="")
    return buffer.getvalue().encode("utf-8")


def _flatten_error_cell(value: Any) -> Any:
    """Render one cell of MERMAID's per-row ingest errors as a readable string.

    The API nests a status, a message and sometimes a code under each column
    that failed.  mermaidr unnests those into further columns; flattening them
    into one string per column keeps the frame rectangular whatever shape the
    payload takes, at the cost of not being able to filter on the status.
    """
    if isinstance(value, Mapping):
        parts = [
            f"{key}: {_flatten_error_cell(item)}"
            for key, item in value.items()
            if item not in (None, "", [], {})
        ]
        return "; ".join(parts)
    if isinstance(value, (list, tuple)):
        rendered = [str(_flatten_error_cell(item)) for item in value if item is not None]
        return "; ".join(part for part in rendered if part)
    return value


def _import_errors_frame(payload: Any) -> pd.DataFrame | None:
    """Turn MERMAID's ingest error payload into a frame, or ``None`` if it isn't one."""
    if not isinstance(payload, list) or not payload:
        return None
    if not all(isinstance(row, Mapping) for row in payload):
        return None

    rows = []
    for row in payload:
        flattened = {
            key: _flatten_error_cell(value) for key, value in row.items() if key != "$row_number"
        }
        # The API counts the header as row 1; the caller counts data rows.
        row_number = row.get("$row_number")
        rows.append({"row_number": row_number, **flattened})

    frame = pd.DataFrame(rows)
    if frame["row_number"].notna().all():
        frame["row_number"] = frame["row_number"].astype("int64") - 1
    return frame


def import_project_data(
    data: pd.DataFrame | str | Path,
    project: ProjectLike | None = None,
    method: str = "fishbelt",
    dryrun: bool = True,
    clearexisting: bool = False,
    *,
    clearexisting_confirm: bool = False,
    client: MermaidClient | None = None,
    token: str | None = None,
) -> pd.DataFrame | None:
    """Import records into a project's Collecting page in MERMAID Collect.

    **Dry runs by default.**  With ``dryrun=True`` MERMAID checks the records
    and reports any problems without saving a thing; only ``dryrun=False``
    actually writes.  Run the dry run first, fix whatever it reports, and only
    then import for real.

    Parameters
    ----------
    data:
        The records to import: a :class:`~pandas.DataFrame` with the columns of
        the method's template, or the path to a CSV file holding them.  Missing
        values are sent as empty fields.
    project:
        The project to import into -- exactly one.  ``None`` uses the default
        project.
    method:
        One of :data:`datamermaid.METHODS`.
    dryrun:
        Check the records without saving them.  ``True`` by default; pass
        ``False`` to import.
    clearexisting:
        Delete **every** existing record for this method in the project before
        importing.  Requires ``clearexisting_confirm=True`` as well, and cannot
        be combined with a dry run.
    clearexisting_confirm:
        Confirms ``clearexisting``.  mermaidr asks at the console; this package
        takes the answer as an argument so that it can run unattended.
    client, token:
        As elsewhere in the package.

    Returns
    -------
    pandas.DataFrame or None
        ``None`` when MERMAID accepted the records.  When it rejected rows, a
        frame of the problems it found -- one row per rejected record, with a
        leading ``row_number`` counting the rows of ``data`` from 1 -- is
        returned and a warning is logged.

    Raises
    ------
    ValueError
        For an invalid method, an unusable ``data``, a project that is not
        exactly one project, or an unconfirmed/contradictory ``clearexisting``.
        Nothing is sent in that case.
    MermaidAPIError
        If the import failed outright: a missing column, an unknown project, a
        project you cannot write to, or a request too big to finish in time.

    Examples
    --------
    >>> import datamermaid
    >>> problems = datamermaid.import_project_data(records, "00673bec-...")  # doctest: +SKIP
    >>> if problems is None:  # doctest: +SKIP
    ...     datamermaid.import_project_data(records, "00673bec-...", dryrun=False)
    """
    method = _check_method(method)
    project_id = _single_project(project)

    if dryrun and clearexisting:
        raise ValueError(
            "`dryrun=True` and `clearexisting=True` contradict each other: a dry run saves "
            f"nothing, while `clearexisting` deletes every existing {method} record. "
            "Pass `dryrun=False` if you really mean to replace them."
        )
    if clearexisting and not clearexisting_confirm:
        raise ValueError(
            f"`clearexisting=True` deletes ALL existing {method} records in this project "
            "and replaces them with the ones being imported. Pass "
            "`clearexisting_confirm=True` as well to confirm."
        )

    csv_bytes = _data_as_csv(data)

    form: dict[str, str] = {"protocol": _wire_method(method)}
    if dryrun:
        form["dryrun"] = "true"
    if clearexisting:
        form["clearexisting"] = "true"

    with client_context(client, token) as api:
        response = api.post(
            f"projects/{project_id}/collectrecords/ingest",
            files={"file": ("data.csv", csv_bytes, "text/csv")},
            data=form,
            require_auth=True,
            raise_for_error=False,
        )

    if not response.is_error:
        if dryrun:
            logger.info(
                "Records checked successfully. To import them, call this function again "
                "with `dryrun=False`."
            )
        else:
            logger.info("Records imported successfully. Please review them in MERMAID Collect.")
        return None

    return _handle_ingest_error(response, project_id)


def _handle_ingest_error(response: httpx.Response, project_id: str) -> pd.DataFrame:
    """Raise for an outright failure, or return the per-row problems MERMAID found."""
    body = response.text
    url = str(response.request.url)

    if response.status_code == 504:
        raise MermaidAPIError(
            status_code=504,
            reason=(
                "The import timed out because of the size of the data. Split it up "
                "(by site or by date, say) and import each part separately."
            ),
            url=url,
        )

    if "Not Found" in body or "is not a valid uuid" in body:
        raise MermaidAPIError(
            status_code=response.status_code,
            reason=f"Failed to import data: '{project_id}' is not a valid project ID.",
            url=url,
        )

    try:
        payload = response.json()
    except ValueError:
        payload = None

    if isinstance(payload, Mapping) and "detail" in payload:
        raise MermaidAPIError(
            status_code=response.status_code,
            reason=f"Failed to import data: {payload['detail']}",
            url=url,
        )

    if "Missing required fields" in body:
        raise MermaidAPIError(
            status_code=response.status_code,
            reason=f"Failed to import data: {body}",
            url=url,
        )

    problems = _import_errors_frame(payload)
    if problems is None:
        raise MermaidAPIError(
            status_code=response.status_code,
            reason=f"Failed to import data: {body}",
            url=url,
        )

    logger.warning(
        "Failed to import data: MERMAID reported problems with %d record(s); "
        "see the returned report.",
        len(problems),
    )
    return problems


# -- bulk actions ----------------------------------------------------------


def _collecting_records(api: MermaidClient, project_id: str) -> pd.DataFrame:
    """Return the project's records in Collecting: id and validation status.

    ``validations`` comes back as a nested object, so the status is lifted out
    here rather than left as a dict-valued cell.  A record that has never been
    validated has no ``validations`` at all, and so a missing status.  As in
    mermaidr the bulk actions cover every protocol at once, so the record's
    own protocol is not carried along.
    """
    records = api.get(f"projects/{project_id}/collectrecords", require_auth=True)

    rows = []
    for record in records:
        validations = record.get("validations")
        rows.append(
            {
                "id": record.get("id"),
                "validations_status": (
                    validations.get("status") if isinstance(validations, Mapping) else None
                ),
            }
        )
    return pd.DataFrame(rows, columns=["id", "validations_status"])


def _batches(ids: Sequence[str], size: int) -> Iterator[list[str]]:
    for start in range(0, len(ids), size):
        yield list(ids[start : start + size])


def _statuses_frame(counts: Mapping[str, int], action: str) -> pd.DataFrame:
    """Build the summary frame, including the statuses that did not occur."""
    statuses = _ACTION_STATUSES[action]
    extra = [status for status in counts if status not in statuses]
    rows = [{"status": status, "n": int(counts.get(status, 0))} for status in (*statuses, *extra)]
    return pd.DataFrame(rows, columns=list(STATUS_COLUMNS))


def _log_summary(summary: pd.DataFrame, action: str) -> None:
    """Log one line per status, skipping the failures that did not happen."""
    verb = _ACTION_VERBS[action]
    for status, count in zip(summary["status"], summary["n"], strict=True):
        if count == 0 and status == "not_ok":
            continue  # No need to announce that nothing failed.
        plural = "" if count == 1 else "s"
        if action == "validate":
            if status == "ok":
                message = f"{count} record{plural} validated without warnings or errors"
            else:
                message = f"{count} record{plural} produced {status}s in validation"
        elif status == "ok":
            message = f"{count} record{plural} successfully {verb}."
        else:
            message = f"{count} record{plural} could not be {verb}."

        if status in ("error", "not_ok") and count:
            logger.warning(message)
        else:
            logger.info(message)


def _post_ids(
    api: MermaidClient,
    project_id: str,
    action: str,
    ids: Sequence[str],
) -> list[str]:
    """POST a batch of record ids to validate/submit, returning a status per record.

    A failed *validation* request is an error worth surfacing.  A failed
    *submit* is simply a record that did not get submitted, so it is counted as
    such rather than raised -- the remaining records still get their turn.  A
    body that is not JSON says nothing about the records either way, so it
    counts the same as a failure rather than surfacing as a parse error.
    """
    response = api.post(
        f"projects/{project_id}/collectrecords/{action}",
        json={"ids": list(ids)},
        require_auth=True,
        raise_for_error=action != "submit",
    )
    if response.is_error:
        return ["not_ok"] * len(ids)

    try:
        payload = response.json()
    except ValueError:
        return ["not_ok"] * len(ids)

    statuses = []
    for value in _iter_status_values(payload, ids):
        if action == "submit":
            value = "ok" if value == "ok" else "not_ok"
        statuses.append(value)
    return statuses


def _iter_status_values(payload: Any, ids: Sequence[str]) -> Iterator[str]:
    """Yield the status MERMAID reported for each record in a validate/submit batch.

    The response is keyed by record id, each value carrying a ``status``.  An
    id the response says nothing about counts as ``not_ok``, so the summary
    always adds up to the number of records acted on.
    """
    if isinstance(payload, Mapping):
        for record_id in ids:
            entry = payload.get(record_id)
            if isinstance(entry, Mapping):
                yield str(entry.get("status", "not_ok"))
            elif isinstance(entry, str):
                yield entry
            else:
                yield "not_ok"
        return
    yield from ("not_ok" for _ in ids)


def _edit_record(api: MermaidClient, project_id: str, endpoint: str, record_id: str) -> list[str]:
    """Move one submitted record back to Collecting, returning its new record id(s).

    An empty list means the edit failed.  MERMAID answers with the id of the
    collect record it created, which is checked against the Collecting page by
    the caller once every record has been through.
    """
    response = api.put(
        f"projects/{project_id}/{endpoint}/{record_id}/edit",
        require_auth=True,
        raise_for_error=False,
    )
    if response.is_error:
        return []

    try:
        payload = response.json()
    except ValueError:
        return []

    if isinstance(payload, Mapping):
        return [str(value) for value in payload.values() if isinstance(value, str)]
    if isinstance(payload, str):
        return [payload]
    if isinstance(payload, list):
        return [str(value) for value in payload if isinstance(value, str)]
    return []


def _bulk_action(
    project: ProjectLike | None,
    action: str,
    method: str | None = None,
    *,
    client: MermaidClient | None = None,
    token: str | None = None,
) -> pd.DataFrame:
    """Run one bulk action over every eligible record in a project."""
    project_id = _single_project(project)
    endpoint = METHOD_ENDPOINTS[_check_method(method)] if action == "edit" else None

    with client_context(client, token) as api:
        if action == "edit":
            records = api.get(f"projects/{project_id}/{endpoint}", require_auth=True)
            ids = [record["id"] for record in records if record.get("id")]
        else:
            collecting = _collecting_records(api, project_id)
            if action == "submit":
                collecting = collecting[collecting["validations_status"] == "ok"]
            ids = list(collecting["id"])

        if not ids:
            logger.info(
                {
                    "validate": "No records in Collecting to validate.",
                    "submit": (
                        "No valid records in Collecting to submit. "
                        "Have you run `import_bulk_validate()`?"
                    ),
                    "edit": "No submitted records to edit.",
                }[action]
            )
            return _statuses_frame({}, action)

        logger.info("%d record(s) being %s...", len(ids), _ACTION_VERBS[action])

        counts: dict[str, int] = {}
        if action == "edit":
            new_ids: list[str] = []
            failed = 0
            for record_id in ids:
                edited = _edit_record(api, project_id, endpoint, record_id)
                if edited:
                    new_ids.extend(edited)
                else:
                    failed += 1
            # One check at the end rather than one per record: ids only ever
            # get added to Collecting, so the final page answers for them all.
            collecting_ids = set(_collecting_records(api, project_id)["id"]) if new_ids else set()
            moved = sum(1 for record_id in new_ids if record_id in collecting_ids)
            counts = {"ok": moved, "not_ok": failed + len(new_ids) - moved}
        else:
            for batch in _batches(ids, _BATCH_SIZES[action]):
                for status in _post_ids(api, project_id, action, batch):
                    counts[status] = counts.get(status, 0) + 1

    summary = _statuses_frame(counts, action)
    _log_summary(summary, action)
    return summary


def import_bulk_validate(
    project: ProjectLike | None = None,
    *,
    client: MermaidClient | None = None,
    token: str | None = None,
) -> pd.DataFrame:
    """Validate every record on a project's Collecting page.

    Run this after :func:`import_project_data` has imported records for real.
    Validation only asks MERMAID to check the records it already holds -- it
    neither creates nor moves any -- so unlike the other bulk actions it needs
    no confirmation.

    Parameters
    ----------
    project:
        Exactly one project; ``None`` uses the default project.

    Returns
    -------
    pandas.DataFrame
        ``status``/``n`` counts over ``error``, ``warning`` and ``ok``, with
        zeroes for the statuses that did not occur.  The same counts are
        logged.

    Examples
    --------
    >>> import datamermaid
    >>> datamermaid.import_bulk_validate("00673bec-...")  # doctest: +SKIP
    """
    return _bulk_action(project, "validate", client=client, token=token)


def import_bulk_submit(
    project: ProjectLike | None = None,
    *,
    confirm: bool = False,
    client: MermaidClient | None = None,
    token: str | None = None,
) -> pd.DataFrame:
    """Submit every record on a project's Collecting page that validated cleanly.

    Records with validation errors or warnings are left alone, so run
    :func:`import_bulk_validate` first.  Submitting moves records out of
    Collecting for the whole project at once, so ``confirm=True`` is required;
    :func:`import_bulk_edit` is the way back.

    Parameters
    ----------
    project:
        Exactly one project; ``None`` uses the default project.
    confirm:
        Must be ``True``.  mermaidr asks at the console; this package takes the
        answer as an argument so that it can run unattended.

    Returns
    -------
    pandas.DataFrame
        ``status``/``n`` counts over ``ok`` and ``not_ok``.

    Raises
    ------
    ValueError
        If ``confirm`` is not ``True``; nothing is sent in that case.

    Examples
    --------
    >>> import datamermaid
    >>> datamermaid.import_bulk_submit("00673bec-...", confirm=True)  # doctest: +SKIP
    """
    if confirm is not True:
        raise ValueError(
            "`import_bulk_submit()` submits every validated record in the project. "
            "Pass `confirm=True` to go ahead."
        )
    return _bulk_action(project, "submit", client=client, token=token)


def import_bulk_edit(
    project: ProjectLike | None = None,
    method: str | None = None,
    *,
    confirm: bool = False,
    client: MermaidClient | None = None,
    token: str | None = None,
) -> pd.DataFrame:
    """Move every submitted record for one method back to Collecting for editing.

    This undoes :func:`import_bulk_submit` for the whole project, so it is only
    worth reaching for when a problem is found in data that has already been
    submitted.  ``confirm=True`` is required.

    Parameters
    ----------
    project:
        Exactly one project; ``None`` uses the default project.
    method:
        One of :data:`datamermaid.METHODS`.  Required -- there is no sensible
        default for an action this broad.
    confirm:
        Must be ``True``.  mermaidr asks at the console; this package takes the
        answer as an argument so that it can run unattended.

    Returns
    -------
    pandas.DataFrame
        ``status``/``n`` counts over ``ok`` and ``not_ok``.

    Raises
    ------
    ValueError
        If ``confirm`` is not ``True`` or ``method`` is not a single valid
        method; nothing is sent in that case.

    Examples
    --------
    >>> import datamermaid
    >>> datamermaid.import_bulk_edit("00673bec-...", "fishbelt", confirm=True)  # doctest: +SKIP
    """
    if confirm is not True:
        raise ValueError(
            "`import_bulk_edit()` moves every submitted record for this method back to "
            "Collecting. Pass `confirm=True` to go ahead."
        )
    _check_method(method)
    return _bulk_action(project, "edit", method, client=client, token=token)
