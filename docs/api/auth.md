# datamermaid.auth

Signing in and holding on to the token. [`authenticate()`][datamermaid.auth.authenticate] runs
the Auth0 flow in a browser, falling back to the device code when there is no
browser to open; [`get_token()`][datamermaid.auth.get_token] is the resolution
order every authenticated call uses (explicit token, then
`MERMAID_API_TOKEN`, then the cache).

::: datamermaid.auth
