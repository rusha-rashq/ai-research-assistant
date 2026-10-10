import xml.etree.ElementTree as ET

import httpx

ARXIV_URL = "https://export.arxiv.org/api/query"
HEADERS = {"User-Agent": "ai-research-assistant/0.1 (homework project)"}
NS = {"a": "http://www.w3.org/2005/Atom"}


def _clean(text):
    return " ".join((text or "").split())


def search_arxiv(query, max_results=10):
    resp = httpx.get(
        ARXIV_URL,
        params={"search_query": f"all:{query}", "start": 0, "max_results": max_results},
        headers=HEADERS,
        timeout=20,
        follow_redirects=True,
    )
    resp.raise_for_status()
    root = ET.fromstring(resp.text)
    results = []
    for e in root.findall("a:entry", NS):
        entry_id = e.findtext("a:id", "", NS)  # e.g. http://arxiv.org/abs/2401.00001v2
        arxiv_id = entry_id.split("/abs/")[-1]
        published = e.findtext("a:published", "", NS)
        results.append({
            "arxiv_id": arxiv_id,
            "title": _clean(e.findtext("a:title", "", NS)),
            "authors": [_clean(a.findtext("a:name", "", NS)) for a in e.findall("a:author", NS)],
            "year": int(published[:4]) if published[:4].isdigit() else None,
            "abstract": _clean(e.findtext("a:summary", "", NS)),
            "url": entry_id,
            "pdf_url": f"https://arxiv.org/pdf/{arxiv_id}",
        })
    return results
