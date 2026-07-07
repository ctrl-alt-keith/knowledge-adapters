from __future__ import annotations

from pathlib import Path

from knowledge_adapters.incremental_sync import SyncChangeKey, classify_incremental_sync
from knowledge_adapters.manifest_stale import PreviousManifestEntry


def _previous_entry(
    *,
    output_path: str = "records/1.md",
    page_version: str | None = None,
    last_modified: str | None = None,
    content_hash: str | None = None,
) -> PreviousManifestEntry:
    return PreviousManifestEntry(
        canonical_id="record:1",
        output_path=output_path,
        page_version=page_version,
        last_modified=last_modified,
        content_hash=content_hash,
    )


def test_classify_incremental_sync_uses_ordered_change_keys(tmp_path: Path) -> None:
    artifact_path = tmp_path / "records" / "1.md"
    artifact_path.parent.mkdir(parents=True)
    artifact_path.write_text("already written\n", encoding="utf-8")
    previous_manifest_index = {
        "record:1": _previous_entry(last_modified="2026-04-20T00:00:00Z")
    }

    decision = classify_incremental_sync(
        str(tmp_path),
        previous_manifest_index,
        canonical_id="record:1",
        output_path="records/1.md",
        change_keys=(
            SyncChangeKey(name="page_version", current_value="7"),
            SyncChangeKey(name="last_modified", current_value="2026-04-20T00:00:00Z"),
        ),
        no_previous_manifest_reason="new page",
        missing_metadata_reason="prior manifest entry missing metadata, so safe rewrite",
    )

    assert decision.status == "unchanged"
    assert decision.reason is None


def test_classify_incremental_sync_reports_single_change_key_missing_reasons(
    tmp_path: Path,
) -> None:
    artifact_path = tmp_path / "records" / "1.md"
    artifact_path.parent.mkdir(parents=True)
    artifact_path.write_text("already written\n", encoding="utf-8")
    previous_manifest_index = {"record:1": _previous_entry()}

    missing_current = classify_incremental_sync(
        str(tmp_path),
        previous_manifest_index,
        canonical_id="record:1",
        output_path="records/1.md",
        change_keys=(SyncChangeKey(name="content_hash", current_value=None),),
        no_previous_manifest_reason="no previous manifest",
        missing_metadata_reason="prior manifest entry missing content_hash",
        missing_current_change_key_reason="content_hash missing",
        missing_previous_change_key_reason="prior manifest entry missing content_hash",
    )
    missing_previous = classify_incremental_sync(
        str(tmp_path),
        previous_manifest_index,
        canonical_id="record:1",
        output_path="records/1.md",
        change_keys=(SyncChangeKey(name="content_hash", current_value="new-hash"),),
        no_previous_manifest_reason="no previous manifest",
        missing_metadata_reason="prior manifest entry missing content_hash",
        missing_current_change_key_reason="content_hash missing",
        missing_previous_change_key_reason="prior manifest entry missing content_hash",
    )

    assert missing_current.status == "changed"
    assert missing_current.reason == "content_hash missing"
    assert missing_previous.status == "changed"
    assert missing_previous.reason == "prior manifest entry missing content_hash"
