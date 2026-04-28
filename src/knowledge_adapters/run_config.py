"""Config loading for sequential multi-run execution."""

from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

import yaml  # type: ignore[import-untyped]

from knowledge_adapters.bundle import (
    BUNDLE_ORDER_CHOICES,
    DEFAULT_BUNDLE_ORDER,
    DEFAULT_HEADER_MODE,
    DEFAULT_STALE_MODE,
    HEADER_MODE_CHOICES,
    STALE_MODE_CHOICES,
    BundleOrder,
    HeaderMode,
    StaleMode,
)
from knowledge_adapters.confluence.auth import CONFLUENCE_CA_BUNDLE_ENV, SUPPORTED_AUTH_METHODS
from knowledge_adapters.confluence.config import validate_explicit_tls_paths
from knowledge_adapters.confluence.resolve import (
    resolve_target_for_base_url,
    space_key_from_url_for_base_url,
    validate_base_url,
    validate_space_key,
)
from knowledge_adapters.github_metadata.config import SUPPORTED_RESOURCE_TYPES

SUPPORTED_RUN_TYPES = frozenset(
    {"bundle", "confluence", "git_repo", "github_metadata", "local_files"}
)
_SUPPORTED_CONFLUENCE_CLIENT_MODES = frozenset({"real", "stub"})
_SUPPORTED_GITHUB_METADATA_STATES = frozenset({"open", "closed", "all"})
_SUPPORTED_GITHUB_METADATA_RESOURCE_TYPES = SUPPORTED_RESOURCE_TYPES

_COMMON_REQUIRED_KEYS = frozenset({"name", "type"})
_BUNDLE_OPTION_KEYS = frozenset(
    {
        "baseline_manifest",
        "changed_only",
        "exclude",
        "header_mode",
        "include",
        "max_bytes",
        "order",
        "output",
        "stale_mode",
    }
)
_CONFLUENCE_ALLOWED_KEYS = _COMMON_REQUIRED_KEYS | frozenset(
    {
        "auth_method",
        "base_url",
        "ca_bundle",
        "client_mode",
        "client_cert_file",
        "client_key_file",
        "clear_cache",
        "debug",
        "dry_run",
        "enabled",
        "fetch_cache_dir",
        "force_refresh",
        "max_depth",
        "output_dir",
        "space_key",
        "space_url",
        "target",
        "tree",
        "tree_cache_dir",
    }
)
_BUNDLE_ALLOWED_KEYS = _COMMON_REQUIRED_KEYS | _BUNDLE_OPTION_KEYS | frozenset(
    {"enabled", "inputs"}
)
_NAMED_BUNDLE_ALLOWED_KEYS = _BUNDLE_OPTION_KEYS | frozenset({"name", "runs"})
_LOCAL_FILES_ALLOWED_KEYS = _COMMON_REQUIRED_KEYS | frozenset(
    {"dry_run", "enabled", "file_path", "output_dir"}
)
_GIT_REPO_ALLOWED_KEYS = _COMMON_REQUIRED_KEYS | frozenset(
    {"dry_run", "enabled", "exclude", "include", "output_dir", "ref", "repo_url", "subdir"}
)
_GITHUB_METADATA_ALLOWED_KEYS = _COMMON_REQUIRED_KEYS | frozenset(
    {
        "base_url",
        "dry_run",
        "enabled",
        "include_issue_comments",
        "max_items",
        "output_dir",
        "repo",
        "resource_type",
        "since",
        "state",
        "token_env",
    }
)


@dataclass(frozen=True)
class ConfiguredRun:
    """One adapter execution described in a config file."""

    name: str
    run_type: str
    argv: tuple[str, ...]
    dry_run: bool
    enabled: bool = True


@dataclass(frozen=True)
class ConfiguredBundle:
    """One named bundle definition described in a config file."""

    name: str
    inputs: tuple[str, ...]
    output: str
    max_bytes: int | None = None
    order: BundleOrder = DEFAULT_BUNDLE_ORDER
    header_mode: HeaderMode = DEFAULT_HEADER_MODE
    include_patterns: tuple[str, ...] = ()
    exclude_patterns: tuple[str, ...] = ()
    changed_only: bool = False
    baseline_manifest: str | None = None
    stale_mode: StaleMode = DEFAULT_STALE_MODE


@dataclass(frozen=True)
class RunConfig:
    """Validated multi-run config."""

    config_path: Path
    runs: tuple[ConfiguredRun, ...]
    bundles: tuple[ConfiguredBundle, ...] = ()


