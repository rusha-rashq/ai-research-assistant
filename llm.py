import json
import os
import re

import anthropic

MODEL = "claude-sonnet-5-5"


class LLMError(Exception):
    pass


def _client():
    if not os.getenv("ANTHROPIC_API_KEY"):
        raise LLMError("ANTHROPIC_API_KEY is not set. Add it to your .env file and restart the server.")
    return anthropic.Anthropic()


def ask_claude(prompt, system=None, max_tokens=1024):
    try:
        kwargs = {"system": system} if system else {}
        msg = _client().messages.create(
            model=MODEL, max_tokens=max_tokens,
            messages=[{"role": "user", "content": prompt}], **kwargs,
        )
    except anthropic.APIError as e:
        raise LLMError(f"Anthropic API error: {e}")
    return "".join(b.text for b in msg.content if b.type == "text")


def extract_metadata(first_page_text):
    """Ask Claude for title/authors/year/abstract of a paper from its first page."""
    prompt = (
        "Below is the text of the first page of a research paper. Extract its metadata and "
        "reply with ONLY a JSON object, no other text, with these keys:\n"
        '  "title": string,\n'
        '  "authors": list of author name strings,\n'
        '  "year": integer publication year (null if not found),\n'
        '  "abstract": string (the abstract text; empty string if not found).\n\n'
        f"First page:\n\"\"\"\n{first_page_text}\n\"\"\""
    )
    raw = ask_claude(prompt, max_tokens=1500)
    match = re.search(r"\{.*\}", raw, re.DOTALL)  # tolerate code fences / stray text
    try:
        data = json.loads(match.group(0)) if match else None
    except json.JSONDecodeError:
        data = None
    if not isinstance(data, dict):
        raise LLMError("The model did not return valid JSON for the paper metadata.")
    authors = data.get("authors") or []
    year = data.get("year")
    return {
        "title": str(data.get("title") or "").strip(),
        "authors": ", ".join(authors) if isinstance(authors, list) else str(authors),
        "year": year if isinstance(year, int) else None,
        "abstract": str(data.get("abstract") or "").strip(),
    }


# ~500k chars is roughly 125k tokens, which fits comfortably in the model's context window.
MAX_PAPER_CHARS = 500_000


def prepare_text(full_text):
    """Return (text, truncated) with the paper cut to MAX_PAPER_CHARS if needed."""
    if len(full_text) <= MAX_PAPER_CHARS:
        return full_text, False
    return full_text[:MAX_PAPER_CHARS], True


def summarize(title, full_text):
    text, truncated = prepare_text(full_text)
    prompt = (
        f"Summarize the research paper below, titled \"{title}\", based on its full text. "
        "Use Markdown with exactly these four sections as '##' headings:\n"
        "## Problem\n## Method\n## Key Results\n## Limitations\n\n"
        "Be specific: include concrete numbers, datasets and baselines where the paper gives them. "
        "For Limitations, include both limitations the authors state and any significant ones that "
        "are evident from the paper; say which is which. Only use information from the paper.\n\n"
        f"<paper>\n{text}\n</paper>"
    )
    return ask_claude(prompt, max_tokens=2000), truncated


QA_SYSTEM = (
    "You answer questions about a single research paper, using only the paper's text provided by the user. "
    "If the paper does not contain the answer, say so plainly instead of guessing or using outside knowledge. "
    "Answer in Markdown, concisely, and refer to sections, figures or tables of the paper when helpful."
)


def answer_question(title, full_text, question):
    text, truncated = prepare_text(full_text)
    prompt = f"<paper title=\"{title}\">\n{text}\n</paper>\n\nQuestion: {question}"
    return ask_claude(prompt, system=QA_SYSTEM, max_tokens=1500), truncated
