"""Browser (Playwright) end-to-end tests. Run separately from the fast suite:

    python -m pytest tests/e2e              # only the browser tests
    python -m pytest tests --ignore=tests/e2e   # only the fast tests

A real uvicorn server runs the real app in a subprocess with a temp data directory;
arXiv and Anthropic are faked inside that process (see server_entry.py).
"""
import json
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
ENTRY = Path(__file__).with_name("server_entry.py")


def _free_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _call(base, method, path, body=None):
    # urllib on purpose: the parent conftest blocks httpx's real transport in-process.
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(base + path, data=data, method=method,
                                 headers={"Content-Type": "application/json"} if data else {})
    with urllib.request.urlopen(req, timeout=10) as r:
        return json.loads(r.read() or b"null")


@pytest.fixture(scope="session")
def server(tmp_path_factory):
    data_dir = tmp_path_factory.mktemp("e2e-server")
    port = _free_port()
    log = open(data_dir / "server.log", "w")
    proc = subprocess.Popen([sys.executable, "-W", "ignore", str(ENTRY), str(ROOT), str(data_dir / "app"), str(port)],
                            stdout=log, stderr=subprocess.STDOUT)
    base = f"http://127.0.0.1:{port}"
    try:
        deadline = time.time() + 30
        while True:
            if proc.poll() is not None:
                raise RuntimeError("e2e server exited early:\n" + (data_dir / "server.log").read_text())
            try:
                _call(base, "GET", "/api/papers")
                break
            except (urllib.error.URLError, ConnectionError):
                if time.time() > deadline:
                    raise RuntimeError("e2e server did not start in time")
                time.sleep(0.2)
        yield base
    finally:
        proc.terminate()
        proc.wait(timeout=10)
        log.close()


@pytest.fixture(scope="session")
def base_url(server):
    return server


@pytest.fixture(autouse=True)
def clean_library(server):
    """Every test starts with an empty library."""
    for p in _call(server, "GET", "/api/papers"):
        _call(server, "DELETE", f"/api/papers/{p['id']}")


@pytest.fixture
def api(server):
    """Tiny helper to seed state through the real HTTP API."""
    return lambda method, path, body=None: _call(server, method, path, body)


@pytest.fixture
def seed_paper(api):
    """Save one of the canned arXiv papers into the library (via the real API); returns the paper dict."""
    def _seed(arxiv_id="2401.00001", title="Graph Neural Networks for Testing", summarize=False):
        paper = api("POST", "/api/papers", {"arxiv_id": arxiv_id + "v1", "title": title,
                                            "authors": ["Ada Lovelace"], "year": 2024,
                                            "abstract": "Seeded abstract.", "url": f"http://arxiv.org/abs/{arxiv_id}"})["paper"]
        if summarize:
            api("POST", f"/api/papers/{paper['id']}/summarize")
        return paper
    return _seed


@pytest.fixture(autouse=True)
def app_page(page):
    """Offline-safe, deterministic page: block the markdown CDN (the UI falls back to plain text),
    and fail the test on any uncaught JavaScript error."""
    errors = []
    page.on("pageerror", lambda e: errors.append(str(e)))
    page.route("**/cdn.jsdelivr.net/**", lambda route: route.abort())
    yield page
    assert not errors, f"uncaught JavaScript errors: {errors}"


@pytest.fixture
def pdf_upload():
    """A small valid PDF in the shape Playwright's set_input_files accepts."""
    import pymupdf
    doc = pymupdf.open()
    doc.new_page().insert_text((72, 72), "Some uploaded paper text on its first page.")
    data = doc.tobytes()
    doc.close()
    return {"name": "my-paper.pdf", "mimeType": "application/pdf", "buffer": data}
