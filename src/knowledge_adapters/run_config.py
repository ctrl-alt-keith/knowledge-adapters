"""Config loading for sequential multi-run execution."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import yaml  # type: ignore[import-untyped]

SUPPORTED_RUN_TYPES = frozenset({"confluence", "local_files"})

_COMMON_REQUIRED_KEYS = frozenset({"name", "type", "output_dir"})
_CONFLUENCE_ALLOWED_KEYS = _COMMON_REQUIRED_KEYS | frozenset(
    {
        "auth_method",
        "base_url",
        "client_mode",
        "debug",
        "dry_run",
        "max_depth",
        "target",
        "tree",
    }
)
_LOCAL_FILES_ALLOWED_KEYS = _COMMON_REQUIRED_KEYS | frozenset({"dry_run", "file_path"})


@dataclass(frozen=True)
class ConfiguredRun:
    """One adapter execution described in a config file."""

    name: str
    run_type: str
    argv: tuple[str, ...]
    dry_run: bool


@dataclass(frozen=True)
class RunConfig:
    """Validated multi-run config."""

    config_path: Path
    runs: tuple[ConfiguredRun, ...]


def load_run_config(config_path: str | Path) -> RunConfig:
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
            _parse_run(run_config, index=index, config_path=resolved_config_path)
            for index, run_config in enumerate(runs, start=1)
        ),
    )


def _parse_run(
    run_config: object,
    *,
    index: int,
    config_path: Path,
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
        argv = _build_confluence_argv(run_config, name=name, config_path=config_path)
        dry_run = _optional_bool(
            run_config,
            "dry_run",
            index=index,
            config_path=config_path,
            default=False,
        )
        return ConfiguredRun(name=name, run_type=run_type, argv=argv, dry_run=dry_run)

    argv = _build_local_files_argv(run_config, name=name, config_path=config_path)
    dry_run = _optional_bool(
        run_config,
        "dry_run",
        index=index,
        config_path=config_path,
        default=False,
    )
    return ConfiguredRun(name=name, run_type=run_type, argv=argv, dry_run=dry_run)


def _build_confluence_argv(
    run_config: dict[str, object],
    *,
    name: str,
    config_path: Path,
) -> tuple[str, ...]:
    _reject_unknown_keys(
        run_config,
        allowed_keys=_CONFLUENCE_ALLOWED_KEYS,
        name=name,
        config_path=config_path,
    )
    index = _run_index(name=name, config_path=config_path)
    base_url = _require_string(run_config, "base_url", index=index, config_path=config_path)
    target = _require_string(run_config, "target", index=index, config_path=config_path)
    output_dir = _resolve_path_string(
        _require_string(run_config, "output_dir", index=index, config_path=config_path),
        config_path=config_path,
    )
    argv: list[str] = [
        "confluence",
        "--base-url",
        base_url,
        "--target",
        target,
        "--output-dir",
        output_dir,
    ]

    client_mode = _optional_string(run_config, "client_mode", index=index, config_path=config_path)
    if client_mode is not None:
        argv.extend(["--client-mode", client_mode])

    auth_method = _optional_string(run_config, "auth_method", index=index, config_path=config_path)
    if auth_method is not None:
        argv.extend(["--auth-method", auth_method])

    if _optional_bool(run_config, "debug", index=index, config_path=config_path, default=False):
        argv.append("--debug")
    if _optional_bool(run_config, "dry_run", index=index, config_path=config_path, default=False):
        argv.append("--dry-run")
    if _optional_bool(run_config, "tree", index=index, config_path=config_path, default=False):
        argv.append("--tree")

    max_depth = run_config.get("max_depth")
    if max_depth is not None:
        if isinstance(max_depth, bool) or not isinstance(max_depth, int):
            raise ValueError(
                f"Run {name!r} in {config_path} must set 'max_depth' to an integer."
            )
        argv.extend(["--max-depth", str(max_depth)])

    return tuple(argv)


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
