"""HTTP-level tests of the FastAPI app with arXiv/PDF/LLM mocked."""
import httpx
import pytest

import app as app_module
import db
import llm


# ---------------------------------------------------------------- search
def test_search_ok(client, monkeypatch):
    seen = {}
    monkeypatch.setattr(app_module, "search_arxiv", lambda q: seen.setdefault("q", q) and [{"arxiv_id": "1"}])
    r = client.get("/api/search", params={"q": "  deep learning  "})
    assert r.status_code == 200 and r.json() == [{"arxiv_id": "1"}]
    assert seen["q"] == "deep learning"  # trimmed


@pytest.mark.parametrize("q", ["", "   "])
def test_search_blank_400(client, q):
    assert client.get("/api/search", params={"q": q}).status_code == 400


def test_search_missing_param_422(client):
    assert client.get("/api/search").status_code == 422


def test_search_arxiv_failure_502(client, monkeypatch):
    def boom(q):
        raise httpx.ConnectError("down")
    monkeypatch.setattr(app_module, "search_arxiv", boom)
    r = client.get("/api/search", params={"q": "x"})
    assert r.status_code == 502 and "arXiv request failed" in r.json()["detail"]


# ---------------------------------------------------------------- save
def test_save_paper_success(client, monkeypatch, sample_paper):
    monkeypatch.setattr(app_module, "fetch_and_extract", lambda i: ("/tmp/x.pdf", "full text"))
    r = client.post("/api/papers", json=sample_paper)
    assert r.status_code == 200
    body = r.json()
    assert body["warning"] is None
    p = body["paper"]
    assert p["arxiv_id"] == "2401.00001"  # version stripped
    assert p["authors"] == "A One, B Two"
    assert p["has_text"] == 1 and p["source"] == "arxiv"


def test_save_paper_pdf_failure_keeps_metadata(client, monkeypatch, sample_paper):
    def boom(i):
        raise httpx.ConnectError("offline")
    monkeypatch.setattr(app_module, "fetch_and_extract", boom)
    r = client.post("/api/papers", json=sample_paper)
    assert r.status_code == 200
    assert "Saved metadata only" in r.json()["warning"]
    assert r.json()["paper"]["has_text"] == 0


def test_save_duplicate_409_even_with_different_version(client, monkeypatch, sample_paper):
    monkeypatch.setattr(app_module, "fetch_and_extract", lambda i: ("/tmp/x.pdf", "t"))
    assert client.post("/api/papers", json=sample_paper).status_code == 200
    again = dict(sample_paper, arxiv_id="2401.00001v5")
    assert client.post("/api/papers", json=again).status_code == 409
    assert len(db.list_papers()) == 1


def test_save_minimal_payload_defaults(client, monkeypatch):
    monkeypatch.setattr(app_module, "fetch_and_extract", lambda i: ("/p", "t"))
    r = client.post("/api/papers", json={"arxiv_id": "1234.5678", "title": "Only"})
    assert r.status_code == 200
    assert r.json()["paper"]["authors"] == "" and r.json()["paper"]["year"] is None


def test_save_invalid_payload_422(client):
    assert client.post("/api/papers", json={"title": "no id"}).status_code == 422


# ---------------------------------------------------------------- upload
def _meta(**over):
    d = {"title": "Extracted Title", "authors": "A, B", "year": 2022, "abstract": "Abs"}
    d.update(over)
    return d


def _upload(client, data, name="paper.pdf"):
    return client.post("/api/upload", files={"file": (name, data, "application/pdf")})


def test_upload_success(client, monkeypatch, pdf_bytes, temp_storage):
    monkeypatch.setattr(llm, "extract_metadata", lambda t: _meta())
    r = _upload(client, pdf_bytes(["Title page text"]))
    assert r.status_code == 200
    p = r.json()["paper"]
    assert p["title"] == "Extracted Title" and p["source"] == "upload" and p["arxiv_id"] is None
    assert p["has_text"] == 1
    assert len(list((temp_storage / "pdfs").glob("upload_*.pdf"))) == 1


def test_upload_passes_first_page_to_llm(client, monkeypatch, pdf_bytes):
    got = {}
    monkeypatch.setattr(llm, "extract_metadata", lambda t: got.setdefault("t", t) and _meta())
    _upload(client, pdf_bytes(["FIRSTPAGE", "SECONDPAGE"]))
    assert "FIRSTPAGE" in got["t"] and "SECONDPAGE" not in got["t"]


