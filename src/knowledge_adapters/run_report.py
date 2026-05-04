"""Lightweight report rendering for config-driven adapter runs."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

RunReportStatus = Literal["completed", "failed", "interrupted"]


@dataclass(frozen=True)
class RunReportRecord:
    """One configured adapter execution recorded for the run report."""

    index: int
    total: int
    name: str
    run_type: str
    command: str
    status: RunReportStatus
    dry_run: bool | None = None
    wrote: int | None = None
    skipped: int | None = None
    failure_message: str | None = None
    failure_details: tuple[str, ...] = field(default_factory=tuple)


@dataclass(frozen=True)
class SkippedRunRecord:
    """One configured run skipped because enabled: false was honored."""

    name: str
    run_type: str


def render_run_report_markdown(
    *,
    config_path: Path,
    selected_run_count: int,
    skipped_disabled_runs: tuple[SkippedRunRecord, ...],
    records: tuple[RunReportRecord, ...],
) -> str:
    """Render a concise, human-readable Markdown report."""
    completed_runs = sum(1 for record in records if record.status == "completed")
    failed_runs = sum(1 for record in records if record.status == "failed")
    interrupted_runs = sum(1 for record in records if record.status == "interrupted")
    write_runs = sum(
        1 for record in records if record.status == "completed" and record.dry_run is False
    )
    dry_run_runs = sum(
        1 for record in records if record.status == "completed" and record.dry_run is True
    )
    wrote = sum(record.wrote or 0 for record in records if record.dry_run is False)
    skipped = sum(record.skipped or 0 for record in records if record.dry_run is False)
    would_write = sum(record.wrote or 0 for record in records if record.dry_run is True)
    would_skip = sum(record.skipped or 0 for record in records if record.dry_run is True)

    lines = [
        "# Knowledge Adapter Run Report",
        "",
        f"- Config: `{config_path}`",
        f"- Runs selected: {selected_run_count}",
        f"- Runs completed: {completed_runs}",
        f"- Runs failed: {failed_runs}",
        f"- Runs interrupted: {interrupted_runs}",
        f"- Runs skipped disabled: {len(skipped_disabled_runs)}",
        f"- Write runs: {write_runs}",
        f"- Dry-run runs: {dry_run_runs}",
        f"- Wrote: {wrote}",
        f"- Skipped: {skipped}",
    ]
    if dry_run_runs > 0:
        lines.extend(
            [
                f"- Would write: {would_write}",
                f"- Would skip: {would_skip}",
            ]
        )

    lines.extend(
        [
            "",
            "## Runs",
            "",
            "| # | Name | Type | Status | Result | Failure class |",
            "| --- | --- | --- | --- | --- | --- |",
        ]
    )
    if records:
        lines.extend(_render_record_row(record) for record in records)
    else:
        lines.append("| - | - | - | none | No runs executed. | - |")

    if skipped_disabled_runs:
        lines.extend(
            [
                "",
                "## Skipped Disabled Runs",
                "",
                "| Name | Type |",
                "| --- | --- |",
            ]
        )
        lines.extend(
            f"| {_markdown_cell(record.name)} | {_markdown_cell(record.run_type)} |"
            for record in skipped_disabled_runs
        )

    failed_records = tuple(record for record in records if record.status == "failed")
    if failed_records:
        lines.extend(["", "## Failure Details"])
        for record in failed_records:
            lines.extend(
                [
                    "",
                    f"### {record.index}. {record.name} ({record.run_type})",
                    "",
                    f"- Message: {_markdown_inline(record.failure_message or 'Run failed.')}",
                    f"- Command: `{_markdown_inline(record.command)}`",
                ]
            )
            if record.failure_details:
                lines.append("- Details:")
                lines.extend(
                    f"  - `{_markdown_inline(detail.strip())}`"
                    for detail in record.failure_details
                )

    return "\n".join(lines) + "\n"


def _render_record_row(record: RunReportRecord) -> str:
    return (
        f"| {record.index}/{record.total} "
        f"| {_markdown_cell(record.name)} "
        f"| {_markdown_cell(record.run_type)} "
        f"| {record.status} "
        f"| {_markdown_cell(_record_result(record))} "
        f"| {_markdown_cell(_failure_class(record) or '-')} |"
    )


def _record_result(record: RunReportRecord) -> str:
    if record.status == "completed":
        if record.dry_run:
            return f"would write {record.wrote or 0}, would skip {record.skipped or 0}"
        return f"wrote {record.wrote or 0}, skipped {record.skipped or 0}"
    if record.status == "interrupted":
        return "interrupted before completion"
    return record.failure_message or "failed"


def _failure_class(record: RunReportRecord) -> str | None:
    for detail in record.failure_details:
        stripped_detail = detail.strip()
        if stripped_detail.startswith("failure_class:"):
            return stripped_detail.partition(":")[2].strip() or None
    return None


def _markdown_cell(value: str) -> str:
    return value.replace("\\", "\\\\").replace("|", "\\|").replace("\n", "<br>")


def _markdown_inline(value: str) -> str:
    return value.replace("`", "\\`")
