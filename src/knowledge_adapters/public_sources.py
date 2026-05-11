"""Shared helpers for public URL source adapters."""

from __future__ import annotations

import hashlib
import ipaddress
import re
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import Request, urlopen

DEFAULT_USER_AGENT = "knowledge-adapters/0.8 public-source-ingestion"
DEFAULT_FETCH_TIMEOUT_SECONDS = 30


@dataclass(frozen=True)
class FetchedPublicResource:
    """One fetched public URL response held in memory."""

    url: str
    final_url: str
    content: bytes
    content_type: str
    content_charset: str | None
    retrieved_at: str


def fetch_public_url(
    url: str,
    *,
    accepted_content_types: tuple[str, ...],
    timeout_seconds: int = DEFAULT_FETCH_TIMEOUT_SECONDS,
    max_bytes: int,
) -> FetchedPublicResource:
    """Fetch one public HTTP(S) URL into memory."""
    validate_public_http_url(url)
    request = Request(
        url,
        headers={
            "Accept": ", ".join(accepted_content_types) if accepted_content_types else "*/*",
            "User-Agent": DEFAULT_USER_AGENT,
        },
    )
    try:
        with urlopen(request, timeout=timeout_seconds) as response:
            final_url = response.geturl()
            validate_public_http_url(final_url)
            headers = response.headers
            content_type = headers.get_content_type()
            content_charset = headers.get_content_charset()
            _validate_content_type(content_type, accepted_content_types)
            content_length = headers.get("Content-Length")
            if content_length is not None and int(content_length) > max_bytes:
                raise ValueError(
                    f"Response is too large: {content_length} bytes exceeds "
                    f"{max_bytes} byte limit."
                )
            content = response.read(max_bytes + 1)
    except HTTPError as exc:
        raise ValueError(f"HTTP request failed for {url}: {exc.code} {exc.reason}.") from exc
    except URLError as exc:
        raise ValueError(f"Could not fetch {url}: {exc.reason}.") from exc
    except TimeoutError as exc:
        raise ValueError(f"Timed out fetching {url}.") from exc
    except OSError as exc:
        raise ValueError(f"Could not fetch {url}: {exc}.") from exc

    if len(content) > max_bytes:
        raise ValueError(f"Response is too large: exceeds {max_bytes} byte limit.")

    return FetchedPublicResource(
        url=url,
        final_url=final_url,
        content=content,
        content_type=content_type,
        content_charset=content_charset,
        retrieved_at=datetime.now(UTC).isoformat().replace("+00:00", "Z"),
    )


def validate_public_http_url(url: str) -> None:
    """Validate that a source URL stays on the public HTTP(S) surface."""
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"}:
        raise ValueError("URL must use http or https.")
    if not parsed.netloc:
        raise ValueError("URL must include a host.")
    if parsed.username or parsed.password:
        raise ValueError("URL must not include embedded credentials.")
    try:
        hostname = parsed.hostname
    except ValueError as exc:
        raise ValueError("URL host is invalid.") from exc
    if hostname is None or not hostname.strip():
        raise ValueError("URL must include a host.")

    _validate_public_hostname(hostname)


def _validate_public_hostname(hostname: str) -> None:
    normalized_hostname = hostname.rstrip(".").lower()
    if normalized_hostname == "localhost":
        raise ValueError("URL host must not be localhost.")
    if normalized_hostname.endswith(".local"):
        raise ValueError("URL host must not be a .local hostname.")

    try:
        address = ipaddress.ip_address(normalized_hostname)
    except ValueError:
        return

    if address.is_loopback:
        raise ValueError("URL host must not be a loopback IP address.")
    if address.is_link_local:
        raise ValueError("URL host must not be a link-local IP address.")
    if address.is_multicast:
        raise ValueError("URL host must not be a multicast IP address.")
    if address.is_unspecified:
        raise ValueError("URL host must not be an unspecified IP address.")
    if address.is_reserved:
        raise ValueError("URL host must not be a reserved IP address.")
    if address.is_private:
        raise ValueError("URL host must not be a private IP address.")


def output_name_for_url(url: str) -> str:
    """Build a deterministic, collision-resistant markdown filename stem."""
    parsed = urlparse(url)
    path_name = Path(parsed.path).name
    if path_name:
        stem = Path(path_name).stem or path_name
    else:
        stem = parsed.netloc
    slug = re.sub(r"[^A-Za-z0-9._-]+", "-", stem).strip("-._").lower()
    if not slug:
        slug = "public-source"
    digest = hashlib.sha256(url.encode("utf-8")).hexdigest()[:12]
    return f"{slug}-{digest}"


def decode_text_response(content: bytes, charset: str | None) -> str:
    """Decode an HTTP text response using declared charset with UTF-8 fallback."""
    charset = charset or "utf-8"
    try:
        return content.decode(charset)
    except (LookupError, UnicodeDecodeError):
        return content.decode("utf-8", errors="replace")


def _validate_content_type(content_type: str, accepted_content_types: tuple[str, ...]) -> None:
    if not accepted_content_types:
        return
    if content_type in accepted_content_types:
        return
    accepted = ", ".join(accepted_content_types)
    raise ValueError(f"Unsupported content type {content_type!r}; expected one of: {accepted}.")
