import pytest

from knowledge_adapters.confluence.resolve import resolve_target, resolve_target_for_base_url


def test_resolve_numeric_page_id() -> None:
    target = resolve_target("123456")

    assert target.page_id == "123456"
    assert target.page_url is None
    assert target.input_kind == "page_id"


def test_resolve_url_with_page_id() -> None:
    url = "https://example.com/pages/viewpage.action?pageId=7890"

    target = resolve_target(url)

    assert target.page_id == "7890"
    assert target.page_url == url
    assert target.input_kind == "url"


def test_resolve_url_with_page_id_in_path() -> None:
    url = "https://example.com/wiki/spaces/ENG/pages/7890/Team+Runbook"

    target = resolve_target(url)

    assert target.page_id == "7890"
    assert target.page_url == url
    assert target.input_kind == "url"


def test_resolve_unknown_format() -> None:
    target = resolve_target("some-random-string")

    assert target.page_id is None
    assert target.page_url is None
    assert target.input_kind == "unknown"


def test_resolve_numeric_page_id_trims_surrounding_whitespace() -> None:
    target = resolve_target("  123456  ")

    assert target.raw_value == "123456"
    assert target.page_id == "123456"
    assert target.page_url is None


def test_resolve_url_with_page_id_trims_surrounding_whitespace() -> None:
    target = resolve_target("  https://example.com/pages/viewpage.action?pageId=7890  ")

    assert target.raw_value == "https://example.com/pages/viewpage.action?pageId=7890"
    assert target.page_id == "7890"
    assert target.page_url == "https://example.com/pages/viewpage.action?pageId=7890"


def test_resolve_blank_target_as_unknown_format() -> None:
    target = resolve_target("   ")

    assert target.raw_value == ""
    assert target.page_id is None
    assert target.page_url is None
    assert target.input_kind == "empty"


def test_resolve_url_without_page_id_preserves_url_without_resolving_id() -> None:
    target = resolve_target("https://example.com/pages/viewpage.action")

    assert target.page_id is None
    assert target.page_url == "https://example.com/pages/viewpage.action"
    assert target.input_kind == "url"


def test_resolve_url_with_missing_page_id_value_preserves_url_without_resolving_id() -> None:
    target = resolve_target("https://example.com/pages/viewpage.action?pageId=")

    assert target.page_id is None
    assert target.page_url == "https://example.com/pages/viewpage.action?pageId="
    assert target.input_kind == "url"


def test_resolve_malformed_url_marks_invalid_url() -> None:
    target = resolve_target("https:///pages/viewpage.action?pageId=7890")

    assert target.page_id is None
    assert target.page_url is None
    assert target.input_kind == "invalid_url"


def test_resolve_path_like_target_with_page_id_pattern_does_not_count_as_url() -> None:
    target = resolve_target("example.com/pages/viewpage.action?pageId=7890")

    assert target.page_id is None
    assert target.page_url is None
    assert target.input_kind == "unknown"


def test_resolve_target_for_base_url_accepts_matching_page_url() -> None:
    target = resolve_target_for_base_url(
        "https://example.com/wiki/spaces/ENG/pages/7890/Team+Runbook",
        base_url="https://example.com/wiki",
    )

    assert target.page_id == "7890"


def test_resolve_target_for_base_url_rejects_url_without_page_id() -> None:
    with pytest.raises(
        ValueError,
        match="does not include a Confluence page ID",
    ):
        resolve_target_for_base_url(
            "https://example.com/wiki/spaces/ENG/overview",
            base_url="https://example.com/wiki",
        )


def test_resolve_target_for_base_url_rejects_base_url_mismatch() -> None:
    with pytest.raises(
        ValueError,
        match="does not match --base-url",
    ):
        resolve_target_for_base_url(
            "https://other.example.com/wiki/spaces/ENG/pages/7890/Team+Runbook",
            base_url="https://example.com/wiki",
        )
