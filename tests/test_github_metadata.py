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
    issue_comments_api_url,
    issue_list_api_url,
    list_repository_issues,
    list_repository_pull_requests,
    pull_request_list_api_url,
    resolve_base_urls,
)
from knowledge_adapters.github_metadata.normalize import (
    EMPTY_BODY_MARKER,
    EMPTY_PULL_REQUEST_BODY_MARKER,
)
from tests.cli_output_assertions import (
    assert_dry_run_summary,
    assert_stale_artifacts,
    assert_write_summary,
)


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


def _pull_request(
    number: int,
    *,
    title: str | None = None,
    body: str | None = "Body",
    state: str = "open",
    author: str | None = "alice",
    updated_at: str | None = None,
) -> dict[str, object]:
    payload: dict[str, object] = {
        "number": number,
        "title": title or f"Pull Request {number}",
        "state": state,
        "created_at": f"2026-04-{number:02d}T00:00:00Z",
        "updated_at": updated_at or f"2026-04-{number:02d}T01:00:00Z",
        "body": body,
    }
    if author is not None:
        payload["user"] = {"login": author}
    return payload


def _issue_comment(
    number: int,
    *,
    body: str | None = "Comment",
    author: str | None = "alice",
    created_at: str | None = None,
    updated_at: str | None = None,
) -> dict[str, object]:
    payload: dict[str, object] = {
        "created_at": created_at or f"2026-04-{number:02d}T02:00:00Z",
        "updated_at": updated_at or f"2026-04-{number:02d}T03:00:00Z",
        "body": body,
    }
    if author is not None:
        payload["user"] = {"login": author}
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
    assert (
        pull_request_list_api_url(
            api_root=github_urls.api_root,
            owner="octo",
            repo_name="project",
            state="open",
        )
        == "https://api.github.com/repos/octo/project/pulls?state=open&per_page=100"
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


def test_github_metadata_pull_requests_paginate_filter_since_and_limit(
    monkeypatch: MonkeyPatch,
) -> None:
    monkeypatch.setenv("GH_TOKEN", "secret-token")
    first_url = pull_request_list_api_url(
        api_root="https://api.github.com",
        owner="octo",
        repo_name="project",
        state="all",
    )
    second_url = "https://api.github.com/repos/octo/project/pulls?state=all&per_page=100&page=2"
    fake_urlopen = _install_fake_urlopen(
        monkeypatch,
        {
            first_url: _FakeGitHubResponse(
                [
                    _pull_request(9, updated_at="2025-12-31T23:59:59Z"),
                    _pull_request(4),
                ],
                headers={"Link": f'<{second_url}>; rel="next"'},
            ),
            second_url: _FakeGitHubResponse([_pull_request(7), _pull_request(2)]),
        },
    )

    pull_requests = list_repository_pull_requests(
        repo="octo/project",
        token_env="GH_TOKEN",
        state="all",
        since="2026-01-01T00:00:00Z",
        max_items=2,
    )

    assert fake_urlopen.calls == [first_url, second_url]
    assert [pull_request.number for pull_request in pull_requests] == [2, 4]
    assert [pull_request.canonical_id for pull_request in pull_requests] == [
        "github_metadata:github.com:octo/project:pull_request:2",
        "github_metadata:github.com:octo/project:pull_request:4",
    ]


def test_github_metadata_issue_comments_paginate_and_sort_deterministically(
    monkeypatch: MonkeyPatch,
) -> None:
    monkeypatch.setenv("GH_TOKEN", "secret-token")
    issues_url = issue_list_api_url(
        api_root="https://api.github.com",
        owner="octo",
        repo_name="project",
        state="open",
        since=None,
    )
    issue_1_comments_url = issue_comments_api_url(
        api_root="https://api.github.com",
        owner="octo",
        repo_name="project",
        issue_number=1,
    )
    issue_1_comments_page_2_url = (
        "https://api.github.com/repos/octo/project/issues/1/comments?per_page=100&page=2"
    )
    issue_2_comments_url = issue_comments_api_url(
        api_root="https://api.github.com",
        owner="octo",
        repo_name="project",
        issue_number=2,
    )
    fake_urlopen = _install_fake_urlopen(
        monkeypatch,
        {
            issues_url: _FakeGitHubResponse([_issue(2), _issue(1)]),
            issue_1_comments_url: _FakeGitHubResponse(
                [
                    _issue_comment(
                        1,
                        body="Second chronologically",
                        created_at="2026-04-01T05:00:00Z",
                        updated_at="2026-04-01T05:30:00Z",
                    )
                ],
                headers={"Link": f'<{issue_1_comments_page_2_url}>; rel="next"'},
            ),
            issue_1_comments_page_2_url: _FakeGitHubResponse(
                [
                    _issue_comment(
                        1,
                        body="First chronologically",
                        author="bob",
                        created_at="2026-04-01T04:00:00Z",
                        updated_at="2026-04-01T04:30:00Z",
                    )
                ]
            ),
            issue_2_comments_url: _FakeGitHubResponse([_issue_comment(2, body=None, author=None)]),
        },
    )

    issues = list_repository_issues(
        repo="octo/project",
        token_env="GH_TOKEN",
        include_issue_comments=True,
    )

    assert fake_urlopen.calls == [
        issues_url,
        issue_1_comments_url,
        issue_1_comments_page_2_url,
        issue_2_comments_url,
    ]
    assert [issue.number for issue in issues] == [1, 2]
    assert [comment.body for comment in issues[0].comments] == [
        "First chronologically",
        "Second chronologically",
    ]
    assert issues[0].comments[0].author == "bob"
    assert issues[1].comments[0].body == ""
    assert issues[1].comments[0].author is None


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
    assert "## Comments" not in issue_2_markdown
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


def test_github_metadata_cli_writes_issue_comments_when_enabled(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
    capsys: CaptureFixture[str],
) -> None:
    monkeypatch.setenv("GH_TOKEN", "secret-token")
    issues_url = issue_list_api_url(
        api_root="https://api.github.com",
        owner="octo",
        repo_name="project",
        state="open",
        since=None,
    )
    issue_2_comments_url = issue_comments_api_url(
        api_root="https://api.github.com",
        owner="octo",
        repo_name="project",
        issue_number=2,
    )
    issue_7_comments_url = issue_comments_api_url(
        api_root="https://api.github.com",
        owner="octo",
        repo_name="project",
        issue_number=7,
    )
    fake_urlopen = _install_fake_urlopen(
        monkeypatch,
        {
            issues_url: _FakeGitHubResponse(
                [
                    _issue(7, title="Follow-up", body="Body for issue 7.\n"),
                    _issue(2, title="Useful bug", body="Bug details.\n"),
                ]
            ),
            issue_2_comments_url: _FakeGitHubResponse(
                [
                    _issue_comment(
                        2,
                        body="Later comment",
                        created_at="2026-04-02T04:00:00Z",
                        updated_at="2026-04-02T05:00:00Z",
                    ),
                    _issue_comment(
                        2,
                        body="Earlier comment",
                        author="bob",
                        created_at="2026-04-02T03:00:00Z",
                        updated_at="2026-04-02T03:30:00Z",
                    ),
                ]
            ),
            issue_7_comments_url: _FakeGitHubResponse([]),
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
            "--include-issue-comments",
        ]
    )

    assert exit_code == 0
    captured = capsys.readouterr()
    assert "include_issue_comments: true" in captured.out
    assert_write_summary(captured.out, wrote=2, skipped=0)
    assert fake_urlopen.calls == [issues_url, issue_2_comments_url, issue_7_comments_url]

    issue_2_markdown = (output_dir / "issues" / "2.md").read_text(encoding="utf-8")
    issue_7_markdown = (output_dir / "issues" / "7.md").read_text(encoding="utf-8")
    assert "## Comments" in issue_2_markdown
    assert "### Comment 1" in issue_2_markdown
    assert "- author: bob" in issue_2_markdown
    assert "Earlier comment" in issue_2_markdown
    assert issue_2_markdown.index("Earlier comment") < issue_2_markdown.index("Later comment")
    assert "## Comments" not in issue_7_markdown


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


def test_github_metadata_cli_writes_pull_request_artifacts_and_manifest(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
    capsys: CaptureFixture[str],
) -> None:
    monkeypatch.setenv("GH_TOKEN", "secret-token")
    first_url = pull_request_list_api_url(
        api_root="https://api.github.com",
        owner="octo",
        repo_name="project",
        state="open",
    )
    _install_fake_urlopen(
        monkeypatch,
        {
            first_url: _FakeGitHubResponse(
                [
                    _pull_request(8, title="Empty PR body", body=None, author=None),
                    _pull_request(4, title="Add API docs", body="Implements docs.\n"),
                ]
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
            "--resource-type",
            "pull_request",
            "--output-dir",
            str(output_dir),
        ]
    )

    assert exit_code == 0
    captured = capsys.readouterr()
    assert "resource_type: pull_request" in captured.out
    assert "pull_requests_planned: 2" in captured.out
    assert_write_summary(captured.out, wrote=2, skipped=0)

    pr_4_path = output_dir / "pull_requests" / "4.md"
    pr_8_path = output_dir / "pull_requests" / "8.md"
    assert pr_4_path.exists()
    assert pr_8_path.exists()
    pr_4_markdown = pr_4_path.read_text(encoding="utf-8")
    pr_8_markdown = pr_8_path.read_text(encoding="utf-8")
    assert "# Pull Request #4: Add API docs" in pr_4_markdown
    assert "Implements docs." in pr_4_markdown
    assert EMPTY_PULL_REQUEST_BODY_MARKER in pr_8_markdown

    manifest_payload = json.loads((output_dir / "manifest.json").read_text(encoding="utf-8"))
    assert isinstance(manifest_payload["generated_at"], str)
    assert manifest_payload["files"] == [
        {
            "canonical_id": "github_metadata:github.com:octo/project:pull_request:4",
            "source_url": "https://github.com/octo/project/pull/4",
            "title": "Add API docs",
            "repo": "octo/project",
            "resource_type": "pull_request",
            "number": 4,
            "state": "open",
            "created_at": "2026-04-04T00:00:00Z",
            "updated_at": "2026-04-04T01:00:00Z",
            "author": "alice",
            "content_hash": hashlib.sha256(pr_4_markdown.encode("utf-8")).hexdigest(),
            "output_path": "pull_requests/4.md",
        },
        {
            "canonical_id": "github_metadata:github.com:octo/project:pull_request:8",
            "source_url": "https://github.com/octo/project/pull/8",
            "title": "Empty PR body",
            "repo": "octo/project",
            "resource_type": "pull_request",
            "number": 8,
            "state": "open",
            "created_at": "2026-04-08T00:00:00Z",
            "updated_at": "2026-04-08T01:00:00Z",
            "author": None,
            "content_hash": hashlib.sha256(pr_8_markdown.encode("utf-8")).hexdigest(),
            "output_path": "pull_requests/8.md",
        },
    ]


def test_github_metadata_pull_request_dry_run_reports_stale_artifacts(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
    capsys: CaptureFixture[str],
) -> None:
    monkeypatch.setenv("GH_TOKEN", "secret-token")
    first_url = pull_request_list_api_url(
        api_root="https://api.github.com",
        owner="octo",
        repo_name="project",
        state="open",
    )
    _install_fake_urlopen(
        monkeypatch,
        {first_url: _FakeGitHubResponse([_pull_request(7, title="Current PR")])},
    )
    output_dir = tmp_path / "out"
    stale_pull_request = output_dir / "pull_requests" / "5.md"
    stale_pull_request.parent.mkdir(parents=True, exist_ok=True)
    stale_pull_request.write_text("legacy artifact\n", encoding="utf-8")
    (output_dir / "manifest.json").write_text(
        json.dumps(
            {
                "generated_at": "2026-04-01T00:00:00Z",
                "files": [
                    {
                        "canonical_id": "github_metadata:github.com:octo/project:pull_request:5",
                        "source_url": "https://github.com/octo/project/pull/5",
                        "title": "Legacy PR",
                        "repo": "octo/project",
                        "resource_type": "pull_request",
                        "number": 5,
                        "state": "open",
                        "created_at": "2026-04-05T00:00:00Z",
                        "updated_at": "2026-04-05T01:00:00Z",
                        "author": "alice",
                        "content_hash": "legacy",
                        "output_path": "pull_requests/5.md",
                    }
                ],
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )

    exit_code = main(
        [
            "github_metadata",
            "--repo",
            "octo/project",
            "--token-env",
            "GH_TOKEN",
            "--resource-type",
            "pull_request",
            "--output-dir",
            str(output_dir),
            "--dry-run",
        ]
    )

    assert exit_code == 0
    captured = capsys.readouterr()
    assert_dry_run_summary(captured.out, would_write=1, would_skip=0)
    assert_stale_artifacts(captured.out, count=1, artifact_paths=[stale_pull_request])
    assert stale_pull_request.read_text(encoding="utf-8") == "legacy artifact\n"
    assert not (output_dir / "pull_requests" / "7.md").exists()
