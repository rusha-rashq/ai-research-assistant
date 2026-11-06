#!/usr/bin/env python
"""Tiny mutation-testing harness (used because mutmut can't run this suite: it re-imports conftest in one process, which breaks `from conftest import ...` class identity).

For every mutant: copy the project sources + a test folder into a fresh temp directory,
apply ONE textual mutation to the temp copy, run pytest there, and record whether the
tests noticed (killed = pytest failed/timed out) or not (survived = pytest still passed).
Your real source files and tests are never modified.

Usage:
    python mutation/run_mutants.py --tests tests --label current
    python mutation/run_mutants.py --tests mutation/round0_tests/tests --label round0
"""
import argparse
import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SOURCES = ["app.py", "arxiv.py", "db.py", "llm.py", "pdf.py"]

# (file, original snippet, mutated snippet, description). Snippets must occur exactly once.
MUTANTS = [
    # ---- app.py: status codes, comparisons, deleted logic
    ("app.py", 'HTTPException(400, "Enter a search keyword.")', 'HTTPException(422, "Enter a search keyword.")', "search blank query: status 400 -> 422"),
    ("app.py", "if not q.strip():", "if not q:", "search: whitespace-only query no longer rejected"),
    ("app.py", "return search_arxiv(q.strip())", "return search_arxiv(q)", "search: query no longer trimmed"),
    ("app.py", 'HTTPException(502, f"arXiv request failed', 'HTTPException(500, f"arXiv request failed', "search arXiv failure: status 502 -> 500"),
    ("app.py", 'HTTPException(409, "Paper is already', 'HTTPException(400, "Paper is already', "save duplicate: status 409 -> 400"),
    ("app.py", "arxiv_id = base_arxiv_id(p.arxiv_id)\n", "arxiv_id = p.arxiv_id\n", "save: version suffix no longer stripped from stored id"),
    ("app.py", 'authors=", ".join(p.authors)', 'authors=",".join(p.authors)', "save: author separator ', ' -> ','"),
    ("app.py", 'HTTPException(400, "Could not read that file as a PDF.")', 'HTTPException(422, "Could not read that file as a PDF.")', "upload unreadable PDF: status 400 -> 422"),
    ("app.py", 'HTTPException(422, "No text found', 'HTTPException(400, "No text found', "upload scanned PDF: status 422 -> 400"),
    ("app.py", "path.unlink(missing_ok=True)  # don't leave orphan files when the upload fails", "pass", "upload: orphan file cleanup on failure deleted"),
    ("app.py", 'title = meta["title"] or (file.filename or "Untitled upload")', 'title = meta["title"]', "upload: filename fallback for empty title removed"),
    ("app.py", 'if paper["summary"] and not force:', 'if paper["summary"]:', "summarize: force flag ignored"),
    ("app.py", "db.update_paper(paper_id, pdf_path=pdf_path, full_text=full_text)\n", "pass\n", "retry download: recovered text no longer persisted"),
    ("app.py", "if not full_text:\n            raise HTTPException(422", "if full_text is None:\n            raise HTTPException(422", "retry download: empty-text check `not` -> `is None`"),
    ("app.py", "db.update_paper(paper_id, summary=summary)", "pass", "summarize: summary no longer cached"),
    ("app.py", "question = body.question.strip()", "question = body.question", "ask: question not trimmed (blank check weakened)"),
    ("app.py", 'os.remove(paper["pdf_path"])', "pass", "delete: PDF file no longer removed"),
    ("app.py", "    db.delete_paper(paper_id)\n    if paper", "    if paper", "delete: DB row no longer deleted"),
    ("app.py", 'if truncated else None', 'if not truncated else None', "truncation_note condition inverted"),
    # ---- arxiv.py
    ("arxiv.py", '"start": 0', '"start": 1', "search: start offset 0 -> 1"),
    ("arxiv.py", "max_results=10", "max_results=5", "search: default max_results 10 -> 5"),
    ("arxiv.py", '"url": entry_id,', '"url": arxiv_id,', "search result url: link replaced by bare id"),
    ("arxiv.py", 'return " ".join((text or "").split())', 'return (text or "").strip()', "_clean: inner whitespace no longer collapsed"),
    ("arxiv.py", "    resp.raise_for_status()\n", "", "search: HTTP errors no longer raised"),
    ("arxiv.py", 'f"all:{query}"', "query", "search: 'all:' field prefix removed"),
    ("arxiv.py", "int(published[:4]) if", "int(published[:3]) if", "year parsing: wrong slice [:4] -> [:3]"),
    # ---- db.py
    ("db.py", "ORDER BY id DESC", "ORDER BY id ASC", "list_papers: newest-first -> oldest-first"),
    ("db.py", "arxiv_id TEXT UNIQUE,", "arxiv_id TEXT,", "schema: UNIQUE constraint on arxiv_id dropped"),
    ("db.py", "title TEXT NOT NULL,", "title TEXT,", "schema: NOT NULL on title dropped"),
    ("db.py", "WHERE arxiv_id = ?", "WHERE arxiv_id != ?", "find_by_arxiv_id: = -> !="),
    ("db.py", "(full_text IS NOT NULL) AS has_text", "(full_text IS NULL) AS has_text", "has_text flag inverted"),
    ("db.py", 'cols = "*" if full_text else LIST_COLS', "cols = LIST_COLS", "get_paper: full_text never returned"),
    ("db.py", "        conn.close()\n", "        pass\n", "connect(): connection no longer closed"),
    ("db.py", "        with conn:  # commit / rollback\n            yield conn", "        yield conn", "connect(): commit/rollback removed"),
    # ---- llm.py
    ("llm.py", "if not os.getenv", "if os.getenv", "_client: missing-key check inverted"),
    ("llm.py", "if len(full_text) <= MAX_PAPER_CHARS:", "if len(full_text) < MAX_PAPER_CHARS:", "prepare_text boundary: <= -> <"),
    ("llm.py", "return full_text[:MAX_PAPER_CHARS], True", "return full_text[:MAX_PAPER_CHARS - 1], True", "prepare_text: truncates one char short"),
    ("llm.py", "## Key Results", "## Results", "summary prompt: section heading 'Key Results' renamed"),
    ("llm.py", "If the paper does not contain the answer, say so plainly instead of guessing or using outside knowledge. ", "", "QA system prompt: 'answer only from paper' instruction removed"),
    ("llm.py", "re.DOTALL", "0", "extract_metadata: regex no longer spans newlines"),
    ("llm.py", "year if isinstance(year, int) else None", "year", "extract_metadata: year no longer validated as int"),
    ("llm.py", "return ask_claude(prompt, max_tokens=2000), truncated", "return ask_claude(prompt, max_tokens=20), truncated", "summarize: max_tokens 2000 -> 20"),
    ("llm.py", 'if b.type == "text")', "if True)", "ask_claude: non-text blocks no longer filtered"),
    ("llm.py", 'kwargs = {"system": system} if system else {}', "kwargs = {}", "ask_claude: system prompt never sent"),
    # ---- pdf.py
    ("pdf.py", 'r"v\\d+$"', 'r"v\\d$"', "base_arxiv_id: multi-digit versions not stripped"),
    ("pdf.py", '.replace("/", "_")', "", "download_pdf: '/' in old-style ids not sanitised"),
    ("pdf.py", "    resp.raise_for_status()\n", "", "download_pdf: HTTP errors ignored"),
    ("pdf.py", 'return "\\n".join(page.get_text() for page in doc).strip()', 'return "".join(page.get_text() for page in doc).strip()', "extract_text: pages joined without newline"),
    ("pdf.py", "doc[0].get_text().strip() if len(doc)", "doc[0].get_text() if len(doc)", "extract_first_page: strip() removed"),
    ("pdf.py", "timeout=60", "timeout=1", "download_pdf: timeout 60 -> 1"),
]


