# datamermaid.client

[`MermaidClient`][datamermaid.client.MermaidClient] is the HTTP layer: one
`httpx.Client`, the `{count, next, previous, results}` pagination envelope,
the CSV endpoints, and lazy token resolution. Public functions reach it
through `default_client()`, so a client set with `set_default_client()` is
reused by every later call.

::: datamermaid.client
