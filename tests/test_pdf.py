import httpx
import pymupdf
import pytest

import pdf


@pytest.mark.parametrize("raw,expected", [
    ("2401.00001v2", "2401.00001"),
    ("2401.00001", "2401.00001"),
    ("cs/0101001v1", "cs/0101001"),
    ("2401.00001v12", "2401.00001"),
    ("", ""),
])
def test_base_arxiv_id(raw, expected):
    assert pdf.base_arxiv_id(raw) == expected


def test_download_pdf_writes_file(monkeypatch, fake_response, pdf_bytes, temp_storage):
    seen = {}

    def fake_get(url, **kw):
        seen["url"] = url
        return fake_response(content=pdf_bytes())

    monkeypatch.setattr(httpx, "get", fake_get)
    path = pdf.download_pdf("2401.00001v2")
    assert seen["url"] == "https://arxiv.org/pdf/2401.00001v2"
    assert path.parent == temp_storage / "pdfs"
    assert path.name == "2401.00001.pdf"
    assert path.read_bytes().startswith(b"%PDF")


def test_download_old_style_id_slash_replaced(monkeypatch, fake_response, pdf_bytes):
    monkeypatch.setattr(httpx, "get", lambda *a, **k: fake_response(content=pdf_bytes()))
    assert pdf.download_pdf("cs/0101001v1").name == "cs_0101001.pdf"


def test_download_http_error(monkeypatch, fake_response, temp_storage):
    monkeypatch.setattr(httpx, "get", lambda *a, **k: fake_response(status=404))
    with pytest.raises(httpx.HTTPStatusError):
        pdf.download_pdf("2401.00001")
    assert list((temp_storage / "pdfs").iterdir()) == []


def test_extract_text_multi_page(tmp_path, pdf_bytes):
    p = tmp_path / "a.pdf"
    p.write_bytes(pdf_bytes(["First page text", "Second page text"]))
    text = pdf.extract_text(p)
    assert "First page text" in text and "Second page text" in text


def test_extract_first_page_only(tmp_path, pdf_bytes):
    p = tmp_path / "a.pdf"
    p.write_bytes(pdf_bytes(["First page text", "Second page text"]))
    first = pdf.extract_first_page(p)
    assert "First" in first and "Second" not in first


def test_blank_pdf_gives_empty_text(tmp_path, pdf_bytes):
    p = tmp_path / "blank.pdf"
    p.write_bytes(pdf_bytes([""]))
    assert pdf.extract_text(p) == ""
    assert pdf.extract_first_page(p) == ""


def test_extract_invalid_file_raises(tmp_path):
    p = tmp_path / "bad.pdf"
    p.write_bytes(b"this is not a pdf")
    with pytest.raises(pymupdf.FileDataError):
        pdf.extract_text(p)


def test_fetch_and_extract(monkeypatch, fake_response, pdf_bytes):
    monkeypatch.setattr(httpx, "get", lambda *a, **k: fake_response(content=pdf_bytes(["Body text"])))
    path, text = pdf.fetch_and_extract("2401.00001v1")
    assert path.endswith("2401.00001.pdf")
    assert "Body text" in text


def test_pages_stay_separated_in_real_pdf(tmp_path, pdf_bytes):
    p = tmp_path / "a.pdf"
    p.write_bytes(pdf_bytes(["endofpageone", "startofpagetwo"]))
    words = pdf.extract_text(p).split()
    assert "endofpageone" in words and "startofpagetwo" in words  # not run together


def test_extract_text_separates_pages_even_without_trailing_newline(monkeypatch, tmp_path):
    """Pages whose text doesn't end in a newline must still not run into the next page."""
    class FakePage:
        def __init__(self, text):
            self.text = text

        def get_text(self):
            return self.text

    class FakeDoc(list):
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    monkeypatch.setattr(pdf.fitz, "open", lambda path: FakeDoc([FakePage("end of page one"),
                                                                FakePage("start of page two")]))
    words = pdf.extract_text("ignored.pdf").split()
    assert words == ["end", "of", "page", "one", "start", "of", "page", "two"]
