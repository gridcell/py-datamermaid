"""Shared fixtures.

Every test runs against a temporary config directory with the token environment
variable cleared, so nothing touches a developer's real MERMAID credentials, and
all HTTP is mocked so the suite works offline.
"""

from __future__ import annotations

import time

import pytest

from datamermaid import auth


@pytest.fixture(autouse=True)
def token_cache_path(tmp_path, monkeypatch):
    """Point the token cache at ``tmp_path`` and unset ``MERMAID_API_TOKEN``."""
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    monkeypatch.delenv(auth.TOKEN_ENV_VAR, raising=False)
    return tmp_path / "config" / "datamermaid" / "token.json"


@pytest.fixture
def write_cached_token(token_cache_path):
    """Write a token to the cache; expires an hour from now by default."""

    def _write(token: str = "cached-token", *, ttl: float = 3600.0) -> str:
        auth._write_cache(token, time.time() + ttl)
        return token

    return _write
