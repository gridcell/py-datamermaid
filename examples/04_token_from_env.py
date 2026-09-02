"""Authenticate without a browser: MERMAID_API_TOKEN, ``token=``, and a client.

This is the path for CI jobs, servers, and notebooks on someone else's machine
-- anywhere an interactive sign-in is not possible.  A token from
:func:`datamermaid.authenticate` (see ``03_authenticate.py``) is put in the
environment instead, where it takes precedence over the cache:

.. code-block:: bash

    export MERMAID_API_TOKEN="eyJhbGciOi..."
    python examples/04_token_from_env.py

The same token can be passed per call with ``token=``, or once to a
:class:`~datamermaid.MermaidClient` that several calls share.

Needs: a network connection and ``MERMAID_API_TOKEN`` set to a valid token.

Run it with::

    python examples/04_token_from_env.py
"""

from __future__ import annotations

import os

try:
    import datamermaid
    from datamermaid import TOKEN_ENV_VAR, MermaidClient
except ImportError as exc:  # explain what to install, instead of a deep traceback
    import sys
    from pathlib import Path

    # `python -P` and PYTHONSAFEPATH=1 keep this directory off sys.path, and the
    # helper below lives in it; without this the handler would fail in its turn.
    sys.path.insert(0, str(Path(__file__).parent))
    from _preflight import missing_dependency

    raise missing_dependency(exc) from None


def read_token() -> str:
    """Return the token from the environment, or explain how to get one."""
    token = os.environ.get(TOKEN_ENV_VAR, "").strip()
    if not token:
        raise SystemExit(
            f"{TOKEN_ENV_VAR} is not set.\n"
            f"Get a token by running `python examples/03_authenticate.py` (or\n"
            f"`python -c 'import datamermaid; print(datamermaid.authenticate())'`)\n"
            f"and export it:  export {TOKEN_ENV_VAR}='eyJhbGciOi...'"
        )
    return token


def main() -> None:
    token = read_token()

    # 1. Implicitly.  Nothing is passed: every authenticated call reads
    #    MERMAID_API_TOKEN by itself, so library code needs no token argument.
    me = datamermaid.get_me()
    print(f"Signed in as {me['full_name']} <{me['email']}>")

    # 2. Explicitly, for one call.  `token=` overrides the environment and the
    #    cache, which is how to use two accounts in one process.
    projects = datamermaid.get_my_projects(limit=5, token=token)
    print(f"{len(projects)} of your projects (token= passed explicitly)")

    # 3. Once, for a whole session.  A MermaidClient holds the token and the
    #    HTTP connection pool; sharing one across calls avoids reconnecting for
    #    each request.  Used as a context manager it closes itself.
    with MermaidClient(token=token) as client:
        me = datamermaid.get_me(client=client)
        projects = datamermaid.get_my_projects(client=client)
        print(f"{me['full_name']} has {len(projects)} projects (one shared client)")
        if not projects.empty:
            sites = datamermaid.get_project_sites(projects.head(1), client=client)
            print(f"...and {len(sites)} sites in the first of them")

    # `client=` and `token=` are mutually exclusive -- a client already carries
    # its token.  To point every module-level function at one client instead of
    # passing it around, set it as the process-wide default:
    #
    #     datamermaid.set_default_client(MermaidClient(token=token))
    #     ...
    #     datamermaid.set_default_client(None)  # back to the default


if __name__ == "__main__":
    main()
