# datamermaid examples

Small, self-contained scripts, each one runnable on its own:

```bash
python examples/01_public_projects.py
uv run examples/01_public_projects.py   # with uv, from a checkout
```

They are numbered so they can be read in order — public endpoints first, then
signing in, then everything that needs a login.

| Example | Shows | Login |
| --- | --- | --- |
| [`quickstart.py`](https://github.com/gridcell/py-datamermaid/blob/main/examples/quickstart.py) | The README walk-through end to end, against a mocked API — runs offline, no account | no |
| [`01_public_projects.py`](https://github.com/gridcell/py-datamermaid/blob/main/examples/01_public_projects.py) | `get_projects()`, `limit`, the columns, collapsed list fields | no |
| [`02_search_projects.py`](https://github.com/gridcell/py-datamermaid/blob/main/examples/02_search_projects.py) | `search_projects()` by name/country/tag, `countries()` | no |
| [`03_authenticate.py`](https://github.com/gridcell/py-datamermaid/blob/main/examples/03_authenticate.py) | `authenticate()` in a browser, the device-code flow, the token cache, `get_token()`, `clear_cached_token()` | signs you in |
| [`04_token_from_env.py`](https://github.com/gridcell/py-datamermaid/blob/main/examples/04_token_from_env.py) | `MERMAID_API_TOKEN`, `token=` per call, one `MermaidClient` shared across calls | yes |
| [`05_my_projects.py`](https://github.com/gridcell/py-datamermaid/blob/main/examples/05_my_projects.py) | `get_me()`, `get_my_projects()`, `search_my_projects()` | yes |
| [`06_project_endpoints.py`](https://github.com/gridcell/py-datamermaid/blob/main/examples/06_project_endpoints.py) | `get_project_sites()`, `get_project_managements()`, `get_project_endpoint()`, `set_default_project()`, `as_project_ids()` | yes |
| [`07_project_data.py`](https://github.com/gridcell/py-datamermaid/blob/main/examples/07_project_data.py) | `get_project_data()` by method and level, `construct_endpoints()`, nested-dict results, covariates | yes |
| [`08_error_handling.py`](https://github.com/gridcell/py-datamermaid/blob/main/examples/08_error_handling.py) | `ValueError`, `MermaidAPIError`, `AuthenticationError`, `MermaidError` | no |
| [`09_marimo_notebook.py`](https://github.com/gridcell/py-datamermaid/blob/main/examples/09_marimo_notebook.py) | The same calls in a reactive [marimo](https://marimo.io) notebook: a sign-in button, `get_me()`, a project dropdown that refetches `get_project_sites()` and `get_project_data()` | signs you in |

## Running them

An example runs against whichever interpreter you invoke it with, so
`datamermaid` has to be installed for *that* interpreter. Spelling the install
`python -m pip` rather than a bare `pip` is what guarantees it:

```bash
python -m venv .venv && source .venv/bin/activate   # optional, but the tidiest
python -m pip install -e .          # or: python -m pip install datamermaid
python examples/quickstart.py
```

[uv](https://docs.astral.sh/uv/) makes the question moot, since `uv run` uses
the environment it just built rather than whatever `python` happens to mean —
and it will fetch an interpreter if there is none:

```bash
uv sync
uv run examples/quickstart.py
```

`quickstart.py` answers every request from an in-process mock transport, so it
needs neither network nor an account, and the test suite runs it. Every other
example talks to the real API at <https://api.datamermaid.org/v1/>.

Python 3.10 or newer; CI runs the suite on 3.10, 3.11, 3.12 and 3.13.

### The notebook

[`09_marimo_notebook.py`](https://github.com/gridcell/py-datamermaid/blob/main/examples/09_marimo_notebook.py)
is a [marimo](https://marimo.io) notebook, which is a Python file like the
rest — but marimo itself is an extra rather than a dependency, so install it
first:

```bash
python -m pip install 'datamermaid[notebook]'   # or: -e '.[notebook]'
marimo edit examples/09_marimo_notebook.py      # notebook, cells re-run as you edit
marimo run examples/09_marimo_notebook.py       # read-only app, no code shown
python examples/09_marimo_notebook.py           # the same read-only app, on 0.0.0.0:8383
```

The third of those is the notebook serving itself: its main guard calls
`serve()`, which builds a read-only app with `marimo.create_asgi_app()` and runs
it under uvicorn — the same thing `marimo run` does, without needing the marimo
CLI on the path. It binds every interface, so the notebook is reachable from
another machine; `MERMAID_EXAMPLE_HOST` and `MERMAID_EXAMPLE_PORT` override the
address and the port.

Two consequences of that address. Read-only is the mode rather than a
precaution to drop: `marimo edit --host 0.0.0.0` would offer a Python REPL on
the serving machine to anyone who can reach the port, and `include_code=False`
additionally keeps the notebook source on the server. And the app has no login
of its own — served with `MERMAID_API_TOKEN` already in the environment it comes
up signed in and shows that account's projects to every visitor, so leave the
variable unset unless that is what you want.

With uv, name the extra on `uv run` as well as on `uv sync` — `uv run` syncs
before it runs, and without the extra it would uninstall marimo again:

```bash
uv sync --extra notebook
uv run --extra notebook marimo edit examples/09_marimo_notebook.py
```

The extra asks for marimo 0.13.15 or newer, the oldest release the notebook has
been checked against: it serves itself there, and its cells stand down with
`mo.stop()` while there is no token, which older marimos got wrong — letting it
escape as a traceback, or running the stopped cell's dependants anyway.

Skip the extra and `python examples/09_marimo_notebook.py` says
`ModuleNotFoundError: No module named 'marimo'`, which is the one import in
`examples/` without the guard described below: marimo's own tooling looks for a
top-level `import marimo` and cannot save over a file that has none, so it has
to sit outside a `try`. A missing `datamermaid` does report itself the usual
way, naming `'datamermaid[notebook]'` as the install — under `python`, at
least; see below.

marimo opens the notebook with a warning that it "has errors": the import guard
every example here carries is module-level code, which a notebook file is not
supposed to have. Nothing breaks, because `marimo edit` and `marimo run` load a
notebook from its parse tree and never execute module-level code — which is
also why the guard only speaks up under `python examples/09_marimo_notebook.py`,
and a missing `datamermaid` reports itself from the first cell instead. Saving
from the editor regenerates the file from its cells and drops the guard; the
docstring survives.

### Troubleshooting

Every example checks its imports before doing anything, so a broken install
reports itself in one message naming your interpreter and the fix. Each message
opens with the package that failed — whichever import came first, so a clean
interpreter reports `httpx` or `pandas` rather than `datamermaid` — and then
says which of three things went wrong:

- **`<package> is not installed for this interpreter`** — the package is
  missing from the interpreter you ran. Usually a bare `pip` installed it into
  a *different* one; `python -m pip install -e .` cannot miss.
- **`httpx is installed for this interpreter but cannot be imported: it needs
  idna, which is missing`** — `httpx` (or `pandas`) is there but one of its own
  dependencies is not, which is a half-finished install rather than anything to
  do with this package. Reinstall it with
  `python -m pip install --force-reinstall httpx`, or start from a fresh
  virtual environment. The same message names `datamermaid` when it is
  `datamermaid` that is installed without its dependencies; the fix is the
  same reinstall.
- **`<package> is installed for this interpreter, but importing it failed
  anyway`** — nothing is missing; the import got as far as the package and
  failed on what it found. Normally that means the installed `datamermaid` is
  an older release than the example, which is written against this checkout, so
  `python -m pip install --upgrade datamermaid` (or `-e .`) is the fix rather
  than a reinstall. The quoted error says which name it could not import.

Without that check the same situation surfaces as a traceback ending in
`ModuleNotFoundError: No module named 'idna'`, several frames inside `httpx`
and with no mention of what to install.
[`_preflight.py`](https://github.com/gridcell/py-datamermaid/blob/main/examples/_preflight.py)
is the helper that writes those messages; it is not an example, and it
deliberately imports nothing beyond the standard library.

All three are ways of running an example against an environment that is not the
one the package was installed into, so all three go away under `uv run`, which
syncs the environment before it runs the script. From a checkout of this
repository, `uv sync && uv run examples/quickstart.py` rebuilds `.venv` from
`pyproject.toml` and cannot get out of step with it.

## Credentials

Examples 01, 02 and 08 use public endpoints and need no account. The rest need
a MERMAID login, resolved in this order:

1. a `token=` argument, if the call passes one;
2. the `MERMAID_API_TOKEN` environment variable;
3. the cache written by `datamermaid.authenticate()`
   (`~/.config/datamermaid/token.json` by default).

Start with `python examples/03_authenticate.py` to sign in and fill the cache,
or export a token you already have:

```bash
export MERMAID_API_TOKEN="eyJhbGciOi..."
```

No example hardcodes a token, and none prints more than a masked prefix of one.

## Choosing a project

The project-scoped examples (06, 07, 09) need a project id. They read
`MERMAID_EXAMPLE_PROJECT` if it is set, and otherwise use the first project on
your account — the notebook puts the named project in its dropdown, whether or
not it is one of your own, and preselects it — so nothing here depends on a
UUID that may go away:

```bash
export MERMAID_EXAMPLE_PROJECT="00673bec-..."
```

## Not covered here

The global reference endpoints (`get_reference()`, `get_sites()`,
`get_managements()`, `get_summary_sampleevents()`, `get_choices()`) and the
import/write path (`import_*`) are documented in the
[main README](https://github.com/gridcell/py-datamermaid/blob/main/README.md#global-data)
instead; the write path in particular is better read than run, since every one
of its actions changes a real project.
