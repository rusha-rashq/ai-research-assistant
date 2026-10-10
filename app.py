import os

import httpx
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

import db
from arxiv import search_arxiv
from pdf import base_arxiv_id, fetch_and_extract

load_dotenv()
db.init_db()
app = FastAPI(title="AI Research Assistant")


class SavePaper(BaseModel):
    arxiv_id: str
    title: str
    authors: list[str] = []
    year: int | None = None
    abstract: str = ""
    url: str = ""


@app.get("/api/search")
def search(q: str):
    if not q.strip():
        raise HTTPException(400, "Enter a search keyword.")
    try:
        return search_arxiv(q.strip())
    except httpx.HTTPError as e:
        raise HTTPException(502, f"arXiv request failed: {e}")


@app.post("/api/papers")
def save_paper(p: SavePaper):
    arxiv_id = base_arxiv_id(p.arxiv_id)
    if db.find_by_arxiv_id(arxiv_id):
        raise HTTPException(409, "Paper is already in your library.")
    # Try to fetch the PDF now; on failure keep the metadata and retry later.
    pdf_path = full_text = warning = None
    try:
        pdf_path, full_text = fetch_and_extract(p.arxiv_id)
    except Exception as e:
        warning = f"Saved metadata only; PDF download failed ({e}). It will be retried when needed."
    paper_id = db.add_paper(
        source="arxiv", arxiv_id=arxiv_id, title=p.title, authors=", ".join(p.authors),
        year=p.year, abstract=p.abstract, url=p.url, pdf_path=pdf_path, full_text=full_text,
    )
    return {"paper": db.get_paper(paper_id), "warning": warning}


@app.get("/api/papers")
def list_papers():
    return db.list_papers()


@app.get("/api/papers/{paper_id}")
def get_paper(paper_id: int):
    paper = db.get_paper(paper_id)
    if not paper:
        raise HTTPException(404, "Paper not found.")
    return paper


@app.delete("/api/papers/{paper_id}")
def delete_paper(paper_id: int):
    paper = db.get_paper(paper_id)
    if not paper:
        raise HTTPException(404, "Paper not found.")
    db.delete_paper(paper_id)
    if paper["pdf_path"] and os.path.exists(paper["pdf_path"]):
        os.remove(paper["pdf_path"])
    return {"ok": True}


@app.get("/")
def index():
    return FileResponse("static/index.html")


app.mount("/static", StaticFiles(directory="static"), name="static")
