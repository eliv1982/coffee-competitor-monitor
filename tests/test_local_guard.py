"""Tests for backend.local_guard — the Host-header and same-origin checks that stand in for
authentication on this local, unauthenticated service (see docs.md). All requests go through
the real ASGI app via TestClient; no real network involved."""
from unittest.mock import MagicMock

from backend.models.schemas import CompetitorAnalysis


def _mock_analyze_text(monkeypatch):
    monkeypatch.setattr(
        "backend.routers.analyze.analyze_text", MagicMock(return_value=CompetitorAnalysis(summary="ok"))
    )


# --- Host header ---

def test_expected_web_host_accepted(client):
    resp = client.get("/health", headers={"host": "127.0.0.1:8000"})
    assert resp.status_code == 200


def test_expected_localhost_host_accepted(client):
    resp = client.get("/health", headers={"host": "localhost:8000"})
    assert resp.status_code == 200


def test_expected_desktop_dynamic_port_host_accepted(client):
    """Desktop mode picks a dynamic port (see desktop_main.py) — the guard must not hardcode one."""
    resp = client.get("/health", headers={"host": "127.0.0.1:8765"})
    assert resp.status_code == 200


def test_ipv6_loopback_host_accepted(client):
    resp = client.get("/health", headers={"host": "[::1]:8000"})
    assert resp.status_code == 200


def test_invalid_host_rejected(client):
    resp = client.get("/health", headers={"host": "evil.example.com"})
    assert resp.status_code == 400
    assert "error" in resp.json()


def test_malformed_host_rejected(client):
    resp = client.get("/health", headers={"host": ""})
    assert resp.status_code == 400


def test_dns_rebinding_style_host_with_attacker_domain_rejected(client):
    """A Host header naming an attacker-controlled domain that merely *resolves* to 127.0.0.1
    must still be rejected — this check is on the header value, not on where it resolves."""
    resp = client.get("/health", headers={"host": "attacker-controlled.example"})
    assert resp.status_code == 400


# --- Origin (state-changing requests only) ---

def test_absent_origin_allowed_for_post(client, monkeypatch):
    _mock_analyze_text(monkeypatch)
    resp = client.post(
        "/analyze_text",
        json={"text": "A coffee shop with excellent pastries and espresso."},
        headers={"host": "127.0.0.1:8000"},
    )
    assert resp.status_code == 200


def test_same_origin_as_host_allowed(client, monkeypatch):
    _mock_analyze_text(monkeypatch)
    resp = client.post(
        "/analyze_text",
        json={"text": "A coffee shop with excellent pastries and espresso."},
        headers={"host": "127.0.0.1:8000", "origin": "http://127.0.0.1:8000"},
    )
    assert resp.status_code == 200


def test_same_origin_localhost_allowed(client, monkeypatch):
    _mock_analyze_text(monkeypatch)
    resp = client.post(
        "/analyze_text",
        json={"text": "A coffee shop with excellent pastries and espresso."},
        headers={"host": "localhost:8000", "origin": "http://localhost:8000"},
    )
    assert resp.status_code == 200


def test_external_origin_rejected(client, monkeypatch):
    _mock_analyze_text(monkeypatch)
    resp = client.post(
        "/analyze_text",
        json={"text": "A coffee shop with excellent pastries and espresso."},
        headers={"host": "127.0.0.1:8000", "origin": "https://evil.example.com"},
    )
    assert resp.status_code == 403
    assert "error" in resp.json()


def test_mismatched_port_origin_rejected(client, monkeypatch):
    """Origin naming a different port than the request's own Host is not the same origin."""
    _mock_analyze_text(monkeypatch)
    resp = client.post(
        "/analyze_text",
        json={"text": "A coffee shop with excellent pastries and espresso."},
        headers={"host": "127.0.0.1:8000", "origin": "http://127.0.0.1:9999"},
    )
    assert resp.status_code == 403


def test_null_origin_rejected(client, monkeypatch):
    _mock_analyze_text(monkeypatch)
    resp = client.post(
        "/analyze_text",
        json={"text": "A coffee shop with excellent pastries and espresso."},
        headers={"host": "127.0.0.1:8000", "origin": "null"},
    )
    assert resp.status_code == 403


def test_configured_cors_origin_allowed(client, monkeypatch):
    """An admin-opted-in separate frontend origin (CORS_ALLOW_ORIGINS) is treated as legitimate
    even though it isn't the same origin as the API's own Host."""
    _mock_analyze_text(monkeypatch)
    monkeypatch.setenv("CORS_ALLOW_ORIGINS", "http://localhost:5173")
    resp = client.post(
        "/analyze_text",
        json={"text": "A coffee shop with excellent pastries and espresso."},
        headers={"host": "127.0.0.1:8000", "origin": "http://localhost:5173"},
    )
    assert resp.status_code == 200


def test_get_request_not_subject_to_origin_check(client):
    """Origin enforcement is scoped to state-changing requests; GET is a safe method."""
    resp = client.get("/history", headers={"host": "127.0.0.1:8000", "origin": "https://evil.example.com"})
    assert resp.status_code == 200


def test_delete_history_enforces_origin(client):
    resp = client.delete("/history", headers={"host": "127.0.0.1:8000", "origin": "https://evil.example.com"})
    assert resp.status_code == 403
