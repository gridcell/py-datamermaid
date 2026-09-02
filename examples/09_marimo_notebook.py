"""MERMAID in a reactive notebook: sign in, pick a project, look at its data.

A [marimo](https://marimo.io) notebook is a Python file, and this one is both:
open it with ``marimo edit`` and it is a notebook whose cells re-run themselves
whenever something they depend on changes, so choosing a different project in
the dropdown refetches that project's sites and survey data; run it with plain
``python`` and it serves those same cells to a browser, no marimo CLI needed.

The login is the point of the example.  Nothing here hardcodes a token: the
notebook reports whatever :func:`datamermaid.get_token` finds
(``MERMAID_API_TOKEN``, or the cache written by an earlier sign-in) and offers
a button that calls :func:`datamermaid.authenticate` when there is none -- so
opening the notebook never blocks on a browser, and only a masked prefix of the
token is ever shown.

Needs: marimo, which is not a dependency of ``datamermaid`` -- install it with
``python -m pip install 'datamermaid[notebook]'`` -- plus a network connection
and a MERMAID login.  Set ``MERMAID_EXAMPLE_PROJECT`` to a project id to put it
in the dropdown and preselect it, whether or not it is one of your own;
otherwise the first project on the account is used.

Run it with::

    marimo edit examples/09_marimo_notebook.py    # notebook, cells re-run as you edit
    marimo run examples/09_marimo_notebook.py     # read-only app, no code shown
    python examples/09_marimo_notebook.py         # serves it on 0.0.0.0:8383

The last of those needs no marimo CLI: the main guard at the bottom of this file
serves the notebook as a read-only app on ``0.0.0.0:8383``, reachable from other
machines on the network as well as this one.  ``MERMAID_EXAMPLE_HOST`` and
``MERMAID_EXAMPLE_PORT`` override either half.

Two things follow from that address not being loopback.  Read-only is the mode
rather than a precaution to be dropped: ``marimo edit`` bound to ``0.0.0.0``
hands a Python REPL on the serving machine to anyone who can reach the port.
And the served app authenticates nobody, so a notebook started with a token
already in the environment shows that account's data to whoever opens it --
leave ``MERMAID_API_TOKEN`` unset and let each visitor use the sign-in button.

Editing this file in marimo and saving it regenerates it from its cells.  marimo
keeps everything above the ``import marimo`` below, so the docstring survives a
save; everything under the cells -- ``serve()`` and the main guard that calls it
-- does not, any more than the import guard does, and is worth putting back.
"""

# Unguarded, and unindented, unlike every other import in these examples:
# marimo's own tooling reads this file looking for a top-level `import marimo`,
# and cannot save over a file that has none.  A missing marimo therefore reports
# itself the plain way -- `ModuleNotFoundError: No module named 'marimo'`, from
# this line -- and the docstring above says what to install.
import marimo

try:
    # The check every example in this directory opens with, and it fires in the
    # one mode that runs this file as a module: `python 09_marimo_notebook.py`.
    # `marimo edit` and `marimo run` read the notebook off its parse tree
    # without executing anything at module level, so under those a missing
    # datamermaid still surfaces from the `imports` cell.  A cell gets its own
    # namespace and cannot see anything bound out here, so every cell imports
    # for itself what it uses; this import is purely the check.
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
    # Label -> id, which is what the dropdown hands back through `.value`.  The
    # id goes in the label too, since two projects may share a name.
    options = {
        f"{name} ({project_id[:8]})": project_id
        for name, project_id in zip(projects["name"], projects["id"], strict=True)
    }

    # A named project wins, the way it does in examples 06 and 07 -- including
    # when it is not one of your own, since being able to read a project is not
    # the same as belonging to it.  Unknown ids join the dropdown rather than
    # replace it, so the account's projects stay one click away.
    chosen = os.environ.get(PROJECT_ENV_VAR, "").strip()
    preselected = [label for label, project_id in options.items() if project_id == chosen]
    if chosen and not preselected:
        preselected = [f"{PROJECT_ENV_VAR} ({chosen[:8]})"]
        options = {preselected[0]: chosen, **options}

    mo.stop(
        not options,
        mo.md(f"*No projects on this account; set `{PROJECT_ENV_VAR}` to one you can read.*"),
    )

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


#: Where the main guard binds.  Loopback would be the safer default, but a
#: notebook you have to be sitting at the machine to open is just `marimo edit`
#: with extra steps, so this serves to the network and says so in the docstring.
DEFAULT_HOST = "0.0.0.0"
DEFAULT_PORT = 8383

#: Overrides for the two above, in the same spirit as MERMAID_EXAMPLE_PROJECT.
HOST_ENV_VAR = "MERMAID_EXAMPLE_HOST"
PORT_ENV_VAR = "MERMAID_EXAMPLE_PORT"


def serve(host: str | None = None, port: int | None = None) -> None:
    """Serve the cells above as a read-only app, the way ``marimo run`` does.

    This is ``marimo run`` spelled out.  :func:`marimo.create_asgi_app` is
    marimo's public embedding API: it builds an ordinary ASGI application from
    one or more notebooks in Run mode, which any ASGI server can then run --
    uvicorn here, because that is what arrives with marimo and what the marimo
    CLI uses itself.  Serving it from your own app, mounted beside your own
    routes, is the same three calls.

    ``include_code=False`` keeps the source on this side of the wire: the
    browser is sent the running app and not the notebook.  Nothing here runs
    the cells in this process -- marimo loads them from the file's parse tree,
    which is why serving does not re-enter this module.
    """
    import os

    # A dependency of marimo rather than of datamermaid, so it is importable
    # wherever the `import marimo` at the top of this file succeeded.
    import uvicorn

    host = host or os.environ.get(HOST_ENV_VAR) or DEFAULT_HOST
    port = port or int(os.environ.get(PORT_ENV_VAR) or DEFAULT_PORT)

    application = (
        marimo.create_asgi_app(include_code=False).with_app(path="/", root=__file__).build()
    )

    print(f"Serving {os.path.basename(__file__)} on http://{host}:{port} -- Ctrl-C to stop")
    uvicorn.run(application, host=host, port=port)


if __name__ == "__main__":
    # `marimo edit` and `marimo run` never reach this line -- they read the
    # cells off the parse tree without executing anything at module level.  It
    # is only `python examples/09_marimo_notebook.py` that lands here, and it
    # serves the notebook rather than running its cells top to bottom, so that
    # reaching it in a browser takes no marimo CLI and no second command.
    serve()
