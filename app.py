import httpx
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from arxiv import search_arxiv

load_dotenv()
app = FastAPI(title="AI Research Assistant")


@app.get("/api/search")
def search(q: str):
    if not q.strip():
        raise HTTPException(400, "Enter a search keyword.")
    try:
        return search_arxiv(q.strip())
    except httpx.HTTPError as e:
        raise HTTPException(502, f"arXiv request failed: {e}")


@app.get("/")
def index():
    return FileResponse("static/index.html")


app.mount("/static", StaticFiles(directory="static"), name="static")
