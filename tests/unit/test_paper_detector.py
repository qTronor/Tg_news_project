import pytest
from paper_detector.detector import detect


def _msg(urls=None, text="", media=None):
    return {
        "urls": urls or [],
        "cleaned_text": text,
        "media": media or {},
    }


def test_detect_arxiv_url():
    is_paper, source_type, url = detect(_msg(urls=["https://arxiv.org/abs/2401.00001"]))
    assert is_paper is True
    assert source_type == "arxiv"
    assert "arxiv" in url


def test_detect_arxiv_pdf_url():
    is_paper, source_type, url = detect(_msg(urls=["https://arxiv.org/pdf/2401.00001"]))
    assert is_paper is True
    assert source_type == "arxiv"


def test_detect_openreview_url():
    is_paper, source_type, url = detect(_msg(urls=["https://openreview.net/forum?id=AbCdEf123"]))
    assert is_paper is True
    assert source_type == "openreview"


def test_detect_pdf_url():
    is_paper, source_type, url = detect(_msg(urls=["https://example.com/paper.pdf"]))
    assert is_paper is True
    assert source_type == "pdf_url"


def test_detect_doi_url():
    is_paper, source_type, url = detect(_msg(urls=["https://doi.org/10.1234/example"]))
    assert is_paper is True
    assert source_type == "doi"


def test_detect_telegram_pdf_attachment():
    is_paper, source_type, url = detect(_msg(media={"type": "document", "mime_type": "application/pdf"}))
    assert is_paper is True
    assert source_type == "telegram_file"
    assert url is None


def test_ignore_regular_news():
    is_paper, source_type, url = detect(_msg(text="Новости политики и экономики сегодня"))
    assert is_paper is False


def test_keyword_detection_benchmark():
    is_paper, source_type, _ = detect(_msg(text="New benchmark released for language models"))
    assert is_paper is True
    assert source_type == "webpage"


def test_keyword_detection_arxiv_word():
    is_paper, source_type, _ = detect(_msg(text="Опубликован на arXiv новый preprint"))
    assert is_paper is True


def test_url_takes_priority_over_keyword():
    is_paper, source_type, url = detect(_msg(
        urls=["https://arxiv.org/abs/2401.99999"],
        text="some text with benchmark"
    ))
    assert source_type == "arxiv"
