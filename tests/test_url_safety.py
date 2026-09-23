"""Tests for backend.services.url_safety — the shared SSRF guard used by both
the httpx parser flow and Selenium. DNS is always mocked; no real network access."""
import socket

import pytest

from backend.services.url_safety import (
    UnsafeURLError,
    ensure_scheme,
    redact_url,
    resolve_hostname,
    validate_public_http_url,
)


def _fake_resolver(ip: str):
    """Build a resolver matching socket.getaddrinfo's return shape for a single IP."""
    family = socket.AF_INET6 if ":" in ip else socket.AF_INET
    sockaddr = (ip, 0, 0, 0) if family == socket.AF_INET6 else (ip, 0)

    def resolver(host, port, *args, **kwargs):
        return [(family, socket.SOCK_STREAM, socket.IPPROTO_TCP, "", sockaddr)]

    return resolver


def _fail_resolver(host, port, *args, **kwargs):
    raise socket.gaierror("name resolution failed")


@pytest.mark.parametrize(
    "ip",
    [
        "127.0.0.1",  # loopback
        "10.1.2.3",  # private
        "172.16.5.5",  # private
        "192.168.1.1",  # private
        "169.254.169.254",  # link-local (cloud metadata endpoint)
        "224.0.0.1",  # multicast
        "0.0.0.0",  # unspecified
        "::1",  # loopback v6
        "fc00::1",  # unique local (private) v6
        "fe80::1",  # link-local v6
        "ff02::1",  # multicast v6
        "::ffff:127.0.0.1",  # IPv4-mapped loopback
        "100.64.0.5",  # carrier-grade NAT (private)
    ],
)
def test_rejects_non_global_destinations(ip):
    with pytest.raises(UnsafeURLError):
        validate_public_http_url("http://example.invalid/", resolver=_fake_resolver(ip))


@pytest.mark.parametrize("ip", ["8.8.8.8", "1.1.1.1", "2001:4860:4860::8888"])
def test_allows_public_destinations(ip):
    safe = validate_public_http_url("http://example.invalid/page", resolver=_fake_resolver(ip))
    assert safe.hostname == "example.invalid"
    assert ip in safe.resolved_ips


@pytest.mark.parametrize("url", ["ftp://example.com/", "file:///etc/passwd", "javascript:alert(1)", "example.com"])
def test_rejects_invalid_scheme(url):
    with pytest.raises(UnsafeURLError):
        validate_public_http_url(url, resolver=_fake_resolver("8.8.8.8"))


@pytest.mark.parametrize(
    "url",
    [
        "http://user:pass@example.com/",
        "https://admin:secret@example.com/dashboard",
        "http://token@example.com/",
    ],
)
def test_rejects_credentials_in_url(url):
    with pytest.raises(UnsafeURLError):
        validate_public_http_url(url, resolver=_fake_resolver("8.8.8.8"))


def test_rejects_unresolvable_host():
    with pytest.raises(UnsafeURLError):
        validate_public_http_url("http://does-not-resolve.invalid/", resolver=_fail_resolver)


def test_rejects_empty_url():
    with pytest.raises(UnsafeURLError):
        validate_public_http_url("", resolver=_fake_resolver("8.8.8.8"))


def test_public_hostname_resolving_to_private_ip_is_rejected():
    """DNS-rebinding-style case: a hostname that looks public but resolves to a private IP."""
    with pytest.raises(UnsafeURLError):
        validate_public_http_url("http://looks-public.example.com/", resolver=_fake_resolver("192.168.0.1"))


def test_redact_url_strips_userinfo_and_query():
    redacted = redact_url("https://user:pass@example.com/path?token=secret123")
    assert "user" not in redacted
    assert "pass" not in redacted
    assert "secret123" not in redacted
    assert redacted == "https://example.com/path?<redacted>"


def test_redact_url_keeps_host_and_path():
    assert redact_url("http://example.com:8080/a/b") == "http://example.com:8080/a/b"


# --- malformed URLs: redact_url/validate_public_http_url must never raise, always 4xx-able ---

