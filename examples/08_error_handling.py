"""What goes wrong, and which exception says so.

Three things can fail: your arguments (``ValueError``, raised before anything
is requested), the login (:class:`datamermaid.AuthenticationError`), and the
request itself (:class:`datamermaid.MermaidAPIError`, carrying the status
code).  The last two share a base class,
:class:`datamermaid.MermaidError`, for catching everything this package raises.

Needs: nothing for the argument section, which runs offline; a network
connection for the two HTTP sections.  No MERMAID account: the login failure is
demonstrated with a deliberately invalid token, passed explicitly so that a
token you have cached is left untouched.

Run it with::

    python examples/08_error_handling.py
"""

from __future__ import annotations

import warnings

import datamermaid

MISSING_PROJECT = "00000000-0000-4000-8000-000000000000"


def argument_mistakes() -> None:
    """Bad arguments raise ValueError before any request is made."""
    print("== ValueError: caught before anything is requested ==")

    try:
        datamermaid.get_project_data(MISSING_PROJECT, method="fishbelt", data="sample-events")
    except ValueError as exc:
        print("bad data level ->", exc)

    try:
        datamermaid.get_reference("fishfamilys")
    except ValueError as exc:
        print("bad reference  ->", exc)

    try:
        datamermaid.as_project_ids([])
    except ValueError as exc:
        print("no project id  ->", exc)

    try:
        # No project argument and no default project set.
        datamermaid.set_default_project(None)
        datamermaid.get_project_sites()
    except ValueError as exc:
        print("no default     ->", exc)

    print()


def http_failures() -> None:
    """An error status becomes a MermaidAPIError carrying the status code."""
    print("== MermaidAPIError: the API answered with an error status ==")

    try:
        # An endpoint that does not exist.  Names outside KNOWN_ENDPOINTS are
        # still requested -- with a warning, silenced here -- so that a new
        # endpoint can be reached before this package learns about it.
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            datamermaid.get_endpoint("not-an-endpoint")
    except datamermaid.MermaidAPIError as exc:
        print("status_code ->", exc.status_code)
        print("reason      ->", exc.reason)
        print("url         ->", exc.url)
        print("str(exc)    ->", exc)

    print()


def login_failures() -> None:
    """A missing or refused token becomes an AuthenticationError."""
    print("== AuthenticationError: no usable login ==")

    try:
        # Passing the token explicitly means a rejected one is only this call's
        # problem: an explicit token is never cached, so a real cached login
        # survives.  (A token from the cache that MERMAID refuses *is* dropped,
        # so the next authenticate() signs in again.)
        datamermaid.get_me(token="not-a-real-token")
    except datamermaid.AuthenticationError as exc:
        print("rejected token ->", exc)

    # With no token at all -- nothing passed, MERMAID_API_TOKEN unset, nothing
    # cached -- the same exception is raised before any request goes out, and
    # its message says how to sign in.

    print()


def catching_everything() -> None:
    """MermaidError is the base class of both failure modes."""
    print("== MermaidError: catch anything this package raises ==")

    try:
        datamermaid.get_project_sites(MISSING_PROJECT, token="not-a-real-token")
    except datamermaid.MermaidError as exc:
        print(f"{type(exc).__name__}: {exc}")

    # Argument mistakes are the exception: they are plain ValueErrors, not
    # MermaidErrors, because they are bugs in the calling code rather than
    # something MERMAID reported.


if __name__ == "__main__":
    argument_mistakes()
    http_failures()
    login_failures()
    catching_everything()
