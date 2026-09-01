# py-datamermaid

Python client for the [MERMAID](https://datamermaid.org) coral reef monitoring
API, in the spirit of the R package [`mermaidr`](https://github.com/data-mermaid/mermaidr).

## Installation

```bash
pip install datamermaid
```

## Quick start

Public data needs no login:

```python
import datamermaid

projects = datamermaid.get_projects()
indonesian = datamermaid.search_projects(country="Indonesia")
```

## Authentication

Your own projects, and anything else behind a login, need a MERMAID access
token. Tokens are issued by MERMAID's Auth0 tenant and last about a day.

### Signing in from a browser

```python
import datamermaid

datamermaid.authenticate()
```

This opens your browser, asks you to sign in to MERMAID, and stores the
resulting token so later sessions do not need to sign in again. The flow is an
OAuth2 Authorization Code grant with PKCE against MERMAID's public client — no
client secret is involved, and the code is exchanged for a token by a
short-lived HTTP server listening on `localhost` only.

If the browser cannot be used (for example over SSH), the flow falls back to a
device code: a URL and a short code are printed for you to open on another
machine. You can request that directly:

```python
datamermaid.authenticate(use_device_code=True)
```

To sign in as a different user, discard the saved token first:

```python
datamermaid.authenticate(new_user=True)
```

Once signed in:

```python
me = datamermaid.get_me()
my_projects = datamermaid.get_my_projects()
matching = datamermaid.search_my_projects(country="Fiji", tag="WCS")
```

### The token cache

The token is written to `$XDG_CONFIG_HOME/datamermaid/token.json` (by default
`~/.config/datamermaid/token.json`) with owner-only permissions, alongside its
expiry. It is reused until it expires, and
`datamermaid.authenticate(new_user=True)` — or
`datamermaid.clear_cached_token()` — removes it. A token rejected by the API is
also discarded automatically, so the next `authenticate()` call signs in afresh.

### `MERMAID_API_TOKEN` (CI and servers)

In a non-interactive environment, set the token in the environment instead. It
takes precedence over both the cache and the browser flow, so nothing will ever
try to open a browser:

```bash
export MERMAID_API_TOKEN="eyJhbGciOi..."
```

```python
datamermaid.get_my_projects()  # uses MERMAID_API_TOKEN
```

A token can also be passed explicitly, which overrides everything else:

```python
from datamermaid import MermaidClient

with MermaidClient(token="eyJhbGciOi...") as client:
    datamermaid.get_me(client=client)
```

## Development

```bash
uv sync
uv run pytest
uv run ruff check
```
