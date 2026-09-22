"""Local-browser boundary: Host-header and same-origin checks.

The service binds to 127.0.0.1 by default and has no authentication (see
docs.md) — loopback binding keeps other machines out, but a browser running
on this same machine can still be made to talk to it: via DNS rebinding (a
page whose hostname resolves to 127.0.0.1 after the fact, arriving with a
forged Host header), or simply by a page loaded from an unrelated origin
issuing a state-changing fetch()/XHR here (the browser sends it regardless of
CORS — CORS only controls whether that page may *read* the response; nothing
stops the request itself from executing server-side unless the server
refuses it). This module is the smallest practical guard against both, not
an authentication layer:

- Host header must name this app's own local host: localhost/127.0.0.1/::1
  for the default (recommended) mode, or whatever the admin explicitly
  configured via API_HOST for the documented LAN opt-in (see backend.config)
  — that opt-in is already unauthenticated/trusted-network-only by its own
  contract (see the startup warning in backend.main), so this check doesn't
  further restrict it.
- For state-changing requests (anything but GET/HEAD/OPTIONS), a present
  Origin header must be either the same origin as the request's own
  (now-validated) Host — i.e. this app's own frontend calling itself, which
  covers the default mode, the desktop WebEngine's dynamic port, and the LAN
  opt-in alike without hardcoding a port — or one of the explicitly
  configured CORS_ALLOW_ORIGINS. Requests with no Origin header (curl, the
  desktop app's own backend calls, direct API clients) are still allowed:
  this is a browser-specific guard, not authentication.
"""
import logging
from urllib.parse import urlsplit

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from backend.config import get_cors_origins_list, get_settings

logger = logging.getLogger("backend.local_guard")

_LOOPBACK_HOSTNAMES = {"localhost", "127.0.0.1", "::1"}
_SAFE_METHODS = {"GET", "HEAD", "OPTIONS"}


def _host_header_hostname_port(host_header: str) -> tuple[str, int] | None:
    """Parse a raw Host-header value ("host[:port]" or "[::1]:port") into (lowercased
    hostname, port-or-80). The Host header never carries a scheme; "http://" is prepended
    purely so urlsplit's own (bracket-aware) hostname/port parsing can be reused. This app
    never serves anything but plain http locally, so that's the only scheme in play here.
    Returns None if there's no parseable hostname. Never raises."""
    try:
        parts = urlsplit(f"http://{host_header}")
    except ValueError:
        return None
    hostname = (parts.hostname or "").lower()
    if not hostname:
        return None
    try:
        port = parts.port or 80
    except ValueError:
        return None
    return hostname, port


def _origin_hostname_port(origin: str) -> tuple[str, int] | None:
    """Parse an Origin header value into (lowercased hostname, port-or-80), requiring an
    explicit http scheme (this app never serves https locally, so a same-origin request can
    never legitimately carry any other scheme). Returns None if unparseable or not http."""
    try:
        parts = urlsplit(origin)
    except ValueError:
        return None
    if parts.scheme.lower() != "http":
        return None
    hostname = (parts.hostname or "").lower()
    if not hostname:
        return None
    try:
        port = parts.port or 80
    except ValueError:
        return None
    return hostname, port


def _host_is_allowed(hostname: str, settings) -> bool:
    if hostname in _LOOPBACK_HOSTNAMES:
        return True
    configured = (settings.api_host or "").strip().lower()
    if configured in ("0.0.0.0", "::"):
        # Explicit wildcard/LAN opt-in — the exact Host a LAN client will send isn't knowable
        # here, and this mode already carries its own "no authentication, trusted network only"
        # warning (see backend.main's startup log), so this check doesn't add further
        # restriction on top of that already-accepted opt-in.
        return True
    return bool(configured) and hostname == configured


def install_local_guard(app: FastAPI) -> None:
    """Register the Host/Origin middleware on `app`. Called once from backend.main."""

    @app.middleware("http")
    async def local_browser_guard(request: Request, call_next):
        settings = get_settings()
        host_header = request.headers.get("host", "")
        host_parsed = _host_header_hostname_port(host_header)
        if host_parsed is None or not _host_is_allowed(host_parsed[0], settings):
            logger.warning("local_guard: rejected request with untrusted Host header=%r", host_header)
            return JSONResponse(status_code=400, content={"error": "Недопустимый заголовок Host."})

        if request.method not in _SAFE_METHODS:
            origin = request.headers.get("origin")
            if origin:
                origin_parsed = _origin_hostname_port(origin)
                is_same_origin = origin_parsed is not None and origin_parsed == host_parsed
                is_configured_cors_origin = origin in get_cors_origins_list(settings)
                if not (is_same_origin or is_configured_cors_origin):
                    logger.warning("local_guard: rejected request with untrusted Origin=%r", origin)
                    return JSONResponse(status_code=403, content={"error": "Недопустимый Origin."})

        return await call_next(request)
