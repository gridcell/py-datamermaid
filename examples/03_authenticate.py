"""Sign in to MERMAID interactively and cache the token.

:func:`datamermaid.authenticate` opens your browser, waits for the Auth0
redirect, and writes the resulting token to a cache so later sessions do not
have to sign in again (until it expires, roughly a day later).  Everything that
needs a login then just works, with no ``token=`` argument anywhere.

Nothing here is ever hardcoded: the token comes from the sign-in, and the
script prints only a masked prefix of it.

Needs: a network connection, a MERMAID account, and a browser -- or a second
device, if you use the device-code flow below.

Run it with::

    python examples/03_authenticate.py
"""

from __future__ import annotations

try:
    import datamermaid
    from datamermaid import TOKEN_ENV_VAR
except ImportError as exc:  # explain what to install, instead of a deep traceback
    import sys
    from pathlib import Path

    # `python -P` and PYTHONSAFEPATH=1 keep this directory off sys.path, and the
    # helper below lives in it; without this the handler would fail in its turn.
    sys.path.insert(0, str(Path(__file__).parent))
    from _preflight import missing_dependency

    raise missing_dependency(exc) from None

#: Where :func:`datamermaid.authenticate` caches the token it obtains.
CACHE_PATH = "$XDG_CONFIG_HOME/datamermaid/token.json (~/.config/... by default)"


def mask(token: str) -> str:
    """Show enough of a token to recognise it, and no more."""
    return f"{token[:6]}...{token[-4:]} ({len(token)} chars)"


def main() -> None:
    # `get_token()` never prompts: it reports the token already available from
    # MERMAID_API_TOKEN or from the cache, and None when there is none.  Use it
    # to decide whether an interactive sign-in is needed at all.
    token = datamermaid.get_token()

    if token:
        print(f"Already signed in -- token from {TOKEN_ENV_VAR} or {CACHE_PATH}")
    else:
        print("No token found; opening a browser to sign in...")
        # The browser flow uses Auth0's PKCE grant with a loopback redirect: no
        # client secret, nothing to keep on disk but the resulting token.  If a
        # browser cannot be opened (a headless box, an SSH session), it falls
        # back to the device-code flow on its own.
        token = datamermaid.authenticate()
        print(f"Signed in; token cached in {CACHE_PATH}")

    print("Token:", mask(token))
    print()

    # Anything that needs a login now works without being handed the token.
    me = datamermaid.get_me()
    print(f"Signed in as {me['full_name']} <{me['email']}>")

    print()
    print("Other things you can do (not run here, they all sign in again):")
    print()
    # Over SSH, or on a machine with no browser: prints a URL and a short code
    # to enter on any other device, then polls Auth0 until you finish.
    print("  datamermaid.authenticate(use_device_code=True)")
    # Clears the cache first, so a different account can sign in.  Note that
    # MERMAID_API_TOKEN, if set, still wins over the cache -- unset it first.
    print("  datamermaid.authenticate(new_user=True)")
    # Seconds to wait for the browser redirect before falling back to a device
    # code; the default is three minutes.
    print("  datamermaid.authenticate(timeout=30)")
    # Sign out: forget the cached token.  The next authenticate() signs in
    # again, and anything needing a login raises AuthenticationError until it
    # does.
    print("  datamermaid.clear_cached_token()")


if __name__ == "__main__":
    main()
