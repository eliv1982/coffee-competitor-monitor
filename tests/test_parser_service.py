"""Tests for backend.services.parser_service. All network is mocked via httpx.MockTransport
and a fake DNS resolver; Selenium is mocked via monkeypatching webdriver.Chrome. No real
websites or Selenium navigation happen in this suite."""
import socket
from unittest.mock import MagicMock

import httpx
import pytest

from backend.services import parser_service


def _resolver_for(mapping: dict[str, str]):
    def resolver(host, port, *args, **kwargs):
        ip = mapping.get(host)
        if ip is None:
            raise socket.gaierror(f"no DNS mapping for {host} in test")
        family = socket.AF_INET6 if ":" in ip else socket.AF_INET
        sockaddr = (ip, 0, 0, 0) if family == socket.AF_INET6 else (ip, 0)
        return [(family, socket.SOCK_STREAM, socket.IPPROTO_TCP, "", sockaddr)]

    return resolver


HTML_PAGE = (
    b"<html><head><title>Coffee Shop</title></head><body>"
    b"<h1>Welcome</h1><p>This is a sufficiently long first paragraph for extraction.</p>"
    b"</body></html>"
)


def test_extract_from_html_is_deterministic():
    title, h1, paragraph = parser_service._extract_from_html(HTML_PAGE.decode("utf-8"))
    assert title == "Coffee Shop"
    assert h1 == "Welcome"
    assert paragraph.startswith("This is a sufficiently long first paragraph")


def test_extract_from_html_skips_short_paragraphs():
    html = "<html><title>T</title><p>short</p><p>" + "x" * 25 + "</p></html>"
    _title, _h1, paragraph = parser_service._extract_from_html(html)
    assert paragraph == "x" * 25


def test_parse_url_follows_safe_redirect_to_public_host():
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.host == "start.example.com":
            return httpx.Response(302, headers={"location": "https://final.example.com/page"})
        return httpx.Response(200, content=HTML_PAGE, headers={"content-type": "text/html; charset=utf-8"})

    transport = httpx.MockTransport(handler)
    resolver = _resolver_for({"start.example.com": "93.184.216.34", "final.example.com": "93.184.216.35"})

    title, h1, paragraph, err = parser_service.parse_url(
        "https://start.example.com/", timeout=5.0, transport=transport, resolver=resolver
    )
    assert err == ""
    assert title == "Coffee Shop"
    assert h1 == "Welcome"


def test_parse_url_rejects_redirect_to_private_address():
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.host == "start.example.com":
            return httpx.Response(302, headers={"location": "http://internal.example/secret"})
        return httpx.Response(200, content=HTML_PAGE)  # should never be reached

    transport = httpx.MockTransport(handler)
    resolver = _resolver_for({"start.example.com": "93.184.216.34", "internal.example": "10.0.0.5"})

    title, h1, paragraph, err = parser_service.parse_url(
        "https://start.example.com/", timeout=5.0, transport=transport, resolver=resolver
    )
    assert title == h1 == paragraph == ""
    assert err  # rejected, non-empty error message


def test_parse_url_caps_response_size():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=b"x" * 5000, headers={"content-type": "text/html"})

    transport = httpx.MockTransport(handler)
    resolver = _resolver_for({"big.example.com": "93.184.216.34"})

    title, h1, paragraph, err = parser_service.parse_url(
        "https://big.example.com/", timeout=5.0, max_response_bytes=100, transport=transport, resolver=resolver
    )
    assert title == h1 == paragraph == ""
    assert "размер" in err.lower() or "size" in err.lower() or err  # rejected


def test_parse_url_rejects_binary_content_type():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=b"\x89PNG\r\n", headers={"content-type": "image/png"})

    transport = httpx.MockTransport(handler)
    resolver = _resolver_for({"img.example.com": "93.184.216.34"})

    title, h1, paragraph, err = parser_service.parse_url(
        "https://img.example.com/", timeout=5.0, transport=transport, resolver=resolver
    )
    assert title == h1 == paragraph == ""
    assert err


