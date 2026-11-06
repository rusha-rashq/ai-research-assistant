"""Launch the real FastAPI app for the browser tests, with arXiv and Anthropic mocked at the
server level (inside this server process). Usage: server_entry.py <project_root> <data_dir> <port>

- cwd is a temp directory (with a copy of static/), so the app's relative "data/" is temporary.
- httpx.get is replaced: arXiv search returns canned Atom XML, PDF downloads return a generated PDF,
  anything else raises.
- anthropic.Anthropic is replaced by a fake client with canned replies.
"""
import os
import shutil
import sys
from pathlib import Path
from types import SimpleNamespace

root, data_dir, port = Path(sys.argv[1]), Path(sys.argv[2]), int(sys.argv[3])
data_dir.mkdir(parents=True, exist_ok=True)
shutil.copytree(root / "static", data_dir / "static")
os.chdir(data_dir)
sys.path.insert(0, str(root))
os.environ["ANTHROPIC_API_KEY"] = "fake-e2e-key"  # never used: the client is faked below

import httpx  # noqa: E402
import pymupdf  # noqa: E402
import anthropic  # noqa: E402

LONG_ABSTRACT = " ".join(
    f"Sentence {i} of a deliberately long abstract that must overflow the three-line clamp." for i in range(1, 25))

ATOM = """<?xml version="1.0" encoding="UTF-8"?>
<feed xmlns="http://www.w3.org/2005/Atom">
  <entry>
    <id>http://arxiv.org/abs/2401.00001v1</id>
    <published>2024-01-02T00:00:00Z</published>
    <title>Graph Neural Networks for Testing</title>
    <summary>{long}</summary>
    <author><name>Ada Lovelace</name></author>
    <author><name>Alan Turing</name></author>
  </entry>
  <entry>
    <id>http://arxiv.org/abs/2302.00002v2</id>
    <published>2023-02-03T00:00:00Z</published>
    <title>A Short Note on Mocks</title>
    <summary>Short abstract.</summary>
    <author><name>Grace Hopper</name></author>
  </entry>
</feed>""".replace("{long}", LONG_ABSTRACT)


def make_pdf(text):
    doc = pymupdf.open()
    doc.new_page().insert_text((72, 72), text)
    data = doc.tobytes()
    doc.close()
    return data


class Resp:
    def __init__(self, text="", content=b""):
        self.text, self.content, self.status_code = text, content, 200

    def raise_for_status(self):
        pass


def fake_get(url, **kw):
    if "export.arxiv.org/api/query" in url:
        return Resp(text=ATOM)
    if "arxiv.org/pdf/" in url:
        return Resp(content=make_pdf("Full text of the mocked arXiv paper about graph networks."))
    raise RuntimeError(f"e2e server: unexpected network call to {url}")


httpx.get = fake_get


class FakeMessages:
    def create(self, **kw):
        prompt = kw["messages"][0]["content"]
        if "reply with ONLY a JSON object" in prompt:
            text = ('{"title": "E2E Uploaded Paper Title", "authors": ["Up Loader", "Pat Author"], '
                    '"year": 2021, "abstract": "Uploaded abstract."}')
        elif "Summarize the research paper" in prompt:
            text = "## Problem\nE2E mocked summary problem.\n\n## Method\nMocked method.\n\n## Key Results\nMocked.\n\n## Limitations\nNone."
        else:
            question = prompt.rsplit("Question:", 1)[-1].strip()
            text = f"E2E mocked answer to: {question}"
        return SimpleNamespace(content=[SimpleNamespace(type="text", text=text)])


anthropic.Anthropic = lambda *a, **k: SimpleNamespace(messages=FakeMessages())

import uvicorn  # noqa: E402
import app  # noqa: E402

uvicorn.run(app.app, host="127.0.0.1", port=port, log_level="warning")
