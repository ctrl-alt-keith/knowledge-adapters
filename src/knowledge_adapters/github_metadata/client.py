"""REST client and payload mapping for the github_metadata adapter."""

from __future__ import annotations

import json
from dataclasses import dataclass, replace
from datetime import datetime
from urllib import parse, request
from urllib.error import HTTPError, URLError

from knowledge_adapters.failures import AdapterFailureClass, AdapterFailureClassification
from knowledge_adapters.github_metadata.auth import (
    RequestAuth,
    build_request_auth,
)
from knowledge_adapters.github_metadata.auth import (
    resolve_token as resolve_token,
)

SUPPORTED_ISSUE_STATES = frozenset({"open", "closed", "all"})
DEFAULT_GITHUB_WEB_ROOT = "https://github.com"
DEFAULT_GITHUB_API_ROOT = "https://api.github.com"
_PAGE_SIZE = 100


@dataclass(frozen=True)
class GitHubMetadataBaseUrls:
    """Resolved GitHub web/API roots for one run."""

    web_root: str
    api_root: str
    host: str


@dataclass(frozen=True)
class GitHubIssue:
    """One normalized GitHub issue record."""

    repo: str
    host: str
    number: int
    title: str
    state: str
    author: str | None
    created_at: str
    updated_at: str
    source_url: str
    body: str
    comments: tuple[GitHubIssueComment, ...] = ()

    @property
    def canonical_id(self) -> str:
        """Return the issue canonical ID."""
        return f"github_metadata:{self.host}:{self.repo}:issue:{self.number}"


@dataclass(frozen=True)
class GitHubIssueComment:
    """One normalized GitHub issue comment record."""

    author: str | None
    created_at: str
    updated_at: str
    body: str


@dataclass(frozen=True)
class GitHubPullRequest:
    """One normalized GitHub pull request record."""

    repo: str
    host: str
    number: int
    title: str
    state: str
    author: str | None
    created_at: str
    updated_at: str
    source_url: str
    body: str

    @property
    def canonical_id(self) -> str:
        """Return the pull request canonical ID."""
        return f"github_metadata:{self.host}:{self.repo}:pull_request:{self.number}"


@dataclass(frozen=True)
class GitHubRelease:
    """One normalized GitHub release record."""

    repo: str
    host: str
    release_id: int
    tag_name: str
    title: str
    author: str | None
    created_at: str
    published_at: str | None
    source_url: str
    body: str
    draft: bool
    prerelease: bool

    @property
    def canonical_id(self) -> str:
        """Return the release canonical ID."""
        return f"github_metadata:{self.host}:{self.repo}:release:{self.release_id}"


class GitHubMetadataRequestError(RuntimeError):
    """Stable request failure for github_metadata API reads."""

    def __init__(
        self,
        message: str,
        *,
        classification: AdapterFailureClassification | None = None,
    ) -> None:
        super().__init__(message)
        self.classification = classification


def resolve_base_urls(base_url: str | None = None) -> GitHubMetadataBaseUrls:
    """Resolve GitHub.com or GHE web/API roots from a configured base URL."""
    raw_base_url = (base_url or DEFAULT_GITHUB_WEB_ROOT).strip().rstrip("/")
    if not raw_base_url:
        raise ValueError("base_url must be a non-empty URL when provided.")

    parsed = parse.urlparse(raw_base_url)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ValueError("base_url must be an absolute http(s) URL.")
    if parsed.query or parsed.fragment:
        raise ValueError("base_url must not include query strings or fragments.")

    normalized = parse.urlunparse(
        (parsed.scheme, parsed.netloc, parsed.path.rstrip("/"), "", "", "")
    )
    path = parsed.path.rstrip("/")

    if parsed.netloc == "github.com" and path in {"", "/"}:
        web_root = DEFAULT_GITHUB_WEB_ROOT
        api_root = DEFAULT_GITHUB_API_ROOT
    elif parsed.netloc == "api.github.com" and path in {"", "/"}:
        web_root = DEFAULT_GITHUB_WEB_ROOT
        api_root = DEFAULT_GITHUB_API_ROOT
    elif path.endswith("/api/v3"):
        api_root = normalized
        web_path = path.removesuffix("/api/v3").rstrip("/")
        web_root = parse.urlunparse((parsed.scheme, parsed.netloc, web_path, "", "", ""))
    else:
        web_root = normalized
        api_root = f"{normalized}/api/v3"

    host = parse.urlparse(web_root).netloc
    if not host:
        raise ValueError("base_url must resolve to a web host.")

    return GitHubMetadataBaseUrls(web_root=web_root, api_root=api_root, host=host)


