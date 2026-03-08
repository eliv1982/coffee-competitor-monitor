"""Endpoints: /analyze_text, /analyze_image."""
import base64
import logging
from fastapi import APIRouter, File, HTTPException, Request, UploadFile
from fastapi.responses import JSONResponse
from openai import OpenAI

from backend.config import get_settings

logger = logging.getLogger("backend.routers.analyze")
from backend.services import history_service
from backend.services.openai_service import (
    analyze_image_from_base64,
    analyze_text,
)
from backend.services.pdf_service import extract_text_from_pdf

router = APIRouter(prefix="", tags=["analyze"])

ALLOWED_IMAGE_TYPES = ["image/jpeg", "image/png", "image/gif", "image/webp"]
PDF_CONTENT_TYPES = ("application/pdf",)
PDF_EXT = (".pdf",)


def _get_client() -> OpenAI:
    settings = get_settings()
    if not (settings.openai_api_key or "").strip():
        raise HTTPException(status_code=503, detail="В .env задайте OPENAI_API_KEY.")
    kwargs = {"api_key": settings.openai_api_key.strip()}
    if getattr(settings, "openai_base_url", "") and settings.openai_base_url.strip():
        kwargs["base_url"] = settings.openai_base_url.strip()
    return OpenAI(**kwargs)


def _build_text_payload(analysis):
    """Собрать payload ответа анализа текста (все поля под кофейни)."""
    return {
        "strengths": list(analysis.strengths),
        "weaknesses": list(analysis.weaknesses),
        "unique_offers": list(analysis.unique_offers),
        "unique_selling_points": list(getattr(analysis, "unique_selling_points", []) or []),
        "recommendations": list(analysis.recommendations),
        "summary": analysis.summary or "",
        "content_quality": getattr(analysis, "content_quality", 0),
        "price_category": getattr(analysis, "price_category", "") or "",
    }


def _err(msg: str):
    """Всегда 200 + JSON, чтобы клиент никогда не получал текст Internal Server Error."""
    return JSONResponse(status_code=200, content={"error": msg})


@router.post("/analyze_text")
async def analyze_text_endpoint(request: Request):
    """Анализ текста: JSON { "text": "..." } или multipart с text/file (PDF). Всегда 200 + JSON."""
    try:
        content_type = (request.headers.get("content-type") or "").lower()
        text_parts = []
        had_pdf_upload = False

        if "application/json" in content_type:
            body = await request.json()
            if not isinstance(body, dict):
                return _err("Тело запроса должно быть JSON-объектом.")
            t = (body.get("text") or "").strip()
            if t:
                text_parts.append(t)
        elif "multipart/form-data" in content_type:
            form = await request.form()
            t = form.get("text")
            if isinstance(t, str) and t.strip():
                text_parts.append(t.strip())
            file = form.get("file")
            if file is not None and hasattr(file, "filename") and file.filename:
                had_pdf_upload = True
                fn = (file.filename or "").lower()
                ct = (getattr(file, "content_type") or "").lower()
                if fn.endswith(PDF_EXT) or "pdf" in ct:
                    content = await file.read()
                    extracted = extract_text_from_pdf(content)
                    if extracted.strip():
                        text_parts.append(extracted.strip())
                else:
                    return _err("Поддерживается только PDF.")
        else:
            return _err("Content-Type: application/json или multipart/form-data.")

        combined = "\n\n".join(text_parts).strip()
        if len(combined) < 10:
            if had_pdf_upload:
                return _err(
                    "Из PDF не удалось извлечь достаточно текста (нужно минимум 10 символов). "
                    "Возможно, файл — скан или только изображения; добавьте текст в поле выше или используйте PDF с читаемым текстом."
                )
            return _err("Введите или вставьте текст не менее 10 символов либо загрузите PDF с текстом.")

        settings = get_settings()
        try:
            client = _get_client()
        except HTTPException as e:
            return _err(e.detail or "Ошибка конфигурации.")
        analysis = analyze_text(client, settings.openai_model, combined)
        payload = _build_text_payload(analysis)
        history_service.add_entry(
            settings.history_file,
            settings.max_history_entries,
            "text",
            combined[:100] + ("..." if len(combined) > 100 else ""),
            analysis.summary or "",
            response_full=payload,
        )
        return JSONResponse(status_code=200, content=payload)
    except Exception as e:
        logger.exception("analyze_text: %s", e)
        return _err(str(e) or "Внутренняя ошибка.")


@router.post("/analyze_image")
async def analyze_image_endpoint(file: UploadFile = File(...)):
    """Анализ изображения. Всегда 200 + JSON (успех или error в теле)."""
    try:
        if file.content_type and file.content_type not in ALLOWED_IMAGE_TYPES:
            return _err(f"Неподдерживаемый тип файла. Разрешены: {', '.join(ALLOWED_IMAGE_TYPES)}")
        settings = get_settings()
        try:
            client = _get_client()
        except HTTPException as e:
            return _err(e.detail or "Ошибка конфигурации.")
        content = await file.read()
        if not content:
            return _err("Пустой файл.")
        mime = file.content_type or "image/jpeg"
        b64 = base64.standard_b64encode(content).decode("ascii")
        analysis = analyze_image_from_base64(client, settings.openai_model, b64, mime)
        image_payload = {
            "description": analysis.description,
            "marketing_insights": list(analysis.marketing_insights),
            "visual_style_score": analysis.visual_style_score,
            "visual_style_analysis": analysis.visual_style_analysis,
            "recommendations": list(analysis.recommendations),
            "design_score": analysis.design_score,
            "animation_potential": analysis.animation_potential,
            "menu_visibility": analysis.menu_visibility,
            "brand_style": analysis.brand_style,
            "usability_score": analysis.usability_score,
            "content_quality": analysis.content_quality,
        }
        history_service.add_entry(
            settings.history_file,
            settings.max_history_entries,
            "image",
            f"Изображение: {file.filename or 'upload'}",
            (analysis.description or "")[:200],
            response_full=image_payload,
        )
        return JSONResponse(status_code=200, content=image_payload)
    except Exception as e:
        logger.exception("analyze_image: %s", e)
        return _err(str(e) or "Внутренняя ошибка.")
