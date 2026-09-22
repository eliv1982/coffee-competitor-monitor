"""Input-boundary tests: oversized/malformed/mismatched uploads -> correct 4xx status codes.
OpenAI is always mocked; no live calls."""
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from backend.errors import PayloadTooLargeError
from backend.limits import is_pdf_signature, read_request_body_limited, sniff_image_mime
from backend.models.schemas import CompetitorAnalysis, ImageAnalysis

PNG_BYTES = b"\x89PNG\r\n\x1a\n" + b"0" * 64
JPEG_BYTES = b"\xff\xd8\xff\xe0" + b"0" * 64
GIF_BYTES = b"GIF89a" + b"0" * 64
WEBP_BYTES = b"RIFF" + b"\x00\x00\x00\x00" + b"WEBP" + b"0" * 64
NOT_AN_IMAGE = b"this is definitely not image data" * 4
PDF_BYTES = b"%PDF-1.4\n" + b"0" * 200
NOT_A_PDF = b"not a pdf file at all" * 10


# --- unit tests: signature sniffing ---

def test_sniff_image_mime_recognizes_each_format():
    assert sniff_image_mime(PNG_BYTES) == "image/png"
    assert sniff_image_mime(JPEG_BYTES) == "image/jpeg"
    assert sniff_image_mime(GIF_BYTES) == "image/gif"
    assert sniff_image_mime(WEBP_BYTES) == "image/webp"


def test_sniff_image_mime_rejects_non_image():
    assert sniff_image_mime(NOT_AN_IMAGE) is None
    assert sniff_image_mime(b"") is None


def test_is_pdf_signature():
    assert is_pdf_signature(PDF_BYTES) is True
    assert is_pdf_signature(NOT_A_PDF) is False
    assert is_pdf_signature(b"") is False


# --- endpoint-level boundary tests ---

def _mock_analyze_text(monkeypatch):
    fake = MagicMock(return_value=CompetitorAnalysis(summary="ok"))
    monkeypatch.setattr("backend.routers.analyze.analyze_text", fake)
    return fake


def _mock_analyze_image(monkeypatch):
    fake = MagicMock(return_value=ImageAnalysis(description="ok"))
    monkeypatch.setattr("backend.routers.analyze.analyze_image_from_base64", fake)
    return fake


def test_analyze_text_too_short_returns_400(client):
    resp = client.post("/analyze_text", json={"text": "short"})
    assert resp.status_code == 400
    assert "error" in resp.json()


def test_analyze_text_wrong_content_type_returns_415(client):
    resp = client.post(
        "/analyze_text", content=b"just some text body", headers={"content-type": "text/plain"}
    )
    assert resp.status_code == 415


def test_analyze_text_malformed_json_returns_400(client):
    resp = client.post(
        "/analyze_text", content=b"{not valid json", headers={"content-type": "application/json"}
    )
    assert resp.status_code == 400


def test_analyze_text_oversized_returns_413(client, monkeypatch):
    monkeypatch.setenv("MAX_TEXT_CHARS", "20")
    _mock_analyze_text(monkeypatch)
    resp = client.post("/analyze_text", json={"text": "x" * 500})
    assert resp.status_code == 413


def test_analyze_text_valid_json_returns_200(client, monkeypatch):
    fake = _mock_analyze_text(monkeypatch)
    resp = client.post("/analyze_text", json={"text": "Our coffee shop has great espresso and pastries."})
    assert resp.status_code == 200
    assert resp.json()["summary"] == "ok"
    fake.assert_called_once()


def test_analyze_text_multipart_pdf_wrong_signature_returns_415(client):
    resp = client.post(
        "/analyze_text",
        files={"file": ("doc.pdf", NOT_A_PDF, "application/pdf")},
    )
    assert resp.status_code == 415


def test_analyze_text_multipart_pdf_oversized_returns_413(client, monkeypatch):
    monkeypatch.setenv("MAX_PDF_BYTES", "50")
    big_pdf = PDF_BYTES + b"0" * 1000
    resp = client.post(
        "/analyze_text",
        files={"file": ("doc.pdf", big_pdf, "application/pdf")},
    )
    assert resp.status_code == 413


def test_analyze_text_multipart_non_pdf_extension_returns_415(client):
    resp = client.post(
        "/analyze_text",
        files={"file": ("doc.txt", b"hello world", "text/plain")},
    )
    assert resp.status_code == 415


def test_analyze_image_empty_upload_returns_400(client):
    resp = client.post("/analyze_image", files={"file": ("empty.png", b"", "image/png")})
    assert resp.status_code == 400


def test_analyze_image_signature_mismatch_returns_415(client):
    resp = client.post("/analyze_image", files={"file": ("fake.png", NOT_AN_IMAGE, "image/png")})
    assert resp.status_code == 415


def test_analyze_image_oversized_returns_413(client, monkeypatch):
    monkeypatch.setenv("MAX_IMAGE_BYTES", "50")
    big_image = PNG_BYTES + b"0" * 1000
    resp = client.post("/analyze_image", files={"file": ("big.png", big_image, "image/png")})
    assert resp.status_code == 413


def test_analyze_image_valid_png_returns_200(client, monkeypatch):
    fake = _mock_analyze_image(monkeypatch)
    resp = client.post("/analyze_image", files={"file": ("ok.png", PNG_BYTES, "image/png")})
    assert resp.status_code == 200
    assert resp.json()["description"] == "ok"
    fake.assert_called_once()


def test_missing_api_key_returns_503(client, monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "")
    resp = client.post("/analyze_text", json={"text": "Enough characters to pass validation here."})
    assert resp.status_code == 503


# --- read_request_body_limited: bounds the actual bytes read regardless of any header ---
# (a Content-Length pre-check is best-effort — the header can be absent or simply wrong; this
# is the real enforcement point for /analyze_text's JSON body, see backend.routers.analyze)

async def _fake_stream(chunks):
    for c in chunks:
        yield c


def _fake_request(chunks):
    return SimpleNamespace(stream=lambda: _fake_stream(chunks))


def test_read_request_body_limited_raises_when_over_cap():
    import asyncio

    request = _fake_request([b"x" * 100, b"y" * 100])
    with pytest.raises(PayloadTooLargeError):
        asyncio.run(read_request_body_limited(request, max_bytes=150, what="Тело запроса"))


def test_read_request_body_limited_returns_body_within_cap():
    import asyncio

    request = _fake_request([b"x" * 50, b"y" * 50])
    result = asyncio.run(read_request_body_limited(request, max_bytes=150, what="Тело запроса"))
    assert result == b"x" * 50 + b"y" * 50
