"""End-to-end router-level tests for the corrective-pass fixes that only show up when a
router actually calls a service with the right arguments: parser config wiring (item 3),
sanitized/correctly-classified Selenium failures (item 4), request-size limits (item 5),
URL scheme/edge cases (item 6), and configured OpenAI timeouts (item 7). OpenAI and the
parser/Selenium layer are always mocked; no live calls or real network."""
from unittest.mock import MagicMock

from backend.models.schemas import CompetitorAnalysis, UrlAnalysis
from backend.services.parser_service import (
    SELENIUM_NOT_INSTALLED_MESSAGE,
    SELENIUM_TIMEOUT_MESSAGE,
    SELENIUM_UPSTREAM_ERROR_MESSAGE,
)

PDF_BYTES = b"%PDF-1.4\n" + b"0" * 200


# === item 3: parser config (connect timeout / redirects / response-byte cap) wired through ===

def test_parse_demo_passes_configured_httpx_settings_to_parser(client, monkeypatch):
    monkeypatch.setenv("PARSER_CONNECT_TIMEOUT", "3.5")
    monkeypatch.setenv("MAX_REDIRECTS", "2")
    monkeypatch.setenv("MAX_REMOTE_RESPONSE_BYTES", "12345")
    mock_parse = MagicMock(return_value=("Title", "H1", "A long enough first paragraph of text.", ""))
    monkeypatch.setattr("backend.routers.parse_demo.parse_url_auto", mock_parse)
    monkeypatch.setattr(
        "backend.routers.parse_demo.analyze_parsed_page", MagicMock(return_value=CompetitorAnalysis(summary="ok"))
    )

    resp = client.post("/parse_demo", json={"url": "https://example.com"})

    assert resp.status_code == 200
    kwargs = mock_parse.call_args.kwargs
    assert kwargs["connect_timeout"] == 3.5
    assert kwargs["max_redirects"] == 2
    assert kwargs["max_response_bytes"] == 12345


def test_parse_demo_batch_passes_configured_httpx_settings_to_parser(client, monkeypatch):
    monkeypatch.setenv("COMPETITOR_URLS", "https://example.com")
    monkeypatch.setenv("PARSER_CONNECT_TIMEOUT", "7.0")
    monkeypatch.setenv("MAX_REDIRECTS", "1")
    monkeypatch.setenv("MAX_REMOTE_RESPONSE_BYTES", "999")
    mock_parse = MagicMock(return_value=("Title", "H1", "A long enough first paragraph of text.", ""))
    monkeypatch.setattr("backend.routers.parse_demo.parse_url_auto", mock_parse)
    monkeypatch.setattr(
        "backend.routers.parse_demo.analyze_parsed_page", MagicMock(return_value=CompetitorAnalysis(summary="ok"))
    )

    resp = client.post("/parse_demo/batch")

    assert resp.status_code == 200
    kwargs = mock_parse.call_args.kwargs
    assert kwargs["connect_timeout"] == 7.0
    assert kwargs["max_redirects"] == 1
    assert kwargs["max_response_bytes"] == 999


def test_analyze_url_passes_configured_response_bytes_as_page_source_cap(client, monkeypatch):
    monkeypatch.setenv("MAX_REMOTE_RESPONSE_BYTES", "54321")
    mock_screenshot = MagicMock(
        return_value=(b"\x89PNG\r\n\x1a\n" + b"0" * 32, "image/png", "some page text", "")
    )
    monkeypatch.setattr("backend.routers.analyze_url.get_url_screenshot_and_text", mock_screenshot)
    monkeypatch.setattr(
        "backend.routers.analyze_url.analyze_url_unified", MagicMock(return_value=UrlAnalysis(summary="ok"))
    )

    resp = client.post("/analyze_url", json={"url": "https://example.com"})

    assert resp.status_code == 200
    assert mock_screenshot.call_args.kwargs["max_page_source_chars"] == 54321


# === item 4: sanitized + correctly classified Selenium failures ===

def test_analyze_url_selenium_timeout_maps_to_504(client, monkeypatch):
    monkeypatch.setattr(
        "backend.routers.analyze_url.get_url_screenshot_and_text",
        MagicMock(return_value=(None, "image/png", "", SELENIUM_TIMEOUT_MESSAGE)),
    )
    resp = client.post("/analyze_url", json={"url": "https://example.com"})
    assert resp.status_code == 504


def test_analyze_url_selenium_generic_failure_maps_to_502(client, monkeypatch):
    monkeypatch.setattr(
        "backend.routers.analyze_url.get_url_screenshot_and_text",
        MagicMock(return_value=(None, "image/png", "", SELENIUM_UPSTREAM_ERROR_MESSAGE)),
    )
    resp = client.post("/analyze_url", json={"url": "https://example.com"})
    assert resp.status_code == 502


def test_analyze_url_selenium_not_installed_maps_to_503(client, monkeypatch):
    monkeypatch.setattr(
        "backend.routers.analyze_url.get_url_screenshot_and_text",
        MagicMock(return_value=(None, "image/png", "", SELENIUM_NOT_INSTALLED_MESSAGE)),
    )
    resp = client.post("/analyze_url", json={"url": "https://example.com"})
    assert resp.status_code == 503


def test_parse_demo_selenium_timeout_maps_to_504(client, monkeypatch):
    monkeypatch.setattr(
        "backend.routers.parse_demo.parse_url_auto",
        MagicMock(return_value=("", "", "", SELENIUM_TIMEOUT_MESSAGE)),
    )
    resp = client.post("/parse_demo", json={"url": "https://example.com"})
    assert resp.status_code == 504


