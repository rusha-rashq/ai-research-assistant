import os
import uuid

import httpx
from dotenv import load_dotenv
from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

import db
import llm
from arxiv import search_arxiv
from pdf import base_arxiv_id, extract_text, extract_first_page, fetch_and_extract

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


@app.post("/api/upload")
def upload_pdf(file: UploadFile = File(...)):
    path = db.PDF_DIR / f"upload_{uuid.uuid4().hex}.pdf"
    path.write_bytes(file.file.read())
    try:
        try:
            full_text = extract_text(path)
            first_page = extract_first_page(path)
        except Exception:
            raise HTTPException(400, "Could not read that file as a PDF.")
        if not first_page.strip():
            raise HTTPException(422, "No text found in the PDF (scanned/image-only PDFs aren't supported).")
        try:
            meta = llm.extract_metadata(first_page)
        except llm.LLMError as e:
            raise HTTPException(502, str(e))
        title = meta["title"] or (file.filename or "Untitled upload")
        paper_id = db.add_paper(
            source="upload", arxiv_id=None, title=title, authors=meta["authors"], year=meta["year"],
            abstract=meta["abstract"], url="", pdf_path=str(path), full_text=full_text,
        )
    except Exception:
        path.unlink(missing_ok=True)  # don't leave orphan files when the upload fails
        raise
    return {"paper": db.get_paper(paper_id)}


class Question(BaseModel):
    question: str


def paper_with_text(paper_id):
    """Load a paper with its full text, retrying the arXiv PDF download if it failed at save time."""
    paper = db.get_paper(paper_id, full_text=True)
    if not paper:
        raise HTTPException(404, "Paper not found.")
    if paper["full_text"]:
        return paper
    if paper["arxiv_id"]:
        try:
            pdf_path, full_text = fetch_and_extract(paper["arxiv_id"])
        except Exception as e:
            raise HTTPException(502, f"The paper's full text isn't available yet: PDF download failed ({e}).")
        if not full_text:
            raise HTTPException(422, "The paper's PDF contains no extractable text.")
        db.update_paper(paper_id, pdf_path=pdf_path, full_text=full_text)
        paper.update(pdf_path=pdf_path, full_text=full_text)
        return paper
    raise HTTPException(422, "This paper has no stored full text.")


def truncation_note(truncated):
    return "This paper is very long, so only the first part of its text was used." if truncated else None


@app.post("/api/papers/{paper_id}/summarize")
def summarize_paper(paper_id: int, force: bool = False):
    paper = paper_with_text(paper_id)
    if paper["summary"] and not force:
        return {"summary": paper["summary"], "cached": True, "warning": None}
    try:
        summary, truncated = llm.summarize(paper["title"], paper["full_text"])
    except llm.LLMError as e:
        raise HTTPException(502, str(e))
    db.update_paper(paper_id, summary=summary)
    return {"summary": summary, "cached": False, "warning": truncation_note(truncated)}


@app.post("/api/papers/{paper_id}/ask")
def ask_paper(paper_id: int, body: Question):
    question = body.question.strip()
    if not question:
        raise HTTPException(400, "Enter a question.")
    paper = paper_with_text(paper_id)
    try:
        answer, truncated = llm.answer_question(paper["title"], paper["full_text"], question)
    except llm.LLMError as e:
        raise HTTPException(502, str(e))
    return {"answer": answer, "warning": truncation_note(truncated)}


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
