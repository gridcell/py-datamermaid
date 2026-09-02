"""MERMAID in a reactive notebook: sign in, pick a project, look at its data.

A [marimo](https://marimo.io) notebook is a Python file, and this one is both:
open it with ``marimo edit`` and it is a notebook whose cells re-run themselves
whenever something they depend on changes, so choosing a different project in
the dropdown refetches that project's sites and survey data; run it with plain
``python`` and the same cells execute top to bottom as a script.

The login is the point of the example.  Nothing here hardcodes a token: the
notebook reports whatever :func:`datamermaid.get_token` finds
(``MERMAID_API_TOKEN``, or the cache written by an earlier sign-in) and offers
a button that calls :func:`datamermaid.authenticate` when there is none -- so
opening the notebook never blocks on a browser, and only a masked prefix of the
token is ever shown.

Needs: marimo, which is not a dependency of ``datamermaid`` -- install it with
``python -m pip install 'datamermaid[notebook]'`` -- plus a network connection
and a MERMAID login.  Set ``MERMAID_EXAMPLE_PROJECT`` to a project id to
preselect it in the dropdown; otherwise the first of your own projects is used.

Run it with::

    marimo edit examples/09_marimo_notebook.py    # notebook, cells re-run as you edit
    marimo run examples/09_marimo_notebook.py     # read-only app, no code shown
    python examples/09_marimo_notebook.py         # top to bottom, as a script

Editing this file in marimo and saving it regenerates it from its cells.  marimo
keeps everything above the ``import marimo`` below, so the docstring survives a
save; the import guard under it does not, and is worth putting back.
"""

# Unguarded, and unindented, unlike every other import in these examples:
# marimo's own tooling reads this file looking for a top-level `import marimo`,
# and cannot save over a file that has none.  A missing marimo therefore reports
# itself the plain way -- `ModuleNotFoundError: No module named 'marimo'`, from
# this line -- and the docstring above says what to install.
import marimo

try:
    # Imported here only so that a missing install is reported by the handler
    # below rather than from inside the first cell that needs it.  A cell gets
    # its own namespace and cannot see anything bound at module level, so every
    # cell imports for itself what it uses; this import is purely the check.
    import datamermaid  # noqa: F401
except ImportError as exc:  # explain what to install, instead of a deep traceback
    import sys
    from pathlib import Path

    # `python -P` and PYTHONSAFEPATH=1 keep this directory off sys.path, and the
    # helper below lives in it; without this the handler would fail in its turn.
    sys.path.insert(0, str(Path(__file__).parent))
    from _preflight import missing_dependency

    # marimo is an extra rather than a dependency of datamermaid, and this
    # notebook needs both -- which is the install to name, since marimo being
    # importable here says nothing about datamermaid being installed beside it.
    raise missing_dependency(exc, distribution="datamermaid[notebook]") from None

app = marimo.App(width="medium")


@app.cell
def imports():
    import os

    import marimo as mo

    import datamermaid

    #: Set this to a project id to preselect a particular project.
    PROJECT_ENV_VAR = "MERMAID_EXAMPLE_PROJECT"
    return PROJECT_ENV_VAR, datamermaid, mo, os


@app.cell
def intro(mo):
    mo.md(r"""
    # MERMAID, reactively

    The cells below are one dependency graph rather than a sequence: picking a
    different project refetches only the cells that read the picker, and
    nothing runs at all until there is a token to run it with.
    """)
    return


@app.cell
def helpers():
    def mask(token):
        """Show enough of a token to recognise it, and no more."""
        return f"{token[:6]}...{token[-4:]} ({len(token)} chars)"

    def present(frame, *columns):
        """``frame`` narrowed to the requested columns the API actually returned."""
        return frame[[column for column in columns if column in frame.columns]]

    return mask, present


@app.cell
def sign_in_button(mo):
    # A button rather than a call, so that opening the notebook never opens a
    # browser.  Reading `.value` has to happen in another cell -- that is what
    # makes the sign-in below re-run when the button is clicked.
    sign_in = mo.ui.run_button(label="Sign in to MERMAID")
    sign_in  # noqa: B018 -- a cell's last expression is its output
    return (sign_in,)


