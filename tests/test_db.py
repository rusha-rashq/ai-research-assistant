import sqlite3

import pytest

import db


def test_add_and_get(add_paper):
    pid = add_paper(title="Hello")
    p = db.get_paper(pid)
    assert p["title"] == "Hello"
    assert p["has_text"] == 1
    assert "full_text" not in p  # excluded from light queries


def test_get_with_full_text(add_paper):
    pid = add_paper(full_text="BODY")
    assert db.get_paper(pid, full_text=True)["full_text"] == "BODY"


def test_has_text_false_when_null(add_paper):
    pid = add_paper(full_text=None)
    assert db.get_paper(pid)["has_text"] == 0


def test_get_missing_returns_none():
    assert db.get_paper(999) is None


def test_list_newest_first(add_paper):
    a = add_paper(arxiv_id="1", title="first")
    b = add_paper(arxiv_id="2", title="second")
    assert [p["id"] for p in db.list_papers()] == [b, a]


def test_list_empty():
    assert db.list_papers() == []


def test_find_by_arxiv_id(add_paper):
    add_paper(arxiv_id="2401.00001")
    assert db.find_by_arxiv_id("2401.00001")["arxiv_id"] == "2401.00001"
    assert db.find_by_arxiv_id("nope") is None


def test_arxiv_id_unique(add_paper):
    add_paper(arxiv_id="dup")
    with pytest.raises(sqlite3.IntegrityError):
        add_paper(arxiv_id="dup")


def test_uploads_may_have_null_arxiv_id(add_paper):
    add_paper(source="upload", arxiv_id=None, title="a")
    add_paper(source="upload", arxiv_id=None, title="b")
    assert len(db.list_papers()) == 2


def test_title_required(add_paper):
    with pytest.raises(sqlite3.IntegrityError):
        add_paper(title=None)


def test_update(add_paper):
    pid = add_paper()
    db.update_paper(pid, summary="S", pdf_path="/x.pdf")
    p = db.get_paper(pid)
    assert p["summary"] == "S" and p["pdf_path"] == "/x.pdf"


def test_delete(add_paper):
    pid = add_paper()
    db.delete_paper(pid)
    assert db.get_paper(pid) is None


def test_delete_missing_is_noop(add_paper):
    keep = add_paper(title="keep me")
    db.delete_paper(12345)  # must not raise
    assert [p["id"] for p in db.list_papers()] == [keep]


def test_init_db_idempotent_and_creates_dirs(temp_storage):
    db.init_db()
    db.init_db()
    assert (temp_storage / "pdfs").is_dir()
    assert (temp_storage / "library.db").exists()


def test_sql_injection_safe_values(add_paper):
    pid = add_paper(title="x'); DROP TABLE papers;--")
    assert db.get_paper(pid)["title"].startswith("x'")
    assert len(db.list_papers()) == 1


def test_library_persists_across_restart(temp_storage):
    pid = db.add_paper(source="arxiv", arxiv_id="2401.00001", title="Persistent", authors="A, B",
                       year=2024, abstract="abs", url="http://arxiv.org/abs/2401.00001",
                       pdf_path="/x.pdf", full_text="body")
    db.update_paper(pid, summary="cached summary")

    db.init_db()  # "restart": startup runs init_db again; must not wipe data

    # Read via a brand-new raw connection, independent of any state in db.py
    conn = sqlite3.connect(db.DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        row = conn.execute("SELECT * FROM papers WHERE id = ?", (pid,)).fetchone()
    finally:
        conn.close()
    assert row["title"] == "Persistent" and row["authors"] == "A, B" and row["year"] == 2024
    assert row["summary"] == "cached summary" and row["full_text"] == "body"
    assert db.get_paper(pid)["title"] == "Persistent"
    assert [p["id"] for p in db.list_papers()] == [pid]


def test_db_functions_close_their_connections(monkeypatch):
    """db.py uses `with sqlite3.connect()`, which commits but does NOT close.
    Every connection opened by a db function should be closed when the function returns.
    (Expected to FAIL against the current db.py: this is an application bug, a connection leak.)"""
    opened = []

    class TrackedConnection(sqlite3.Connection):
        closed = False

        def close(self):
            self.closed = True
            super().close()

    real_connect = sqlite3.connect

    def tracking_connect(*args, **kwargs):
        conn = real_connect(*args, factory=TrackedConnection, **kwargs)
        opened.append(conn)
        return conn

    monkeypatch.setattr(db.sqlite3, "connect", tracking_connect)

    db.init_db()
    pid = db.add_paper(source="arxiv", arxiv_id="x1", title="t", authors="a", year=1,
                       abstract="", url="", pdf_path=None, full_text="f")
    db.get_paper(pid)
    db.list_papers()
    db.find_by_arxiv_id("x1")
    db.update_paper(pid, summary="s")
    db.delete_paper(pid)

    assert len(opened) == 7
    leaked = [c for c in opened if not c.closed]
    assert not leaked, f"{len(leaked)} of {len(opened)} SQLite connections were never closed"
