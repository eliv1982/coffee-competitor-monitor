"""Endpoint: POST /analyze_url — анализ сайта по URL (Selenium: скриншот + текст, затем OpenAI)."""
import base64
import logging

from fastapi import APIRouter
from pydantic import BaseModel
from starlette.concurrency import run_in_threadpool

from backend.config import get_settings
from backend.errors import InvalidInputError, ServiceUnavailableError, UpstreamError, UpstreamTimeoutError
from backend.models.schemas import AnalyzeUrlRequest, UrlAnalysis
from backend.services import history_service
from backend.services.openai_service import analyze_url_unified, get_openai_client
from backend.services.parser_service import (
    SELENIUM_NOT_INSTALLED_MESSAGE,
    SELENIUM_TIMEOUT_MESSAGE,
    get_url_screenshot_and_text,
)
from backend.services.url_safety import UnsafeURLError, ensure_scheme, redact_url

logger = logging.getLogger("backend.routers.analyze_url")

router = APIRouter(prefix="", tags=["analyze_url"])


class AnalyzeUrlResponse(BaseModel):
    """Ответ POST /analyze_url."""

    url: str
    analysis: UrlAnalysis


@router.post("/analyze_url", response_model=AnalyzeUrlResponse)
async def analyze_url_endpoint(body: AnalyzeUrlRequest):
    """
    По URL: Selenium открывает страницу, делает скриншот и извлекает текст (см.
    backend.services.parser_service.get_url_screenshot_and_text — только начальный URL
    проверяется политикой безопасности, только доверенные/публичные сайты поддерживаются).
    Скриншот и текст передаются в OpenAI одним запросом (structured output).
    Ответ: { "url": "...", "analysis": {...} }, запись сохраняется в историю.
    """
    url = ensure_scheme(body.url)
    logger.info("POST /analyze_url: url=%s", redact_url(url))
    settings = get_settings()
    timeout = settings.parser_timeout

    try:
        screenshot_bytes, mime, extracted_text, err_msg = await run_in_threadpool(
            get_url_screenshot_and_text,
            url,
            timeout=timeout,
            user_agent=settings.parser_user_agent,
            allow_no_sandbox=settings.selenium_allow_no_sandbox,
            max_page_source_chars=settings.max_remote_response_bytes,
        )
    except UnsafeURLError as e:
        raise InvalidInputError(str(e)) from e

    if err_msg or not screenshot_bytes:
        if err_msg == SELENIUM_NOT_INSTALLED_MESSAGE:
            raise ServiceUnavailableError(err_msg)
        if err_msg == SELENIUM_TIMEOUT_MESSAGE:
            raise UpstreamTimeoutError(err_msg)
        raise UpstreamError(err_msg or "Не удалось получить скриншот и текст страницы.")

    client = get_openai_client(settings)
    analysis = await run_in_threadpool(
        analyze_url_unified,
        client,
        settings.openai_model,
        base64.standard_b64encode(screenshot_bytes).decode("ascii"),
        mime,
        extracted_text or "",
        timeout=settings.openai_timeout,
        max_ai_text_chars=settings.max_ai_text_chars,
    )

    response_payload = {"url": url, "analysis": analysis.model_dump(mode="json")}
    history_service.add_entry(
        settings.history_file,
        settings.max_history_entries,
        "analyze_url",
        f"URL: {url}",
        (analysis.summary or url)[:200],
        response_full=response_payload,
    )
    return response_payload
