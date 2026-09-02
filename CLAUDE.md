# Project Instructions for AI Agents

This file provides instructions and context for AI coding agents working on this project.

<!-- BEGIN BEADS INTEGRATION v:1 profile:minimal hash:6cd5cc61 -->
## Beads Issue Tracker

This project uses **bd (beads)** for issue tracking. Run `bd prime` to see full workflow context and commands.

### Quick Reference

```bash
bd ready              # Find available work
bd show <id>          # View issue details
bd update <id> --claim  # Claim work
bd close <id>         # Complete work
```

### Rules

- Use `bd` for ALL task tracking — do NOT use TodoWrite, TaskCreate, or markdown TODO lists
- Run `bd prime` for detailed command reference and session close protocol
- Use `bd remember` for persistent knowledge — do NOT use MEMORY.md files

**Architecture in one line:** issues live in a local Dolt DB; sync uses `refs/dolt/data` on your git remote; `.beads/issues.jsonl` is a passive export. See https://github.com/gastownhall/beads/blob/main/docs/SYNC_CONCEPTS.md for details and anti-patterns.

## Agent Context Profiles

The managed Beads block is task-tracking guidance, not permission to override repository, user, or orchestrator instructions.

- **Conservative (default)**: Use `bd` for task tracking. Do not run git commits, git pushes, or Dolt remote sync unless explicitly asked. At handoff, report changed files, validation, and suggested next commands.
- **Minimal**: Keep tool instruction files as pointers to `bd prime`; use the same conservative git policy unless active instructions say otherwise.
- **Team-maintainer**: Only when the repository explicitly opts in, agents may close beads, run quality gates, commit, and push as part of session close. A current "do not commit" or "do not push" instruction still wins.

## Session Completion

This protocol applies when ending a Beads implementation workflow. It is subordinate to explicit user, repository, and orchestrator instructions.

1. **File issues for remaining work** - Create beads for anything that needs follow-up
2. **Run quality gates** (if code changed) - Tests, linters, builds
3. **Update issue status** - Close finished work, update in-progress items
4. **Handle git/sync by active profile**:
   ```bash
   # Conservative/minimal/default: report status and proposed commands; wait for approval.
   git status

   # Team-maintainer opt-in only, unless current instructions forbid it:
   git pull --rebase
   git push
   git status
   ```
5. **Hand off** - Summarize changes, validation, issue status, and any blocked sync/commit/push step

**Critical rules:**
- Explicit user or orchestrator instructions override this Beads block.
- Do not commit or push without clear authority from the active profile or the current user request.
- If a required sync or push is blocked, stop and report the exact command and error.
<!-- END BEADS INTEGRATION -->


## Build & Test

Pure-Python package (`hatchling` build, `src/` layout). Python 3.10+; runtime
dependencies are `httpx` and `pandas` only.

```bash
python -m pip install -e ".[dev]"  # package + pytest, respx, ruff, marimo
pytest                       # unit tests + doctests; fully offline (respx / MockTransport)
ruff check .                 # lint (E, F, I, UP, B, W; line length 100)
ruff format --check .        # formatting
python examples/quickstart.py  # README workflow against a mocked API
```