def test_upload_title_falls_back_to_filename(client, monkeypatch, pdf_bytes):
    monkeypatch.setattr(llm, "extract_metadata", lambda t: _meta(title=""))
    r = _upload(client, pdf_bytes(), name="my-notes.pdf")
    assert r.json()["paper"]["title"] == "my-notes.pdf"


def test_upload_not_a_pdf_400_and_cleans_up(client, temp_storage):
    r = _upload(client, b"plain text, not pdf")
    assert r.status_code == 400
    assert list((temp_storage / "pdfs").iterdir()) == []


def test_upload_empty_file_400(client, temp_storage):
    assert _upload(client, b"").status_code == 400
    assert list((temp_storage / "pdfs").iterdir()) == []


def test_upload_scanned_pdf_422(client, pdf_bytes, temp_storage):
    r = _upload(client, pdf_bytes([""]))
    assert r.status_code == 422 and "No text found" in r.json()["detail"]
    assert list((temp_storage / "pdfs").iterdir()) == []


def test_upload_llm_error_502_and_cleans_up(client, monkeypatch, pdf_bytes, temp_storage):
    def boom(t):
        raise llm.LLMError("no key")
    monkeypatch.setattr(llm, "extract_metadata", boom)
    r = _upload(client, pdf_bytes())
    assert r.status_code == 502 and r.json()["detail"] == "no key"
    assert list((temp_storage / "pdfs").iterdir()) == []
    assert db.list_papers() == []


def test_upload_missing_file_422(client):
    assert client.post("/api/upload").status_code == 422


# ---------------------------------------------------------------- summarize
def test_summarize_generates_and_caches(client, monkeypatch, add_paper):
    pid = add_paper()
    calls = []
    monkeypatch.setattr(llm, "summarize", lambda t, x: calls.append(1) or ("## Problem\nS", False))
    r1 = client.post(f"/api/papers/{pid}/summarize")
    assert r1.json() == {"summary": "## Problem\nS", "cached": False, "warning": None}
    r2 = client.post(f"/api/papers/{pid}/summarize")
    assert r2.json()["cached"] is True
    assert len(calls) == 1
    assert db.get_paper(pid)["summary"] == "## Problem\nS"


def test_summarize_force_regenerates(client, monkeypatch, add_paper):
    pid = add_paper()
    out = iter([("one", False), ("two", False)])
    monkeypatch.setattr(llm, "summarize", lambda t, x: next(out))
    client.post(f"/api/papers/{pid}/summarize")
    r = client.post(f"/api/papers/{pid}/summarize", params={"force": "true"})
    assert r.json()["summary"] == "two" and r.json()["cached"] is False


def test_summarize_truncation_warning(client, monkeypatch, add_paper):
    pid = add_paper()
    monkeypatch.setattr(llm, "summarize", lambda t, x: ("s", True))
    assert "very long" in client.post(f"/api/papers/{pid}/summarize").json()["warning"]


def test_summarize_404(client):
    assert client.post("/api/papers/999/summarize").status_code == 404


def test_summarize_llm_error_502_not_cached(client, monkeypatch, add_paper):
    pid = add_paper()

    def boom(t, x):
        raise llm.LLMError("api down")
    monkeypatch.setattr(llm, "summarize", boom)
    assert client.post(f"/api/papers/{pid}/summarize").status_code == 502
    assert db.get_paper(pid)["summary"] is None


# ---------------------------------------------------------------- retry download
def test_missing_text_retries_download(client, monkeypatch, add_paper):
    pid = add_paper(full_text=None)
    monkeypatch.setattr(app_module, "fetch_and_extract", lambda i: ("/p.pdf", "recovered text"))
    seen = {}
    monkeypatch.setattr(llm, "summarize", lambda t, x: seen.setdefault("x", x) and ("S", False))
    assert client.post(f"/api/papers/{pid}/summarize").status_code == 200
    assert seen["x"] == "recovered text"
    stored = db.get_paper(pid, full_text=True)
    assert stored["full_text"] == "recovered text" and stored["pdf_path"] == "/p.pdf"


def test_retry_download_fails_502(client, monkeypatch, add_paper):
    pid = add_paper(full_text=None)

    def boom(i):
        raise httpx.ConnectError("x")
    monkeypatch.setattr(app_module, "fetch_and_extract", boom)
    r = client.post(f"/api/papers/{pid}/summarize")
    assert r.status_code == 502 and "PDF download failed" in r.json()["detail"]


