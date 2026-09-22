"""App-level smoke tests: health, history, static route, OpenAPI, and key request/response
contracts. OpenAI/Selenium are mocked where a request would otherwise reach them."""
from unittest.mock import MagicMock

from fastapi.testclient import TestClient

from backend.models.schemas import CompetitorAnalysis, UrlAnalysis


def test_health(client):
    resp = client.get("/health")
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "healthy"


def test_ping(client):
    resp = client.get("/api/ping")
    assert resp.status_code == 200
    assert resp.json()["ok"] is True


def test_root(client):
    resp = client.get("/")
    assert resp.status_code == 200
    assert "docs" in resp.json()


def test_static_index_served(client):
    resp = client.get("/static/index.html")
    assert resp.status_code == 200
    assert "text/html" in resp.headers["content-type"]


def test_openapi_schema_generates_and_lists_endpoints(client):
    resp = client.get("/openapi.json")
    assert resp.status_code == 200
    schema = resp.json()
    for path in ("/analyze_text", "/analyze_image", "/analyze_url", "/parse_demo", "/parse_demo/batch", "/history"):
        assert path in schema["paths"], f"{path} missing from OpenAPI schema"
    # /analyze_text should document a real request body, not be contract-less (see docs.md).
    assert "requestBody" in schema["paths"]["/analyze_text"]["post"]


def test_parse_demo_batch_has_meaningful_response_schema(client):
    """/parse_demo/batch previously had no response_model at all, so its OpenAPI entry
    documented no response shape — now it must (ParseDemoBatchResponse: results + total)."""
    resp = client.get("/openapi.json")
    schema = resp.json()
    responses = schema["paths"]["/parse_demo/batch"]["post"]["responses"]
    ok_schema = responses["200"]["content"]["application/json"]["schema"]
    # $ref to a real component schema, not an empty/untyped object.
    ref = ok_schema.get("$ref") or ""
    assert "ParseDemoBatchResponse" in ref
    component = schema["components"]["schemas"]["ParseDemoBatchResponse"]
    assert set(component["properties"].keys()) == {"results", "total"}


def test_history_empty_by_default(client):
    resp = client.get("/history")
    assert resp.status_code == 200
    body = resp.json()
    assert body["items"] == []
    assert body["total"] == 0


def test_history_roundtrip_after_analysis(client, monkeypatch):
    monkeypatch.setattr(
        "backend.routers.analyze.analyze_text", MagicMock(return_value=CompetitorAnalysis(summary="great shop"))
    )
    resp = client.post("/analyze_text", json={"text": "A coffee shop with excellent pastries and espresso."})
    assert resp.status_code == 200

    hist = client.get("/history").json()
    assert hist["total"] == 1
    assert hist["items"][0]["request_type"] == "text"
    assert hist["items"][0]["result"]["summary"] == "great shop"


def test_history_clear(client, monkeypatch):
    monkeypatch.setattr(
        "backend.routers.analyze.analyze_text", MagicMock(return_value=CompetitorAnalysis(summary="x"))
    )
    client.post("/analyze_text", json={"text": "A coffee shop with excellent pastries and espresso."})
    resp = client.delete("/history")
    assert resp.status_code == 200
    assert client.get("/history").json()["total"] == 0


def test_parse_demo_batch_without_competitor_urls_returns_400(client):
    resp = client.post("/parse_demo/batch")
    assert resp.status_code == 400


def test_analyze_url_invalid_destination_returns_400(client):
    # loopback address -> rejected by the shared SSRF policy before any Selenium/OpenAI call
    resp = client.post("/analyze_url", json={"url": "http://127.0.0.1:9/"})
    assert resp.status_code == 400


def test_unexpected_internal_error_is_sanitized_and_returns_500(app_env, monkeypatch):
    def boom(*args, **kwargs):
        raise RuntimeError("some sensitive internal detail that must not leak")

    monkeypatch.setattr("backend.routers.analyze.analyze_text", boom)
    # Starlette's TestClient re-raises server exceptions by default (useful for debugging),
    # even though the real HTTP response was already sent by our handler; disable that here
    # so we can assert on the actual sanitized response a real client would receive.
    from backend.main import app

    with TestClient(app, base_url="http://127.0.0.1", raise_server_exceptions=False) as unsafe_client:
        resp = unsafe_client.post(
            "/analyze_text", json={"text": "A coffee shop with excellent pastries and espresso."}
        )
    assert resp.status_code == 500
    body = resp.json()
    assert "sensitive internal detail" not in body["error"]
    assert body["error"] == "Внутренняя ошибка сервера."


def test_validation_error_returns_422(client):
    resp = client.post("/parse_demo", json={})  # missing required "url"
    assert resp.status_code == 422


def test_analyze_url_response_contract(client, monkeypatch):
    monkeypatch.setattr(
        "backend.routers.analyze_url.get_url_screenshot_and_text",
        MagicMock(return_value=(b"\x89PNG\r\n\x1a\n" + b"0" * 32, "image/png", "some page text", "")),
    )
    monkeypatch.setattr(
        "backend.routers.analyze_url.analyze_url_unified",
        MagicMock(return_value=UrlAnalysis(summary="Nice site", design_score=7)),
    )
    resp = client.post("/analyze_url", json={"url": "https://example.com"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["url"] == "https://example.com"
    assert body["analysis"]["summary"] == "Nice site"
    assert body["analysis"]["design_score"] == 7
