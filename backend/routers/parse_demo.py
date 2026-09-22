"""Endpoints: /parse_demo, /parse_demo/batch."""
import logging

from fastapi import APIRouter

from backend.config import get_competitor_urls_list, get_settings
from backend.errors import InvalidInputError, UpstreamError, UpstreamTimeoutError
from backend.models.schemas import ParseDemoBatchResponse, ParsedContent, ParseDemoRequest
from backend.services import history_service
from backend.services.openai_service import analyze_parsed_page, get_openai_client
from backend.services.parser_service import parse_url_auto
from backend.services.url_safety import UnsafeURLError, ensure_scheme, redact_url

logger = logging.getLogger("backend.routers.parse_demo")

router = APIRouter(prefix="", tags=["parse_demo"])


def _parse_url_auto(url: str, settings, *, timeout: float, use_selenium: bool) -> tuple[str, str, str, str]:
    """parse_url_auto with every configured parser setting wired through — connect timeout,
    redirect count and response-size cap were previously only honored by parse_url's own
    (hardcoded) defaults, never by what's actually configured (see docs.md)."""
    return parse_url_auto(
        url,
        timeout=timeout,
        user_agent=settings.parser_user_agent,
        use_selenium=use_selenium,
        connect_timeout=settings.parser_connect_timeout,
        max_redirects=settings.max_redirects,
        max_response_bytes=settings.max_remote_response_bytes,
        allow_no_sandbox=settings.selenium_allow_no_sandbox,
    )


@router.post("/parse_demo", response_model=ParsedContent)
def parse_demo_endpoint(body: ParseDemoRequest):
    """Парсинг URL: извлечение title, h1, первого абзаца и анализ контента.
    Синхронный def-эндпоинт: FastAPI выполняет его в threadpool, поэтому блокирующий
    Selenium/httpx-запрос и вызов OpenAI не блокируют event loop.
    """
    settings = get_settings()
    url = ensure_scheme(body.url)
    logger.info("POST /parse_demo: url=%s", redact_url(url))
    use_selenium = settings.parser_use_selenium

    try:
        title, h1, first_paragraph, parse_error = _parse_url_auto(
            url, settings, timeout=settings.parser_timeout, use_selenium=use_selenium
        )
        # Повтор с Selenium при таймауте или при скудном контенте (JS-сайты отдают только title)
        content_len = len(title or "") + len(h1 or "") + len(first_paragraph or "")
        retry_selenium = not use_selenium and (
            (parse_error and "таймаут" in parse_error.lower())
            or (content_len > 0 and content_len < 100)
        )
        if retry_selenium:
            logger.info("POST /parse_demo: retry with Selenium (timeout or little content) url=%s", redact_url(url))
            title, h1, first_paragraph, parse_error = _parse_url_auto(
                url, settings, timeout=min(settings.parser_timeout + 15, 60), use_selenium=True
            )
    except UnsafeURLError as e:
        raise InvalidInputError(str(e)) from e

    logger.debug(
        "POST /parse_demo parsed: title=%s h1=%s paragraph_len=%d", bool(title), bool(h1), len(first_paragraph)
    )
    if not title and not h1 and not first_paragraph:
        err_msg = parse_error or "Не удалось извлечь контент по URL (таймаут или недоступность)."
        history_service.add_entry(
            settings.history_file,
            settings.max_history_entries,
            "parse",
            f"URL: {url}",
            err_msg[:300],
            response_full={"error": err_msg, "url": url},
        )
        if "таймаут" in err_msg.lower():
            raise UpstreamTimeoutError(err_msg)
        raise UpstreamError(err_msg)

    client = get_openai_client(settings)
    analysis = analyze_parsed_page(
        client,
        settings.openai_model,
        title,
        h1,
        first_paragraph,
        timeout=settings.openai_timeout,
        max_ai_text_chars=settings.max_ai_text_chars,
    )
    parsed = ParsedContent(
        url=url,
        title=title or None,
        h1=h1 or None,
        first_paragraph=first_paragraph or None,
        analysis=analysis,
    )
    payload = parsed.model_dump(mode="json")
    history_service.add_entry(
        settings.history_file,
        settings.max_history_entries,
        "parse",
        f"URL: {url}",
        title or (analysis.summary[:100] if analysis.summary else "N/A"),
        response_full=payload,
    )
    return parsed


@router.post("/parse_demo/batch", response_model=ParseDemoBatchResponse)
def parse_demo_batch_endpoint():
    """
    Автоматический сбор по всем URL конкурентов из config (COMPETITOR_URLS).
    Для каждого URL: парсинг (Selenium, если parser_use_selenium=True), анализ ИИ, запись в историю.
    Возвращает { results: [...], total: N }. Отдельный URL, который не удалось обработать,
    отражается как элемент results с непустым полем error (а не как отказ всего запроса) —
    это пакетная операция, где частичный успех — нормальный исход.
    """
    settings = get_settings()
    urls = get_competitor_urls_list(settings)
    if not urls:
        raise InvalidInputError("В настройках нет URL конкурентов. Задайте COMPETITOR_URLS в .env (через запятую).")

    client = get_openai_client(settings)

    results = []
    for raw_url in urls:
        url = ensure_scheme(raw_url)
        logger.info("parse_demo/batch: url=%s", redact_url(url))
        try:
            title, h1, first_paragraph, parse_error = _parse_url_auto(
                url, settings, timeout=settings.parser_timeout, use_selenium=settings.parser_use_selenium
            )
        except UnsafeURLError as e:
            results.append({"url": url, "error": str(e), "analysis": None})
            continue

        if not title and not h1 and not first_paragraph:
            results.append({
                "url": url,
                "error": parse_error or "Не удалось извлечь контент.",
                "analysis": None,
            })
            continue
        try:
            analysis = analyze_parsed_page(
                client,
                settings.openai_model,
                title or "",
                h1 or "",
                first_paragraph or "",
                timeout=settings.openai_timeout,
                max_ai_text_chars=settings.max_ai_text_chars,
            )
            payload_item = {
                "url": url,
                "title": title or None,
                "h1": h1 or None,
                "first_paragraph": (first_paragraph or "")[:500],
                "analysis": analysis.model_dump(mode="json"),
                "error": None,
            }
            history_service.add_entry(
                settings.history_file,
                settings.max_history_entries,
                "parse",
                f"URL: {url}",
                title or (analysis.summary[:100] if analysis.summary else "N/A"),
                response_full=payload_item,
            )
            results.append(payload_item)
        except Exception as e:
            logger.warning("parse_demo/batch analyze failed for %s: %s", redact_url(url), type(e).__name__)
            message = getattr(e, "message", None) or "Ошибка анализа."
            results.append({"url": url, "error": message, "analysis": None})

    return {"results": results, "total": len(results)}
