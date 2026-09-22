"""Typed application errors mapped to coherent HTTP status codes.

Routers raise these instead of catching every exception and returning
HTTP 200 with an "error" field. See backend.main for the handlers that
turn these into sanitized JSON responses (full detail stays in server logs).
"""


class AppError(Exception):
    """Base class for errors that map to a specific HTTP status code.

    `message` is safe to return to the client. `log_message` (defaults to
    `message`) is what gets written to the server log and may include more
    internal detail.
    """

    status_code: int = 500

    def __init__(self, message: str, *, log_message: str | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.log_message = log_message or message


class InvalidInputError(AppError):
    """400 — malformed or semantically invalid input."""

    status_code = 400


class PayloadTooLargeError(AppError):
    """413 — input exceeds a configured size/count limit."""

    status_code = 413


class UnsupportedMediaTypeError(AppError):
    """415 — declared or sniffed content type is not supported."""

    status_code = 415


class ServiceUnavailableError(AppError):
    """503 — required configuration or a local service (e.g. Selenium/Chrome) is missing."""

    status_code = 503


class UpstreamError(AppError):
    """502 — a call to an upstream service (OpenAI, target website) failed."""

    status_code = 502


class UpstreamTimeoutError(AppError):
    """504 — a call to an upstream service timed out."""

    status_code = 504
