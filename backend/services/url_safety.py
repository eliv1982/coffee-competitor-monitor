"""Shared outbound-URL safety policy, used by both the HTTPX parser flow and Selenium.

Scope: this is a basic SSRF guard appropriate for a local, trusted-user tool that
fetches user-supplied competitor URLs. It is NOT a full network sandbox: it
validates scheme, rejects embedded credentials, resolves DNS and rejects
non-globally-routable destinations (loopback/private/link-local/multicast/
reserved/unspecified), for both IPv4 and IPv6. Callers doing HTTP requests are
expected to re-validate each redirect hop (see parser_service.safe_get);
Selenium navigation only validates the initial destination (see docstring on
get_url_screenshot_and_text) — only trusted/public competitor URLs are supported.
"""
import ipaddress
import logging
import socket
from dataclasses import dataclass
from urllib.parse import urlsplit

logger = logging.getLogger("backend.services.url_safety")

ALLOWED_SCHEMES = {"http", "https"}


class UnsafeURLError(ValueError):
    """Raised when a URL fails the outbound safety policy (bad scheme, credentials, or unsafe destination)."""


@dataclass(frozen=True)
class SafeURL:
    url: str
    scheme: str
    hostname: str
    port: int
    resolved_ips: tuple[str, ...]


def redact_url(url: str) -> str:
    """Return a log-safe form of a URL: strip userinfo and query string/fragment.

    Must never raise, even on malformed input (e.g. a non-numeric port like
    ":bad") — this is called from logging and error-message paths, including
    inside except blocks, so an exception here must not turn a clean 4xx into
    an unhandled 500. `.hostname`/`.port` are lazy properties that themselves
    raise ValueError on malformed input, so they're accessed inside the guard.
    """
    try:
        parts = urlsplit(url)
        host = parts.hostname or ""
        port = parts.port
        scheme = parts.scheme
        path = parts.path
        query = parts.query
    except ValueError:
        return "(invalid url)"
    if port:
        host = f"{host}:{port}"
    redacted = f"{scheme}://{host}{path}"
    if query:
        redacted += "?<redacted>"
    return redacted


def ensure_scheme(url: str) -> str:
    """If `url` has no recognizable http(s):// prefix, assume https://.

    The scheme check is case-insensitive (RFC 3986 schemes are case-insensitive)
    so "HTTP://example.com" isn't mistaken for schemeless input and double-prefixed
    into the malformed "https://HTTP://example.com". Does not itself validate the
    result — callers still run it through validate_public_http_url.
    """
    url = (url or "").strip()
    lowered = url.lower()
    if lowered.startswith("http://") or lowered.startswith("https://"):
        return url
    return "https://" + url


def _is_unsafe_ip(ip: ipaddress.IPv4Address | ipaddress.IPv6Address) -> bool:
    """True if the address must NOT be reachable from this tool (SSRF-relevant ranges)."""
    return (
        ip.is_loopback
        or ip.is_private
        or ip.is_link_local
        or ip.is_multicast
        or ip.is_reserved
        or ip.is_unspecified
        or not ip.is_global
    )


def resolve_hostname(hostname: str, *, resolver=socket.getaddrinfo) -> list[str]:
    """Resolve a hostname to its IP address strings (deduplicated). Raises UnsafeURLError if unresolvable."""
    try:
        infos = resolver(hostname, None, proto=socket.IPPROTO_TCP)
    except socket.gaierror as e:
        raise UnsafeURLError(f"Не удалось разрешить адрес хоста: {hostname}") from e
    ips = sorted({info[4][0] for info in infos if info and info[4]})
    if not ips:
        raise UnsafeURLError(f"Не удалось разрешить адрес хоста: {hostname}")
    return ips


def validate_public_http_url(url: str, *, resolver=socket.getaddrinfo) -> SafeURL:
    """Validate a user-supplied URL against the outbound safety policy.

    Checks (in order): non-empty, http/https scheme only, no embedded userinfo
    (credentials), hostname present, DNS resolves, and every resolved address
    is globally routable (not loopback/private/link-local/multicast/reserved/
    unspecified). Raises UnsafeURLError with a user-safe message on any violation.
    """
    if not url or not isinstance(url, str):
        raise UnsafeURLError("Пустой URL.")
    try:
        parts = urlsplit(url)
    except ValueError as e:
        raise UnsafeURLError("Некорректный URL.") from e

    scheme = (parts.scheme or "").lower()
    if scheme not in ALLOWED_SCHEMES:
        raise UnsafeURLError(f"Недопустимая схема URL: {scheme or '(нет)'}. Разрешены только http/https.")

    if parts.username is not None or parts.password is not None:
        raise UnsafeURLError("URL с учётными данными (userinfo) не поддерживается.")

    try:
        hostname = parts.hostname
    except ValueError as e:
        raise UnsafeURLError("Некорректный хост в URL.") from e
    if not hostname:
        raise UnsafeURLError("В URL отсутствует хост.")

    try:
        port = parts.port or (443 if scheme == "https" else 80)
    except ValueError as e:
        raise UnsafeURLError("Некорректный порт в URL.") from e

    ips = resolve_hostname(hostname, resolver=resolver)
    for ip_str in ips:
        try:
            ip = ipaddress.ip_address(ip_str)
        except ValueError:
            raise UnsafeURLError(f"Некорректный IP-адрес хоста: {ip_str}")
        if _is_unsafe_ip(ip):
            logger.warning("url_safety: rejected unsafe destination host=%s ip=%s", hostname, ip_str)
            raise UnsafeURLError(
                "Адрес назначения недоступен для запроса (локальный, приватный или иной нестандартный диапазон)."
            )

    return SafeURL(url=url, scheme=scheme, hostname=hostname, port=port, resolved_ips=tuple(ips))
