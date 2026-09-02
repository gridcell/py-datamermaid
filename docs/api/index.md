# API reference

Everything on this page and the ones below it is rendered from the docstrings
in `src/datamermaid/`, so it cannot drift from the code. The narrative
introduction is the [guide](../index.md); the runnable scripts are in
[examples](../examples.md).

`datamermaid.__all__` is the public contract. Import from the top-level
package:

```python
import datamermaid

projects = datamermaid.get_projects(country="Fiji", limit=10)
```

The submodules below are where those names are defined; importing from either
place works, but the top-level package is the supported spelling.

| Module | What lives there |
| --- | --- |
| [`datamermaid.auth`](auth.md) | Sign-in (browser PKCE and device code), the token cache, `MERMAID_API_TOKEN` |
| [`datamermaid.projects`](projects.md) | Listing and searching projects, public and your own |
| [`datamermaid.me`](me.md) | The signed-in user |
| [`datamermaid.project_endpoints`](project-endpoints.md) | Project-scoped endpoints, project-id coercion, the default project |
| [`datamermaid.project_data`](project-data.md) | Survey data by method and aggregation level |
| [`datamermaid.endpoints`](endpoints.md) | Global unauthenticated endpoints and reference tables |
| [`datamermaid.import_`](import.md) | The write path: templates, option checks, ingest, bulk actions |
| [`datamermaid.client`](client.md) | `MermaidClient`, the HTTP layer every call goes through |
| [`datamermaid.exceptions`](exceptions.md) | The exception hierarchy |
| [`datamermaid.utils`](utils.md) | Records to `DataFrame`, list-column collapsing |

## The package

::: datamermaid
    options:
      members: false
      show_root_heading: false