def test_redact_url_never_raises_on_malformed_port():
    """.hostname/.port are lazy properties that raise ValueError on malformed input; redact_url
    is called from logging and error-message paths (including inside except blocks), so an
    exception here would turn a clean 4xx into an unhandled 500."""
    assert redact_url("http://example.com:bad/path") == "(invalid url)"


def test_redact_url_never_raises_on_out_of_range_port():
    assert redact_url("http://example.com:999999/path") == "(invalid url)"


def test_validate_public_http_url_rejects_malformed_port():
    with pytest.raises(UnsafeURLError):
        validate_public_http_url("http://example.com:bad/path", resolver=_fake_resolver("8.8.8.8"))


def test_validate_public_http_url_accepts_mixed_case_scheme():
    safe = validate_public_http_url("HTTP://example.invalid/", resolver=_fake_resolver("8.8.8.8"))
    assert safe.scheme == "http"
    safe2 = validate_public_http_url("HtTpS://example.invalid/", resolver=_fake_resolver("8.8.8.8"))
    assert safe2.scheme == "https"


# --- final corrective pass, item 2: malformed hostnames (oversized DNS label / invalid IDNA
# input) must become UnsafeURLError, never an unhandled UnicodeError/UnicodeEncodeError that
# would escape as a 500. socket.getaddrinfo IDNA-encodes the hostname internally *before* any
# actual network access, so these raise purely from string processing — no real DNS/network. ---

def _unicode_error_resolver(host, port, *args, **kwargs):
    raise UnicodeError("label empty or too long")


def test_resolve_hostname_rejects_unicode_error_from_resolver():
    with pytest.raises(UnsafeURLError):
        resolve_hostname("whatever.invalid", resolver=_unicode_error_resolver)


def test_validate_public_http_url_rejects_unicode_error_from_resolver():
    with pytest.raises(UnsafeURLError):
        validate_public_http_url("http://whatever.invalid/", resolver=_unicode_error_resolver)


def test_resolve_hostname_rejects_real_oversized_dns_label():
    """End-to-end with the real stdlib resolver (no mock): a hostname whose label exceeds the
    63-octet DNS limit makes Python's IDNA codec raise UnicodeError inside socket.getaddrinfo
    before any actual network I/O — this must not escape resolve_hostname unhandled."""
    oversized_label_host = "a" * 100 + ".invalid"
    with pytest.raises(UnsafeURLError):
        resolve_hostname(oversized_label_host)


def test_validate_public_http_url_rejects_real_oversized_dns_label():
    oversized_label_url = "http://" + "a" * 100 + ".invalid/"
    with pytest.raises(UnsafeURLError):
        validate_public_http_url(oversized_label_url)


def test_validate_public_http_url_rejects_real_malformed_idna_empty_label():
    """A different malformed-hostname shape (empty label between dots) triggers the same
    stdlib IDNA UnicodeError class as the oversized-label case, via a different code path."""
    with pytest.raises(UnsafeURLError):
        validate_public_http_url("http://sub..example.invalid/")


# --- ensure_scheme: router-level "add https:// if missing" normalization ---

def test_ensure_scheme_adds_https_for_schemeless_input():
    assert ensure_scheme("example.com") == "https://example.com"


def test_ensure_scheme_does_not_double_prefix_lowercase():
    assert ensure_scheme("http://example.com") == "http://example.com"
    assert ensure_scheme("https://example.com") == "https://example.com"


def test_ensure_scheme_does_not_double_prefix_mixed_case():
    """A case-sensitive prefix check would fail to recognize "HTTP://..." as already having a
    scheme and prepend another, producing the malformed "https://HTTP://example.com"."""
    assert ensure_scheme("HTTP://example.com") == "HTTP://example.com"
    assert ensure_scheme("HTTPS://example.com") == "HTTPS://example.com"
    assert ensure_scheme("Http://Example.com") == "Http://Example.com"


def test_ensure_scheme_strips_whitespace():
    assert ensure_scheme("  example.com  ") == "https://example.com"
