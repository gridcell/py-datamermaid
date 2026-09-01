"""Find public projects by name, country, or tag.  No login needed.

:func:`datamermaid.search_projects` filters the same list
:func:`datamermaid.get_projects` returns.  Every argument is an optional
case-insensitive *substring* match -- the API has no search parameter, so the
filtering happens client-side after the projects are fetched.

Needs: a network connection.  No MERMAID account.

Run it with::

    python examples/02_search_projects.py
"""

from __future__ import annotations

import pandas as pd

import datamermaid


def show(frame: pd.DataFrame, *columns: str) -> None:
    """Print the requested columns of ``frame`` that the API actually returned."""
    present = [column for column in columns if column in frame.columns]
    print(frame[present].to_string(index=False))


def main() -> None:
    # One country.  Matching is a substring match, so "Fij" would work too.
    fiji = datamermaid.search_projects(country="Fiji")
    print(f"Projects in Fiji: {len(fiji)}")
    show(fiji.head(5), "name", "countries", "num_sites")
    print()

    # Arguments combine with AND: a Fijian project tagged WCS.
    wcs_fiji = datamermaid.search_projects(country="Fiji", tag="WCS")
    print(f"...of which tagged 'WCS': {len(wcs_fiji)}")
    show(wcs_fiji.head(5), "name", "tags")
    print()

    # `name` matches part of the project name, and `limit` caps the results.
    reefs = datamermaid.search_projects(name="reef", limit=3)
    print("Up to three projects with 'reef' in the name:")
    show(reefs, "name", "countries")
    print()

    # Spelling matters, so ask MERMAID which countries it knows about.  This is
    # the `countries` vocabulary of the public `choices/` endpoint.
    names = datamermaid.countries()
    print(f"MERMAID knows {len(names)} countries, e.g. {', '.join(names[:5])}")

    # No arguments at all is the same as get_projects().
    assert len(datamermaid.search_projects(limit=5)) == len(datamermaid.get_projects(limit=5))


if __name__ == "__main__":
    main()
