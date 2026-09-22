"""Input/upload size limits and file-signature sniffing.

Conservative defaults appropriate for a local single/few-user tool, not a
public-facing service. Values are configurable via Settings (env vars) — see
backend.config. Enforced as typed errors (backend.errors), mapped to 413/415
by the FastAPI handlers in backend.main.
"""
import logging

from fastapi import Request, UploadFile

from backend.errors import InvalidInputError, PayloadTooLargeError, UnsupportedMediaTypeError

logger = logging.getLogger("backend.limits")

READ_CHUNK_BYTES = 256 * 1024

ALLOWED_IMAGE_TYPES = ("image/jpeg", "image/png", "image/gif", "image/webp")

# Magic-byte signatures for the image types we accept. WEBP needs two checks
# (RIFF container + WEBP fourcc) so it isn't a simple prefix.
_JPEG_SIG = b"\xff\xd8\xff"
_PNG_SIG = b"\x89PNG\r\n\x1a\n"
_GIF_SIGS = (b"GIF87a", b"GIF89a")
_PDF_SIG = b"%PDF-"


def sniff_image_mime(content: bytes) -> str | None:
    """Return the detected image MIME type from magic bytes, or None if unrecognized."""
    if content.startswith(_JPEG_SIG):
        return "image/jpeg"
    if content.startswith(_PNG_SIG):
        return "image/png"
    if content.startswith(_GIF_SIGS):
        return "image/gif"
    if len(content) >= 12 and content[0:4] == b"RIFF" and content[8:12] == b"WEBP":
        return "image/webp"
    return None


def is_pdf_signature(content: bytes) -> bool:
    """PDFs start with %PDF- (allow a small amount of leading junk, per spec tolerance)."""
    return _PDF_SIG in content[:1024]


async def read_upload_limited(file: UploadFile, max_bytes: int, *, what: str) -> bytes:
    """Read an UploadFile in bounded chunks, aborting with 413 before buffering past max_bytes."""
    chunks: list[bytes] = []
    total = 0
    while True:
        chunk = await file.read(READ_CHUNK_BYTES)
        if not chunk:
            break
        total += len(chunk)
        if total > max_bytes:
            raise PayloadTooLargeError(f"{what} превышает допустимый размер ({max_bytes} байт).")
        chunks.append(chunk)
    return b"".join(chunks)


async def read_request_body_limited(request: Request, max_bytes: int, *, what: str) -> bytes:
    """Read a raw request body in bounded chunks straight off the ASGI stream, aborting with
    413 before buffering past max_bytes.

    Unlike a Content-Length pre-check (best-effort: the header may be absent, or a client may
    simply lie about it), this bounds the actual bytes read regardless of what the client
    claims — used for the JSON body of /analyze_text instead of the framework's Request.json()
    (which buffers the whole body with no size cap of its own).
    """
    chunks: list[bytes] = []
    total = 0
    async for chunk in request.stream():
        total += len(chunk)
        if total > max_bytes:
            raise PayloadTooLargeError(f"{what} превышает допустимый размер ({max_bytes} байт).")
        chunks.append(chunk)
    return b"".join(chunks)


def validate_image_upload(content: bytes, declared_content_type: str | None) -> str:
    """Validate image bytes by signature (not just declared content-type). Returns the sniffed MIME type."""
    if not content:
        raise InvalidInputError("Пустой файл.")
    sniffed = sniff_image_mime(content)
    if sniffed is None:
        raise UnsupportedMediaTypeError(
            f"Неподдерживаемый или повреждённый файл изображения. Разрешены: {', '.join(ALLOWED_IMAGE_TYPES)}"
        )
    if declared_content_type and declared_content_type in ALLOWED_IMAGE_TYPES and declared_content_type != sniffed:
        logger.warning(
            "limits: declared image content-type=%s does not match sniffed=%s", declared_content_type, sniffed
        )
    return sniffed