def test_parse_url_rejects_unsafe_initial_url_immediately():
    resolver = _resolver_for({"internal.local": "127.0.0.1"})
    with pytest.raises(parser_service.UnsafeURLError):
        parser_service.parse_url("http://internal.local/", timeout=5.0, resolver=resolver)


def test_selenium_driver_quit_is_called_even_on_failure(monkeypatch):
    """driver.quit() must run even when driver.get() raises (resource cleanup), and the raw
    exception text must never reach the returned error message (only the sanitized constant) —
    the raw detail belongs in the server log only."""
    fake_driver = MagicMock()
    fake_driver.get.side_effect = RuntimeError("navigation boom: /secret/local/path leaked")
    monkeypatch.setattr(parser_service.webdriver, "Chrome", MagicMock(return_value=fake_driver))
    monkeypatch.setattr(parser_service, "_SELENIUM_AVAILABLE", True)
    # parse_url_selenium's initial destination check uses the real resolver by default;
    # bypass it here since this test is about Selenium cleanup behavior, not DNS/SSRF policy
    # (that policy is covered exhaustively in tests/test_url_safety.py).
    monkeypatch.setattr(parser_service, "validate_public_http_url", lambda url, **kw: None)

    title, h1, paragraph, err = parser_service.parse_url_selenium(
        "https://competitor.example.com/", timeout=5.0
    )
    fake_driver.quit.assert_called_once()
    assert err == parser_service.SELENIUM_UPSTREAM_ERROR_MESSAGE
    assert "navigation boom" not in err
    assert "/secret/local/path" not in err


def test_parse_url_selenium_timeout_maps_to_timeout_message(monkeypatch):
    from selenium.common.exceptions import TimeoutException

    fake_driver = MagicMock()
    fake_driver.get.side_effect = TimeoutException("page load timed out after 30000ms, session=abc123")
    monkeypatch.setattr(parser_service.webdriver, "Chrome", MagicMock(return_value=fake_driver))
    monkeypatch.setattr(parser_service, "_SELENIUM_AVAILABLE", True)
    monkeypatch.setattr(parser_service, "validate_public_http_url", lambda url, **kw: None)

    title, h1, paragraph, err = parser_service.parse_url_selenium("https://competitor.example.com/", timeout=5.0)
    assert err == parser_service.SELENIUM_TIMEOUT_MESSAGE
    assert "session=abc123" not in err
    fake_driver.quit.assert_called_once()


def test_get_url_screenshot_and_text_quits_driver_on_failure(monkeypatch):
    fake_driver = MagicMock()
    fake_driver.get.side_effect = RuntimeError("boom: C:\\Users\\dev\\secret")
    monkeypatch.setattr(parser_service.webdriver, "Chrome", MagicMock(return_value=fake_driver))
    monkeypatch.setattr(parser_service, "_SELENIUM_AVAILABLE", True)
    monkeypatch.setattr(
        parser_service,
        "validate_public_http_url",
        lambda url, **kw: None,  # bypass real DNS for this Selenium-focused test
    )

    screenshot, mime, text, err = parser_service.get_url_screenshot_and_text("https://competitor.example.com/")
    assert screenshot is None
    assert err == parser_service.SELENIUM_UPSTREAM_ERROR_MESSAGE
    assert "secret" not in err
    fake_driver.quit.assert_called_once()


def test_get_url_screenshot_and_text_timeout_maps_to_timeout_message(monkeypatch):
    from selenium.common.exceptions import TimeoutException

    fake_driver = MagicMock()
    fake_driver.get.side_effect = TimeoutException("timed out")
    monkeypatch.setattr(parser_service.webdriver, "Chrome", MagicMock(return_value=fake_driver))
    monkeypatch.setattr(parser_service, "_SELENIUM_AVAILABLE", True)
    monkeypatch.setattr(parser_service, "validate_public_http_url", lambda url, **kw: None)

    screenshot, mime, text, err = parser_service.get_url_screenshot_and_text("https://competitor.example.com/")
    assert screenshot is None
    assert err == parser_service.SELENIUM_TIMEOUT_MESSAGE
    fake_driver.quit.assert_called_once()


