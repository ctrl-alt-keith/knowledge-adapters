from __future__ import annotations

import socket
import subprocess
import sys
import time
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path
from urllib import request
from urllib.error import HTTPError, URLError

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
STUB_DIR = REPO_ROOT / "tools" / "confluence_stub"


@dataclass(frozen=True)
class ConfluenceStubServer:
    base_url: str
    log_path: Path


def _find_available_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def _read_log_excerpt(log_path: Path) -> str:
    if not log_path.exists():
        return "(no stub log output)"

    log_text = log_path.read_text(encoding="utf-8").strip()
    if not log_text:
        return "(stub produced no log output)"
    return log_text


def _wait_for_stub_ready(
    base_url: str,
    process: subprocess.Popen[str],
    *,
    log_path: Path,
    timeout_seconds: float = 10.0,
) -> None:
    deadline = time.monotonic() + timeout_seconds
    readiness_url = f"{base_url}/rest/api/content"

    while time.monotonic() < deadline:
        if process.poll() is not None:
            raise RuntimeError(
                "Confluence stub exited before becoming ready.\n"
                f"Stub log:\n{_read_log_excerpt(log_path)}"
            )

        try:
            with request.urlopen(readiness_url, timeout=0.2) as response:
                if response.status == 200:
                    return
        except (HTTPError, URLError):
            pass

        time.sleep(0.1)

    raise RuntimeError(
        "Timed out waiting for the Confluence stub to become ready.\n"
        f"Stub log:\n{_read_log_excerpt(log_path)}"
    )


@pytest.fixture
def confluence_stub_server(
    tmp_path_factory: pytest.TempPathFactory,
) -> Iterator[ConfluenceStubServer]:
    log_dir = tmp_path_factory.mktemp("confluence-stub")
    log_path = log_dir / "uvicorn.log"
    port = _find_available_port()

    with log_path.open("w", encoding="utf-8") as log_file:
        process = subprocess.Popen(
            [
                sys.executable,
                "-m",
                "uvicorn",
                "app:app",
                "--host",
                "127.0.0.1",
                "--port",
                str(port),
            ],
            cwd=STUB_DIR,
            stdout=log_file,
            stderr=subprocess.STDOUT,
            text=True,
        )
        base_url = f"http://127.0.0.1:{port}"
        _wait_for_stub_ready(base_url, process, log_path=log_path)
        try:
            yield ConfluenceStubServer(base_url=base_url, log_path=log_path)
        finally:
            if process.poll() is None:
                process.terminate()
                try:
                    process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=5)
