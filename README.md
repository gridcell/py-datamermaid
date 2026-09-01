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

## Development

```bash
pytest        # offline; all HTTP is mocked with respx
ruff check .
```

## License

MIT
