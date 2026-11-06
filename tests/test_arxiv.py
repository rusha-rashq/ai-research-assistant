import httpx
import pytest

import arxiv


def test_parses_entries(monkeypatch, fake_response, arxiv_xml):
    calls = {}

    def fake_get(url, **kw):
        calls.update(url=url, **kw)
        return fake_response(text=arxiv_xml)

    monkeypatch.setattr(httpx, "get", fake_get)
    results = arxiv.search_arxiv("transformers", max_results=5)

    assert calls["params"]["search_query"] == "all:transformers"
    assert calls["params"]["max_results"] == 5
    assert len(results) == 2
    r = results[0]
    assert r["arxiv_id"] == "2401.00001v2"
    assert r["title"] == "Attention Is Still All You Need"  # whitespace normalised
    assert r["abstract"] == "An abstract spanning lines."
    assert r["authors"] == ["Ada Lovelace", "Alan Turing"]
    assert r["year"] == 2024
    assert r["pdf_url"] == "https://arxiv.org/pdf/2401.00001v2"


def test_old_style_id_missing_year_and_authors(monkeypatch, fake_response, arxiv_xml):
    monkeypatch.setattr(httpx, "get", lambda *a, **k: fake_response(text=arxiv_xml))
    r = arxiv.search_arxiv("x")[1]
    assert r["arxiv_id"] == "cs/0101001v1"
    assert r["year"] is None
    assert r["authors"] == []


def test_no_results(monkeypatch, fake_response):
    xml = '<feed xmlns="http://www.w3.org/2005/Atom"></feed>'
    monkeypatch.setattr(httpx, "get", lambda *a, **k: fake_response(text=xml))
    assert arxiv.search_arxiv("nothing") == []


def test_http_error_propagates(monkeypatch, fake_response):
    monkeypatch.setattr(httpx, "get", lambda *a, **k: fake_response(status=503))
    with pytest.raises(httpx.HTTPStatusError):
        arxiv.search_arxiv("x")


def test_malformed_xml_raises(monkeypatch, fake_response):
    monkeypatch.setattr(httpx, "get", lambda *a, **k: fake_response(text="not xml"))
    with pytest.raises(Exception):
        arxiv.search_arxiv("x")


def test_clean_handles_none():
    assert arxiv._clean(None) == ""
    assert arxiv._clean("  a \n b ") == "a b"
