from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from pathlib import Path
from typing import Any, Literal
from urllib import request

import pytest
from pytest import CaptureFixture, MonkeyPatch

from knowledge_adapters.cli import main
from knowledge_adapters.github_metadata.client import (
    issue_list_api_url,
    list_repository_issues,
    resolve_base_urls,
)
from knowledge_adapters.github_metadata.normalize import EMPTY_BODY_MARKER
from tests.cli_output_assertions import assert_dry_run_summary, assert_write_summary


class _FakeGitHubResponse:
    def __init__(
        self,
        payload: list[dict[str, object]],
        *,
        headers: Mapping[str, str] | None = None,
    ) -> None:
        self._payload = payload
        self.headers = dict(headers or {})

    def __enter__(self) -> _FakeGitHubResponse:
        return self

    def __exit__(self, exc_type: object, exc: object, tb: object) -> Literal[False]:
        return False

    def read(self) -> bytes:
        return json.dumps(self._payload).encode("utf-8")


class _FakeUrlopen:
    def __init__(self, responses: Mapping[str, _FakeGitHubResponse]) -> None:
        self._responses = dict(responses)
        self.calls: list[str] = []

    def __call__(self, api_request: request.Request, timeout: int) -> _FakeGitHubResponse:
        del timeout
        url = api_request.full_url
        self.calls.append(url)
        return self._responses[url]


def _issue(
    number: int,
    *,
    title: str | None = None,
    body: str | None = "Body",
    state: str = "open",
    author: str | None = "alice",
    extra: Mapping[str, Any] | None = None,
) -> dict[str, object]:
    payload: dict[str, object] = {
        "number": number,
        "title": title or f"Issue {number}",
        "state": state,
        "created_at": f"2026-04-{number:02d}T00:00:00Z",
        "updated_at": f"2026-04-{number:02d}T01:00:00Z",
        "body": body,
    }
    if author is not None:
        payload["user"] = {"login": author}
    if extra is not None:
        payload.update(extra)
    return payload


def _install_fake_urlopen(
    monkeypatch: MonkeyPatch,
    responses: Mapping[str, _FakeGitHubResponse],
) -> _FakeUrlopen:
    fake_urlopen = _FakeUrlopen(responses)
    monkeypatch.setattr("knowledge_adapters.github_metadata.client.request.urlopen", fake_urlopen)
    return fake_urlopen


def test_github_metadata_resolves_github_and_ghe_base_urls() -> None:
    github_urls = resolve_base_urls(None)
    assert github_urls.web_root == "https://github.com"
    assert github_urls.api_root == "https://api.github.com"
    assert github_urls.host == "github.com"
    assert (
        issue_list_api_url(
            api_root=github_urls.api_root,
            owner="octo",
            repo_name="project",
            state="open",
            since=None,
        )
        == "https://api.github.com/repos/octo/project/issues?state=open&per_page=100"
    )

    ghe_web_urls = resolve_base_urls("https://github.example.com")
    assert ghe_web_urls.web_root == "https://github.example.com"
    assert ghe_web_urls.api_root == "https://github.example.com/api/v3"
    assert ghe_web_urls.host == "github.example.com"

    ghe_api_urls = resolve_base_urls("https://github.example.com/api/v3")
    assert ghe_api_urls.web_root == "https://github.example.com"
    assert ghe_api_urls.api_root == "https://github.example.com/api/v3"
    assert ghe_api_urls.host == "github.example.com"


def test_github_metadata_missing_token_env_fails_before_request(
    monkeypatch: MonkeyPatch,
) -> None:
    monkeypatch.delenv("GH_TOKEN", raising=False)

    def fail_urlopen(api_request: request.Request, timeout: int) -> None:
        del api_request, timeout
        raise AssertionError("urlopen should not be called")

    monkeypatch.setattr(
        "knowledge_adapters.github_metadata.client.request.urlopen",
        fail_urlopen,
    )

    with pytest.raises(ValueError, match="token_env 'GH_TOKEN' is not set"):
        list_repository_issues(
            repo="octo/project",
            token_env="GH_TOKEN",
        )


def test_github_metadata_paginates_filters_prs_orders_and_limits_after_filtering(
    monkeypatch: MonkeyPatch,
) -> None:
    monkeypatch.setenv("GH_TOKEN", "secret-token")
    first_url = issue_list_api_url(
        api_root="https://api.github.com",
        owner="octo",
        repo_name="project",
        state="all",
        since=None,
    )
    second_url = "https://api.github.com/repos/octo/project/issues?state=all&per_page=100&page=2"
    fake_urlopen = _install_fake_urlopen(
        monkeypatch,
        {
            first_url: _FakeGitHubResponse(
                [
                    _issue(3),
                    _issue(2, extra={"pull_request": {"url": "https://api.github.com/pr/2"}}),
                ],
                headers={"Link": f'<{second_url}>; rel="next"'},
            ),
            second_url: _FakeGitHubResponse([_issue(4), _issue(1)]),
        },
    )

    issues = list_repository_issues(
        repo="octo/project",
        token_env="GH_TOKEN",
        state="all",
        max_items=3,
    )

    assert fake_urlopen.calls == [first_url, second_url]
    assert [issue.number for issue in issues] == [1, 3, 4]
    assert [issue.canonical_id for issue in issues] == [
        "github_metadata:github.com:octo/project:issue:1",
        "github_metadata:github.com:octo/project:issue:3",
        "github_metadata:github.com:octo/project:issue:4",
    ]