def test_parse_demo_non_timeout_failure_maps_to_502(client, monkeypatch):
    monkeypatch.setattr(
        "backend.routers.parse_demo.parse_url_auto",
        MagicMock(return_value=("", "", "", SELENIUM_UPSTREAM_ERROR_MESSAGE)),
    )
    resp = client.post("/parse_demo", json={"url": "https://example.com"})
    assert resp.status_code == 502


# === item 5: hard-limit gaps ===

def test_analyze_text_json_body_over_limit_without_content_length_returns_413(client, monkeypatch):
    """A body sent without a (reliable) Content-Length header must still be bounded — the
    bounded read (backend.limits.read_request_body_limited), not the best-effort header
    pre-check, is what actually enforces this."""
    monkeypatch.setenv("MAX_REQUEST_BODY_BYTES", "100")

    def body_stream():
        yield b'{"text": "'
        yield b"x" * 1000
        yield b'"}'

    resp = client.post("/analyze_text", content=body_stream(), headers={"content-type": "application/json"})
    assert resp.status_code == 413


def test_analyze_text_multipart_too_many_fields_returns_400(client):
    data = {f"field{i}": "value" for i in range(20)}
    resp = client.post(
        "/analyze_text", data=data, files={"file": ("x.pdf", PDF_BYTES, "application/pdf")}
    )
    assert resp.status_code == 400


def test_analyze_text_multipart_too_many_files_returns_400(client):
    resp = client.post(
        "/analyze_text",
        files=[
            ("file", ("a.pdf", PDF_BYTES, "application/pdf")),
            ("extra_file", ("b.pdf", PDF_BYTES, "application/pdf")),
        ],
    )
    assert resp.status_code == 400


# === item 6: URL normalization / malformed-input edge cases ===

def test_parse_demo_malformed_port_returns_400_not_500(client):
    resp = client.post("/parse_demo", json={"url": "http://example.com:bad/"})
    assert resp.status_code == 400


def test_analyze_url_malformed_port_returns_400_not_500(client):
    resp = client.post("/analyze_url", json={"url": "http://example.com:bad/"})
    assert resp.status_code == 400


def test_parse_demo_mixed_case_scheme_not_double_prefixed(client, monkeypatch):
    mock_parse = MagicMock(return_value=("Title", "H1", "A long enough first paragraph of text.", ""))
    monkeypatch.setattr("backend.routers.parse_demo.parse_url_auto", mock_parse)
    monkeypatch.setattr(
        "backend.routers.parse_demo.analyze_parsed_page", MagicMock(return_value=CompetitorAnalysis(summary="ok"))
    )

    resp = client.post("/parse_demo", json={"url": "HTTP://example.com"})

    assert resp.status_code == 200
    called_url = mock_parse.call_args.args[0]
    assert called_url == "HTTP://example.com"  # left as-is, not "https://HTTP://example.com"


# === item 7: configured OpenAI timeout actually reaches every analyze_* call ===

def test_analyze_text_passes_configured_openai_timeout(client, monkeypatch):
    monkeypatch.setenv("OPENAI_TIMEOUT", "12.5")
    mock = MagicMock(return_value=CompetitorAnalysis(summary="ok"))
    monkeypatch.setattr("backend.routers.analyze.analyze_text", mock)

    client.post("/analyze_text", json={"text": "A coffee shop with excellent pastries and espresso."})

    assert mock.call_args.kwargs["timeout"] == 12.5


def test_analyze_image_passes_configured_openai_timeout(client, monkeypatch):
    monkeypatch.setenv("OPENAI_TIMEOUT", "13.5")
    from backend.models.schemas import ImageAnalysis

    mock = MagicMock(return_value=ImageAnalysis(description="ok"))
    monkeypatch.setattr("backend.routers.analyze.analyze_image_from_base64", mock)

    client.post("/analyze_image", files={"file": ("ok.png", b"\x89PNG\r\n\x1a\n" + b"0" * 64, "image/png")})

    assert mock.call_args.kwargs["timeout"] == 13.5


def test_parse_demo_passes_configured_openai_timeout_and_ai_text_cap(client, monkeypatch):
    monkeypatch.setenv("OPENAI_TIMEOUT", "14.5")
    monkeypatch.setenv("MAX_AI_TEXT_CHARS", "777")
    monkeypatch.setattr(
        "backend.routers.parse_demo.parse_url_auto",
        MagicMock(return_value=("Title", "H1", "A long enough first paragraph of text.", "")),
    )
    mock_analyze = MagicMock(return_value=CompetitorAnalysis(summary="ok"))
    monkeypatch.setattr("backend.routers.parse_demo.analyze_parsed_page", mock_analyze)

    client.post("/parse_demo", json={"url": "https://example.com"})

    assert mock_analyze.call_args.kwargs["timeout"] == 14.5
    assert mock_analyze.call_args.kwargs["max_ai_text_chars"] == 777


def test_analyze_url_passes_configured_openai_timeout(client, monkeypatch):
    monkeypatch.setenv("OPENAI_TIMEOUT", "15.5")
    monkeypatch.setattr(
        "backend.routers.analyze_url.get_url_screenshot_and_text",
        MagicMock(return_value=(b"\x89PNG\r\n\x1a\n" + b"0" * 32, "image/png", "some page text", "")),
    )
    mock_analyze = MagicMock(return_value=UrlAnalysis(summary="ok"))
    monkeypatch.setattr("backend.routers.analyze_url.analyze_url_unified", mock_analyze)

    client.post("/analyze_url", json={"url": "https://example.com"})

    assert mock_analyze.call_args.kwargs["timeout"] == 15.5
