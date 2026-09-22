"""Endpoints: /analyze_text, /analyze_image."""
import base64
import json
import logging

from fastapi import APIRouter, File, Request, UploadFile
from starlette.concurrency import run_in_threadpool

from backend.config import get_settings
from backend.errors import InvalidInputError, PayloadTooLargeError, UnsupportedMediaTypeError
from backend.limits import is_pdf_signature, read_request_body_limited, read_upload_limited, validate_image_upload
from backend.models.schemas import CompetitorAnalysis, ImageAnalysis
from backend.services import history_service
from backend.services.openai_service import analyze_image_from_base64, analyze_text, get_openai_client
from backend.services.pdf_service import extract_text_from_pdf

# Multipart form fields this endpoint actually accepts (text, file) — small headroom over the
# real count via Starlette's own Request.form(max_fields=..., max_files=...) limits (see
# docs.md and item 5 of the corrective pass) rather than a hand-rolled multipart parser.
_MAX_FORM_FIELDS = 8
_MAX_FORM_FILES = 1

logger = logging.getLogger("backend.routers.analyze")

router = APIRouter(prefix="", tags=["analyze"])

PDF_EXT = (".pdf",)

_ANALYZE_TEXT_OPENAPI_EXTRA = {
    "requestBody": {
        "required": True,
        "content": {
            "application/json": {
                "schema": {
                    "type": "object",
                    "properties": {"text": {"type": "string", "minLength": 10}},
                    "required": ["text"],
                },
                "example": {"text": "Наша кофейня открылась в 2020 году, предлагает авторские напитки..."},
            },
            "multipart/form-data": {
                "schema": {
                    "type": "object",
                    "properties": {
                        "text": {"type": "string", "description": "Необязательный сопроводительный текст"},
                        "file": {"type": "string", "format": "binary", "description": "PDF-файл (опционально)"},
                    },
                },
            },
        },
    }
}


def _check_content_length(request: Request, max_bytes: int) -> None:
    """Fast-fail on an oversized declared body before reading it. Best-effort: a client
    that omits/understates Content-Length is still bounded by the chunked-read caps below."""
    content_length = request.headers.get("content-length")
    if content_length is None:
        return
    try:
        length = int(content_length)
    except ValueError:
        return
    if length > max_bytes:
        raise PayloadTooLargeError(f"Тело запроса превышает допустимый размер ({max_bytes} байт).")


@router.post("/analyze_text", response_model=CompetitorAnalysis, openapi_extra=_ANALYZE_TEXT_OPENAPI_EXTRA)
async def analyze_text_endpoint(request: Request):
    """Анализ текста: JSON { "text": "..." } или multipart с полями text/file (PDF)."""
    settings = get_settings()
    _check_content_length(request, settings.max_request_body_bytes)

    content_type = (request.headers.get("content-type") or "").lower()
    text_parts: list[str] = []
    had_pdf_upload = False

    if "application/json" in content_type:
        # Bounded read regardless of Content-Length (which may be absent/unreliable) — see
        # backend.limits.read_request_body_limited and docs.md.
        raw_body = await read_request_body_limited(request, settings.max_request_body_bytes, what="Тело запроса")
        try:
            body = json.loads(raw_body.decode("utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError) as e:
            raise InvalidInputError("Тело запроса не является корректным JSON.") from e
        if not isinstance(body, dict):
            raise InvalidInputError("Тело запроса должно быть JSON-объектом.")
        t = (body.get("text") or "").strip()
        if t:
            text_parts.append(t)
    elif "multipart/form-data" in content_type:
        # max_fields/max_files: Starlette's own form-parsing limits (see docs.md) — this
        # endpoint only ever expects a "text" field and a "file" field.
        form = await request.form(max_files=_MAX_FORM_FILES, max_fields=_MAX_FORM_FIELDS)
        t = form.get("text")
        if isinstance(t, str) and t.strip():
            text_parts.append(t.strip())
        file = form.get("file")
        if file is not None and hasattr(file, "filename") and file.filename:
            had_pdf_upload = True
            fn = (file.filename or "").lower()
            ct = (getattr(file, "content_type", "") or "").lower()
            if not (fn.endswith(PDF_EXT) or "pdf" in ct):
                raise UnsupportedMediaTypeError("Поддерживается только PDF.")
            content = await read_upload_limited(file, settings.max_pdf_bytes, what="PDF-файл")
            if not is_pdf_signature(content):
                raise UnsupportedMediaTypeError("Файл не является корректным PDF (не совпадает сигнатура).")
            extracted = await run_in_threadpool(
                extract_text_from_pdf,
                content,
                max_pages=settings.max_pdf_pages,
                max_extracted_chars=settings.max_pdf_extracted_chars,
            )
            if extracted.strip():
                text_parts.append(extracted.strip())
    else:
        raise UnsupportedMediaTypeError("Content-Type должен быть application/json или multipart/form-data.")

    combined = "\n\n".join(text_parts).strip()
    if len(combined) < 10:
        if had_pdf_upload:
            raise InvalidInputError(
                "Из PDF не удалось извлечь достаточно текста (нужно минимум 10 символов). "
                "Возможно, файл — скан или только изображения; добавьте текст в поле выше или используйте PDF с читаемым текстом."
            )
        raise InvalidInputError("Введите или вставьте текст не менее 10 символов либо загрузите PDF с текстом.")
    if len(combined) > settings.max_text_chars:
        raise PayloadTooLargeError(f"Текст превышает допустимый размер ({settings.max_text_chars} символов).")

    client = get_openai_client(settings)
    ai_text = combined[: settings.max_ai_text_chars]
    analysis = await run_in_threadpool(
        analyze_text, client, settings.openai_model, ai_text, timeout=settings.openai_timeout
    )
    history_service.add_entry(
        settings.history_file,
        settings.max_history_entries,
        "text",
        combined[:100] + ("..." if len(combined) > 100 else ""),
        analysis.summary or "",
        response_full=analysis.model_dump(mode="json"),
    )
    return analysis


@router.post("/analyze_image", response_model=ImageAnalysis)
async def analyze_image_endpoint(file: UploadFile = File(...)):
    """Анализ изображения (JPEG/PNG/GIF/WebP, проверка по сигнатуре файла)."""
    settings = get_settings()
    client = get_openai_client(settings)
    content = await read_upload_limited(file, settings.max_image_bytes, what="Изображение")
    sniffed_mime = validate_image_upload(content, file.content_type)
    b64 = base64.standard_b64encode(content).decode("ascii")
    analysis = await run_in_threadpool(
        analyze_image_from_base64, client, settings.openai_model, b64, sniffed_mime, timeout=settings.openai_timeout
    )
    history_service.add_entry(
        settings.history_file,
        settings.max_history_entries,
        "image",
        f"Изображение: {file.filename or 'upload'}",
        (analysis.description or "")[:200],
        response_full=analysis.model_dump(mode="json"),
    )
    return analysis
