# datamermaid

A Python client for the [MERMAID](https://datamermaid.org) coral reef
monitoring API, and a port of the R package
[mermaidr](https://github.com/data-mermaid/mermaidr). Every `mermaid_*`
function in mermaidr has a `datamermaid` equivalent — see
[Migrating from mermaidr](#migrating-from-mermaidr) — and tabular results come
back as [pandas](https://pandas.pydata.org) `DataFrame`s.

The workflow is mermaidr's: **authenticate → find projects → pull project
data → pull reference data**. Public data needs no account.

- [Install](#install)
- [Authentication](#authentication)
- [Quickstart](#quickstart)
- [Examples](#examples)
- [Finding projects](#finding-projects)
- [Project data](#project-data)
  - [`get_project_data()` — methods and data levels](#get_project_data--methods-and-data-levels)
- [Global data](#global-data)
- [Return shapes](#return-shapes)
- [Errors](#errors)
- [Importing data](#importing-data)
- [Migrating from mermaidr](#migrating-from-mermaidr)
- [Development](#development)
- [License](#license)

## Install

```bash
python -m pip install datamermaid
```

Or, from a checkout of this repository:

```bash
python -m pip install -e .               # the package
python -m pip install -e ".[dev]"        # plus pytest, respx, ruff and marimo
python -m pip install -e ".[notebook]"   # just marimo, for examples/09_marimo_notebook.py
```

Or with [uv](https://docs.astral.sh/uv/), which needs no interpreter of its own
and will fetch one:

```bash
uv add datamermaid                  # into a uv project
uv pip install datamermaid          # into the active environment
uv sync --extra dev                 # from a checkout: .venv with the package and its dev tools
```

Python 3.10 or newer; the only runtime dependencies are `httpx` and `pandas`.
CI runs the test suite on 3.10 and 3.12, under uv.

`python -m pip` rather than a bare `pip` on purpose: it installs into the
interpreter you name, whereas `pip` may belong to another one — the usual
reason an import fails for a package that looks installed. The examples check
for this and say so; see
[Troubleshooting](examples/README.md#troubleshooting) if one of them reports a
missing module. `uv run` sidesteps the question entirely: it runs whatever it
just installed.

## Authentication

Your own projects, and anything else behind a login, need a MERMAID access
token. Tokens are issued by MERMAID's Auth0 tenant and last about a day.
Public endpoints — `get_projects()`, `get_sites()`, `get_reference()`, and so
on — work without one.

### Signing in from a browser

```python
import datamermaid

datamermaid.authenticate()
```

This opens your browser, asks you to sign in to MERMAID, and stores the
resulting token so later sessions do not have to sign in again. The flow is an
OAuth2 Authorization Code grant with PKCE against MERMAID's public client — no
client secret is involved, and the code is exchanged for a token by a
short-lived HTTP server listening on `localhost` only.

If the browser cannot be used (over SSH, for example), the flow falls back to a
device code: a URL and a short code are printed for you to open on another
machine. You can ask for that directly:

```python
datamermaid.authenticate(use_device_code=True)
```

To sign in as a different user, discard the saved token first:

```python
datamermaid.authenticate(new_user=True)
```

### The token cache

The token is written to `$XDG_CONFIG_HOME/datamermaid/token.json` (by default
`~/.config/datamermaid/token.json`) with owner-only permissions, alongside its
expiry. It is reused until it expires, and
`datamermaid.authenticate(new_user=True)` — or
`datamermaid.clear_cached_token()` — removes it. A token the API rejects is
discarded too, so the next `authenticate()` call signs in afresh.
`get_token()` returns the current token without ever prompting, or `None` when
there is none.

### `MERMAID_API_TOKEN` (CI and servers)

In a non-interactive environment, set the token in the environment instead. It
takes precedence over the cache and the browser flow, so nothing tries to open
a browser:

```bash
export MERMAID_API_TOKEN="eyJhbGciOi..."
```

```python
datamermaid.get_my_projects()  # uses MERMAID_API_TOKEN
```

### Passing a token explicitly

Every function that needs a login takes `token=`, which overrides everything
else for that call, and `client=`, for reusing one connection:

```python
from datamermaid import MermaidClient

my_projects = datamermaid.get_my_projects(token="eyJhbGciOi...")

with MermaidClient(token="eyJhbGciOi...") as client:
    me = datamermaid.get_me(client=client)
    sites = datamermaid.get_project_sites(my_projects, client=client)
```

`set_default_client()` swaps the client every module-level function uses,
which is how to point the package at another API root or, as
[`examples/quickstart.py`](examples/quickstart.py) does, at a mock transport.

## Quickstart

The mermaidr README's walk-through, in Python:

```python
import datamermaid

datamermaid.authenticate()

me = datamermaid.get_me()
me["full_name"]

# Your projects, as a DataFrame
projects = datamermaid.get_my_projects()
projects[["id", "name", "countries", "num_sites"]]

# ...or just the ones matching a country or tag
fiji = datamermaid.search_my_projects(country="Fiji", tag="WCS Fiji")

# Anything that takes a project accepts an id, a list of ids, or a frame of projects
sites = datamermaid.get_project_sites(fiji)
managements = datamermaid.get_project_managements(fiji)

# Survey data: one method and one aggregation level gives a single frame
sample_events = datamermaid.get_project_data(fiji, "fishbelt", "sampleevents")
sample_events[["site", "sample_date", "biomass_kgha_avg"]]

# Ask for several and get a nested dict of frames
fishbelt = datamermaid.get_project_data(fiji, "fishbelt", "all")
fishbelt["fishbelt"]["observations"]

# Set a default project to leave it out of later calls
datamermaid.set_default_project(fiji)
datamermaid.get_project_data(method="benthicpit", data="sampleunits")

# Reference data needs no login
fish_families = datamermaid.get_reference("fishfamilies")
```

[`examples/quickstart.py`](examples/quickstart.py) runs exactly this against a
mocked API, so it can be executed offline:

```bash
python examples/quickstart.py
```

## Examples

[`examples/`](examples/README.md) holds a numbered set of small runnable
scripts, one per capability — public project listing and search, the three
ways to authenticate, your own projects, project-scoped endpoints, survey
data, and error handling:

```bash
python examples/01_public_projects.py   # public data; no account needed
python examples/03_authenticate.py      # sign in and cache a token
python examples/07_project_data.py      # survey data, by method and level
```

The last of them, [`09_marimo_notebook.py`](examples/09_marimo_notebook.py), is
a [marimo](https://marimo.io) notebook rather than a script: a sign-in button
and a project dropdown, with the cells that read them refetching on their own.
marimo is an extra, since nothing in the package needs it:

```bash
python -m pip install 'datamermaid[notebook]'
marimo edit examples/09_marimo_notebook.py
```

[`examples/README.md`](examples/README.md) indexes them and says which need a
login. Only `quickstart.py` runs offline; the rest talk to the real API.

Each script verifies that `datamermaid` and its dependencies are importable
before it does anything, so running one against an interpreter that lacks them
prints what to install rather than a traceback from inside `httpx`. The cases
and their fixes are in
[Troubleshooting](examples/README.md#troubleshooting).

## Finding projects

```python
projects = datamermaid.get_projects(limit=5)  # public; no login needed
projects[["id", "name", "countries", "num_sites"]]
```

`get_projects()` returns a `DataFrame` with one row per project. Pass
`limit=None` (the default) to fetch every project — pagination is handled for
you. Test projects are excluded unless you pass `include_test_projects=True`.

`search_projects()` narrows the list by name, country, or tag. Each is an
optional case-insensitive substring match, applied client-side after every
project has been read, so `limit` caps the *matches*:

```python
fijian = datamermaid.search_projects(country="Fiji", tag="WCS")
```

Once signed in, `get_my_projects()` and `search_my_projects()` do the same for
the projects you are a member of.

### Naming a project

Every function that takes a `project` accepts the same shapes: a project id,
a list of ids, a project record (any mapping with an `id`), the `DataFrame`
returned by `get_projects()`, or a single row of it. `as_project_ids()` is the
coercion behind this, and is exposed for validating an argument up front:

```python
datamermaid.as_project_ids(projects)  # ['00673bec-...', '2c0c9857-...']
```

### The default project

Set a default project once to leave it out of every later call:

```python
datamermaid.set_default_project("00673bec-...")
datamermaid.get_project_sites()  # uses the default project
datamermaid.get_default_project()  # ['00673bec-...']
datamermaid.set_default_project(None)  # clear it
```

The default is also read from the `MERMAID_DEFAULT_PROJECT` environment
variable (comma separated for several projects), and `set_default_project()`
exports it there so subprocesses inherit it. Calling a project function with no
project and no default raises `ValueError`.

## Project data

A project's sites, management regimes, and survey data live behind
`projects/{project_id}/...` and need a login, since only project members can
read them. The token is resolved as described under
[Authentication](#authentication), so once you are signed in nothing has to be
passed:

```python
sites = datamermaid.get_project_sites("00673bec-...")
managements = datamermaid.get_project_managements("00673bec-...")
```

Passing several projects issues one request per project and returns a single
concatenated frame whose leading `project` column names the project each row
came from. `limit` applies per project.

Other project endpoints can be reached with the generic getter, which takes
extra keyword arguments as query parameters:

```python
datamermaid.get_project_endpoint("00673bec-...", "sites", country="Fiji")
```

### `get_project_data()` — methods and data levels

`get_project_data()` returns a project's survey data. A survey `method` and an
aggregation level (`data`) name a CSV endpoint under the project, which is
parsed into a `DataFrame`:

```python
observations = datamermaid.get_project_data("00673bec-...", "fishbelt", "observations")
sample_events = datamermaid.get_project_data("00673bec-...", "fishbelt", "sampleevents")
```

Every method MERMAID publishes is supported at every level. The table lists the
endpoint each combination reads, relative to `projects/{project_id}/` and
before the trailing `csv/`; it is what `datamermaid.construct_endpoints()`
returns, and needs no login to inspect:

| `method` | `observations` | `sampleunits` | `sampleevents` |
| --- | --- | --- | --- |
| `fishbelt` | `beltfishes/obstransectbeltfishes` | `beltfishes/sampleunits` | `beltfishes/sampleevents` |
| `benthiclit` | `benthiclits/obstransectbenthiclits` | `benthiclits/sampleunits` | `benthiclits/sampleevents` |
| `benthicpit` | `benthicpits/obstransectbenthicpits` | `benthicpits/sampleunits` | `benthicpits/sampleevents` |
| `benthicpqt` | `benthicpqts/obstransectbenthicpqts` | `benthicpqts/sampleunits` | `benthicpqts/sampleevents` |
| `habitatcomplexity` | `habitatcomplexities/obshabitatcomplexities` | `habitatcomplexities/sampleunits` | `habitatcomplexities/sampleevents` |
| `bleaching` | `bleachingqcs/obscoloniesbleacheds` + `bleachingqcs/obsquadratbenthicpercents` | `bleachingqcs/sampleunits` | `bleachingqcs/sampleevents` |
| `macroinvertebrate` | `beltinverts/obstransectbeltinverts` | `beltinverts/sampleunits` | `beltinverts/sampleevents` |

The valid names are exposed as `datamermaid.METHODS` and
`datamermaid.DATA_LEVELS`. Either argument also takes a list, or `"all"`.
Asking for more than one combination returns a nested
`{method: {data: DataFrame}}` dict instead of a single frame, keyed in the
order of the table above however you asked for them:

```python
fishbelt = datamermaid.get_project_data("00673bec-...", "fishbelt", "all")
fishbelt["fishbelt"]["sampleunits"]

everything = datamermaid.get_project_data("00673bec-...", "all", "all")
everything["macroinvertebrate"]["sampleevents"]
```

Bleaching observations are the one combination MERMAID splits across two
endpoints — colonies bleached and percent cover — so they come back as two
named frames rather than one, the same split mermaidr returns as a named list:

```python
bleaching = datamermaid.get_project_data("00673bec-...", "bleaching", "observations")
bleaching["colonies_bleached"]
bleaching["percent_cover"]
```

That pair takes the place of a frame wherever one would otherwise sit, so it is
what the `"observations"` entry holds inside the nested dict too.

`project` takes the same shapes as the other project functions, and the
default project is used when it is omitted. When more than one project is
named, the rows are stacked and a leading `project_id` column says which
project each row came from (MERMAID's own CSVs already use `project` for the
project *name*). `limit` truncates the rows returned per project (per
endpoint, so both bleaching observation frames are truncated), and
`covariates=True` asks MERMAID for its derived site covariates alongside the
survey data. A project with no data for a method gives an empty frame rather
than an error. An invalid method or data level raises `ValueError` naming the
valid options, before any request is made.

## Global data

MERMAID publishes its sites, management regimes, reference tables and summary
data without a login. Each getter returns a `DataFrame` and takes the same
`limit` as `get_projects()`:

```python
sites = datamermaid.get_sites(limit=100)
managements = datamermaid.get_managements()
events = datamermaid.get_summary_sampleevents(limit=1000)  # large; sample it

fish_families = datamermaid.get_reference("fishfamilies")
```

`get_reference()` accepts `"fishfamilies"`, `"fishgenera"`, `"fishspecies"`,
`"benthicattributes"` or `"fishgroupings"` (`datamermaid.REFERENCE_ENDPOINTS`)
and raises `ValueError` listing those options for anything else.

`get_choices()` returns MERMAID's controlled vocabularies as a dict of frames,
one per vocabulary, and `countries()` pulls the country names out of it:

```python
choices = datamermaid.get_choices()
choices["reeftypes"]  # DataFrame with id, name, ...
datamermaid.countries()[:3]  # ['Afghanistan', 'Albania', 'Algeria']
```

Any other global endpoint can be reached with the generic getter, which passes
extra keyword arguments through as query parameters. Endpoint names outside
`datamermaid.KNOWN_ENDPOINTS` are still requested, with a `UserWarning`:

```python
datamermaid.get_endpoint("fishsizes")
datamermaid.get_endpoint("sites", country="Fiji", limit=50)
```

## Return shapes

| Function | Returns |
| --- | --- |
| `get_projects`, `search_projects`, `get_my_projects`, `search_my_projects` | `DataFrame`, one row per project |
| `get_sites`, `get_managements`, `get_reference`, `get_summary_sampleevents`, `get_endpoint` | `DataFrame`, one row per record |
| `get_project_sites`, `get_project_managements`, `get_project_endpoint` | `DataFrame` with a leading `project` column (the project id) |
| `get_project_data` — one method, one level | `DataFrame`; with several projects, a leading `project_id` column |
| `get_project_data` — `bleaching`/`observations` | `{"colonies_bleached": DataFrame, "percent_cover": DataFrame}` |
| `get_project_data` — several methods or levels | `{method: {data: <either of the above>}}` |
| `get_me` | `dict` — `me/` answers with a single object |
| `get_choices` | `dict[str, DataFrame]`, one frame per vocabulary |
| `countries` | `list[str]` |
| `get_default_project`, `as_project_ids` | `list[str]` of project ids (`None` when no default is set) |
| `construct_endpoints` | `{method: {data: [endpoint, ...]}}` |
| `get_token`, `authenticate` | the bearer token as a `str` (`get_token` gives `None` when there is none) |
| `import_get_template_and_options` | `(DataFrame, dict)` — the empty template and the field options |
| `import_check_options`, `import_bulk_*` | `DataFrame` reports, described under [Importing data](#importing-data) |
| `import_project_data` | `None` on success, otherwise a `DataFrame` of problems |

Frames keep MERMAID's column names. List-valued fields such as `countries` and
`tags` are collapsed to comma-separated strings, as mermaidr does — a list of
`{id, name}` objects collapses to its names — so a project in two countries
shows `"Fiji, Tonga"`.

## Errors

| Exception | When |
| --- | --- |
| `datamermaid.MermaidAPIError` | The API answered with an error status; carries `status_code`, `reason` and `url`. |
| `datamermaid.AuthenticationError` | No token could be found for an endpoint that needs one (raised before any request), or MERMAID rejected the token. The message says how to sign in. |
| `datamermaid.MermaidError` | Base class of both, for catching everything the package raises. |
| `ValueError` | Argument mistakes: an unknown method, data level or reference table, a bad `limit`, a project argument with no id, a project function called with no project and no default, or a bulk action without `confirm=True`. |

## Importing data

The write path pushes records into MERMAID Collect. It needs a login, and the
project must be one you can write to.

**Nothing is written unless you say so.** `import_project_data()` dry-runs by
default: MERMAID checks the records and reports what is wrong with them without
saving anything. Only `dryrun=False` actually imports. The same goes for the
rest of the workflow — `clearexisting=True` also needs
`clearexisting_confirm=True`, and the bulk submit and edit actions need
`confirm=True`. Nothing prompts, so all of this runs unattended.

### 1. Get the template and the field options

```python
template, options = datamermaid.import_get_template_and_options("00673bec-...", "fishbelt")

list(template.columns)
# ['Site *', 'Management *', 'Sample date: Year *', ...]

options["Reef slope"]
# {'required': False, 'help_text': 'Slope of the reef', 'choices': ['crest', 'flat', 'slope', 'wall']}
```

`template` is an empty `DataFrame` whose columns are the headings MERMAID
expects — required ones carry a trailing `*`. `options` maps each of those
headings to whether it is required, its help text, and the values MERMAID will
accept. A column with no `choices` accepts any value. (mermaidr returns these as
one list with the template under a `"Template"` key; keeping them apart means
`options` is a plain mapping.)

### 2. Check your columns against the options

```python
datamermaid.import_check_options(my_data, options, "Reef slope")
#   data_value closest_choice  match
# 0        wal           wall  False
# 1      crest          crest   True
```

One row per distinct value in the column, with the closest allowed value and
whether it matched (case-insensitively). Values that did not match come first.
The report is empty when there is nothing to check — the column accepts any
value, or it is optional and entirely empty.

### 3. Import

```python
problems = datamermaid.import_project_data(my_data, "00673bec-...", "fishbelt")

if problems is None:
    datamermaid.import_project_data(my_data, "00673bec-...", "fishbelt", dryrun=False)
```

`data` is a `DataFrame` or the path to a CSV file; missing values are uploaded
as empty fields. The return value is `None` when MERMAID accepted the records,
and a `DataFrame` of the per-row problems it found when it did not — with a
leading `row_number` counting the rows of your data from 1. An outright failure
(a missing column, an unknown project, one you cannot write to) raises
`MermaidAPIError`.

`clearexisting=True` deletes every existing record for that method in the
project first. It cannot be combined with a dry run, and it needs
`clearexisting_confirm=True` as well.

### 4. Validate, submit, and edit in bulk

```python
datamermaid.import_bulk_validate("00673bec-...")
#      status  n
# 0     error  2
# 1   warning  1
# 2        ok  3

datamermaid.import_bulk_submit("00673bec-...", confirm=True)
datamermaid.import_bulk_edit("00673bec-...", "fishbelt", confirm=True)
```

Each returns a `status`/`n` summary, including the statuses that did not occur.
`import_bulk_validate()` asks MERMAID to check every record on the Collecting
page and needs no confirmation, since it neither creates nor moves anything.
`import_bulk_submit()` submits only the records that validated without errors
*or* warnings; `import_bulk_edit()` moves every submitted record for one method
back to Collecting. Both act on the whole project at once, so both require
`confirm=True`.

Progress is reported through the `datamermaid` logger rather than printed, so
turn logging on to see it:

```python
import logging

logging.basicConfig(level=logging.INFO)
```

## Migrating from mermaidr

Drop the `mermaid_` prefix and you usually have the Python name. Arguments are
singular where mermaidr's are plural (`country=` rather than `countries=`),
results are `DataFrame`s rather than tibbles, and named lists become dicts.
Every function mermaidr exports is listed here.

| mermaidr | datamermaid | Notes |
| --- | --- | --- |
| `mermaid_auth()` | `datamermaid.authenticate()` | Same `new_user=`. Adds `use_device_code=` for headless machines and the `MERMAID_API_TOKEN` environment variable. Returns the token. |
| `mermaid_token()` | `datamermaid.get_token()` | Never prompts; returns `None` when there is no token. `clear_cached_token()` discards the cache. |
| `mermaid_get_me()` | `datamermaid.get_me()` | Returns a `dict`, not a one-row tibble. |
| `mermaid_get_projects()` | `datamermaid.get_projects()` | Same `limit=` and `include_test_projects=`. |
| `mermaid_search_projects()` | `datamermaid.search_projects()` | `name=`, `country=`, `tag=` (singular). Filters client-side, like mermaidr. |
| `mermaid_get_my_projects()` | `datamermaid.get_my_projects()` | Adds `token=` and `client=`, as does every function that needs a login. |
| `mermaid_search_my_projects()` | `datamermaid.search_my_projects()` | As `search_projects()`. |
| `mermaid_set_default_project()` | `datamermaid.set_default_project()` | Also exports `MERMAID_DEFAULT_PROJECT`; pass `None` to clear. |
| `mermaid_get_default_project()` | `datamermaid.get_default_project()` | Always a `list`, or `None` when unset. |
| `mermaid_get_project_endpoint()` | `datamermaid.get_project_endpoint()` | Extra keyword arguments become query parameters; `columns=` selects columns. |
| `mermaid_get_project_sites()` | `datamermaid.get_project_sites()` | Leading `project` column holds the project *id*. |
| `mermaid_get_project_managements()` | `datamermaid.get_project_managements()` | As above. |
| `mermaid_get_project_data()` | `datamermaid.get_project_data()` | Same `method=`, `data=`, `limit=`, `covariates=`. Several methods or levels give a nested `dict` rather than a named list; stacked projects carry `project_id`. |
| `mermaid_get_endpoint()` | `datamermaid.get_endpoint()` | Extra keyword arguments become query parameters. Unknown endpoints warn rather than error. |
| `mermaid_get_sites()` | `datamermaid.get_sites()` | |
| `mermaid_get_managements()` | `datamermaid.get_managements()` | |
| `mermaid_get_reference()` | `datamermaid.get_reference()` | Same five reference tables (`REFERENCE_ENDPOINTS`). |
| `mermaid_get_summary_sampleevents()` | `datamermaid.get_summary_sampleevents()` | |
| `mermaid_countries()` | `datamermaid.countries()` | A `list[str]`. `get_choices()` (internal in mermaidr) exposes every vocabulary as a `dict` of frames. |
| `mermaid_import_get_template_and_options()` | `datamermaid.import_get_template_and_options()` | Returns a `(template, options)` tuple rather than one list with a `"Template"` entry. No `save=`; write the template with `template.to_csv()`. |
| `mermaid_import_check_options()` | `datamermaid.import_check_options()` | Same `data, options, field` arguments; reports as a `DataFrame`. |
| `mermaid_import_project_data()` | `datamermaid.import_project_data()` | Same `dryrun=True` default. `clearexisting=True` also needs `clearexisting_confirm=True` instead of a console prompt. Returns `None` on success, or a frame of problems. |
| `mermaid_import_bulk_validate()` | `datamermaid.import_bulk_validate()` | Returns the `status`/`n` counts instead of printing them. |
| `mermaid_import_bulk_submit()` | `datamermaid.import_bulk_submit()` | `confirm=True` replaces the console prompt. |
| `mermaid_import_bulk_edit()` | `datamermaid.import_bulk_edit()` | `confirm=True` replaces the console prompt; `method` is required. |

Not ported yet: `mermaid_get_classification_labelmappings()` and
`mermaid_get_gfcr_report()`. Both endpoints can be reached in the meantime with
`get_endpoint()` / `get_project_endpoint()`. mermaidr's `%>%` re-export has no
counterpart; use pandas method chaining.

Python-only additions: `MermaidClient` / `default_client()` /
`set_default_client()` for connection reuse and testing, `as_project_ids()`,
`construct_endpoints()`, and the constants `METHODS`, `DATA_LEVELS`,
`REFERENCE_ENDPOINTS`, `KNOWN_ENDPOINTS`, `METHOD_ENDPOINTS`, `API_BASE_URL`,
`DEFAULT_PAGE_SIZE`, `TOKEN_ENV_VAR` and `DEFAULT_PROJECT_ENV_VAR`.

## Development

```bash
python -m pip install -e ".[dev]"
pytest                    # offline; all HTTP is mocked with respx
ruff check .
ruff format --check .
python examples/quickstart.py
```

The same thing under [uv](https://docs.astral.sh/uv/), which is what CI runs.
`uv sync` builds a `.venv` holding the checkout (editable) plus pytest, respx
and ruff, and `uv run` uses it without anything being activated:

```bash
uv sync --extra dev
uv run --extra dev pytest
uv run --extra dev ruff check .
uv run --extra dev ruff format --check .
uv run python examples/quickstart.py
```

`--extra dev` on the `uv run` calls as well as the `uv sync`: `uv run` syncs
before it runs, and without the extra it is entitled to take pytest and ruff
back out again. Adding `--python 3.10` re-syncs against another interpreter,
fetching it if need be, which is how to reproduce the CI matrix locally. No
`uv.lock` is committed: this is a library with deliberately loose pins, and a
lockfile would pin the one resolution the matrix exists to vary.

`notebook` is the other extra: marimo, for
`examples/09_marimo_notebook.py`. Neither CI nor `pytest` needs it — the suite
parses that example like every other one rather than running it — but `dev`
carries the same pin, so a checkout set up with `--extra dev` can open the
notebook without a second sync. `notebook` on its own is for people who install
the published package instead of the repository.

`tests/test_docs.py` runs the quickstart and checks that this README's
migration table and `get_project_data()` matrix agree with the package, so
changes to either need to be made in both places. `tests/test_examples.py`
parses everything in [`examples/`](examples/README.md) — the scripts there talk
to the real API, so they are checked for drift rather than executed — and
exercises `examples/_preflight.py`, the helper that turns a missing or
half-installed dependency into an actionable message. CI runs the same commands
on Python 3.10 and 3.12.

## License

MIT, like mermaidr. See [LICENSE](LICENSE).
