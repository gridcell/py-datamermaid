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

Endpoints that do not require authentication work out of the box. To use a token,
create a client explicitly:

```python
from datamermaid import MermaidClient

client = MermaidClient(token="...")
projects = datamermaid.get_projects(client=client)
```

Failed requests raise `datamermaid.MermaidAPIError`, which carries the HTTP
`status_code`.

### Project endpoints

A project's sites and management regimes live behind
`projects/{project_id}/{endpoint}/` and require a token, since only project
members can read them:

```python
import datamermaid

sites = datamermaid.get_project_sites("00673bec-...", token="...")
managements = datamermaid.get_project_managements("00673bec-...", token="...")
```

The project can be given as an id, a list of ids, a project record, or the
`DataFrame` returned by `get_projects()` — anything `as_project_ids()` accepts.
Passing several projects issues one request per project and returns a single
concatenated frame whose leading `project` column names the project each row
came from. `limit` applies per project.

Set a default project once to leave it out of every later call:

```python
datamermaid.set_default_project("00673bec-...")
datamermaid.get_project_sites(token="...")  # uses the default project
datamermaid.get_default_project()  # ['00673bec-...']
datamermaid.set_default_project(None)  # clear it
```

The default is also read from the `MERMAID_DEFAULT_PROJECT` environment
variable (comma separated for several projects), and `set_default_project()`
exports it there so subprocesses inherit it. Calling a project function with no
project and no default raises `ValueError`; calling one without a token raises
`datamermaid.AuthenticationError` before any request is made.

Other project endpoints can be reached with the generic getter, which takes
extra keyword arguments as query parameters:

```python
datamermaid.get_project_endpoint("00673bec-...", "sites", token="...", country="Fiji")
```

## Development

```bash
pytest        # offline; all HTTP is mocked with respx
ruff check .
```

## License

MIT
