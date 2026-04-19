"""Authentication helpers for the Confluence adapter."""

from __future__ import annotations

import os
from collections.abc import Mapping


def build_auth_headers(auth_method: str) -> Mapping[str, str]:
    """Build auth headers for a supported auth method.
    """
    if auth_method != "bearer-env":
        raise ValueError(f"Unsupported auth method: {auth_method}")

    token = os.getenv("CONFLUENCE_BEARER_TOKEN", "").strip()
    if not token:
        raise ValueError("CONFLUENCE_BEARER_TOKEN must be set for --client-mode real.")

    return {"Authorization": f"Bearer {token}"}
