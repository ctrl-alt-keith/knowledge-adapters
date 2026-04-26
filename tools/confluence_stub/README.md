# Confluence Stub

Small local HTTP stub for exercising Confluence adapter behavior without hitting a real Confluence instance. Edit [`data/pages.json`](./data/pages.json) to change the base responses.

Run it locally:

```bash
cd tools/confluence_stub
uvicorn app:app --reload --port 8000
```

Example requests:

```bash
curl http://127.0.0.1:8000/rest/api/content
curl http://127.0.0.1:8000/rest/api/content/12345
curl "http://127.0.0.1:8000/rest/api/content/12345?version=2"
curl "http://127.0.0.1:8000/rest/api/content/12345?last_modified=2026-04-21T00:00:00Z"
```
