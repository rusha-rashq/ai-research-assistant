import json
from types import SimpleNamespace

import anthropic
import httpx
import pytest

import llm


class FakeMessages:
    def __init__(self, reply=None, error=None):
        self.reply, self.error, self.calls = reply, error, []

    def create(self, **kw):
        self.calls.append(kw)
        if self.error:
            raise self.error
        return SimpleNamespace(content=self.reply)


def text_block(t):
    return SimpleNamespace(type="text", text=t)


@pytest.fixture
def fake_claude(monkeypatch, api_key):
    def _install(reply="ok", error=None):
        if isinstance(reply, str):
            reply = [text_block(reply)]
        msgs = FakeMessages(reply, error)
        monkeypatch.setattr(llm.anthropic, "Anthropic", lambda: SimpleNamespace(messages=msgs))
        return msgs
    return _install


def api_error():
    return anthropic.APIError("kaboom", request=httpx.Request("POST", "http://x"), body=None)


# --- ask_claude ---------------------------------------------------------------
def test_missing_api_key_raises():
    with pytest.raises(llm.LLMError, match="ANTHROPIC_API_KEY"):
        llm.ask_claude("hi")


def test_ask_claude_joins_text_blocks_only(fake_claude):
    msgs = fake_claude([text_block("a"), SimpleNamespace(type="tool_use"), text_block("b")])
    assert llm.ask_claude("hi") == "ab"
    assert msgs.calls[0]["model"] == llm.MODEL
    assert "system" not in msgs.calls[0]


def test_ask_claude_passes_system_and_max_tokens(fake_claude):
    msgs = fake_claude("x")
    llm.ask_claude("hi", system="SYS", max_tokens=7)
    assert msgs.calls[0]["system"] == "SYS" and msgs.calls[0]["max_tokens"] == 7


def test_api_error_wrapped(fake_claude):
    fake_claude(error=api_error())
    with pytest.raises(llm.LLMError, match="Anthropic API error"):
        llm.ask_claude("hi")


# --- extract_metadata ---------------------------------------------------------
GOOD = {"title": " A Title ", "authors": ["X", "Y"], "year": 2023, "abstract": " Abs "}


def test_metadata_plain_json(fake_claude):
    fake_claude(json.dumps(GOOD))
    assert llm.extract_metadata("page") == {
        "title": "A Title", "authors": "X, Y", "year": 2023, "abstract": "Abs"}


def test_metadata_in_code_fence(fake_claude):
    fake_claude("Sure!\n```json\n" + json.dumps(GOOD) + "\n```")
    assert llm.extract_metadata("page")["title"] == "A Title"


def test_metadata_prompt_contains_page(fake_claude):
    msgs = fake_claude(json.dumps(GOOD))
    llm.extract_metadata("UNIQUE-PAGE-TEXT")
    assert "UNIQUE-PAGE-TEXT" in msgs.calls[0]["messages"][0]["content"]


def test_metadata_missing_and_null_fields(fake_claude):
    fake_claude('{"title": null, "authors": null, "year": null}')
    assert llm.extract_metadata("p") == {"title": "", "authors": "", "year": None, "abstract": ""}


def test_metadata_year_must_be_int(fake_claude):
    fake_claude('{"title": "t", "year": "2023"}')
    assert llm.extract_metadata("p")["year"] is None


def test_metadata_authors_string_kept(fake_claude):
    fake_claude('{"title": "t", "authors": "Solo Author"}')
    assert llm.extract_metadata("p")["authors"] == "Solo Author"


@pytest.mark.parametrize("reply", ["no json here", "{not: valid}", "[1, 2, 3]", ""])
def test_metadata_invalid_raises(fake_claude, reply):
    fake_claude(reply)
    with pytest.raises(llm.LLMError, match="valid JSON"):
        llm.extract_metadata("p")


# --- prepare_text / summarize / answer_question ---------------------------------
def test_prepare_text_short_unchanged():
    assert llm.prepare_text("abc") == ("abc", False)


def test_prepare_text_boundary_not_truncated():
    t = "a" * llm.MAX_PAPER_CHARS
    assert llm.prepare_text(t) == (t, False)


def test_prepare_text_truncates():
    t = "a" * (llm.MAX_PAPER_CHARS + 1)
    out, trunc = llm.prepare_text(t)
    assert trunc and len(out) == llm.MAX_PAPER_CHARS


def test_summarize(fake_claude):
    msgs = fake_claude("## Problem\n...")
    summary, trunc = llm.summarize("My Title", "body text")
    prompt = msgs.calls[0]["messages"][0]["content"]
    assert summary.startswith("## Problem") and trunc is False
    assert "My Title" in prompt and "body text" in prompt
    for h in ("## Problem", "## Method", "## Key Results", "## Limitations"):
        assert h in prompt


def test_summarize_truncated_flag(fake_claude):
    msgs = fake_claude("s")
    _, trunc = llm.summarize("t", "a" * (llm.MAX_PAPER_CHARS + 10))
    assert trunc is True
    assert "a" * (llm.MAX_PAPER_CHARS + 1) not in msgs.calls[0]["messages"][0]["content"]


def test_answer_question(fake_claude):
    msgs = fake_claude("The answer.")
    ans, trunc = llm.answer_question("T", "paper body", "What is X?")
    assert ans == "The answer." and trunc is False
    system = msgs.calls[0]["system"].lower()
    # The instruction must actually restrict the model to the paper's text
    assert "only" in system and "paper" in system
    assert "outside knowledge" in system
    assert "does not contain the answer" in system and "say so" in system
    content = msgs.calls[0]["messages"][0]["content"]
    assert "paper body" in content and "What is X?" in content


def test_summarize_propagates_llm_error(fake_claude):
    fake_claude(error=api_error())
    with pytest.raises(llm.LLMError):
        llm.summarize("t", "b")


# --- multi-line (pretty-printed) JSON from the model ------------------------------
PRETTY = json.dumps(GOOD, indent=2)
EXPECTED = {"title": "A Title", "authors": "X, Y", "year": 2023, "abstract": "Abs"}


def test_metadata_pretty_printed_json(fake_claude):
    assert "\n" in PRETTY
    fake_claude(PRETTY)
    assert llm.extract_metadata("page") == EXPECTED


def test_metadata_pretty_printed_json_in_code_fence_with_chatter(fake_claude):
    fake_claude("Here is the metadata:\n```json\n" + PRETTY + "\n```\nLet me know if you need more.")
    assert llm.extract_metadata("page") == EXPECTED


def test_metadata_multiline_abstract_value(fake_claude):
    # a JSON string can't contain raw newlines, but the object around it spans many lines
    reply = '{\n  "title": "T",\n  "authors": [\n    "X",\n    "Y"\n  ],\n  "year": 2020,\n  "abstract": "line1\\nline2"\n}'
    fake_claude(reply)
    out = llm.extract_metadata("page")
    assert out["authors"] == "X, Y" and out["abstract"] == "line1\nline2"


# --- summaries need room for four sections ---------------------------------------
def test_summary_gets_enough_tokens(fake_claude):
    msgs = fake_claude("## Problem\n...")
    llm.summarize("T", "body")
    assert msgs.calls[0]["max_tokens"] >= 1000
