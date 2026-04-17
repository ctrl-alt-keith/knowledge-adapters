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