def load_run_config(
    config_path: str | Path,
    *,
    no_confluence_ca_bundle: bool = False,
) -> RunConfig:
    """Load and validate a config-driven run file."""
    resolved_config_path = Path(config_path).expanduser().resolve()
    try:
        raw_config = yaml.safe_load(resolved_config_path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise ValueError(f"Config file not found: {resolved_config_path}.") from exc
    except OSError as exc:
        raise ValueError(f"Could not read config file {resolved_config_path}: {exc}.") from exc
    except yaml.YAMLError as exc:
        raise ValueError(f"Could not parse YAML config {resolved_config_path}: {exc}.") from exc

    if raw_config is None:
        raise ValueError(
            f"Config file is empty: {resolved_config_path}. Add a top-level 'runs:' list."
        )
    if not isinstance(raw_config, dict):
        raise ValueError(
            f"Config file {resolved_config_path} must contain a top-level 'runs:' list."
        )

    runs = raw_config.get("runs")
    if not isinstance(runs, list) or not runs:
        raise ValueError(
            f"Config file {resolved_config_path} must define a non-empty top-level 'runs:' list."
        )

    configured_runs = tuple(
        _parse_run(
            run_config,
            index=index,
            config_path=resolved_config_path,
            no_confluence_ca_bundle=no_confluence_ca_bundle,
        )
        for index, run_config in enumerate(runs, start=1)
    )

    configured_bundles: tuple[ConfiguredBundle, ...] = ()
    if "bundles" in raw_config:
        raw_bundles = raw_config.get("bundles")
        if not isinstance(raw_bundles, list) or not raw_bundles:
            raise ValueError(
                f"Config file {resolved_config_path} must define top-level 'bundles:' "
                "as a non-empty list when provided."
            )

        configured_runs_by_name = _configured_runs_by_name(
            configured_runs,
            config_path=resolved_config_path,
        )
        configured_bundles = tuple(
            _parse_named_bundle(
                bundle_config,
                index=index,
                config_path=resolved_config_path,
                configured_runs_by_name=configured_runs_by_name,
            )
            for index, bundle_config in enumerate(raw_bundles, start=1)
        )
        _reject_duplicate_bundle_names(configured_bundles, config_path=resolved_config_path)

    return RunConfig(
        config_path=resolved_config_path,
        runs=configured_runs,
        bundles=configured_bundles,
    )


def select_runs(
    run_config: RunConfig,
    *,
    only_names: tuple[str, ...] | None = None,
) -> tuple[ConfiguredRun, ...]:
    """Select runs for execution, preserving config order."""
    if only_names is None:
        return tuple(configured_run for configured_run in run_config.runs if configured_run.enabled)

    available_names = {configured_run.name for configured_run in run_config.runs}
    missing_names = tuple(name for name in only_names if name not in available_names)
    if missing_names:
        missing = ", ".join(repr(name) for name in missing_names)
        available = ", ".join(repr(configured_run.name) for configured_run in run_config.runs)
        raise ValueError(
            f"Unknown run name(s) for --only in {run_config.config_path}: {missing}. "
            f"Available run names: {available}."
        )

    selected_names = frozenset(only_names)
    return tuple(
        configured_run
        for configured_run in run_config.runs
        if configured_run.name in selected_names
    )


def select_bundle(run_config: RunConfig, *, name: str) -> ConfiguredBundle:
    """Select one named bundle definition by name."""
    if not run_config.bundles:
        raise ValueError(
            f"Config file {run_config.config_path} does not define any top-level named "
            "bundles. Add a 'bundles:' list or use direct bundle inputs."
        )

    for configured_bundle in run_config.bundles:
        if configured_bundle.name == name:
            return configured_bundle

    available = ", ".join(repr(configured_bundle.name) for configured_bundle in run_config.bundles)
    raise ValueError(
        f"Unknown bundle name {name!r} in {run_config.config_path}. "
        f"Available bundle names: {available}."
    )


def _parse_run(
    run_config: object,
    *,
    index: int,
    config_path: Path,
    no_confluence_ca_bundle: bool,
) -> ConfiguredRun:
    if not isinstance(run_config, dict):
        raise ValueError(
            f"Run #{index} in {config_path} must be a mapping with name, type, and inputs."
        )

    name = _require_string(run_config, "name", index=index, config_path=config_path)
    run_type = _require_string(run_config, "type", index=index, config_path=config_path)
    if run_type not in SUPPORTED_RUN_TYPES:
        supported_types = ", ".join(sorted(SUPPORTED_RUN_TYPES))
        raise ValueError(
            f"Run {name!r} in {config_path} uses unsupported type {run_type!r}. "
            f"Supported types: {supported_types}."
        )

    if run_type == "confluence":
        argv = _build_confluence_argv(
            run_config,
            name=name,
            config_path=config_path,
            no_ca_bundle=no_confluence_ca_bundle,
        )
        dry_run = _optional_bool(
            run_config,
            "dry_run",
            index=index,
            config_path=config_path,
            default=False,
        )
        enabled = _optional_bool(
            run_config,
            "enabled",
            index=index,
            config_path=config_path,
            default=True,
        )
        return ConfiguredRun(
            name=name,
            run_type=run_type,
            argv=argv,
            dry_run=dry_run,
            enabled=enabled,
        )

    if run_type == "bundle":
        argv = _build_bundle_argv(run_config, name=name, config_path=config_path)
        enabled = _optional_bool(
            run_config,
            "enabled",
            index=index,
            config_path=config_path,
            default=True,
        )
        return ConfiguredRun(
            name=name,
            run_type=run_type,
            argv=argv,
            dry_run=False,
            enabled=enabled,
        )

    if run_type == "git_repo":
        argv = _build_git_repo_argv(run_config, name=name, config_path=config_path)
    elif run_type == "github_metadata":
        argv = _build_github_metadata_argv(run_config, name=name, config_path=config_path)
    else:
        argv = _build_local_files_argv(run_config, name=name, config_path=config_path)
    dry_run = _optional_bool(
        run_config,
        "dry_run",
        index=index,
        config_path=config_path,
        default=False,
    )
    enabled = _optional_bool(
        run_config,
        "enabled",
        index=index,
        config_path=config_path,
        default=True,
    )
    return ConfiguredRun(
        name=name,
        run_type=run_type,
        argv=argv,
        dry_run=dry_run,
        enabled=enabled,
    )


def _build_confluence_argv(
    run_config: dict[str, object],
    *,
    name: str,
    config_path: Path,
    no_ca_bundle: bool,
) -> tuple[str, ...]:
    _reject_unknown_keys(
        run_config,
        allowed_keys=_CONFLUENCE_ALLOWED_KEYS,
        name=name,
        config_path=config_path,
    )
    index = _run_index(name=name, config_path=config_path)
    base_url = _require_string(run_config, "base_url", index=index, config_path=config_path)
    try:
        validate_base_url(base_url)
    except ValueError as exc:
        raise ValueError(f"Run {name!r} in {config_path} has invalid 'base_url': {exc}") from exc

    output_dir = _resolve_path_string(
        _require_string(run_config, "output_dir", index=index, config_path=config_path),
        config_path=config_path,
    )
    client_mode = _optional_string(run_config, "client_mode", index=index, config_path=config_path)
    if client_mode is not None and client_mode not in _SUPPORTED_CONFLUENCE_CLIENT_MODES:
        supported_values = " or ".join(
            repr(mode) for mode in sorted(_SUPPORTED_CONFLUENCE_CLIENT_MODES)
        )
        raise ValueError(
            f"Run {name!r} in {config_path} has unsupported 'client_mode' value "
            f"{client_mode!r}. Use {supported_values}."
        )

    target = _optional_string(run_config, "target", index=index, config_path=config_path)
    space_key = _optional_string(run_config, "space_key", index=index, config_path=config_path)
    space_url = _optional_string(run_config, "space_url", index=index, config_path=config_path)
    space_mode = space_key is not None or space_url is not None
    tree = _optional_bool(run_config, "tree", index=index, config_path=config_path, default=False)
    max_depth = run_config.get("max_depth")

    if space_key is not None and space_url is not None:
        raise ValueError(
            f"Run {name!r} in {config_path} must set only one of 'space_key' or 'space_url'."
        )
    if space_mode:
        if client_mode != "real":
            raise ValueError(
                f"Run {name!r} in {config_path}: space mode requires --client-mode real."
            )
        if target is not None:
            raise ValueError(
                f"Run {name!r} in {config_path} cannot combine space mode with 'target'."
            )
        if tree:
            raise ValueError(
                f"Run {name!r} in {config_path} cannot combine space mode with 'tree'."
            )
        if max_depth is not None:
            raise ValueError(
                f"Run {name!r} in {config_path} cannot combine space mode with 'max_depth'."
            )
        if space_key is not None:
            try:
                validate_space_key(space_key)
            except ValueError as exc:
                raise ValueError(
                    f"Run {name!r} in {config_path} has invalid 'space_key': {exc}"
                ) from exc
        if space_url is not None:
            try:
                space_key_from_url_for_base_url(space_url, base_url=base_url)
            except ValueError as exc:
                raise ValueError(
                    f"Run {name!r} in {config_path} has invalid 'space_url': {exc}"
                ) from exc
    else:
        if target is None:
            raise ValueError(
                f"Run {name!r} in {config_path} must set 'target', 'space_key', or 'space_url'."
            )
        try:
            resolve_target_for_base_url(target, base_url=base_url)
        except ValueError as exc:
            raise ValueError(f"Run {name!r} in {config_path} has invalid 'target': {exc}") from exc

    argv: list[str] = [
        "confluence",
        "--base-url",
        base_url,
    ]
    if target is not None:
        argv.extend(["--target", target])
    if space_key is not None:
        argv.extend(["--space-key", space_key])
    if space_url is not None:
        argv.extend(["--space-url", space_url])
    argv.extend(
        [
            "--output-dir",
            output_dir,
        ]
    )
    if client_mode is not None:
        argv.extend(["--client-mode", client_mode])

    auth_method = _optional_string(run_config, "auth_method", index=index, config_path=config_path)
    if auth_method is not None:
        if auth_method not in SUPPORTED_AUTH_METHODS:
            supported_values = " or ".join(repr(method) for method in SUPPORTED_AUTH_METHODS)
            raise ValueError(
                f"Run {name!r} in {config_path} has unsupported 'auth_method' value "
                f"{auth_method!r}. Use {supported_values}."
            )
        argv.extend(["--auth-method", auth_method])

    ca_bundle = _optional_string(run_config, "ca_bundle", index=index, config_path=config_path)
    resolved_ca_bundle = _resolve_configured_ca_bundle(
        ca_bundle,
        config_path=config_path,
        no_ca_bundle=no_ca_bundle,
    )
    client_cert_file = _optional_string(
        run_config,
        "client_cert_file",
        index=index,
        config_path=config_path,
    )
    resolved_client_cert_file = (
        _resolve_path_string(client_cert_file, config_path=config_path)
        if client_cert_file is not None
        else None
    )
    client_key_file = _optional_string(
        run_config,
        "client_key_file",
        index=index,
        config_path=config_path,
    )
    resolved_client_key_file = (
        _resolve_path_string(client_key_file, config_path=config_path)
        if client_key_file is not None
        else None
    )
    if client_key_file is not None and client_cert_file is None:
        raise ValueError(
            f"Run {name!r} in {config_path} must set 'client_cert_file' when "
            "'client_key_file' is provided."
        )
    try:
        validate_explicit_tls_paths(
            ca_bundle=resolved_ca_bundle,
            client_cert_file=resolved_client_cert_file,
            client_key_file=resolved_client_key_file,
        )
    except ValueError as exc:
        raise ValueError(f"Run {name!r} in {config_path}: {exc}") from exc

    if resolved_ca_bundle is not None:
        argv.extend(
            [
                "--ca-bundle",
                resolved_ca_bundle,
            ]
        )
    if no_ca_bundle:
        argv.append("--no-ca-bundle")
    if resolved_client_cert_file is not None:
        argv.extend(
            [
                "--client-cert-file",
                resolved_client_cert_file,
            ]
        )
    if resolved_client_key_file is not None:
        argv.extend(
            [
                "--client-key-file",
                resolved_client_key_file,
            ]
        )

    fetch_cache_dir = _optional_string(
        run_config,
        "fetch_cache_dir",
        index=index,
        config_path=config_path,
    )
    if fetch_cache_dir is not None:
        argv.extend(
            [
                "--fetch-cache-dir",
                _resolve_path_string(fetch_cache_dir, config_path=config_path),
            ]
        )

    tree_cache_dir = _optional_string(
        run_config,
        "tree_cache_dir",
        index=index,
        config_path=config_path,
    )
    if tree_cache_dir is not None:
        argv.extend(
            [
                "--tree-cache-dir",
                _resolve_path_string(tree_cache_dir, config_path=config_path),
            ]
        )

    if _optional_bool(
        run_config,
        "force_refresh",
        index=index,
        config_path=config_path,
        default=False,
    ):
        argv.append("--force-refresh")
    if _optional_bool(
        run_config,
        "clear_cache",
        index=index,
        config_path=config_path,
        default=False,
    ):
        argv.append("--clear-cache")

    if _optional_bool(run_config, "debug", index=index, config_path=config_path, default=False):
        argv.append("--debug")
    if _optional_bool(run_config, "dry_run", index=index, config_path=config_path, default=False):
        argv.append("--dry-run")
    if tree:
        argv.append("--tree")

    if max_depth is not None:
        if isinstance(max_depth, bool) or not isinstance(max_depth, int):
            raise ValueError(f"Run {name!r} in {config_path} must set 'max_depth' to an integer.")
        if max_depth < 0:
            raise ValueError(
                f"Run {name!r} in {config_path} must set 'max_depth' to an integer "
                "greater than or equal to 0."
            )
        argv.extend(["--max-depth", str(max_depth)])

    return tuple(argv)


def _build_bundle_argv(
    run_config: dict[str, object],
    *,
    name: str,
    config_path: Path,
) -> tuple[str, ...]:
    _reject_unknown_keys(
        run_config,
        allowed_keys=_BUNDLE_ALLOWED_KEYS,
        name=name,
        config_path=config_path,
    )
    index = _run_index(name=name, config_path=config_path)
    inputs = tuple(
        _resolve_path_string(input_path, config_path=config_path)
        for input_path in _required_string_sequence(
            run_config,
            "inputs",
            index=index,
            config_path=config_path,
        )
    )
    configured_bundle = _parse_configured_bundle(
        run_config,
        name=name,
        config_path=config_path,
        inputs=inputs,
    )
    return _configured_bundle_to_argv(configured_bundle)


def _parse_named_bundle(
    bundle_config: object,
    *,
    index: int,
    config_path: Path,
    configured_runs_by_name: dict[str, ConfiguredRun],
) -> ConfiguredBundle:
    if not isinstance(bundle_config, dict):
        raise ValueError(
            f"Bundle #{index} in {config_path} must be a mapping with name, runs, and output."
        )

    name = bundle_config.get("name")
    if not isinstance(name, str) or not name.strip():
        raise ValueError(
            f"Bundle #{index} in {config_path} must define a non-empty string for 'name'."
        )
    normalized_name = name.strip()
    _reject_unknown_keys(
        bundle_config,
        allowed_keys=_NAMED_BUNDLE_ALLOWED_KEYS,
        name=normalized_name,
        config_path=config_path,
    )
    run_names = _named_bundle_run_names(
        bundle_config,
        name=normalized_name,
        config_path=config_path,
    )
    inputs = tuple(
        _resolve_named_bundle_input(
            configured_runs_by_name.get(run_name),
            run_name=run_name,
            bundle_name=normalized_name,
            config_path=config_path,
        )
        for run_name in run_names
    )
    return _parse_configured_bundle(
        bundle_config,
        name=normalized_name,
        config_path=config_path,
        inputs=inputs,
    )


def _parse_configured_bundle(
    run_config: dict[str, object],
    *,
    name: str,
    config_path: Path,
    inputs: tuple[str, ...],
) -> ConfiguredBundle:
    index = _run_index(name=name, config_path=config_path)
    output = _resolve_path_string(
        _require_string(run_config, "output", index=index, config_path=config_path),
        config_path=config_path,
    )

    max_bytes = run_config.get("max_bytes")
    if max_bytes is not None:
        if isinstance(max_bytes, bool) or not isinstance(max_bytes, int) or max_bytes < 1:
            raise ValueError(
                f"Run {name!r} in {config_path} must set 'max_bytes' to a positive integer."
            )

    order = _optional_string(run_config, "order", index=index, config_path=config_path)
    resolved_order: BundleOrder = DEFAULT_BUNDLE_ORDER
    if order is not None:
        if order not in BUNDLE_ORDER_CHOICES:
            supported_values = " or ".join(repr(value) for value in BUNDLE_ORDER_CHOICES)
            raise ValueError(
                f"Run {name!r} in {config_path} has unsupported 'order' value "
                f"{order!r}. Use {supported_values}."
            )
        resolved_order = order

    header_mode = _optional_string(run_config, "header_mode", index=index, config_path=config_path)
    resolved_header_mode: HeaderMode = DEFAULT_HEADER_MODE
    if header_mode is not None:
        if header_mode not in HEADER_MODE_CHOICES:
            supported_values = " or ".join(repr(value) for value in HEADER_MODE_CHOICES)
            raise ValueError(
                f"Run {name!r} in {config_path} has unsupported 'header_mode' value "
                f"{header_mode!r}. Use {supported_values}."
            )
        resolved_header_mode = header_mode

    stale_mode = _optional_string(run_config, "stale_mode", index=index, config_path=config_path)
    resolved_stale_mode: StaleMode = DEFAULT_STALE_MODE
    if stale_mode is not None:
        if stale_mode not in STALE_MODE_CHOICES:
            supported_values = " or ".join(repr(value) for value in STALE_MODE_CHOICES)
            raise ValueError(
                f"Run {name!r} in {config_path} has unsupported 'stale_mode' value "
                f"{stale_mode!r}. Use {supported_values}."
            )
        resolved_stale_mode = stale_mode

    include_patterns = _optional_string_sequence(
        run_config,
        "include",
        index=index,
        config_path=config_path,
    )
    exclude_patterns = _optional_string_sequence(
        run_config,
        "exclude",
        index=index,
        config_path=config_path,
    )
    changed_only = _optional_bool(
        run_config,
        "changed_only",
        index=index,
        config_path=config_path,
        default=False,
    )
    baseline_manifest = _optional_string(
        run_config,
        "baseline_manifest",
        index=index,
        config_path=config_path,
    )
    resolved_baseline_manifest = (
        _resolve_path_string(baseline_manifest, config_path=config_path)
        if baseline_manifest is not None
        else None
    )

    return ConfiguredBundle(
        name=name,
        inputs=inputs,
        output=output,
        max_bytes=max_bytes,
        order=resolved_order,
        header_mode=resolved_header_mode,
        include_patterns=include_patterns,
        exclude_patterns=exclude_patterns,
        changed_only=changed_only,
        baseline_manifest=resolved_baseline_manifest,
        stale_mode=resolved_stale_mode,
    )


def _configured_bundle_to_argv(configured_bundle: ConfiguredBundle) -> tuple[str, ...]:
    argv: list[str] = [
        "bundle",
        *configured_bundle.inputs,
        "--output",
        configured_bundle.output,
    ]
    if configured_bundle.max_bytes is not None:
        argv.extend(["--max-bytes", str(configured_bundle.max_bytes)])
    if configured_bundle.order != DEFAULT_BUNDLE_ORDER:
        argv.extend(["--order", configured_bundle.order])
    if configured_bundle.header_mode != DEFAULT_HEADER_MODE:
        argv.extend(["--header-mode", configured_bundle.header_mode])
    if configured_bundle.stale_mode != DEFAULT_STALE_MODE:
        argv.extend(["--stale-mode", configured_bundle.stale_mode])
    for include_pattern in configured_bundle.include_patterns:
        argv.extend(["--include", include_pattern])
    for exclude_pattern in configured_bundle.exclude_patterns:
        argv.extend(["--exclude", exclude_pattern])
    if configured_bundle.changed_only:
        argv.append("--changed-only")
    if configured_bundle.baseline_manifest is not None:
        argv.extend(["--baseline-manifest", configured_bundle.baseline_manifest])
    return tuple(argv)


def _configured_runs_by_name(
    configured_runs: tuple[ConfiguredRun, ...],
    *,
    config_path: Path,
) -> dict[str, ConfiguredRun]:
    runs_by_name: dict[str, ConfiguredRun] = {}
    duplicate_names: list[str] = []
    for configured_run in configured_runs:
        if configured_run.name in runs_by_name:
            if configured_run.name not in duplicate_names:
                duplicate_names.append(configured_run.name)
            continue
        runs_by_name[configured_run.name] = configured_run
    if duplicate_names:
        duplicates = ", ".join(repr(name) for name in duplicate_names)
        raise ValueError(
            f"Config file {config_path} must use unique run names when defining top-level "
            f"bundles. Duplicate run names: {duplicates}."
        )
    return runs_by_name


def _reject_duplicate_bundle_names(
    configured_bundles: tuple[ConfiguredBundle, ...],
    *,
    config_path: Path,
) -> None:
    seen_names: set[str] = set()
    duplicate_names: list[str] = []
    for configured_bundle in configured_bundles:
        if configured_bundle.name in seen_names:
            if configured_bundle.name not in duplicate_names:
                duplicate_names.append(configured_bundle.name)
            continue
        seen_names.add(configured_bundle.name)
    if duplicate_names:
        duplicates = ", ".join(repr(name) for name in duplicate_names)
        raise ValueError(
            f"Config file {config_path} contains duplicate bundle names: {duplicates}."
        )


def _named_bundle_run_names(
    bundle_config: dict[str, object],
    *,
    name: str,
    config_path: Path,
) -> tuple[str, ...]:
    raw_run_names = bundle_config.get("runs")
    if raw_run_names is None:
        raise ValueError(
            f"Bundle {name!r} in {config_path} must define 'runs' as a non-empty string "
            "or list of non-empty strings."
        )
    if isinstance(raw_run_names, str):
        normalized_name = raw_run_names.strip()
        if not normalized_name:
            raise ValueError(
                f"Bundle {name!r} in {config_path} must define 'runs' as a non-empty string "
                "or list of non-empty strings."
            )
        return (normalized_name,)
    if not isinstance(raw_run_names, list) or not raw_run_names:
        raise ValueError(
            f"Bundle {name!r} in {config_path} must define 'runs' as a non-empty string "
            "or list of non-empty strings."
        )

    normalized_names: list[str] = []
    for run_name in raw_run_names:
        if not isinstance(run_name, str) or not run_name.strip():
            raise ValueError(
                f"Bundle {name!r} in {config_path} must define 'runs' as a non-empty string "
                "or list of non-empty strings."
            )
        normalized_names.append(run_name.strip())
    return tuple(normalized_names)


def _resolve_named_bundle_input(
    configured_run: ConfiguredRun | None,
    *,
    run_name: str,
    bundle_name: str,
    config_path: Path,
) -> str:
    if configured_run is None:
        raise ValueError(
            f"Bundle {bundle_name!r} in {config_path} references unknown run name "
            f"{run_name!r}."
        )
    resolved_output_dir = _argv_flag_value(configured_run.argv, "--output-dir")
    if resolved_output_dir is None:
        raise ValueError(
            f"Bundle {bundle_name!r} in {config_path} references run {run_name!r}, but "
            "that run has no resolvable output directory or manifest path for bundling."
        )
    return resolved_output_dir


def _argv_flag_value(argv: tuple[str, ...], flag: str) -> str | None:
    for index, value in enumerate(argv):
        if value == flag and index + 1 < len(argv):
            return argv[index + 1]
    return None


def _resolve_configured_ca_bundle(
    ca_bundle: str | None,
    *,
    config_path: Path,
    no_ca_bundle: bool,
) -> str | None:
    if no_ca_bundle:
        return None

    env_ca_bundle = os.getenv(CONFLUENCE_CA_BUNDLE_ENV)
    if env_ca_bundle is not None:
        normalized_env_ca_bundle = env_ca_bundle.strip()
        return normalized_env_ca_bundle or None

    if ca_bundle is None:
        return None

    return _resolve_path_string(ca_bundle, config_path=config_path)


def _build_local_files_argv(
    run_config: dict[str, object],
    *,
    name: str,
    config_path: Path,
) -> tuple[str, ...]:
    _reject_unknown_keys(
        run_config,
        allowed_keys=_LOCAL_FILES_ALLOWED_KEYS,
        name=name,
        config_path=config_path,
    )
    index = _run_index(name=name, config_path=config_path)
    file_path = _resolve_path_string(
        _require_string(run_config, "file_path", index=index, config_path=config_path),
        config_path=config_path,
    )
    output_dir = _resolve_path_string(
        _require_string(run_config, "output_dir", index=index, config_path=config_path),
        config_path=config_path,
    )
    argv: list[str] = [
        "local_files",
        "--file-path",
        file_path,
        "--output-dir",
        output_dir,
    ]
    if _optional_bool(run_config, "dry_run", index=index, config_path=config_path, default=False):
        argv.append("--dry-run")
    return tuple(argv)


def _build_git_repo_argv(
    run_config: dict[str, object],
    *,
    name: str,
    config_path: Path,
) -> tuple[str, ...]:
    _reject_unknown_keys(
        run_config,
        allowed_keys=_GIT_REPO_ALLOWED_KEYS,
        name=name,
        config_path=config_path,
    )
    index = _run_index(name=name, config_path=config_path)
    repo_url = _require_string(run_config, "repo_url", index=index, config_path=config_path)
    output_dir = _resolve_path_string(
        _require_string(run_config, "output_dir", index=index, config_path=config_path),
        config_path=config_path,
    )
    argv: list[str] = [
        "git_repo",
        "--repo-url",
        repo_url,
        "--output-dir",
        output_dir,
    ]

    ref = _optional_string(run_config, "ref", index=index, config_path=config_path)
    if ref is not None:
        argv.extend(["--ref", ref])

    subdir = _optional_string(run_config, "subdir", index=index, config_path=config_path)
    if subdir is not None:
        argv.extend(["--subdir", subdir])

    for include_pattern in _optional_string_sequence(
        run_config,
        "include",
        index=index,
        config_path=config_path,
    ):
        argv.extend(["--include", include_pattern])
    for exclude_pattern in _optional_string_sequence(
        run_config,
        "exclude",
        index=index,
        config_path=config_path,
    ):
        argv.extend(["--exclude", exclude_pattern])

    if _optional_bool(run_config, "dry_run", index=index, config_path=config_path, default=False):
        argv.append("--dry-run")
    return tuple(argv)


def _build_github_metadata_argv(
    run_config: dict[str, object],
    *,
    name: str,
    config_path: Path,
) -> tuple[str, ...]:
    _reject_unknown_keys(
        run_config,
        allowed_keys=_GITHUB_METADATA_ALLOWED_KEYS,
        name=name,
        config_path=config_path,
    )
    index = _run_index(name=name, config_path=config_path)
    repo = _require_string(run_config, "repo", index=index, config_path=config_path)
    token_env = _require_string(run_config, "token_env", index=index, config_path=config_path)
    output_dir = _resolve_path_string(
        _require_string(run_config, "output_dir", index=index, config_path=config_path),
        config_path=config_path,
    )
    argv: list[str] = [
        "github_metadata",
        "--repo",
        repo,
        "--token-env",
        token_env,
        "--output-dir",
        output_dir,
    ]

    resource_type = _optional_string(
        run_config,
        "resource_type",
        index=index,
        config_path=config_path,
    )
    if resource_type is not None:
        if resource_type not in _SUPPORTED_GITHUB_METADATA_RESOURCE_TYPES:
            supported_values = " or ".join(
                repr(value) for value in sorted(_SUPPORTED_GITHUB_METADATA_RESOURCE_TYPES)
            )
            raise ValueError(
                f"Run {name!r} in {config_path} has unsupported 'resource_type' value "
                f"{resource_type!r}. Use {supported_values}."
            )
        argv.extend(["--resource-type", resource_type])

    base_url = _optional_string(run_config, "base_url", index=index, config_path=config_path)
    if base_url is not None:
        argv.extend(["--base-url", base_url])

    state = _optional_string(run_config, "state", index=index, config_path=config_path)
    if state is not None:
        if state not in _SUPPORTED_GITHUB_METADATA_STATES:
            supported_values = " or ".join(
                repr(value) for value in sorted(_SUPPORTED_GITHUB_METADATA_STATES)
            )
            raise ValueError(
                f"Run {name!r} in {config_path} has unsupported 'state' value "
                f"{state!r}. Use {supported_values}."
            )
        argv.extend(["--state", state])

    since = _optional_string_or_datetime(run_config, "since", index=index, config_path=config_path)
    if since is not None:
        argv.extend(["--since", since])

    max_items = run_config.get("max_items")
    if max_items is not None:
        if isinstance(max_items, bool) or not isinstance(max_items, int) or max_items < 1:
            raise ValueError(
                f"Run {name!r} in {config_path} must set 'max_items' to a positive integer."
            )
        argv.extend(["--max-items", str(max_items)])

    if _optional_bool(
        run_config,
        "include_issue_comments",
        index=index,
        config_path=config_path,
        default=False,
    ):
        argv.append("--include-issue-comments")

    if _optional_bool(run_config, "dry_run", index=index, config_path=config_path, default=False):
        argv.append("--dry-run")
    return tuple(argv)


def _reject_unknown_keys(
    run_config: dict[str, object],
    *,
    allowed_keys: frozenset[str],
    name: str,
    config_path: Path,
) -> None:
    unknown_keys = sorted(set(run_config) - allowed_keys)
    if unknown_keys:
        unknown_key_list = ", ".join(repr(key) for key in unknown_keys)
        raise ValueError(
            f"Run {name!r} in {config_path} contains unsupported keys: {unknown_key_list}."
        )


def _require_string(
    run_config: dict[str, object],
    key: str,
    *,
    index: int | str,
    config_path: Path,
) -> str:
    value = run_config.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(
            f"Run {index!r} in {config_path} must define a non-empty string for {key!r}."
        )
    return value.strip()


def _optional_string(
    run_config: dict[str, object],
    key: str,
    *,
    index: int | str,
    config_path: Path,
) -> str | None:
    if key not in run_config:
        return None
    value = run_config.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(
            f"Run {index!r} in {config_path} must define a non-empty string for {key!r}."
        )
    return value.strip()


def _optional_string_or_datetime(
    run_config: dict[str, object],
    key: str,
    *,
    index: int | str,
    config_path: Path,
) -> str | None:
    if key not in run_config:
        return None
    value = run_config.get(key)
    if isinstance(value, str) and value.strip():
        return value.strip()
    if isinstance(value, datetime):
        normalized_datetime = value
        if normalized_datetime.tzinfo is UTC:
            return normalized_datetime.isoformat().replace("+00:00", "Z")
        return normalized_datetime.isoformat()
    raise ValueError(f"Run {index!r} in {config_path} must define a non-empty string for {key!r}.")


def _optional_string_sequence(
    run_config: dict[str, object],
    key: str,
    *,
    index: int | str,
    config_path: Path,
) -> tuple[str, ...]:
    if key not in run_config:
        return ()

    raw_value = run_config.get(key)
    if isinstance(raw_value, str):
        normalized_value = raw_value.strip()
        if not normalized_value:
            raise ValueError(
                f"Run {index!r} in {config_path} must define a non-empty string for {key!r}."
            )
        return (normalized_value,)

    if not isinstance(raw_value, list) or not raw_value:
        raise ValueError(
            f"Run {index!r} in {config_path} must define {key!r} as a non-empty string "
            "or list of non-empty strings."
        )

    normalized_values: list[str] = []
    for item in raw_value:
        if not isinstance(item, str) or not item.strip():
            raise ValueError(
                f"Run {index!r} in {config_path} must define {key!r} as a non-empty "
                "string or list of non-empty strings."
            )
        normalized_values.append(item.strip())
    return tuple(normalized_values)


def _required_string_sequence(
    run_config: dict[str, object],
    key: str,
    *,
    index: int | str,
    config_path: Path,
) -> tuple[str, ...]:
    if key not in run_config:
        raise ValueError(
            f"Run {index!r} in {config_path} must define {key!r} as a non-empty string "
            "or list of non-empty strings."
        )

    return _optional_string_sequence(
        run_config,
        key,
        index=index,
        config_path=config_path,
    )


def _optional_bool(
    run_config: dict[str, object],
    key: str,
    *,
    index: int | str,
    config_path: Path,
    default: bool,
) -> bool:
    if key not in run_config:
        return default
    value = run_config.get(key)
    if not isinstance(value, bool):
        raise ValueError(f"Run {index!r} in {config_path} must set {key!r} to true or false.")
    return value


def _resolve_path_string(value: str, *, config_path: Path) -> str:
    path = Path(value).expanduser()
    if path.is_absolute():
        return str(path)
    return str((config_path.parent / path).resolve())


def _run_index(*, name: str, config_path: Path) -> str:
    return f"{name} in {config_path}"