def validate_repo(repo: str) -> tuple[str, str, str]:
    """Validate and split an owner/name repository input."""
    normalized_repo = repo.strip()
    parts = normalized_repo.split("/")
    if (
        len(parts) != 2
        or not parts[0]
        or not parts[1]
        or any(part.strip() != part for part in parts)
    ):
        raise ValueError("repo must use owner/name form.")
    return parts[0], parts[1], normalized_repo


def validate_state(state: str) -> str:
    """Validate the configured issue state filter."""
    normalized_state = state.strip()
    if normalized_state not in SUPPORTED_ISSUE_STATES:
        supported = ", ".join(sorted(SUPPORTED_ISSUE_STATES))
        raise ValueError(f"state must be one of: {supported}.")
    return normalized_state


def validate_since(since: str | None) -> str | None:
    """Validate an optional ISO 8601 timestamp without reformatting it."""
    if since is None:
        return None
    normalized_since = since.strip()
    if not normalized_since:
        raise ValueError("since must be a non-empty ISO 8601 timestamp when provided.")
    try:
        datetime.fromisoformat(normalized_since.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError("since must be an ISO 8601 timestamp.") from exc
    return normalized_since


def validate_max_items(max_items: int | None) -> int | None:
    """Validate an optional positive max_items limit."""
    if max_items is None:
        return None
    if isinstance(max_items, bool) or max_items < 1:
        raise ValueError("max_items must be a positive integer.")
    return max_items


def issue_list_api_url(
    *,
    api_root: str,
    owner: str,
    repo_name: str,
    state: str,
    since: str | None,
) -> str:
    """Build the first repository issues API URL."""
    encoded_owner = parse.quote(owner, safe="")
    encoded_repo = parse.quote(repo_name, safe="")
    query: dict[str, str | int] = {
        "state": state,
        "per_page": _PAGE_SIZE,
    }
    if since is not None:
        query["since"] = since
    return (
        f"{api_root.rstrip('/')}/repos/{encoded_owner}/{encoded_repo}/issues?"
        f"{parse.urlencode(query)}"
    )


def pull_request_list_api_url(
    *,
    api_root: str,
    owner: str,
    repo_name: str,
    state: str,
) -> str:
    """Build the first repository pull requests API URL."""
    encoded_owner = parse.quote(owner, safe="")
    encoded_repo = parse.quote(repo_name, safe="")
    query: dict[str, str | int] = {
        "state": state,
        "per_page": _PAGE_SIZE,
    }
    return (
        f"{api_root.rstrip('/')}/repos/{encoded_owner}/{encoded_repo}/pulls?"
        f"{parse.urlencode(query)}"
    )


def release_list_api_url(
    *,
    api_root: str,
    owner: str,
    repo_name: str,
) -> str:
    """Build the first repository releases API URL."""
    encoded_owner = parse.quote(owner, safe="")
    encoded_repo = parse.quote(repo_name, safe="")
    query = parse.urlencode({"per_page": _PAGE_SIZE})
    return f"{api_root.rstrip('/')}/repos/{encoded_owner}/{encoded_repo}/releases?{query}"


def list_repository_issues(
    *,
    repo: str,
    token_env: str,
    base_url: str | None = None,
    state: str = "open",
    since: str | None = None,
    max_items: int | None = None,
    include_issue_comments: bool = False,
) -> tuple[GitHubIssue, ...]:
    """List normalized issues for one repository through the REST API."""
    owner, repo_name, normalized_repo = validate_repo(repo)
    normalized_state = validate_state(state)
    normalized_since = validate_since(since)
    normalized_max_items = validate_max_items(max_items)
    base_urls = resolve_base_urls(base_url)
    request_auth = build_request_auth(token_env)

    next_url: str | None = issue_list_api_url(
        api_root=base_urls.api_root,
        owner=owner,
        repo_name=repo_name,
        state=normalized_state,
        since=normalized_since,
    )
    seen_urls: set[str] = set()
    issues: list[GitHubIssue] = []
    while next_url is not None:
        if next_url in seen_urls:
            raise ValueError("Response error: repeated GitHub issues pagination URL.")
        seen_urls.add(next_url)

        payload, link_header = _request_json_list(
            next_url,
            request_auth=request_auth,
            repo=normalized_repo,
            api_root=base_urls.api_root,
        )
        for item in payload:
            if "pull_request" in item:
                continue
            issues.append(
                _map_issue(
                    item,
                    repo=normalized_repo,
                    owner=owner,
                    repo_name=repo_name,
                    base_urls=base_urls,
                )
            )
        next_url = _next_link_url(link_header)

    ordered_issues = tuple(sorted(issues, key=lambda issue: issue.number))
    selected_issues = (
        ordered_issues if normalized_max_items is None else ordered_issues[:normalized_max_items]
    )
    if not include_issue_comments:
        return selected_issues

    return tuple(
        replace(
            issue,
            comments=_list_issue_comments(
                issue_number=issue.number,
                owner=owner,
                repo_name=repo_name,
                repo=normalized_repo,
                api_root=base_urls.api_root,
                request_auth=request_auth,
            ),
        )
        for issue in selected_issues
    )


def list_repository_pull_requests(
    *,
    repo: str,
    token_env: str,
    base_url: str | None = None,
    state: str = "open",
    since: str | None = None,
    max_items: int | None = None,
) -> tuple[GitHubPullRequest, ...]:
    """List normalized pull requests for one repository through the REST API."""
    owner, repo_name, normalized_repo = validate_repo(repo)
    normalized_state = validate_state(state)
    normalized_since = validate_since(since)
    normalized_max_items = validate_max_items(max_items)
    base_urls = resolve_base_urls(base_url)
    request_auth = build_request_auth(token_env)

    next_url: str | None = pull_request_list_api_url(
        api_root=base_urls.api_root,
        owner=owner,
        repo_name=repo_name,
        state=normalized_state,
    )
    seen_urls: set[str] = set()
    pull_requests: list[GitHubPullRequest] = []
    while next_url is not None:
        if next_url in seen_urls:
            raise ValueError("Response error: repeated GitHub pull requests pagination URL.")
        seen_urls.add(next_url)

        payload, link_header = _request_json_list(
            next_url,
            request_auth=request_auth,
            repo=normalized_repo,
            api_root=base_urls.api_root,
        )
        for item in payload:
            pull_requests.append(
                _map_pull_request(
                    item,
                    repo=normalized_repo,
                    owner=owner,
                    repo_name=repo_name,
                    base_urls=base_urls,
                )
            )
        next_url = _next_link_url(link_header)

    ordered_pull_requests = tuple(
        sorted(pull_requests, key=lambda pull_request: pull_request.number)
    )
    if normalized_since is not None:
        since_cutoff = _parse_timestamp(normalized_since)
        ordered_pull_requests = tuple(
            pull_request
            for pull_request in ordered_pull_requests
            if _parse_timestamp(pull_request.updated_at) >= since_cutoff
        )
    if normalized_max_items is None:
        return ordered_pull_requests
    return ordered_pull_requests[:normalized_max_items]


def list_repository_releases(
    *,
    repo: str,
    token_env: str,
    base_url: str | None = None,
    since: str | None = None,
    max_items: int | None = None,
) -> tuple[GitHubRelease, ...]:
    """List normalized releases for one repository through the REST API."""
    owner, repo_name, normalized_repo = validate_repo(repo)
    normalized_since = validate_since(since)
    normalized_max_items = validate_max_items(max_items)
    base_urls = resolve_base_urls(base_url)
    request_auth = build_request_auth(token_env)

    next_url: str | None = release_list_api_url(
        api_root=base_urls.api_root,
        owner=owner,
        repo_name=repo_name,
    )
    seen_urls: set[str] = set()
    releases: list[GitHubRelease] = []
    while next_url is not None:
        if next_url in seen_urls:
            raise ValueError("Response error: repeated GitHub releases pagination URL.")
        seen_urls.add(next_url)

        payload, link_header = _request_json_list(
            next_url,
            request_auth=request_auth,
            repo=normalized_repo,
            api_root=base_urls.api_root,
        )
        for item in payload:
            releases.append(
                _map_release(
                    item,
                    repo=normalized_repo,
                    owner=owner,
                    repo_name=repo_name,
                    base_urls=base_urls,
                )
            )
        next_url = _next_link_url(link_header)

    ordered_releases = tuple(
        sorted(
            releases,
            key=lambda release: (
                "" if release.published_at is None else release.published_at,
                release.tag_name,
                release.release_id,
            ),
        )
    )
    if normalized_since is not None:
        since_cutoff = _parse_timestamp(normalized_since)
        ordered_releases = tuple(
            release
            for release in ordered_releases
            if release.published_at is not None
            and _parse_timestamp(release.published_at) >= since_cutoff
        )
    if normalized_max_items is None:
        return ordered_releases
    return ordered_releases[:normalized_max_items]


def _map_issue(
    payload: dict[str, object],
    *,
    repo: str,
    owner: str,
    repo_name: str,
    base_urls: GitHubMetadataBaseUrls,
) -> GitHubIssue:
    number = payload.get("number")
    if not isinstance(number, int) or isinstance(number, bool):
        raise ValueError("Response error: invalid issue number.")

    title = _require_string(payload, "title")
    state = _require_string(payload, "state")
    created_at = _require_string(payload, "created_at")
    updated_at = _require_string(payload, "updated_at")
    body_value = payload.get("body")
    if body_value is None:
        body = ""
    elif isinstance(body_value, str):
        body = body_value
    else:
        raise ValueError("Response error: invalid issue body.")

    user = payload.get("user")
    author: str | None = None
    if isinstance(user, dict):
        login = user.get("login")
        if isinstance(login, str) and login:
            author = login

    encoded_owner = parse.quote(owner, safe="")
    encoded_repo = parse.quote(repo_name, safe="")
    source_url = f"{base_urls.web_root}/{encoded_owner}/{encoded_repo}/issues/{number}"
    return GitHubIssue(
        repo=repo,
        host=base_urls.host,
        number=number,
        title=title,
        state=state,
        author=author,
        created_at=created_at,
        updated_at=updated_at,
        source_url=source_url,
        body=body,
    )


def _map_pull_request(
    payload: dict[str, object],
    *,
    repo: str,
    owner: str,
    repo_name: str,
    base_urls: GitHubMetadataBaseUrls,
) -> GitHubPullRequest:
    number = payload.get("number")
    if not isinstance(number, int) or isinstance(number, bool):
        raise ValueError("Response error: invalid pull request number.")

    title = _require_string(payload, "title")
    state = _require_string(payload, "state")
    created_at = _require_string(payload, "created_at")
    updated_at = _require_string(payload, "updated_at")
    body_value = payload.get("body")
    if body_value is None:
        body = ""
    elif isinstance(body_value, str):
        body = body_value
    else:
        raise ValueError("Response error: invalid pull request body.")

    user = payload.get("user")
    author: str | None = None
    if isinstance(user, dict):
        login = user.get("login")
        if isinstance(login, str) and login:
            author = login

    encoded_owner = parse.quote(owner, safe="")
    encoded_repo = parse.quote(repo_name, safe="")
    source_url = f"{base_urls.web_root}/{encoded_owner}/{encoded_repo}/pull/{number}"
    return GitHubPullRequest(
        repo=repo,
        host=base_urls.host,
        number=number,
        title=title,
        state=state,
        author=author,
        created_at=created_at,
        updated_at=updated_at,
        source_url=source_url,
        body=body,
    )


def _map_release(
    payload: dict[str, object],
    *,
    repo: str,
    owner: str,
    repo_name: str,
    base_urls: GitHubMetadataBaseUrls,
) -> GitHubRelease:
    release_id = payload.get("id")
    if not isinstance(release_id, int) or isinstance(release_id, bool):
        raise ValueError("Response error: invalid release id.")

    tag_name = _require_string(payload, "tag_name")
    created_at = _require_string(payload, "created_at")
    published_at = _optional_string(payload, "published_at")
    title = _optional_string(payload, "name") or ""
    draft = _require_bool(payload, "draft")
    prerelease = _require_bool(payload, "prerelease")
    body_value = payload.get("body")
    if body_value is None:
        body = ""
    elif isinstance(body_value, str):
        body = body_value
    else:
        raise ValueError("Response error: invalid release body.")

    user = payload.get("user")
    author: str | None = None
    if isinstance(user, dict):
        login = user.get("login")
        if isinstance(login, str) and login:
            author = login

    encoded_owner = parse.quote(owner, safe="")
    encoded_repo = parse.quote(repo_name, safe="")
    encoded_tag = parse.quote(tag_name, safe="")
    source_url = f"{base_urls.web_root}/{encoded_owner}/{encoded_repo}/releases/tag/{encoded_tag}"
    return GitHubRelease(
        repo=repo,
        host=base_urls.host,
        release_id=release_id,
        tag_name=tag_name,
        title=title,
        author=author,
        created_at=created_at,
        published_at=published_at,
        source_url=source_url,
        body=body,
        draft=draft,
        prerelease=prerelease,
    )


def issue_comments_api_url(
    *,
    api_root: str,
    owner: str,
    repo_name: str,
    issue_number: int,
) -> str:
    """Build the first issue comments API URL."""
    encoded_owner = parse.quote(owner, safe="")
    encoded_repo = parse.quote(repo_name, safe="")
    query = parse.urlencode({"per_page": _PAGE_SIZE})
    return (
        f"{api_root.rstrip('/')}/repos/{encoded_owner}/{encoded_repo}/issues/"
        f"{issue_number}/comments?{query}"
    )


def _list_issue_comments(
    *,
    issue_number: int,
    owner: str,
    repo_name: str,
    repo: str,
    api_root: str,
    request_auth: RequestAuth,
) -> tuple[GitHubIssueComment, ...]:
    next_url: str | None = issue_comments_api_url(
        api_root=api_root,
        owner=owner,
        repo_name=repo_name,
        issue_number=issue_number,
    )
    seen_urls: set[str] = set()
    comments: list[GitHubIssueComment] = []
    while next_url is not None:
        if next_url in seen_urls:
            raise ValueError("Response error: repeated GitHub issue comments pagination URL.")
        seen_urls.add(next_url)

        payload, link_header = _request_json_list(
            next_url,
            request_auth=request_auth,
            repo=repo,
            api_root=api_root,
        )
        for item in payload:
            comments.append(_map_issue_comment(item))
        next_url = _next_link_url(link_header)

    return tuple(
        sorted(
            comments,
            key=lambda comment: (
                comment.created_at,
                comment.updated_at,
                "" if comment.author is None else comment.author,
                comment.body,
            ),
        )
    )


def _map_issue_comment(payload: dict[str, object]) -> GitHubIssueComment:
    created_at = _require_string(payload, "created_at")
    updated_at = _require_string(payload, "updated_at")
    body_value = payload.get("body")
    if body_value is None:
        body = ""
    elif isinstance(body_value, str):
        body = body_value
    else:
        raise ValueError("Response error: invalid issue comment body.")

    user = payload.get("user")
    author: str | None = None
    if isinstance(user, dict):
        login = user.get("login")
        if isinstance(login, str) and login:
            author = login

    return GitHubIssueComment(
        author=author,
        created_at=created_at,
        updated_at=updated_at,
        body=body,
    )


def _require_string(payload: dict[str, object], key: str) -> str:
    value = payload.get(key)
    if not isinstance(value, str):
        raise ValueError(f"Response error: missing or invalid {key}.")
    return value


def _optional_string(payload: dict[str, object], key: str) -> str | None:
    value = payload.get(key)
    if value is None:
        return None
    if not isinstance(value, str):
        raise ValueError(f"Response error: missing or invalid {key}.")
    return value


def _require_bool(payload: dict[str, object], key: str) -> bool:
    value = payload.get(key)
    if not isinstance(value, bool):
        raise ValueError(f"Response error: missing or invalid {key}.")
    return value


def _request_json_list(
    api_url: str,
    *,
    request_auth: RequestAuth,
    repo: str,
    api_root: str,
) -> tuple[list[dict[str, object]], str | None]:
    api_request = request.Request(
        api_url,
        headers=dict(request_auth.headers),
    )
    try:
        with request.urlopen(api_request, timeout=30) as response:
            raw_payload = json.loads(response.read().decode("utf-8"))
            link_header = response.headers.get("Link")
    except HTTPError as exc:
        raise GitHubMetadataRequestError(
            _request_failure_message(
                exc,
                repo=repo,
                api_root=api_root,
                token_env=request_auth.token_env,
            ),
            classification=_request_failure_classification(exc),
        ) from exc
    except URLError as exc:
        raise GitHubMetadataRequestError(
            f"GitHub request failed while reading {repo} from {api_root}: {exc.reason}.",
            classification=AdapterFailureClassification(AdapterFailureClass.EXPECTED_RETRYABLE),
        ) from exc
    except json.JSONDecodeError as exc:
        raise ValueError("Response error: invalid JSON payload.") from exc

    if not isinstance(raw_payload, list):
        raise ValueError("Response error: expected a list of GitHub resources.")

    payload: list[dict[str, object]] = []
    for item in raw_payload:
        if not isinstance(item, dict):
            raise ValueError("Response error: invalid GitHub resource payload.")
        payload.append(item)
    return payload, link_header


def _request_failure_message(
    exc: HTTPError,
    *,
    repo: str,
    api_root: str,
    token_env: str,
) -> str:
    rate_limit_hint = _rate_limit_hint(exc)
    if rate_limit_hint is not None:
        return f"GitHub API rate limit exceeded while reading {repo}: {rate_limit_hint}."
    if exc.code == 401:
        return f"GitHub auth failed while reading {repo} using token_env {token_env!r}."
    if exc.code == 403:
        return f"GitHub authorization failed while reading {repo} using token_env {token_env!r}."
    if exc.code == 404:
        return f"GitHub repository not found or inaccessible: {repo} at {api_root}."
    if 500 <= exc.code <= 599:
        return f"GitHub request failed (status {exc.code}) while reading {repo} from {api_root}."
    return f"GitHub request failed (status {exc.code}) while reading {repo} from {api_root}."


def _request_failure_classification(exc: HTTPError) -> AdapterFailureClassification:
    retry_after = exc.headers.get("Retry-After") if exc.headers is not None else None
    if _rate_limit_hint(exc) is not None:
        return AdapterFailureClassification(
            AdapterFailureClass.EXPECTED_RETRYABLE,
            provider_status_code=exc.code,
            retry_after=retry_after,
        )
    if exc.code in {401, 403}:
        return AdapterFailureClassification(
            AdapterFailureClass.AUTH,
            provider_status_code=exc.code,
        )
    if exc.code == 404:
        return AdapterFailureClassification(
            AdapterFailureClass.PERMANENT,
            provider_status_code=exc.code,
        )
    if 500 <= exc.code <= 599:
        return AdapterFailureClassification(
            AdapterFailureClass.PROVIDER,
            provider_status_code=exc.code,
            retry_after=retry_after,
        )
    return AdapterFailureClassification(
        AdapterFailureClass.PERMANENT,
        provider_status_code=exc.code,
    )


def _rate_limit_hint(exc: HTTPError) -> str | None:
    retry_after = exc.headers.get("Retry-After") if exc.headers is not None else None
    if retry_after:
        return f"retry after {retry_after} second(s)"

    remaining = exc.headers.get("X-RateLimit-Remaining") if exc.headers is not None else None
    if remaining != "0" and exc.code != 429:
        return None

    reset = exc.headers.get("X-RateLimit-Reset") if exc.headers is not None else None
    if reset:
        try:
            reset_time = datetime.fromtimestamp(int(reset)).isoformat()
        except ValueError:
            reset_time = reset
        return f"reset at {reset_time}"
    return "no retry time provided"


def _next_link_url(link_header: str | None) -> str | None:
    if not link_header:
        return None
    for raw_link in link_header.split(","):
        link_url, separator, link_params = raw_link.strip().partition(";")
        if not separator:
            continue
        if 'rel="next"' not in link_params:
            continue
        if link_url.startswith("<") and link_url.endswith(">"):
            return link_url[1:-1]
    return None


def _parse_timestamp(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))