def run_pytest(workdir, timeout=120):
    try:
        p = subprocess.run(
            [sys.executable, "-W", "ignore", "-m", "pytest", "-x", "-q", "-p", "no:cacheprovider",
             "-p", "no:warnings", "tests"],
            cwd=workdir, capture_output=True, text=True, timeout=timeout)
        return p.returncode, p.stdout
    except subprocess.TimeoutExpired:
        return -1, "TIMEOUT"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--tests", required=True, help="folder containing the test files (copied as tests/)")
    ap.add_argument("--label", required=True)
    args = ap.parse_args()
    tests_dir = Path(args.tests).resolve()
    before = {f: (ROOT / f).read_bytes() for f in SOURCES}

    with tempfile.TemporaryDirectory(prefix="mut-") as tmp:
        work = Path(tmp)
        for f in SOURCES:
            shutil.copy(ROOT / f, work / f)
        shutil.copytree(ROOT / "static", work / "static")
        (work / "pytest.ini").write_text("[pytest]\n")
        shutil.copytree(tests_dir, work / "tests", ignore=shutil.ignore_patterns("__pycache__"))

        rc, out = run_pytest(work)
        if rc != 0:
            print("Baseline (unmutated) run FAILED; aborting.\n" + out[-1500:])
            sys.exit(2)
        print(f"[{args.label}] baseline OK: {out.strip().splitlines()[-1]}\n")

        results = []
        for i, (fname, old, new, desc) in enumerate(MUTANTS, 1):
            original = (ROOT / fname).read_text()
            assert original.count(old) == 1, f"mutant #{i}: snippet must occur once in {fname}: {old!r}"
            line = original[:original.index(old)].count("\n") + 1
            (work / fname).write_text(original.replace(old, new))
            try:
                rc, out = run_pytest(work)
            finally:
                (work / fname).write_text(original)  # restore the temp copy
            killed = rc != 0
            by = ""
            if killed:
                failed = [l for l in out.splitlines() if l.startswith("FAILED")]
                by = failed[0].split(" - ")[0][7:] if failed else ("timeout" if rc == -1 else "error")
            results.append(dict(id=i, file=fname, line=line, change=desc, killed=killed, killed_by=by))
            print(f"#{i:02d} {'KILLED  ' if killed else 'SURVIVED'} {fname}:{line}  {desc}" + (f"  <- {by}" if by else ""))

    k = sum(r["killed"] for r in results)
    print(f"\n[{args.label}] mutation score: {k}/{len(results)} killed = {100 * k / len(results):.1f}%")
    out_dir = ROOT / "mutation" / "results"
    out_dir.mkdir(exist_ok=True)
    (out_dir / f"{args.label}.json").write_text(json.dumps(results, indent=2))
    # sanity: the real source files must be byte-for-byte what they were before we started
    assert {f: (ROOT / f).read_bytes() for f in SOURCES} == before, "real source files were modified!"


if __name__ == "__main__":
    main()
