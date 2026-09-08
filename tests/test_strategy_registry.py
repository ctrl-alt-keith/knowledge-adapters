from __future__ import annotations

import pytest

from knowledge_adapters.strategy_registry import select_strategy


def test_select_strategy_returns_requested_named_strategy() -> None:
    primary = object()
    fallback = object()

    selected = select_strategy(
        {"primary": primary, "fallback": fallback},
        "fallback",
        label="adapter strategy",
    )

    assert selected is fallback


def test_select_strategy_rejects_unknown_name_with_supported_options() -> None:
    with pytest.raises(
        ValueError,
        match="^Unsupported adapter strategy 'missing'\. Use 'primary' or 'fallback'\.$",
    ):
        select_strategy(
            {"primary": object(), "fallback": object()},
            "missing",
            label="adapter strategy",
        )
