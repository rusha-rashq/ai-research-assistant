import re
from pathlib import Path

import fitz  # PyMuPDF
import httpx

from arxiv import HEADERS
from db import PDF_DIR


def base_arxiv_id(arxiv_id):
    """2401.00001v2 -> 2401.00001 (also handles old-style ids like cs/0101001v1)."""
    return re.sub(r"v\d+$", "", arxiv_id)


def download_pdf(arxiv_id):
    """Download an arXiv PDF into data/pdfs and return its path. Raises on failure."""
    dest = PDF_DIR / (base_arxiv_id(arxiv_id).replace("/", "_") + ".pdf")
    resp = httpx.get(f"https://arxiv.org/pdf/{arxiv_id}", headers=HEADERS, timeout=60, follow_redirects=True)
    resp.raise_for_status()
    dest.write_bytes(resp.content)
    return dest


def extract_text(path):
    with fitz.open(path) as doc:
        return "\n".join(page.get_text() for page in doc).strip()


def fetch_and_extract(arxiv_id):
    """Download + extract. Returns (pdf_path, full_text) or raises."""
    path = download_pdf(arxiv_id)
    return str(path), extract_text(path)