@app.cell
def login(datamermaid, mask, mo, sign_in):
    if sign_in.value:
        # Opens a browser (or falls back to a device code on a headless box)
        # and caches the token; it blocks until the sign-in finishes.
        datamermaid.authenticate()

    # `get_token()` never prompts: it reports the token already available from
    # MERMAID_API_TOKEN or from the cache, and None when there is none.
    token = datamermaid.get_token()
    print("Token:", mask(token) if token else "none found")

    mo.md(
        f"**Signed in.**  Token `{mask(token)}`."
        if token
        else "**Not signed in.**  Click the button above, set "
        f"`{datamermaid.TOKEN_ENV_VAR}`, or run `python examples/03_authenticate.py`."
    )
    return (token,)


@app.cell
def profile(datamermaid, mo, token):
    # Stop rather than raise while there is no token: marimo skips this cell
    # and everything downstream of it, and shows the message in its place.
    mo.stop(token is None, mo.md("*Waiting for a login.*"))

    # `me/` is the one endpoint that answers with a single object rather than a
    # page of records, so it comes back as a dict, not a DataFrame.
    me = datamermaid.get_me()
    print(f"Signed in as {me['full_name']} <{me['email']}>")

    mo.md(f"Signed in as **{me['full_name']}** &lt;{me['email']}&gt;")
    return (me,)


@app.cell
def project_list(datamermaid, me, mo, present):
    # Your own projects, private ones included -- which is what makes this the
    # authenticated counterpart of `get_projects()`.
    projects = datamermaid.get_my_projects()
    print(f"{len(projects)} projects on this account")

    mo.vstack(
        [
            mo.md(f"**{me['full_name']}** belongs to {len(projects)} projects:"),
            present(projects, "id", "name", "countries", "num_sites"),
        ]
    )
    return (projects,)


@app.cell
def project_picker(PROJECT_ENV_VAR, mo, os, projects):
    mo.stop(
        projects.empty,
        mo.md(f"*No projects on this account; set `{PROJECT_ENV_VAR}` to one you can read.*"),
    )

    # Label -> id, which is what the dropdown hands back through `.value`.  The
    # id goes in the label too, since two projects may share a name.
    options = {
        f"{name} ({project_id[:8]})": project_id
        for name, project_id in zip(projects["name"], projects["id"], strict=True)
    }
    chosen = os.environ.get(PROJECT_ENV_VAR, "").strip()
    preselected = [label for label, project_id in options.items() if project_id == chosen]

    project = mo.ui.dropdown(
        options=options,
        value=preselected[0] if preselected else next(iter(options)),
        label="Project",
    )
    project  # noqa: B018 -- a cell's last expression is its output
    return (project,)


@app.cell
def project_sites(datamermaid, mo, present, project):
    # Everything from here on reads `project.value`, so picking another project
    # refetches exactly these cells and leaves the rest of the notebook alone.
    sites = datamermaid.get_project_sites(project.value)
    print(f"{len(sites)} sites in project {project.value}")

    mo.vstack(
        [
            mo.md(f"### Sites\n{len(sites)} in this project."),
            present(sites, "name", "reef_type", "reef_zone", "exposure"),
        ]
    )
    return (sites,)


@app.cell
def survey_data(datamermaid, mo, project):
    # One method, one aggregation level, one DataFrame.  `sampleevents` is the
    # most aggregated of the three levels: one row per site and sample date.
    events = datamermaid.get_project_data(project.value, "fishbelt", "sampleevents", limit=50)
    print(f"fishbelt/sampleevents: {len(events)} rows x {events.shape[1]} columns")

    mo.vstack(
        [
            mo.md(f"### Fishbelt sample events\n{len(events)} rows, {events.shape[1]} columns."),
            mo.ui.table(events, page_size=10, selection=None),
        ]
    )
    return (events,)


@app.cell
def outro(mo):
    mo.md(r"""
    ### Where to go next

    - `datamermaid.METHODS` and `datamermaid.DATA_LEVELS` list the other things
      `get_project_data()` can be asked for; swap either into the cell above
      and the notebook refetches on its own.
    - `mo.ui.dropdown` is not special: any `mo.ui` element read from another
      cell has the same effect, so a method picker is three lines.
    - `examples/07_project_data.py` covers the fetching in depth, and
      `examples/03_authenticate.py` the sign-in flows.
    """)
    return


if __name__ == "__main__":
    app.run()
