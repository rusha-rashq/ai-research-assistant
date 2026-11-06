"""Shared fixtures.

Safety: app.py calls db.init_db() at import time and uses relative paths
("data", "static"). To keep the real data/ folder untouched we chdir into a
throwaway directory (with a copy of static/) BEFORE importing any app module,
and every test additionally gets its own temp DB / PDF dir. All network access
(arXiv via httpx, Anthropic) is blocked unless a test mocks it explicitly.
"""
import atexit
import os
import shutil
import sys
import tempfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent

# --- import-time sandbox -----------------------------------------------------
_SANDBOX = Path(tempfile.mkdtemp(prefix="ara-sandbox-"))
shutil.copytree(ROOT / "static", _SANDBOX / "static")
_ORIG_CWD = os.getcwd()
os.chdir(_SANDBOX)
sys.path.insert(0, str(ROOT))
os.environ.pop("ANTHROPIC_API_KEY", None)

import fitz  # noqa: E402
import httpx  # noqa: E402
import httpx2  # noqa: E402  (the anthropic SDK uses this, not httpx)

import app as app_module  # noqa: E402
import db  # noqa: E402
import pdf  # noqa: E402


@atexit.register
def _cleanup():
    os.chdir(_ORIG_CWD)
    shutil.rmtree(_SANDBOX, ignore_errors=True)


# --- per-test fixtures ---------------------------------------------------------
@pytest.fixture(autouse=True)
def temp_storage(tmp_path, monkeypatch):
    """Fresh DB + PDF directory per test; never touches the real data/."""
    data_dir = tmp_path / "data"
    pdf_dir = data_dir / "pdfs"
    monkeypatch.setattr(db, "DATA_DIR", data_dir)
    monkeypatch.setattr(db, "PDF_DIR", pdf_dir)
    monkeypatch.setattr(db, "DB_PATH", data_dir / "library.db")
    monkeypatch.setattr(pdf, "PDF_DIR", pdf_dir)
    db.init_db()
    return data_dir


@pytest.fixture(autouse=True)
def no_api_key(monkeypatch):
    """load_dotenv() may have pulled a real key from .env; start every test without one."""
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)


class NetworkBlocked(BaseException):
    """BaseException on purpose: the Anthropic SDK catches Exception and retries/wraps it,
    which would hide an accidental real call. This can't be swallowed that way."""


@pytest.fixture(autouse=True)
def block_network(monkeypatch):
    """Any un-mocked HTTP call fails loudly. Covers httpx (arXiv) and httpx2 (anthropic SDK).

    We block the real socket transport rather than Client.send, because FastAPI's TestClient
    (also built on httpx2) uses Client.send with an in-process ASGI transport.
    """
    def _blocked(*a, **kw):
        raise NetworkBlocked("Real network access attempted in a test")
    for lib in (httpx, httpx2):
        monkeypatch.setattr(lib, "get", _blocked)
        monkeypatch.setattr(lib, "post", _blocked)
        monkeypatch.setattr(lib.HTTPTransport, "handle_request", _blocked)
        monkeypatch.setattr(lib.AsyncHTTPTransport, "handle_async_request", _blocked)


@pytest.fixture
def client():
    from fastapi.testclient import TestClient
    return TestClient(app_module.app)


@pytest.fixture
def api_key(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")


# --- helpers -------------------------------------------------------------------
def make_pdf_bytes(pages=("Hello world. This is page one.",)):
    doc = fitz.open()
    for text in pages:
        page = doc.new_page()
        if text:
            page.insert_text((72, 72), text)
    data = doc.tobytes()
    doc.close()
    return data


@pytest.fixture
def pdf_bytes():
    return make_pdf_bytes


class FakeResponse:
    def __init__(self, text="", content=b"", status=200):
        self.text, self.content, self.status_code = text, content, status

    def raise_for_status(self):
        if self.status_code >= 400:
            req = httpx.Request("GET", "http://test")
            raise httpx.HTTPStatusError("boom", request=req, response=httpx.Response(self.status_code, request=req))


@pytest.fixture
def fake_response():
    return FakeResponse


ARXIV_XML = """<?xml version="1.0" encoding="UTF-8"?>
<feed xmlns="http://www.w3.org/2005/Atom">
  <entry>
    <id>http://arxiv.org/abs/2401.00001v2</id>
    <published>2024-01-02T00:00:00Z</published>
    <title>  Attention   Is
      Still All You Need </title>
    <summary>  An abstract
      spanning lines. </summary>
    <author><name>Ada Lovelace</name></author>
    <author><name> Alan  Turing </name></author>
  </entry>
  <entry>
    <id>http://arxiv.org/abs/cs/0101001v1</id>
    <published></published>
    <title>Old Style</title>
    <summary>Old.</summary>
  </entry>
</feed>"""


@pytest.fixture
def arxiv_xml():
    return ARXIV_XML


SAMPLE_PAPER = dict(
    arxiv_id="2401.00001v2", title="Sample Paper", authors=["A One", "B Two"],
    year=2024, abstract="An abstract.", url="http://arxiv.org/abs/2401.00001v2",
)


@pytest.fixture
def sample_paper():
    return dict(SAMPLE_PAPER)


@pytest.fixture
def add_paper():
    """Insert a paper straight into the temp DB."""
    def _add(**over):
        f = dict(source="arxiv", arxiv_id="2401.00001", title="T", authors="A", year=2024,
                 abstract="abs", url="u", pdf_path=None, full_text="full text")
        f.update(over)
        return db.add_paper(**f)
    return _add
