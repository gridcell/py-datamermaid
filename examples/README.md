# datamermaid examples

Small, self-contained scripts, each one runnable on its own:

```bash
python examples/01_public_projects.py
```

They are numbered so they can be read in order — public endpoints first, then
signing in, then everything that needs a login.

| Example | Shows | Login |
| --- | --- | --- |
| [`quickstart.py`](quickstart.py) | The README walk-through end to end, against a mocked API — runs offline, no account | no |
| [`01_public_projects.py`](01_public_projects.py) | `get_projects()`, `limit`, the columns, collapsed list fields | no |
| [`02_search_projects.py`](02_search_projects.py) | `search_projects()` by name/country/tag, `countries()` | no |
| [`03_authenticate.py`](03_authenticate.py) | `authenticate()` in a browser, the device-code flow, the token cache, `get_token()`, `clear_cached_token()` | signs you in |
| [`04_token_from_env.py`](04_token_from_env.py) | `MERMAID_API_TOKEN`, `token=` per call, one `MermaidClient` shared across calls | yes |
| [`05_my_projects.py`](05_my_projects.py) | `get_me()`, `get_my_projects()`, `search_my_projects()` | yes |
| [`06_project_endpoints.py`](06_project_endpoints.py) | `get_project_sites()`, `get_project_managements()`, `get_project_endpoint()`, `set_default_project()`, `as_project_ids()` | yes |
| [`07_project_data.py`](07_project_data.py) | `get_project_data()` by method and level, `construct_endpoints()`, nested-dict results, covariates | yes |
| [`08_error_handling.py`](08_error_handling.py) | `ValueError`, `MermaidAPIError`, `AuthenticationError`, `MermaidError` | no |

## Running them

```bash
pip install -e .            # or: pip install datamermaid
python examples/quickstart.py
```

`quickstart.py` answers every request from an in-process mock transport, so it
needs neither network nor an account, and the test suite runs it. Every other
example talks to the real API at <https://api.datamermaid.org/v1/>.

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

The project-scoped examples (06, 07) need a project id. They read
`MERMAID_EXAMPLE_PROJECT` if it is set, and otherwise use the first project on
your account, so nothing here depends on a UUID that may go away:

```bash
export MERMAID_EXAMPLE_PROJECT="00673bec-..."
```

## Not covered here

The global reference endpoints (`get_reference()`, `get_sites()`,
`get_managements()`, `get_summary_sampleevents()`, `get_choices()`) and the
import/write path (`import_*`) are documented in the
[main README](../README.md#global-data) instead; the write path in particular
is better read than run, since every one of its actions changes a real project.
