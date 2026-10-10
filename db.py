import sqlite3
from pathlib import Path

DATA_DIR = Path("data")
PDF_DIR = DATA_DIR / "pdfs"
DB_PATH = DATA_DIR / "library.db"

# Columns returned to the UI (full_text is large, so it's excluded from lists).
LIST_COLS = "id, source, arxiv_id, title, authors, year, abstract, url, pdf_path, summary, created_at, (full_text IS NOT NULL) AS has_text"


def connect():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    PDF_DIR.mkdir(parents=True, exist_ok=True)
    with connect() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS papers (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                source TEXT NOT NULL,            -- 'arxiv' or 'upload'
                arxiv_id TEXT UNIQUE,            -- version stripped, NULL for uploads
                title TEXT NOT NULL,
                authors TEXT,                    -- comma-separated
                year INTEGER,
                abstract TEXT,
                url TEXT,
                pdf_path TEXT,
                full_text TEXT,
                summary TEXT,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP
            )""")


def add_paper(**f):
    with connect() as conn:
        cur = conn.execute(
            """INSERT INTO papers (source, arxiv_id, title, authors, year, abstract, url, pdf_path, full_text)
               VALUES (:source, :arxiv_id, :title, :authors, :year, :abstract, :url, :pdf_path, :full_text)""",
            f,
        )
        return cur.lastrowid


def list_papers():
    with connect() as conn:
        rows = conn.execute(f"SELECT {LIST_COLS} FROM papers ORDER BY id DESC").fetchall()
    return [dict(r) for r in rows]


def get_paper(paper_id, full_text=False):
    cols = "*" if full_text else LIST_COLS
    with connect() as conn:
        row = conn.execute(f"SELECT {cols} FROM papers WHERE id = ?", (paper_id,)).fetchone()
    return dict(row) if row else None


def find_by_arxiv_id(arxiv_id):
    with connect() as conn:
        row = conn.execute(f"SELECT {LIST_COLS} FROM papers WHERE arxiv_id = ?", (arxiv_id,)).fetchone()
    return dict(row) if row else None


def update_paper(paper_id, **fields):
    sets = ", ".join(f"{k} = :{k}" for k in fields)
    with connect() as conn:
        conn.execute(f"UPDATE papers SET {sets} WHERE id = :id", {**fields, "id": paper_id})


def delete_paper(paper_id):
    with connect() as conn:
        conn.execute("DELETE FROM papers WHERE id = ?", (paper_id,))
