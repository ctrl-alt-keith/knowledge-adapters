"""Config loading for sequential multi-run execution."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

import yaml  # type: ignore[import-untyped]

from knowledge_adapters.confluence.auth import CONFLUENCE_CA_BUNDLE_ENV, SUPPORTED_AUTH_METHODS
from knowledge_adapters.confluence.config import validate_explicit_tls_paths
from knowledge_adapters.confluence.resolve import (
    resolve_target_for_base_url,
    space_key_from_url_for_base_url,
    validate_base_url,
    validate_space_key,
)

SUPPORTED_RUN_TYPES = frozenset({"confluence", "git_repo", "local_files"})
_SUPPORTED_CONFLUENCE_CLIENT_MODES = frozenset({"real", "stub"})

_COMMON_REQUIRED_KEYS = frozenset({"name", "type", "output_dir"})
_CONFLUENCE_ALLOWED_KEYS = _COMMON_REQUIRED_KEYS | frozenset(
    {
        "auth_method",
        "base_url",
        "ca_bundle",
        "client_mode",
        "client_cert_file",
        "client_key_file",
        "debug",
        "dry_run",
        "enabled",
        "max_depth",
        "space_key",
        "space_url",
        "target",
        "tree",
    }
)
_LOCAL_FILES_ALLOWED_KEYS = _COMMON_REQUIRED_KEYS | frozenset(
    {"dry_run", "enabled", "file_path"}
)
_GIT_REPO_ALLOWED_KEYS = _COMMON_REQUIRED_KEYS | frozenset(
    {"dry_run", "enabled", "exclude", "include", "ref", "repo_url", "subdir"}
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
class RunConfig:
    """Validated multi-run config."""

    config_path: Path
    runs: tuple[ConfiguredRun, ...]


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

    return RunConfig(
        config_path=resolved_config_path,
        runs=tuple(
            _parse_run(
                run_config,
                index=index,
                config_path=resolved_config_path,
                no_confluence_ca_bundle=no_confluence_ca_bundle,
            )
            for index, run_config in enumerate(runs, start=1)
        ),
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

    if run_type == "git_repo":
        argv = _build_git_repo_argv(run_config, name=name, config_path=config_path)
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
        raise ValueError(
            f"Run {name!r} in {config_path} has invalid 'base_url': {exc}"
        ) from exc

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
                f"Run {name!r} in {config_path} must set 'target', 'space_key', or "
                "'space_url'."
            )
        try:
            resolve_target_for_base_url(target, base_url=base_url)
        except ValueError as exc:
            raise ValueError(
                f"Run {name!r} in {config_path} has invalid 'target': {exc}"
            ) from exc

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

    if _optional_bool(run_config, "debug", index=index, config_path=config_path, default=False):
        argv.append("--debug")
    if _optional_bool(run_config, "dry_run", index=index, config_path=config_path, default=False):
        argv.append("--dry-run")
    if tree:
        argv.append("--tree")

    if max_depth is not None:
        if isinstance(max_depth, bool) or not isinstance(max_depth, int):
            raise ValueError(
                f"Run {name!r} in {config_path} must set 'max_depth' to an integer."
            )
        if max_depth < 0:
            raise ValueError(
                f"Run {name!r} in {config_path} must set 'max_depth' to an integer "
                "greater than or equal to 0."
            )
        argv.extend(["--max-depth", str(max_depth)])

    return tuple(argv)


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