def test_retry_download_empty_text_422(client, monkeypatch, add_paper):
    pid = add_paper(full_text=None)
    monkeypatch.setattr(app_module, "fetch_and_extract", lambda i: ("/p.pdf", ""))
    assert client.post(f"/api/papers/{pid}/summarize").status_code == 422


def test_upload_without_text_422(client, add_paper):
    pid = add_paper(source="upload", arxiv_id=None, full_text=None)
    r = client.post(f"/api/papers/{pid}/summarize")
    assert r.status_code == 422 and "no stored full text" in r.json()["detail"]


# ---------------------------------------------------------------- ask
def test_ask_success(client, monkeypatch, add_paper):
    pid = add_paper()
    seen = {}
    monkeypatch.setattr(llm, "answer_question",
                        lambda t, x, q: seen.update(q=q) or ("Because.", False))
    r = client.post(f"/api/papers/{pid}/ask", json={"question": "  Why?  "})
    assert r.status_code == 200 and r.json() == {"answer": "Because.", "warning": None}
    assert seen["q"] == "Why?"


@pytest.mark.parametrize("q", ["", "   \n"])
def test_ask_blank_400(client, add_paper, q):
    pid = add_paper()
    assert client.post(f"/api/papers/{pid}/ask", json={"question": q}).status_code == 400


def test_ask_missing_body_422(client, add_paper):
    pid = add_paper()
    assert client.post(f"/api/papers/{pid}/ask", json={}).status_code == 422


def test_ask_404(client):
    assert client.post("/api/papers/999/ask", json={"question": "hi"}).status_code == 404


def test_ask_llm_error_502(client, monkeypatch, add_paper):
    pid = add_paper()

    def boom(t, x, q):
        raise llm.LLMError("nope")
    monkeypatch.setattr(llm, "answer_question", boom)
    assert client.post(f"/api/papers/{pid}/ask", json={"question": "hi"}).status_code == 502


def test_ask_truncation_warning(client, monkeypatch, add_paper):
    pid = add_paper()
    monkeypatch.setattr(llm, "answer_question", lambda t, x, q: ("a", True))
    assert client.post(f"/api/papers/{pid}/ask", json={"question": "hi"}).json()["warning"]


# ---------------------------------------------------------------- library CRUD
def test_list_empty_and_ordering(client, add_paper):
    assert client.get("/api/papers").json() == []
    a = add_paper(arxiv_id="1")
    b = add_paper(arxiv_id="2")
    assert [p["id"] for p in client.get("/api/papers").json()] == [b, a]


def test_list_excludes_full_text(client, add_paper):
    add_paper()
    assert "full_text" not in client.get("/api/papers").json()[0]


def test_get_paper_and_404(client, add_paper):
    pid = add_paper(title="Findme")
    assert client.get(f"/api/papers/{pid}").json()["title"] == "Findme"
    assert client.get("/api/papers/999").status_code == 404


def test_get_paper_non_int_id_422(client):
    assert client.get("/api/papers/abc").status_code == 422


def test_delete_removes_row_and_pdf(client, add_paper, temp_storage):
    f = temp_storage / "pdfs" / "x.pdf"
    f.write_bytes(b"%PDF")
    pid = add_paper(pdf_path=str(f))
    assert client.delete(f"/api/papers/{pid}").json() == {"ok": True}
    assert not f.exists()
    assert client.get(f"/api/papers/{pid}").status_code == 404


def test_delete_with_missing_pdf_file_ok(client, add_paper, temp_storage):
    pid = add_paper(pdf_path=str(temp_storage / "pdfs" / "gone.pdf"))
    assert client.delete(f"/api/papers/{pid}").status_code == 200


def test_delete_without_pdf_path(client, add_paper):
    pid = add_paper(pdf_path=None)
    assert client.delete(f"/api/papers/{pid}").status_code == 200


def test_delete_404(client):
    assert client.delete("/api/papers/999").status_code == 404


def test_index_serves_html(client):
    r = client.get("/")
    assert r.status_code == 200 and "<html" in r.text.lower()


# ---------------------------------------------------------------- isolation guard
def test_tests_use_temp_db(temp_storage):
    from pathlib import Path
    assert db.DB_PATH.parent == temp_storage
    assert Path(db.DB_PATH).resolve() != (Path(__file__).resolve().parent.parent / "data" / "library.db")
