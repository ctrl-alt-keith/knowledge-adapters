"""Human-readable adapter reliability coverage reporting."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass


@dataclass(frozen=True)
class ReadinessDimension:
    """One tracked reliability coverage dimension."""

    key: str
    title: str


@dataclass(frozen=True)
class AdapterReadiness:
    """Observed reliability coverage for one adapter."""

    adapter: str
    coverage: dict[str, bool]
    evidence: dict[str, str]


READINESS_DIMENSIONS: tuple[ReadinessDimension, ...] = (
    ReadinessDimension(
        key="contract_invariant",
        title="Contract/invariant",
    ),
    ReadinessDimension(
        key="chaos",
        title="Chaos",
    ),
    ReadinessDimension(
        key="replay",
        title="Replay",
    ),
    ReadinessDimension(
        key="no_partial_artifacts",
        title="No partial artifacts",
    ),
)

ADAPTER_READINESS: tuple[AdapterReadiness, ...] = (
    AdapterReadiness(
        adapter="confluence",
        coverage={
            "contract_invariant": True,
            "chaos": True,
            "replay": True,
            "no_partial_artifacts": True,
        },
        evidence={
            "contract_invariant": (
                "tests/confluence/test_contracts.py uses tests.adapter_contracts helpers."
            ),
            "chaos": (
                "tests/confluence/test_chaos.py covers deterministic Confluence HTTP failures."
            ),
            "replay": "make chaos-replay reruns named Confluence chaos scenarios.",
            "no_partial_artifacts": (
                "Confluence failure tests assert no manifest or markdown artifacts are written."
            ),
        },
    ),
    AdapterReadiness(
        adapter="git_repo",
        coverage={
            "contract_invariant": False,
            "chaos": False,
            "replay": False,
            "no_partial_artifacts": False,
        },
        evidence={
            "contract_invariant": "Not yet registered in the readiness model.",
            "chaos": "No git_repo chaos scenarios are registered.",
            "replay": "Replay applies to registered chaos scenarios; git_repo has none.",
            "no_partial_artifacts": "No no-partial-artifact failure coverage is registered.",
        },
    ),
    AdapterReadiness(
        adapter="github_metadata",
        coverage={
            "contract_invariant": False,
            "chaos": False,
            "replay": False,
            "no_partial_artifacts": False,
        },
        evidence={
            "contract_invariant": "Not yet registered in the readiness model.",
            "chaos": "No github_metadata chaos scenarios are registered.",
            "replay": "Replay applies to registered chaos scenarios; github_metadata has none.",
            "no_partial_artifacts": "No no-partial-artifact failure coverage is registered.",
        },
    ),
    AdapterReadiness(
        adapter="local_files",
        coverage={
            "contract_invariant": False,
            "chaos": False,
            "replay": False,
            "no_partial_artifacts": False,
        },
        evidence={
            "contract_invariant": "Not yet registered in the readiness model.",
            "chaos": "No local_files chaos scenarios are registered.",
            "replay": "Replay applies to registered chaos scenarios; local_files has none.",
            "no_partial_artifacts": "No no-partial-artifact failure coverage is registered.",
        },
    ),
)


def adapter_readiness() -> tuple[AdapterReadiness, ...]:
    """Return readiness rows in deterministic adapter-name order."""
    return tuple(sorted(ADAPTER_READINESS, key=lambda row: row.adapter))


def render_adapter_readiness_report(
    rows: Sequence[AdapterReadiness] | None = None,
) -> str:
    """Render the readiness model as deterministic plain text."""
    readiness_rows = tuple(rows) if rows is not None else adapter_readiness()
    _validate_rows(readiness_rows)

    headers = ("Adapter", *(dimension.title for dimension in READINESS_DIMENSIONS))
    table_rows = [
        (
            row.adapter,
            *(_format_coverage(row.coverage[dimension.key]) for dimension in READINESS_DIMENSIONS),
        )
        for row in readiness_rows
    ]
    widths = _column_widths((headers, *table_rows))

    lines = [
        "Adapter Readiness Coverage",
        "",
        "Lightweight coverage map; not a quality score.",
        "",
        _format_table_row(headers, widths),
        _format_table_row(tuple("-" * width for width in widths), widths),
    ]
    lines.extend(_format_table_row(row, widths) for row in table_rows)
    lines.extend(("", "Evidence:"))

    for row in readiness_rows:
        lines.append(f"{row.adapter}:")
        for dimension in READINESS_DIMENSIONS:
            status = _format_coverage(row.coverage[dimension.key])
            lines.append(f"  {dimension.title}: {status} - {row.evidence[dimension.key]}")

    return "\n".join(lines) + "\n"


def main() -> None:
    """Print the adapter readiness report."""
    print(render_adapter_readiness_report(), end="")


def _format_coverage(value: bool) -> str:
    return "yes" if value else "no"


def _column_widths(rows: Sequence[Sequence[str]]) -> tuple[int, ...]:
    column_count = len(rows[0])
    return tuple(max(len(row[index]) for row in rows) for index in range(column_count))


def _format_table_row(row: Sequence[str], widths: Sequence[int]) -> str:
    return "  ".join(cell.ljust(widths[index]) for index, cell in enumerate(row)).rstrip()


def _validate_rows(rows: Sequence[AdapterReadiness]) -> None:
    expected_keys = {dimension.key for dimension in READINESS_DIMENSIONS}
    for row in rows:
        coverage_keys = set(row.coverage)
        evidence_keys = set(row.evidence)
        if coverage_keys != expected_keys:
            raise ValueError(f"{row.adapter} coverage keys do not match readiness dimensions.")
        if evidence_keys != expected_keys:
            raise ValueError(f"{row.adapter} evidence keys do not match readiness dimensions.")


if __name__ == "__main__":
    main()