def test_selenium_not_installed_returns_service_message(monkeypatch):
    monkeypatch.setattr(parser_service, "_SELENIUM_AVAILABLE", False)
    screenshot, mime, text, err = parser_service.get_url_screenshot_and_text("https://competitor.example.com/")
    assert screenshot is None
    assert err == parser_service.SELENIUM_NOT_INSTALLED_MESSAGE


def test_no_sandbox_flag_only_added_when_explicitly_allowed():
    default_options = parser_service._build_chrome_options(None, allow_no_sandbox=False)
    opt_in_options = parser_service._build_chrome_options(None, allow_no_sandbox=True)
    assert "--no-sandbox" not in default_options.arguments
    assert "--no-sandbox" in opt_in_options.arguments


# --- parse_url_auto: configured non-default values must actually reach the httpx call ---
# (a previous version silently dropped connect_timeout/max_redirects/max_response_bytes,
# always using parse_url's own hardcoded defaults regardless of what callers configured)

def test_parse_url_auto_forwards_configured_max_redirects():
    """An infinite redirect loop fails either way (default cap 5 or a lower configured cap) —
    the only observable proof that the *configured* value (not parse_url's hardcoded default)
    was actually used is how many requests were made before giving up."""
    call_count = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        call_count["n"] += 1
        return httpx.Response(302, headers={"location": "https://start.example.com/loop"})

    transport = httpx.MockTransport(handler)
    resolver = _resolver_for({"start.example.com": "93.184.216.34"})

    title, h1, paragraph, err = parser_service.parse_url_auto(
        "https://start.example.com/loop", timeout=5.0, max_redirects=1, transport=transport, resolver=resolver
    )
    assert title == h1 == paragraph == ""
    assert "редирект" in err.lower()
    # max_redirects=1 -> at most 2 requests (the original + 1 followed redirect). If the
    # configured value were silently dropped in favor of parse_url's default of 5, this would
    # be 6 instead.
    assert call_count["n"] == 2


def test_parse_url_auto_forwards_configured_max_response_bytes():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=b"x" * 5000, headers={"content-type": "text/html"})

    transport = httpx.MockTransport(handler)
    resolver = _resolver_for({"big.example.com": "93.184.216.34"})

    title, h1, paragraph, err = parser_service.parse_url_auto(
        "https://big.example.com/", timeout=5.0, max_response_bytes=100, transport=transport, resolver=resolver
    )
    assert title == h1 == paragraph == ""
    assert err


def test_parse_url_auto_default_values_match_parse_url_defaults():
    """parse_url_auto's own defaults (used by tests/direct callers that don't specify) should
    still line up with parse_url's, now that they're threaded through explicitly."""
    import inspect

    sig = inspect.signature(parser_service.parse_url_auto)
    assert sig.parameters["max_redirects"].default == 5
    assert sig.parameters["max_response_bytes"].default == 5 * 1024 * 1024
    assert sig.parameters["connect_timeout"].default == 10.0


def test_parse_url_auto_selenium_path_bounds_page_source(monkeypatch):
    """max_response_bytes is reused as the Selenium page_source character cap (see
    parser_service.DEFAULT_MAX_PAGE_SOURCE_CHARS) — proves parse_url_auto forwards it."""
    fake_driver = MagicMock()
    fake_driver.page_source = "<html><title>" + ("A" * 1000) + "</title></html>"
    monkeypatch.setattr(parser_service.webdriver, "Chrome", MagicMock(return_value=fake_driver))
    monkeypatch.setattr(parser_service, "_SELENIUM_AVAILABLE", True)
    monkeypatch.setattr(parser_service, "validate_public_http_url", lambda url, **kw: None)

    title, h1, paragraph, err = parser_service.parse_url_auto(
        "https://competitor.example.com/", timeout=5.0, use_selenium=True, max_response_bytes=50
    )
    assert err == ""
    # The 50-char page_source cap truncates the source well before the full 1000-char title.
    assert len(title) < 50
