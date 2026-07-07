"""Named strategy registry helpers."""

from __future__ import annotations

from collections.abc import Mapping


def select_strategy[T](strategies: Mapping[str, T], name: str, *, label: str) -> T:
    """Select a named strategy or raise a stable unsupported-strategy error."""
    try:
        return strategies[name]
    except KeyError as exc:
        supported_values = " or ".join(repr(strategy_name) for strategy_name in strategies)
        raise ValueError(f"Unsupported {label} {name!r}. Use {supported_values}.") from exc
