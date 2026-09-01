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

## Development

```bash
pytest        # offline; all HTTP is mocked with respx
ruff check .
```

## License

MIT
