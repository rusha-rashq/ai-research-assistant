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
