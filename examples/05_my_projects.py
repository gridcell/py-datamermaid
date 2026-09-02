"""Your profile and your own projects.  Needs a login.

The authenticated counterparts of examples 01 and 02:
:func:`datamermaid.get_me` returns the signed-in profile, and
:func:`datamermaid.get_my_projects` / :func:`datamermaid.search_my_projects`
return the projects that account belongs to -- including private ones, which
never appear in :func:`datamermaid.get_projects`.

Needs: a network connection and a login -- ``MERMAID_API_TOKEN``, or a token
cached by ``python examples/03_authenticate.py``.

Run it with::

    python examples/05_my_projects.py
"""

from __future__ import annotations

try:
    import pandas as pd

    import datamermaid
except ImportError as exc:  # explain what to install, instead of a deep traceback
    from _preflight import missing_dependency

    raise missing_dependency(exc) from None


def show(frame: pd.DataFrame, *columns: str) -> None:
    """Print the requested columns of ``frame`` that the API actually returned."""
    present = [column for column in columns if column in frame.columns]
    print(frame[present].to_string(index=False))


def main() -> None:
    if datamermaid.get_token() is None:
        raise SystemExit(
            "No MERMAID token found. Run `python examples/03_authenticate.py` "
            "first, or set MERMAID_API_TOKEN."
        )

    # `me/` is the one endpoint that answers with a single object rather than a
    # page of records, so it comes back as a dict, not a DataFrame.
    me = datamermaid.get_me()
    print(f"Signed in as {me['full_name']} <{me['email']}>")
    print(f"Profile id: {me['id']}")
    print()

    # Your projects, in the same shape and columns as get_projects().
    projects = datamermaid.get_my_projects()
    print(f"You belong to {len(projects)} projects:")
    show(projects, "id", "name", "countries", "num_sites")
    print()

    if projects.empty:
        print("No projects on this account; the rest of the examples need one.")
        return

    # ...and the same substring filtering as search_projects(), applied to
    # them.  Use whichever country your own projects are in: `countries` is a
    # comma-separated string, so take the first one listed.
    countries = projects["countries"].dropna()
    if not countries.empty:
        country = str(countries.iloc[0]).split(",")[0].strip()
        matching = datamermaid.search_my_projects(country=country)
        print(f"Yours in {country}: {len(matching)}")
        show(matching, "name", "countries")
        print()

    # The data policy of a project decides what other people can pull from it.
    print("Fishbelt data policy per project:")
    show(projects, "name", "data_policy_beltfish")


if __name__ == "__main__":
    main()
