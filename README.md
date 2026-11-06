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

## Testing

The automated tests use [pytest](https://docs.pytest.org/). They never call the real arXiv or Anthropic APIs (both are mocked, and any un-mocked network call fails the test), and they never touch your `data/` folder or `data/library.db` (every test runs against a temporary database and PDF directory). No API key is needed to run them.

**Install the dev dependencies** (inside your activated virtual environment):

```bash
pip install -r requirements-dev.txt
```

**Install the browser for the end-to-end tests** (one-time; downloads Chromium for Playwright):

```bash
python -m playwright install chromium
```

**Run the tests.** Use `python -m pytest` rather than bare `pytest`, so the virtual environment's pytest is used instead of a system-wide one. The suite has two parts:

```bash
python -m pytest tests --ignore=tests/e2e   # fast unit/API tests (well under a second)
python -m pytest tests/e2e                  # browser tests with Playwright (~10 seconds)
python -m pytest                            # everything
```

The browser tests in `tests/e2e/` start the real app on a free port in a subprocess, with a temporary data directory and arXiv and Anthropic faked inside that server process. They drive the UI in headless Chromium (search, save, upload, summarize, ask, plus UI details such as the "Re-summarize" label and the abstract "Show more" toggle). The markdown CDN scripts are blocked in these tests, so the UI's plain-text fallback is what gets checked.

**Reproduce the coverage numbers** (line and branch coverage for the five application modules; this command also runs the browser tests, which don't change the Python numbers much because the server runs in a separate process. Add `tests --ignore=tests/e2e` for the fast suite only):

```bash
python -m pytest --cov=app --cov=arxiv --cov=db --cov=llm --cov=pdf --cov-branch --cov-report=term-missing
```

**Run the mutation tests.** [mutmut](https://github.com/boxed/mutmut) could not run this suite, so `mutation/run_mutants.py` is a small purpose-built script instead. It applies about 50 hand-written mutants (changed status codes, comparison operators, boundary values, prompt strings, deleted cleanup logic) one at a time to a temporary copy of the source, runs the tests against each, and reports how many were killed or survived. Your real source files are never modified. It takes a few minutes:

```bash
python mutation/run_mutants.py --tests tests --label current
```

Per-mutant results are written to `mutation/results/<label>.json` (git-ignored). The original first-round tests are kept in `mutation/round0_tests/tests` for comparison:

```bash
python mutation/run_mutants.py --tests mutation/round0_tests/tests --label round0
```

## Limitations

- **No authentication or multi-user support.** It's a local single-user tool; don't expose it to the internet.
- **No RAG.** The whole paper text goes into the prompt. Papers over ~500,000 characters are truncated (the UI warns when this happens). Each summarize/ask call re-sends the full paper, so it costs tokens.
- **Scanned PDFs are not supported.** There is no OCR, so image-only PDFs are rejected.
- **Metadata from uploads depends on the LLM.** It reads only the first page, so unusual layouts can give a wrong title, author list or year.
- **Requests are blocking.** There is no streaming, so summaries take 10-30 seconds with a spinner.
- **Search is basic.** Results are the top 10 from arXiv's `all:` keyword query, with no pagination or filters.
- **Markdown rendering needs internet access** to load `marked` and `DOMPurify` from a CDN. Without it, responses show as plain text.
- **Frontend tests cover the main flows only.** The Playwright tests exercise the key user flows and a few UI behaviours in Chromium; they don't cover other browsers, error states for every request, or the Markdown rendering path (the CDN scripts are blocked in tests).

## How this was built

This project was built with a coding agent, [Claude Code](https://claude.com/claude-code). The architecture was proposed and approved up front. The work then went step by step (search, save and library, upload, summarize and ask, UI polish), with a manual test and a git commit after each step.
