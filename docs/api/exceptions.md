# datamermaid.exceptions

Three exceptions, and `MermaidError` is the base of the other two, so
`except MermaidError` catches everything this package raises. Bad arguments
are the exception to the exceptions: they raise plain `ValueError`, before any
request goes out.

::: datamermaid.exceptions
