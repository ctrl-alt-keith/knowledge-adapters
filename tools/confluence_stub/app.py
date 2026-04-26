from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request

DATA_PATH = Path(__file__).parent / "data" / "pages.json"


@dataclass(frozen=True)
class Page:
    id: str
    title: str
    version: int
    last_modified: str
    content: str


app = FastAPI(title="Confluence Stub")


def _load_pages() -> list[Page]:
    raw_pages = json.loads(DATA_PATH.read_text(encoding="utf-8"))
    if not isinstance(raw_pages, list):
        raise ValueError("Stub data must be a JSON list.")

    pages: list[Page] = []
    for raw_page in raw_pages:
        if not isinstance(raw_page, dict):
            raise ValueError("Each stub page must be a JSON object.")

        page_id = raw_page.get("id")
        title = raw_page.get("title")
        version = raw_page.get("version")
        last_modified = raw_page.get("last_modified")
        content = raw_page.get("content")
        if not isinstance(page_id, str) or not page_id:
            raise ValueError("Each stub page must include a non-empty string id.")
        if not isinstance(title, str) or not title:
            raise ValueError(f"Stub page {page_id} must include a non-empty string title.")
        if not isinstance(version, int) or isinstance(version, bool):
            raise ValueError(f"Stub page {page_id} must include an integer version.")
        if not isinstance(last_modified, str) or not last_modified:
            raise ValueError(f"Stub page {page_id} must include a non-empty last_modified.")
        if not isinstance(content, str):
            raise ValueError(f"Stub page {page_id} must include string content.")

        pages.append(
            Page(
                id=page_id,
                title=title,
                version=version,
                last_modified=last_modified,
                content=content,
            )
        )

    return pages


def _find_page(page_id: str) -> Page:
    for page in _load_pages():
        if page.id == page_id:
            return page
    raise HTTPException(status_code=404, detail=f"Page {page_id} not found.")


def _base_url(request: Request) -> str:
    return str(request.base_url).rstrip("/")


def _page_links(request: Request, page_id: str) -> dict[str, str]:
    return {
        "base": _base_url(request),
        "webui": f"/pages/viewpage.action?pageId={page_id}",
    }


def _summary_payload(request: Request, page: Page) -> dict[str, object]:
    return {
        "id": page.id,
        "type": "page",
        "title": page.title,
        "version": {
            "number": page.version,
            "when": page.last_modified,
        },
        "last_modified": page.last_modified,
        "_links": _page_links(request, page.id),
    }


def _detail_payload(
    request: Request,
    page: Page,
    *,
    version: int | None = None,
    last_modified: str | None = None,
) -> dict[str, object]:
    page_version = page.version if version is None else version
    modified_at = page.last_modified if last_modified is None else last_modified
    return {
        "id": page.id,
        "type": "page",
        "title": page.title,
        "version": {
            "number": page_version,
            "when": modified_at,
        },
        "last_modified": modified_at,
        "content": page.content,
        "body": {
            "storage": {
                "value": page.content,
                "representation": "storage",
            }
        },
        "_links": _page_links(request, page.id),
    }


@app.get("/rest/api/content")
def list_pages(
    request: Request,
    start: int = 0,
    limit: int = 100,
) -> dict[str, object]:
    pages = _load_pages()
    sliced_pages = pages[start : start + limit]
    return {
        "results": [_summary_payload(request, page) for page in sliced_pages],
        "start": start,
        "limit": limit,
        "size": len(sliced_pages),
    }


@app.get("/rest/api/content/{page_id}")
def get_page(
    page_id: str,
    request: Request,
    version: int | None = None,
    last_modified: str | None = None,
) -> dict[str, object]:
    page = _find_page(page_id)
    return _detail_payload(
        request,
        page,
        version=version,
        last_modified=last_modified,
    )
