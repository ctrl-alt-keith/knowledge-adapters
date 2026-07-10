from pathlib import Path

from knowledge_adapters.source_package import (
    AdapterIdentity,
    Artifact,
    ItemOutcome,
    PackageBuilder,
    PackageItem,
    verify_package,
)


def builder() -> PackageBuilder:
    value = PackageBuilder(
        package_id="pkg-1",
        request_id="req-1",
        run_id="run-1",
        created_at="2026-07-10T00:00:00Z",
        adapter=AdapterIdentity("fixture", "1.0.0"),
        boundary={"live": "fixture", "deterministic": "assembly"},
    )
    value.add_artifact(Artifact("request.json", b"{}\n", "request", "application/json"))
    value.add_item(PackageItem("one", "document", ItemOutcome.COMPLETED))
    return value


def test_seal_is_deterministic_and_verifiable(tmp_path: Path) -> None:
    first, second = tmp_path / "first", tmp_path / "second"
    one, two = builder().seal(first), builder().seal(second)
    assert one.ok and two.ok
    assert one.content_address == two.content_address
    result = verify_package(first)
    assert result.ok
    assert result.content_address == one.content_address


def test_verifier_rejects_manifest_before_parsing(tmp_path: Path) -> None:
    destination = tmp_path / "package"
    assert builder().seal(destination).ok
    (destination / "package.json").write_bytes(b"not json")
    result = verify_package(destination)
    assert not result.ok
    assert result.issues[0].code == "manifest-digest"


def test_builder_rejects_unsafe_paths() -> None:
    value = builder()
    try:
        value.add_artifact(Artifact("../escape", b"x", "bad", "text/plain"))
    except ValueError as exc:
        assert "unsafe" in str(exc)
    else:
        raise AssertionError("unsafe path accepted")
