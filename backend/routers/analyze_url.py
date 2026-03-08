"""Endpoint: POST /analyze_url — анализ сайта по URL (Selenium: скриншот + текст, затем OpenAI)."""
import base64
import logging
from fastapi import APIRouter, HTTPException
from fastapi.responses import JSONResponse

from backend.config import get_settings
from backend.models.schemas import AnalyzeUrlRequest
from backend.services import history_service
from backend.services.openai_service import analyze_url_unified
from backend.services.parser_service import get_url_screenshot_and_text
from openai import OpenAI

logger = logging.getLogger("backend.routers.analyze_url")

router = APIRouter(prefix="", tags=["analyze_url"])


def _get_client() -> OpenAI:
    settings = get_settings()
    if not (settings.openai_api_key or "").strip():
        raise HTTPException(status_code=503, detail="В .env задайте OPENAI_API_KEY.")
    kwargs = {"api_key": settings.openai_api_key.strip()}
    if getattr(settings, "openai_base_url", "") and settings.openai_base_url.strip():
        kwargs["base_url"] = settings.openai_base_url.strip()
    return OpenAI(**kwargs)


def _err(msg: str, **extra):
    return JSONResponse(status_code=200, content={"error": msg, **extra})


@router.post("/analyze_url")
async def analyze_url_endpoint(body: AnalyzeUrlRequest):
    """
    По URL: Selenium открывает страницу, делает скриншот и извлекает текст.
    Скриншот и текст передаются в OpenAI (два анализа по промптам из сценариев).
    Результат: screenshot_analysis (по скриншоту) и text_analysis (по тексту), запись в историю.
    """
    try:
        url = body.url.strip()
        if not url.startswith("http://") and not url.startswith("https://"):
            url = "https://" + url
        logger.info("POST /analyze_url: url=%s", url)
        settings = get_settings()
        timeout = getattr(settings, "parser_timeout", 15.0) or 15.0
        if timeout < 20:
            timeout = 20
        user_agent = getattr(settings, "parser_user_agent", None)

        screenshot_bytes, mime, extracted_text, err_msg = get_url_screenshot_and_text(
            url, timeout=timeout, user_agent=user_agent
        )
        if err_msg:
            return _err(err_msg, url=url, analysis=None)

        try:
            client = _get_client()
        except HTTPException as e:
            return _err(e.detail or "Ошибка конфигурации (OPENAI_API_KEY).", url=url)

        analysis = None
        if screenshot_bytes:
            b64 = base64.standard_b64encode(screenshot_bytes).decode("ascii")
            analysis = analyze_url_unified(
                client, settings.openai_model, b64, mime, extracted_text or ""
            )

        summary = (analysis or {}).get("summary", "")[:200] if analysis else url
        response_payload = {
            "url": url,
            "analysis": analysis,
        }
        history_service.add_entry(
            settings.history_file,
            settings.max_history_entries,
            "analyze_url",
            f"URL: {url}",
            summary or url,
            response_full=response_payload,
        )
        return JSONResponse(status_code=200, content=response_payload)
    except Exception as e:
        logger.exception("POST /analyze_url error: %s", e)
        return _err(str(e) or "Внутренняя ошибка.")