Or with [uv](https://docs.astral.sh/uv/), which is what CI runs and which needs
no pre-existing interpreter:

```bash
uv sync --extra dev          # .venv: the checkout (editable) + pytest, respx, ruff, marimo
uv run --extra dev pytest
uv run --extra dev ruff check .
uv run --extra dev ruff format --check .
uv run python examples/quickstart.py
uv run --python 3.10 --extra dev pytest   # the other half of the CI matrix
```

The suite never needs marimo -- `examples/09_marimo_notebook.py` is parsed like
the rest -- but the dev extra installs it anyway, so a `uv sync --extra dev`
checkout can run the notebook without a second sync:

```bash
uv run --extra dev marimo edit examples/09_marimo_notebook.py
uv run --extra dev python examples/09_marimo_notebook.py  # as a script
```

The `notebook` extra is the same marimo pin for people who install the package
rather than the checkout; it is what `datamermaid[notebook]` means.

`--extra dev` on `uv run` too: it syncs before running, and without the extra
it may uninstall the dev tools. `uv.lock` and `.python-version` are gitignored
on purpose — the pins are loose and the matrix is meant to vary them — so
nothing here takes `--frozen`.

CI (`.github/workflows/ci.yml`) runs `ruff check`, `ruff format --check`, and
`pytest` under uv on Python 3.10 and 3.12. All three must pass; there is no
network in tests, so never add a test that hits `api.datamermaid.org`.

## Architecture Overview

`datamermaid` is a port of the R package [mermaidr](https://github.com/data-mermaid/mermaidr):
each `mermaid_*` function maps to a same-named function without the prefix, and
tibbles become `pandas.DataFrame`s. The README's migration table is the
authoritative list; `tests/test_docs.py` checks it against `__all__`.

```
src/datamermaid/
  __init__.py          public surface; `__all__` is the contract
  client.py            MermaidClient: httpx wrapper, pagination, CSV, lazy auth; default_client()
  auth.py              Auth0 PKCE + device-code sign-in, token cache, MERMAID_API_TOKEN
  exceptions.py        MermaidError > MermaidAPIError, AuthenticationError
  utils.py             records -> DataFrame, list-column collapsing (mermaidr semantics)
  projects.py          get_projects / search_projects / get_my_projects / search_my_projects
  me.py                get_me (single object, returns dict)
  project_endpoints.py projects/{id}/{endpoint}: sites, managements, generic getter,
                       as_project_ids() coercion and the default project
  project_data.py      get_project_data(): method x data level -> CSV endpoints
  endpoints.py         global unauthenticated endpoints: sites, managements, reference, choices
  import_.py           write path: template/options, option checks, ingest, bulk actions
tests/                 pytest + respx; fixtures/ holds trimmed real MERMAID CSVs
examples/quickstart.py the README walk-through on an httpx.MockTransport (run by tests)
examples/NN_*.py       numbered, runnable scripts per capability; they hit the real
                       API, so tests/test_examples.py only parses them (drift guard)
examples/09_marimo_notebook.py
                       the one example that is a marimo notebook rather than a
                       script (`marimo.App`, @app.cell, app.run() under the main
                       guard) -- authenticated walk-through driven by a sign-in
                       button and a project dropdown.  marimo is an extra
                       (`dev` and `notebook`), never a dependency; a cell cannot see module-level
                       names, so each imports what it uses, and `import marimo`
                       stays unindented because marimo's tooling needs it there
examples/_preflight.py stdlib-only helper: every example wraps its third-party
                       imports in try/except ImportError and raises
                       missing_dependency(exc), which names the interpreter and
                       the fix -- install (absent), reinstall (its own deps are
                       absent) or upgrade (imported, wrong version) -- instead
                       of letting a traceback surface from inside httpx.  The
                       handler puts examples/ on sys.path first, so it works
                       under `python -P` too.  `distribution=` names an extra
                       ("datamermaid[notebook]") for an example that needs more
                       than the package.  `_`-prefixed files in examples/ are
                       helpers, not examples.
```

Request flow: a public function resolves its `client=`/`token=` arguments via
`client_context()` (client.py), which yields the process-wide `MermaidClient`
or a throwaway one carrying the token. `MermaidClient.get()` walks MERMAID's
`{count, next, previous, results}` envelope honouring `limit`; `get_one()`
fetches bare objects (`me/`); `get_csv()` parses the per-project CSV
endpoints. Endpoints marked `require_auth=True` resolve a token lazily
(explicit > `MERMAID_API_TOKEN` > cache) and raise `AuthenticationError`
before any request when none is found.

## Conventions & Patterns

- Mirror mermaidr's behaviour and argument names (singular: `country=`, `tag=`)
  unless Python idiom clearly wins; note deviations in the README migration table.
- Every public function: numpy-style docstring with Parameters / Returns /
  Raises / Examples (`# doctest: +SKIP` for anything that needs the network;
  offline examples run as doctests via `pytest --doctest-modules`).
- Adding a public name: export it in the module's `__all__`, in
  `datamermaid/__init__.py`'s `__all__`, and in the README (migration table or
  "Python-only additions").
- Argument mistakes raise `ValueError` before any request; HTTP failures raise
  `MermaidAPIError`; missing/rejected logins raise `AuthenticationError`.
- Anything that writes to MERMAID or acts on a whole project needs an explicit
  `confirm=True`-style argument — nothing prompts, so it can run unattended.
- Tests are offline. Mock with `respx` against `API_BASE_URL` (see
  `tests/conftest.py` helpers) or `httpx.MockTransport`; the autouse fixtures
  isolate the token cache and default project.
- `CLAUDE.md` and `AGENTS.md` are independent files: mirror substantive edits
  to both.
