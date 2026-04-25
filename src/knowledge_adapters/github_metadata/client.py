"""REST client and payload mapping for the github_metadata adapter."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from datetime import datetime
from urllib import parse, request
from urllib.error import HTTPError, URLError

SUPPORTED_ISSUE_STATES = frozenset({"open", "closed", "all"})
DEFAULT_GITHUB_WEB_ROOT = "https://github.com"
DEFAULT_GITHUB_API_ROOT = "https://api.github.com"
GITHUB_API_VERSION = "2022-11-28"
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

    @property
    def canonical_id(self) -> str:
        """Return the issue canonical ID."""
        return f"github_metadata:{self.host}:{self.repo}:issue:{self.number}"


class GitHubMetadataRequestError(RuntimeError):
    """Stable request failure for github_metadata API reads."""


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


def resolve_token(token_env: str) -> tuple[str, str]:
    """Resolve the GitHub token from an environment variable name."""
    normalized_token_env = token_env.strip()
    if not normalized_token_env:
        raise ValueError("token_env must name a non-empty environment variable.")

    token = os.getenv(normalized_token_env)
    if token is None or not token.strip():
        raise ValueError(
            f"token_env {normalized_token_env!r} is not set or contains an empty value."
        )
    return normalized_token_env, token.strip()


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


def list_repository_issues(
    *,
    repo: str,
    token_env: str,
    base_url: str | None = None,
    state: str = "open",
    since: str | None = None,
    max_items: int | None = None,
) -> tuple[GitHubIssue, ...]:
    """List normalized issues for one repository through the REST API."""
    owner, repo_name, normalized_repo = validate_repo(repo)
    normalized_state = validate_state(state)
    normalized_since = validate_since(since)
    normalized_max_items = validate_max_items(max_items)
    base_urls = resolve_base_urls(base_url)
    token_env_name, token = resolve_token(token_env)

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
            token=token,
            token_env=token_env_name,
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
    if normalized_max_items is None:
        return ordered_issues
    return ordered_issues[:normalized_max_items]


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


def _require_string(payload: dict[str, object], key: str) -> str:
    value = payload.get(key)
    if not isinstance(value, str):
        raise ValueError(f"Response error: missing or invalid {key}.")
    return value


def _request_json_list(
    api_url: str,
    *,
    token: str,
    token_env: str,
    repo: str,
    api_root: str,
) -> tuple[list[dict[str, object]], str | None]:
    api_request = request.Request(
        api_url,
        headers={
            "Accept": "application/vnd.github+json",
            "Authorization": f"Bearer {token}",
            "User-Agent": "knowledge-adapters-github-metadata",
            "X-GitHub-Api-Version": GITHUB_API_VERSION,
        },
    )
    try:
        with request.urlopen(api_request, timeout=30) as response:
            raw_payload = json.loads(response.read().decode("utf-8"))
            link_header = response.headers.get("Link")
    except HTTPError as exc:
        raise GitHubMetadataRequestError(
            _request_failure_message(exc, repo=repo, api_root=api_root, token_env=token_env)
        ) from exc
    except URLError as exc:
        raise GitHubMetadataRequestError(
            f"GitHub request failed while reading {repo} from {api_root}: {exc.reason}."
        ) from exc
    except json.JSONDecodeError as exc:
        raise ValueError("Response error: invalid JSON payload.") from exc

    if not isinstance(raw_payload, list):
        raise ValueError("Response error: expected a list of GitHub issues.")

    payload: list[dict[str, object]] = []
    for item in raw_payload:
        if not isinstance(item, dict):
            raise ValueError("Response error: invalid issue payload.")
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


def _rate_limit_hint(exc: HTTPError) -> str | None:
    retry_after = exc.headers.get("Retry-After") if exc.headers is not None else None
    if retry_after:
        return f"retry after {retry_after} second(s)"

    remaining = (
        exc.headers.get("X-RateLimit-Remaining") if exc.headers is not None else None
    )
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
