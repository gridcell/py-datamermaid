# datamermaid.project_endpoints

The `projects/{id}/{endpoint}` family, plus the two pieces of plumbing every
project-scoped call shares: [`as_project_ids()`][datamermaid.project_endpoints.as_project_ids],
which accepts an id, a list of ids or a `DataFrame` of projects, and the
process-wide default project.

::: datamermaid.project_endpoints
