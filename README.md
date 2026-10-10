# AI Research Assistant

A small web app for working with research papers. Search arXiv, save papers to a local library, upload your own PDFs, and use Claude to summarize a paper or answer questions about it, based on the paper's full text.

Built as a homework project: simple by design, not production quality.

## Features (mapped to the requirements)

| # | Requirement | How it works |
|---|---|---|
| 1 | Search papers via an external API | Keyword search against the arXiv API. Each result shows title, authors, year, abstract (clamped to 3 lines with "Show more") and a link. |
| 2 | Save to a local DB, browse the library | "Save to library" stores the paper in a SQLite file (`data/library.db`) that persists across restarts. The Library tab lists saved papers on the left with a detail panel on the right. Papers can be deleted. |
| 3 | Upload a PDF and extract metadata | The PDF's text is extracted with PyMuPDF. The first page is sent to Claude, which returns title, authors, year and abstract as JSON. The paper is stored in the same library. |
| 4 | Summarize a paper from its full text | The full text is sent to Claude, which returns a Markdown summary with Problem, Method, Key Results and Limitations sections. The summary is cached in the DB. |
| 5 | Ask questions about a paper | Questions are answered from the paper's full text. Claude is told to say so when the paper doesn't contain the answer. |

Details worth knowing:
- Saving an arXiv paper downloads its PDF and extracts the text at save time. If the download fails, the metadata is still saved, and the download is retried the first time you summarize or ask.
- Saving the same arXiv paper twice is rejected (versions such as `v1`/`v2` count as the same paper).
- Responses are rendered as Markdown.

## Architecture and file layout

FastAPI backend, SQLite storage, and a single-page HTML/JS frontend served by the backend (no React, no build step).

```
app.py             FastAPI routes; serves the frontend
arxiv.py           arXiv API search (Atom feed parsing)
pdf.py             arXiv PDF download + PyMuPDF text extraction
llm.py             Anthropic API calls: metadata extraction, summarize, Q&A
db.py              SQLite helpers (single `papers` table)
static/index.html  The whole frontend (vanilla JS, CSS inline)
requirements.txt   Python dependencies
.env.example       Template for your API key
data/              Created at runtime: library.db and downloaded/uploaded PDFs (gitignored)
```

API endpoints:

| Method | Path | Purpose |
|---|---|---|
| GET | `/api/search?q=` | Search arXiv |
| POST | `/api/papers` | Save a search result (downloads the PDF) |
| GET | `/api/papers` | List the library |
| GET | `/api/papers/{id}` | One paper |
| DELETE | `/api/papers/{id}` | Delete a paper and its PDF |
| POST | `/api/upload` | Upload a PDF; Claude extracts the metadata |
| POST | `/api/papers/{id}/summarize` | Summarize (`?force=true` to regenerate) |
| POST | `/api/papers/{id}/ask` | Ask a question (`{"question": "..."}`) |

## Setup

Requires Python 3.10+ and an [Anthropic API key](https://console.anthropic.com/).

```bash
# 1. Create and activate a virtual environment
python3 -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate

# 2. Install dependencies
pip install -r requirements.txt

# 3. Configure your API key
cp .env.example .env
# then edit .env and set ANTHROPIC_API_KEY=your-key-here
```

`.env` is listed in `.gitignore`, so your key is never committed.

## Run

```bash
source .venv/bin/activate
uvicorn app:app --reload
```

Then open <http://localhost:8000>. Run it from the project root: the app uses relative paths for `static/` and `data/`.

The database and PDFs are created under `data/` on first start. Delete that folder to reset the library.

## Limitations

- **No authentication or multi-user support.** It's a local single-user tool; don't expose it to the internet.
- **No RAG.** The whole paper text goes into the prompt. Papers over ~500,000 characters are truncated (the UI warns when this happens). Each summarize/ask call re-sends the full paper, so it costs tokens.
- **Scanned PDFs are not supported.** There is no OCR, so image-only PDFs are rejected.
- **Metadata from uploads depends on the LLM.** It reads only the first page, so unusual layouts can give a wrong title, author list or year.
- **Requests are blocking.** There is no streaming, so summaries take 10-30 seconds with a spinner.
- **Search is basic.** Results are the top 10 from arXiv's `all:` keyword query, with no pagination or filters.
- **Markdown rendering needs internet access** to load `marked` and `DOMPurify` from a CDN. Without it, responses show as plain text.
- **No automated tests.** Features were checked manually.

## How this was built

This project was built with a coding agent, [Claude Code](https://claude.com/claude-code). The architecture was proposed and approved up front. The work then went step by step (search, save and library, upload, summarize and ask, UI polish), with a manual test and a git commit after each step.
