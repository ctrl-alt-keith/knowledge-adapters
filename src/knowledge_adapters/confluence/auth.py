"""Authentication helpers for the Confluence adapter."""

from __future__ import annotations

from collections.abc import Mapping


def build_auth_headers(auth_method: str) -> Mapping[str, str]:
    """Build auth headers for a supported auth method.

    This is intentionally stubbed for the initial scaffold.
    Runtime-specific credential injection will be added later.
    """
    if auth_method == "bearer-env":
        return {}
    raise ValueError(f"Unsupported auth method: {auth_method}")