def test_github_metadata_cli_writes_issue_artifacts_and_manifest(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
    capsys: CaptureFixture[str],
) -> None:
    monkeypatch.setenv("GH_TOKEN", "secret-token")
    first_url = issue_list_api_url(
        api_root="https://api.github.com",
        owner="octo",
        repo_name="project",
        state="open",
        since=None,
    )
    _install_fake_urlopen(
        monkeypatch,
        {
            first_url: _FakeGitHubResponse(
                [
                    _issue(7, title="Empty body", body=None, author=None),
                    _issue(2, title="Useful bug", body="Bug details.\n"),
                    _issue(3, extra={"pull_request": {"url": "https://api.github.com/pr/3"}}),
                ],
            )
        },
    )
    output_dir = tmp_path / "out"

    exit_code = main(
        [
            "github_metadata",
            "--repo",
            "octo/project",
            "--token-env",
            "GH_TOKEN",
            "--output-dir",
            str(output_dir),
        ]
    )

    assert exit_code == 0
    captured = capsys.readouterr()
    assert "GitHub metadata adapter invoked" in captured.out
    assert "repo: octo/project" in captured.out
    assert "api_root: https://api.github.com" in captured.out
    assert "token_env: GH_TOKEN" in captured.out
    assert "secret-token" not in captured.out
    assert_write_summary(captured.out, wrote=2, skipped=0)

    issue_2_path = output_dir / "issues" / "2.md"
    issue_7_path = output_dir / "issues" / "7.md"
    assert issue_2_path.exists()
    assert issue_7_path.exists()
    issue_2_markdown = issue_2_path.read_text(encoding="utf-8")
    issue_7_markdown = issue_7_path.read_text(encoding="utf-8")
    assert "# Issue #2: Useful bug" in issue_2_markdown
    assert "Bug details." in issue_2_markdown
    assert EMPTY_BODY_MARKER in issue_7_markdown

    manifest_payload = json.loads((output_dir / "manifest.json").read_text(encoding="utf-8"))
    assert isinstance(manifest_payload["generated_at"], str)
    assert manifest_payload["files"] == [
        {
            "canonical_id": "github_metadata:github.com:octo/project:issue:2",
            "source_url": "https://github.com/octo/project/issues/2",
            "title": "Useful bug",
            "repo": "octo/project",
            "resource_type": "issue",
            "number": 2,
            "state": "open",
            "created_at": "2026-04-02T00:00:00Z",
            "updated_at": "2026-04-02T01:00:00Z",
            "author": "alice",
            "content_hash": hashlib.sha256(issue_2_markdown.encode("utf-8")).hexdigest(),
            "output_path": "issues/2.md",
        },
        {
            "canonical_id": "github_metadata:github.com:octo/project:issue:7",
            "source_url": "https://github.com/octo/project/issues/7",
            "title": "Empty body",
            "repo": "octo/project",
            "resource_type": "issue",
            "number": 7,
            "state": "open",
            "created_at": "2026-04-07T00:00:00Z",
            "updated_at": "2026-04-07T01:00:00Z",
            "author": None,
            "content_hash": hashlib.sha256(issue_7_markdown.encode("utf-8")).hexdigest(),
            "output_path": "issues/7.md",
        },
    ]


def test_github_metadata_cli_dry_run_does_not_write_files(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
    capsys: CaptureFixture[str],
) -> None:
    monkeypatch.setenv("GH_TOKEN", "secret-token")
    first_url = issue_list_api_url(
        api_root="https://github.example.com/api/v3",
        owner="octo",
        repo_name="project",
        state="closed",
        since="2026-01-01T00:00:00Z",
    )
    _install_fake_urlopen(
        monkeypatch,
        {first_url: _FakeGitHubResponse([_issue(5, state="closed")])},
    )
    output_dir = tmp_path / "out"

    exit_code = main(
        [
            "github_metadata",
            "--repo",
            "octo/project",
            "--base-url",
            "https://github.example.com/api/v3",
            "--token-env",
            "GH_TOKEN",
            "--output-dir",
            str(output_dir),
            "--state",
            "closed",
            "--since",
            "2026-01-01T00:00:00Z",
            "--dry-run",
        ]
    )

    assert exit_code == 0
    captured = capsys.readouterr()
    assert "web_root: https://github.example.com" in captured.out
    assert "api_root: https://github.example.com/api/v3" in captured.out
    assert "source_url: https://github.example.com/octo/project/issues/5" in captured.out
    assert_dry_run_summary(captured.out, would_write=1, would_skip=0)
    assert not output_dir.exists()
