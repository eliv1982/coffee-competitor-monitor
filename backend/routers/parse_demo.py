"""Endpoints: /parse_demo, /parse_demo/batch."""
import logging
from fastapi import APIRouter, HTTPException
from fastapi.responses import JSONResponse

from backend.config import get_settings, get_competitor_urls_list

logger = logging.getLogger("backend.routers.parse_demo")
from backend.models.schemas import ParsedContent, ParseDemoRequest
from backend.services import history_service
from backend.services.openai_service import analyze_parsed_page
from backend.services.parser_service import parse_url, parse_url_auto
from openai import OpenAI

router = APIRouter(prefix="", tags=["parse_demo"])


def _get_client() -> OpenAI:
    settings = get_settings()
    if not (settings.openai_api_key or "").strip():
        raise HTTPException(status_code=503, detail="В .env задайте OPENAI_API_KEY.")
    kwargs = {"api_key": settings.openai_api_key.strip()}
    if getattr(settings, "openai_base_url", "") and settings.openai_base_url.strip():
        kwargs["base_url"] = settings.openai_base_url.strip()
    return OpenAI(**kwargs)


@router.post("/parse_demo")
def parse_demo_endpoint(body: ParseDemoRequest):
    """Парсинг URL: извлечение title, h1, первого абзаца и анализ контента.
    Успех: 200, тело = { url, title, h1, first_paragraph, analysis }.
    Ошибка: 200, тело = { error: "..." }.
    """
    try:
        url = body.url.strip()
        if not url.startswith("http://") and not url.startswith("https://"):
            url = "https://" + url
        logger.info("POST /parse_demo: url=%s", url)
        settings = get_settings()
        use_selenium = getattr(settings, "parser_use_selenium", False)
        title, h1, first_paragraph, parse_error = parse_url_auto(
            url,
            timeout=settings.parser_timeout,
            user_agent=settings.parser_user_agent,
            use_selenium=use_selenium,
        )
        # Повтор с Selenium при таймауте или при скудном контенте (JS-сайты отдают только title)
        content_len = len(title or "") + len(h1 or "") + len(first_paragraph or "")
        retry_selenium = not use_selenium and (
            (parse_error and "таймаут" in parse_error.lower())
            or (content_len > 0 and content_len < 100)
        )
        if retry_selenium:
            logger.info("POST /parse_demo: retry with Selenium (timeout or little content) url=%s", url)
            title, h1, first_paragraph, parse_error = parse_url_auto(
                url,
                timeout=min(settings.parser_timeout + 15, 60),
                user_agent=settings.parser_user_agent,
                use_selenium=True,
            )
        logger.debug("POST /parse_demo parsed: title=%s h1=%s paragraph_len=%d", bool(title), bool(h1), len(first_paragraph))
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
            return JSONResponse(status_code=200, content={"error": err_msg})
        try:
            client = _get_client()
        except HTTPException as e:
            return JSONResponse(status_code=200, content={"error": e.detail or "Ошибка конфигурации."})
        analysis = analyze_parsed_page(
            client, settings.openai_model, title, h1, first_paragraph
        )
        parsed = ParsedContent(
            url=url,
            title=title or None,
            h1=h1 or None,
            first_paragraph=first_paragraph or None,
            analysis=analysis,
        )
        payload = {
            "url": parsed.url,
            "title": parsed.title,
            "h1": parsed.h1,
            "first_paragraph": parsed.first_paragraph,
            "analysis": parsed.analysis.model_dump(mode="json") if parsed.analysis else None,
        }
        history_service.add_entry(
            settings.history_file,
            settings.max_history_entries,
            "parse",
            f"URL: {url}",
            title or (analysis.summary[:100] if analysis.summary else "N/A"),
            response_full=payload,
        )
        return JSONResponse(status_code=200, content=payload)
    except Exception as e:
        logger.exception("POST /parse_demo error: %s", e)
        err_msg = str(e) or "Внутренняя ошибка."
        try:
            url = body.url.strip() if body else ""
            if not url.startswith("http"):
                url = "https://" + url
            settings = get_settings()
            history_service.add_entry(
                settings.history_file,
                settings.max_history_entries,
                "parse",
                f"URL: {url}",
                err_msg[:300],
                response_full={"error": err_msg, "url": url},
            )
        except Exception:
            pass
        return JSONResponse(status_code=200, content={"error": err_msg})


@router.post("/parse_demo/batch")
def parse_demo_batch_endpoint():
    """
    Автоматический сбор по всем URL конкурентов из config (COMPETITOR_URLS).
    Для каждого URL: парсинг (Selenium, если parser_use_selenium=True), анализ ИИ, запись в историю.
    Возвращает список результатов по каждому URL.
    """
    try:
        settings = get_settings()
        urls = get_competitor_urls_list(settings)
        if not urls:
            return JSONResponse(
                status_code=200,
                content={
                    "error": "В настройках нет URL конкурентов. Задайте COMPETITOR_URLS в .env (через запятую).",
                    "results": [],
                },
            )
        use_selenium = getattr(settings, "parser_use_selenium", False)
        try:
            client = _get_client()
        except HTTPException as e:
            return JSONResponse(status_code=200, content={"error": e.detail or "Ошибка конфигурации (OPENAI_API_KEY).", "results": []})

        results = []
        for url in urls:
            url = url.strip()
            if not url.startswith("http://") and not url.startswith("https://"):
                url = "https://" + url
            logger.info("parse_demo/batch: url=%s", url)
            title, h1, first_paragraph, parse_error = parse_url_auto(
                url,
                timeout=settings.parser_timeout,
                user_agent=settings.parser_user_agent,
                use_selenium=use_selenium,
            )
            if not title and not h1 and not first_paragraph:
                results.append({
                    "url": url,
                    "error": parse_error or "Не удалось извлечь контент.",
                    "analysis": None,
                })
                continue
            try:
                analysis = analyze_parsed_page(
                    client, settings.openai_model, title or "", h1 or "", first_paragraph or ""
                )
                payload_item = {
                    "url": url,
                    "title": title or None,
                    "h1": h1 or None,
                    "first_paragraph": (first_paragraph or "")[:500],
                    "analysis": analysis.model_dump(mode="json") if hasattr(analysis, "model_dump") else None,
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
                logger.warning("parse_demo/batch analyze failed for %s: %s", url, e)
                results.append({"url": url, "error": str(e), "analysis": None})

        return JSONResponse(status_code=200, content={"results": results, "total": len(results)})
    except Exception as e:
        logger.exception("POST /parse_demo/batch error: %s", e)
        return JSONResponse(status_code=200, content={"error": str(e) or "Внутренняя ошибка.", "results": []})
