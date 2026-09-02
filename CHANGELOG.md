# Changelog

All notable changes to `datamermaid` are recorded here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and the project
adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

This file is for user-visible change: new or renamed public functions, changes
in behaviour or arguments, bug fixes, and anything that breaks existing code.
Refactors, test-only work and internal cleanups do not belong here.

## [Unreleased]

Nothing yet.

## [0.1.0] - 2026-09-02

Initial development release: the first complete pass at porting
[mermaidr](https://github.com/data-mermaid/mermaidr) to Python. Every
`mermaid_*` function except `mermaid_get_classification_labelmappings()` has a
counterpart, tibbles are returned as `pandas.DataFrame` objects, and the
README's migration table maps the two surfaces name by name.

### Added

- HTTP core: `MermaidClient` wrapping `httpx`, with pagination over MERMAID's
  `{count, next, previous, results}` envelope, single-object and CSV fetches,
  and `default_client()` / `set_default_client()` for connection reuse and
  testing. `API_BASE_URL` and `DEFAULT_PAGE_SIZE` are exported.
- Errors: `MermaidError`, with `MermaidAPIError` for HTTP failures and
  `AuthenticationError` for a missing or rejected login. Argument mistakes
  raise `ValueError` before any request is made.
- Authentication: `authenticate()` signs in through MERMAID's Auth0 tenant
  using an OAuth2 Authorization Code grant with PKCE, falling back to a device
  code with `use_device_code=True` for machines without a browser. `get_token()`
  reads a token without ever prompting, `clear_cached_token()` discards the
  cached one, and `MERMAID_API_TOKEN` (`TOKEN_ENV_VAR`) overrides the cache.
  Authenticated endpoints resolve a token lazily, so they fail before issuing a
  request when there is none.
- Projects: `get_projects()`, `search_projects()`, `get_my_projects()`,
  `search_my_projects()`, and `get_me()` for the signed-in user.
- Project-scoped endpoints: `get_project_sites()`,
  `get_project_managements()`, and the generic `get_project_endpoint()`, plus
  `as_project_ids()` for coercing projects, ids or frames into a list of ids.
  `set_default_project()` and `get_default_project()` hold a project for the
  rest of the session and export `MERMAID_DEFAULT_PROJECT`
  (`DEFAULT_PROJECT_ENV_VAR`).
- Survey data: `get_project_data()` covers all seven methods (`METHODS`:
  fishbelt, benthiclit, benthicpit, benthicpqt, habitatcomplexity, bleaching,
  macroinvertebrate) at all three aggregation levels (`DATA_LEVELS`:
  observations, sampleunits, sampleevents), with `limit=` and `covariates=`.
  Several methods or levels at once give a nested `dict` of frames, bleaching
  observations arrive as `colonies_bleached` and `percent_cover`, and stacking
  several projects adds a `project_id` column. `construct_endpoints()` exposes
  the method-by-level endpoint matrix.
- Global, unauthenticated endpoints: `get_sites()`, `get_managements()`,
  `get_summary_sampleevents()`, `get_reference()` over the seven reference
  tables in `REFERENCE_ENDPOINTS` (fish families, genera and species, benthic
  attributes, fish groupings, invertebrate attributes and species),
  `countries()`, `get_choices()` for every vocabulary, and `get_endpoint()` for
  anything else, which warns rather than errors on a name outside
  `KNOWN_ENDPOINTS`.
- Import: `import_get_template_and_options()`,
  `import_check_options()`, `import_project_data()` (`dryrun=True` by default;
  `clearexisting=True` also requires `clearexisting_confirm=True`),
  `import_bulk_validate()`, `import_bulk_submit()`, `import_bulk_edit()`, and
  `METHOD_ENDPOINTS`. Nothing prompts: every call that writes to MERMAID or
  acts on a whole project takes an explicit `confirm=True`-style argument, so
  it can run unattended.
- Reports: `get_gfcr_report()` requests the GFCR workbook, unzips it and
  returns one frame per worksheet. It needs the `datamermaid[excel]` extra
  (openpyxl), which is imported lazily and never a runtime dependency.
- Packaging: Python 3.10 and newer, with `httpx` and `pandas` as the only
  runtime dependencies. Extras are `dev` (pytest, respx, ruff, marimo,
  openpyxl), `notebook` (marimo), `excel` (openpyxl) and `docs` (MkDocs).
- Documentation and examples: a README with the mermaidr migration table,
  numbered runnable scripts in `examples/` including a marimo notebook, a
  `quickstart.py` that runs the README walk-through against a mock transport,
  and a MkDocs Material site published to GitHub Pages.
- Tests and CI: an entirely offline pytest suite (`respx` and
  `httpx.MockTransport`) with doctests, run alongside `ruff check` and
  `ruff format --check` on Python 3.10 and 3.12.

<!--
Link-reference definitions such as
`[0.1.0]: https://github.com/gridcell/py-datamermaid/releases/tag/v0.1.0` are
deliberately absent: there are no tags or releases to point at yet. Add them
with the first tagged release, along with an [Unreleased] compare link.
-->
