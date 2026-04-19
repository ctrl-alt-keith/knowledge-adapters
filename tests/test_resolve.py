from knowledge_adapters.confluence.resolve import resolve_target


def test_resolve_numeric_page_id() -> None:
    target = resolve_target("123456")

    assert target.page_id == "123456"
    assert target.page_url is None


def test_resolve_url_with_page_id() -> None:
    url = "https://example.com/pages/viewpage.action?pageId=7890"

    target = resolve_target(url)

    assert target.page_id == "7890"
    assert target.page_url == url


def test_resolve_unknown_format() -> None:
    target = resolve_target("some-random-string")

    assert target.page_id is None
    assert target.page_url is None


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


def test_resolve_url_without_page_id_preserves_url_without_resolving_id() -> None:
    target = resolve_target("https://example.com/pages/viewpage.action")

    assert target.page_id is None
    assert target.page_url == "https://example.com/pages/viewpage.action"


def test_resolve_url_with_missing_page_id_value_preserves_url_without_resolving_id() -> None:
    target = resolve_target("https://example.com/pages/viewpage.action?pageId=")

    assert target.page_id is None
    assert target.page_url == "https://example.com/pages/viewpage.action?pageId="


def test_resolve_path_like_target_with_page_id_pattern_does_not_count_as_url() -> None:
    target = resolve_target("example.com/pages/viewpage.action?pageId=7890")

    assert target.page_id is None
    assert target.page_url is None
