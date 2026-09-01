"""Helpers for turning MERMAID API records into tidy data frames."""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from typing import Any

import pandas as pd

__all__ = ["collapse_value", "records_to_df"]


def collapse_value(value: Any) -> Any:
    """Collapse a list-valued cell into a comma-separated string.

    Lists of ``{"id": ..., "name": ...}`` objects collapse to their names,
    matching mermaidr's ``collapse_id_name_lists``; any other list collapses to
    its stringified elements, matching mermaidr's ``paste0(collapse = ", ")``.
    Non-list values pass through untouched.
    """
    if not isinstance(value, (list, tuple)):
        return value

    parts: list[str] = []
    for item in value:
        if isinstance(item, dict):
            # Prefer a human-readable name, falling back to the id.
            named = item.get("name", item.get("id"))
            parts.append("" if named is None else str(named))
        elif item is None:
            parts.append("")
        else:
            parts.append(str(item))
    return ", ".join(parts)


def _flatten_list_columns(df: pd.DataFrame) -> pd.DataFrame:
    """Collapse every column that holds list values into strings."""
    for column in df.columns:
        series = df[column]
        if series.dtype != object:
            continue
        if series.map(lambda value: isinstance(value, (list, tuple))).any():
            df[column] = series.map(collapse_value)
    return df


def records_to_df(
    records: Iterable[dict[str, Any]],
    columns: Sequence[str] | None = None,
) -> pd.DataFrame:
    """Build a :class:`~pandas.DataFrame` from raw API records.

    ``columns`` selects and orders the output columns.  Only the requested
    columns that are actually present are kept, so an API that adds or drops a
    field does not break the call.  Empty results still yield a frame with the
    requested columns.
    """
    df = pd.DataFrame(list(records))

    if df.empty:
        return pd.DataFrame(columns=list(columns) if columns else [])

    df = _flatten_list_columns(df)

    if columns is not None:
        present = [column for column in columns if column in df.columns]
        df = df[present]

    return df.reset_index(drop=True)
