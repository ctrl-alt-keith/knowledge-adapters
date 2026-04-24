"""Configuration models for the Confluence adapter."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from knowledge_adapters.confluence.auth import CONFLUENCE_CA_BUNDLE_ENV, resolve_tls_inputs


@dataclass(frozen=True)
class ConfluenceConfig:
    """Runtime configuration for the Confluence adapter."""

    base_url: str
    target: str | None
    output_dir: str
    space_key: str | None = None
    space_url: str | None = None
    ca_bundle: str | None = None
    no_ca_bundle: bool = False
    client_cert_file: str | None = None
    client_key_file: str | None = None
    client_mode: str = "stub"
    auth_method: str = "bearer-env"
    debug: bool = False
    dry_run: bool = False
    tree: bool = False
    max_depth: int = 0


_TLS_INPUT_OPTION_NAMES = {
    "ca_bundle": "--ca-bundle",
    "client_cert_file": "--client-cert-file",
    "client_key_file": "--client-key-file",
}

_TLS_INPUT_ENV_NAMES = {
    "ca_bundle": (CONFLUENCE_CA_BUNDLE_ENV, "REQUESTS_CA_BUNDLE", "SSL_CERT_FILE"),
    "client_cert_file": ("CONFLUENCE_CLIENT_CERT_FILE",),
    "client_key_file": ("CONFLUENCE_CLIENT_KEY_FILE",),
}


def validate_explicit_tls_paths(
    *,
    ca_bundle: str | None = None,
    client_cert_file: str | None = None,
    client_key_file: str | None = None,
) -> None:
    """Fail fast when explicit TLS/client-certificate file paths do not exist."""
    for field_name, path_value in (
        ("ca_bundle", ca_bundle),
        ("client_cert_file", client_cert_file),
        ("client_key_file", client_key_file),
    ):
        if path_value is None:
            continue
        _validate_path_exists(
            field_name=field_name,
            path_value=path_value,
            source_hint=_TLS_INPUT_OPTION_NAMES[field_name],
        )


def validate_selected_real_tls_paths(config: ConfluenceConfig) -> None:
    """Fail fast when real-mode TLS/client-certificate file paths do not exist."""
    resolved_tls_inputs = resolve_tls_inputs(
        ca_bundle=config.ca_bundle,
        no_ca_bundle=config.no_ca_bundle,
        client_cert_file=config.client_cert_file,
        client_key_file=config.client_key_file,
    )
    for field_name in _TLS_INPUT_OPTION_NAMES:
        path_value = getattr(resolved_tls_inputs, field_name)
        if path_value is None:
            continue

        explicit_value = getattr(config, field_name)
        source_hint = (
            _TLS_INPUT_OPTION_NAMES[field_name]
            if explicit_value is not None
            else " or ".join(_TLS_INPUT_ENV_NAMES[field_name])
        )
        _validate_path_exists(
            field_name=field_name,
            path_value=path_value,
            source_hint=source_hint,
        )


def _validate_path_exists(
    *,
    field_name: str,
    path_value: str,
    source_hint: str,
) -> None:
    resolved_path = Path(path_value).expanduser().resolve()
    if resolved_path.exists():
        return

    raise ValueError(
        f"Confluence TLS/client-certificate path for {field_name!r} does not exist: "
        f"{resolved_path}. Check {source_hint}."
    )
