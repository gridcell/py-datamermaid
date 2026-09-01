# datamermaid

A Python client for the [MERMAID](https://datamermaid.org) coral reef monitoring API,
a port of the R package [mermaidr](https://github.com/data-mermaid/mermaidr).

## Install

```bash
pip install -e .
```

For development (tests and linting):

```bash
pip install -e ".[dev]"
```

## Usage

```python
import datamermaid

projects = datamermaid.get_projects(limit=5)
print(projects[["id", "name", "countries", "num_sites"]])
```

`get_projects()` returns a `pandas.DataFrame`. Pass `limit=None` (the default) to
fetch every project — pagination is handled for you. Test projects are excluded
unless you pass `include_test_projects=True`.

`search_projects()` narrows the list by name, country, or tag. Each is an
optional case-insensitive substring match:

```python
fijian = datamermaid.search_projects(country="Fiji", tag="WCS")
```

Endpoints that do not require authentication work out of the box.

Failed requests raise `datamermaid.MermaidAPIError`, which carries the HTTP
`status_code`.

### Global data

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
`"benthicattributes"` or `"fishgroupings"` and raises `ValueError` listing those
options for anything else.

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

## Authentication

Your own projects, and anything else behind a login, need a MERMAID access
token. Tokens are issued by MERMAID's Auth0 tenant and last about a day.

### Signing in from a browser

```python
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

Once signed in:

```python
me = datamermaid.get_me()  # a dict
my_projects = datamermaid.get_my_projects()  # a DataFrame
matching = datamermaid.search_my_projects(country="Fiji")  # a DataFrame
```

`get_me()` returns a dict rather than a frame, because `me/` answers with a
single object.

### The token cache

The token is written to `$XDG_CONFIG_HOME/datamermaid/token.json` (by default
`~/.config/datamermaid/token.json`) with owner-only permissions, alongside its
expiry. It is reused until it expires, and
`datamermaid.authenticate(new_user=True)` — or
`datamermaid.clear_cached_token()` — removes it. A token the API rejects is
discarded too, so the next `authenticate()` call signs in afresh.

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

A token can also be passed explicitly, which overrides everything else:

```python
from datamermaid import MermaidClient

my_projects = datamermaid.get_my_projects(token="eyJhbGciOi...")

# ...or reuse one client across calls:
with MermaidClient(token="eyJhbGciOi...") as client:
    me = datamermaid.get_me(client=client)
```

Authentication problems raise `datamermaid.AuthenticationError`, whose message
says how to obtain a fresh token.

### Project endpoints

A project's sites and management regimes live behind
`projects/{project_id}/{endpoint}/` and need a login, since only project
members can read them. The token is resolved as described above, so once you
are signed in no token has to be passed:

```python
sites = datamermaid.get_project_sites("00673bec-...")
managements = datamermaid.get_project_managements("00673bec-...")

# ...or supply one for this call only:
sites = datamermaid.get_project_sites("00673bec-...", token="eyJhbGciOi...")
```

The project can be given as an id, a list of ids, a project record, or the
`DataFrame` returned by `get_projects()` — anything `as_project_ids()` accepts.
Passing several projects issues one request per project and returns a single
concatenated frame whose leading `project` column names the project each row
came from. `limit` applies per project.

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
project and no default raises `ValueError`; calling one when no token can be
resolved raises `datamermaid.AuthenticationError` before any request is made.

Other project endpoints can be reached with the generic getter, which takes
extra keyword arguments as query parameters:

```python
datamermaid.get_project_endpoint("00673bec-...", "sites", country="Fiji")
```

### Project data

`get_project_data()` returns a project's survey data. A survey `method` and an
aggregation level (`data`) name a CSV endpoint under the project, which is
parsed into a `pandas.DataFrame`:

```python
observations = datamermaid.get_project_data("00673bec-...", "fishbelt", "observations")
sample_events = datamermaid.get_project_data("00673bec-...", "fishbelt", "sampleevents")
```

`project` takes the same shapes as the endpoints above, and the default project
is used when it is omitted. When more than one project is named, the rows are
stacked and a leading `project_id` column says which project each row came from
(MERMAID's own CSVs already use `project` for the project *name*).

The valid methods are `fishbelt`, `benthiclit`, `benthicpit`, `benthicpqt`,
`habitatcomplexity`, `bleaching`, and `macroinvertebrate`; the valid data
levels are `observations`, `sampleunits`, and `sampleevents`. Either argument
also takes a list, or `"all"`. Asking for more than one combination returns a
nested `{method: {data: DataFrame}}` dict instead of a single frame, keyed in
the order the methods and levels are listed above however you asked for them:

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
what the `"observations"` entry holds inside the nested dict too. Every other
method and level is a single frame:

| Request | Result |
| --- | --- |
| one method, one level | a `DataFrame` |
| one method, one level, `bleaching`/`observations` | `{"colonies_bleached": df, "percent_cover": df}` |
| several methods or levels | `{method: {data: <either of the above>}}` |

`limit` truncates the rows returned per project (per endpoint, so both
bleaching observation frames are truncated), and `covariates=True` asks MERMAID
for its derived site covariates alongside the survey data. A project with no
data for a method gives an empty frame rather than an error. An invalid method
or data level raises `ValueError` naming the valid options, before any request
is made.

The endpoint mapping itself is exposed as `datamermaid.construct_endpoints()`,
which is pure and needs no login.

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

## Development

```bash
pytest        # offline; all HTTP is mocked with respx
ruff check .
```

## License

MIT
