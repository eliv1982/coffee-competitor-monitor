"""OpenAI API calls for text and image analysis (ниша: кофейни).

Uses the OpenAI SDK's structured-output support (`client.beta.chat.completions.parse`
with a Pydantic `response_format`) instead of prompting for JSON and recovering it
with regex: the SDK enforces the schema server-side, so a successful call always
returns a validated instance of the requested model. Refusals, schema/parse
failures, timeouts, and upstream API errors are handled explicitly and mapped to
backend.errors types (never silently substituted with misleading zero/default values).
"""
import logging
from typing import Any, TypeVar

from openai import (
    APIConnectionError,
    APIStatusError,
    APITimeoutError,
    AuthenticationError,
    BadRequestError,
    ContentFilterFinishReasonError,
    LengthFinishReasonError,
    OpenAI,
)
from pydantic import BaseModel, ValidationError

from backend.errors import InvalidInputError, ServiceUnavailableError, UpstreamError, UpstreamTimeoutError
from backend.models.schemas import CompetitorAnalysis, ImageAnalysis, UrlAnalysis

logger = logging.getLogger("backend.services.openai")

T = TypeVar("T", bound=BaseModel)

DEFAULT_TIMEOUT = 60.0


def get_openai_client(settings) -> OpenAI:
    """Build a client for the official OpenAI API using the configured key/timeout.

    Only api.openai.com is supported by this project (portfolio scope — see docs.md);
    there is deliberately no OPENAI_BASE_URL/provider-abstraction mechanism here.
    Raises ServiceUnavailableError if OPENAI_API_KEY isn't configured.
    """
    if not (settings.openai_api_key or "").strip():
        raise ServiceUnavailableError("В .env задайте OPENAI_API_KEY.")
    return OpenAI(api_key=settings.openai_api_key.strip(), timeout=settings.openai_timeout)


SYSTEM_COFFEE = """Ты — эксперт по анализу кофеен и кофейного бизнеса. Отвечай на русском языке."""

# Анализ текста — строго по контексту загруженного содержимого
TEXT_USER_TEMPLATE = """Проанализируй ТОЛЬКО тот контент, который приведён ниже. Оценки и выводы должны относиться исключительно к нему.

Важно: если в тексте речь о карьере, вакансиях, команде — анализируй карьеру и команду; если о меню и ценах — анализируй меню и цены. Не предлагай «добавить меню» или «уточнить цены», если в тексте об этом нет речи. Не придумывай темы, которых нет в тексте.

Заполни поля:
- strengths: сильные стороны (по контексту текста)
- weaknesses: слабые стороны (по контексту текста)
- unique_offers: уникальные предложения (если есть в тексте)
- unique_selling_points: уникальные торговые предложения (если есть в тексте)
- recommendations: рекомендации только по тому, что реально есть в тексте
- summary: краткое резюме (1-2 предложения) именно этого контента
- content_quality: число от 0 до 10 — качество поданного контента
- price_category: "низкие"/"средние"/"высокие" только если в тексте есть намёки на цены; иначе пустая строка

Текст:
---
{text}
---"""

# Анализ скриншота — только по тому, что видно на изображении
IMAGE_USER_COFFEE = """Оцени ТОЛЬКО то, что реально видно на скриншоте. Не предлагай контент, которого на скриншоте нет.

- description: что именно изображено на скриншоте (страница о карьере, меню, главная и т.д.)
- design_score: число 0–10 — по видимому дизайну
- animation_potential: true/false — по видимым элементам
- menu_visibility: число 0–10 — только если на скриншоте видно меню или навигацию к нему; иначе 0
- brand_style: строка — по визуалу
- usability_score: число 0–10 — по видимой структуре
- content_quality: число 0–10 — качество того контента, что виден на скриншоте
- marketing_insights: инсайты только по видимому
- recommendations: рекомендации только по тому, что видно
- visual_style_score: число 0–10
- visual_style_analysis: строка — кратко по визуалу"""

PARSE_ANALYZE_TEMPLATE = """Проанализируй ТОЛЬКО приведённые ниже данные страницы. Выводы — строго по этому контексту: если данные о карьере/вакансиях — анализируй карьеру; если о меню/ценах — анализируй их. Не предлагай «добавить меню» или «уточнить цены», если в данных об этом нет.
Если данных мало (только title или короткий текст) — сделай краткий вывод по названию/бренду и укажи в summary, что основное содержимое страницы не удалось извлечь (возможно, сайт подгружает контент через JS). Не пиши «данные отсутствуют, анализ провести нельзя» — всегда дай хотя бы краткий анализ по тому, что есть.

Заполни поля:
- strengths: сильные стороны (по контексту)
- weaknesses: слабые стороны (по контексту)
- unique_offers: уникальные предложения (если есть в данных)
- unique_selling_points: уникальные торговые предложения (если есть)
- recommendations: рекомендации только по имеющимся данным
- summary: краткое резюме именно этого контента
- content_quality: число 0-10
- price_category: "низкие"/"средние"/"высокие" только при намёках на цены в данных; иначе пустая строка

Данные страницы:
title: {title}
h1: {h1}
first_paragraph: {first_paragraph}"""

# === Единый анализ по URL (скриншот + текст в одном запросе, ответ только на русском) ===
SYSTEM_URL_UNIFIED = "Ты эксперт по анализу сайтов кофеен. Все текстовые поля в ответе — строго на русском языке."

URL_UNIFIED_TEMPLATE = """По скриншоту сайта и извлечённому тексту страницы сделай единый анализ кофейни/кафе. Учитывай и визуал (скриншот), и текст. Весь ответ — только на русском языке.

Заполни поля (все строки и списки — по-русски):
- summary: краткое резюме анализа сайта (2–4 предложения)
- design_score: число 0–10 (оценка дизайна по скриншоту)
- usability_score: число 0–10 (удобство навигации/интерфейса)
- content_quality: число 0–10 (качество контента)
- unique_selling_points: уникальные торговые предложения для гостей заведения: акции, программа лояльности, подарочные предложения, фишка бренда (например «подарок при заказе двух напитков»). НЕ включай сюда условия франшизы (инвестиции, окупаемость, прибыль) — их укажи в franchise_info.
- franchise_info: только если на странице есть блок про франшизу: инвестиции, окупаемость, прибыль, условия для партнёров. Если страница не про франшизу — пустой список.
- price_category: "низкие" / "средние" / "высокие" или пустая строка, если цен нет
- target_audience: целевая аудитория (если понятно из контента)
- strengths: сильные стороны сайта
- weaknesses: слабые стороны или что можно улучшить
- recommendations: краткие рекомендации

Текст со страницы (для контекста):
{extracted_text}

Проанализируй скриншот и текст вместе и верни один объединённый результат. Все поля — на русском."""


def _run_structured(
    client: OpenAI,
    *,
    model: str,
    system: str,
    user_content: Any,
    response_model: type[T],
    timeout: float = DEFAULT_TIMEOUT,
    temperature: float = 0.3,
    max_tokens: int | None = None,
) -> T:
    """Call OpenAI with a structured-output contract. Raises backend.errors types on any failure
    (refusal, malformed/truncated result, timeout, upstream API error) — never returns a
    silently-defaulted result."""
    kwargs: dict[str, Any] = {}
    if max_tokens is not None:
        kwargs["max_tokens"] = max_tokens
    try:
        completion = client.beta.chat.completions.parse(
            model=model,
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": user_content},
            ],
            response_format=response_model,
            temperature=temperature,
            timeout=timeout,
            **kwargs,
        )
    except APITimeoutError as e:
        raise UpstreamTimeoutError("Таймаут запроса к OpenAI.", log_message=str(e)) from e
    except AuthenticationError as e:
        raise ServiceUnavailableError("Некорректный или отсутствующий OPENAI_API_KEY.", log_message=str(e)) from e
    except BadRequestError as e:
        raise InvalidInputError("OpenAI отклонил запрос: некорректные входные данные.", log_message=str(e)) from e
    except LengthFinishReasonError as e:
        raise UpstreamError(
            "Ответ модели был обрезан (превышен лимит токенов). Попробуйте сократить входные данные.",
            log_message=str(e),
        ) from e
    except ContentFilterFinishReasonError as e:
        # Raised by the SDK's own structured-output parsing when finish_reason=="content_filter"
        # (generation itself was stopped by moderation) — distinct from choice.message.refusal
        # (a "soft" refusal with a completed message), handled separately below.
        logger.warning("openai content_filter finish_reason: model=%s", model)
        raise UpstreamError(
            "Модель отказалась выполнить анализ этого содержимого (фильтр содержимого).",
            log_message=str(e),
        ) from e
    except (APIConnectionError, APIStatusError) as e:
        raise UpstreamError("Ошибка обращения к OpenAI.", log_message=str(e)) from e
    except ValidationError as e:
        # The SDK validates the model's JSON against response_model itself (model_validate_json)
        # as part of .parse() — a schema mismatch raises pydantic's ValidationError directly,
        # uncaught by any of the openai.* exception types above. Must not become a silently
        # defaulted result or leak raw validation detail to the client (see docs.md).
        raise UpstreamError(
            "Не удалось разобрать структурированный ответ модели.",
            log_message=str(e),
        ) from e

    choice = completion.choices[0]
    if choice.message.refusal:
        logger.warning("openai refusal: model=%s refusal_len=%d", model, len(choice.message.refusal))
        raise UpstreamError(
            "Модель отказалась выполнить анализ этого содержимого.",
            log_message=f"refusal (len={len(choice.message.refusal)})",
        )
    parsed = choice.message.parsed
    if parsed is None:
        raise UpstreamError(
            "Не удалось разобрать структурированный ответ модели.",
            log_message=f"parsed is None, finish_reason={choice.finish_reason}",
        )
    return parsed


def analyze_text(client: OpenAI, model: str, text: str, *, timeout: float = DEFAULT_TIMEOUT) -> CompetitorAnalysis:
    """Run text analysis (coffee niche) and return a validated CompetitorAnalysis."""
    logger.info("openai analyze_text: model=%s text_len=%d", model, len(text))
    return _run_structured(
        client,
        model=model,
        system=SYSTEM_COFFEE,
        user_content=TEXT_USER_TEMPLATE.format(text=text),
        response_model=CompetitorAnalysis,
        timeout=timeout,
    )


def analyze_image_from_base64(
    client: OpenAI, model: str, base64_image: str, mime_type: str = "image/jpeg", *, timeout: float = DEFAULT_TIMEOUT
) -> ImageAnalysis:
    """Run image analysis (coffee shop site/landing screenshot) and return a validated ImageAnalysis."""
    logger.info("openai analyze_image: model=%s mime=%s base64_len=%d", model, mime_type, len(base64_image))
    user_content = [
        {"type": "text", "text": IMAGE_USER_COFFEE},
        {"type": "image_url", "image_url": {"url": f"data:{mime_type};base64,{base64_image}"}},
    ]
    return _run_structured(
        client,
        model=model,
        system=SYSTEM_COFFEE,
        user_content=user_content,
        response_model=ImageAnalysis,
        timeout=timeout,
        max_tokens=1024,
    )


def analyze_parsed_page(
    client: OpenAI,
    model: str,
    title: str,
    h1: str,
    first_paragraph: str,
    *,
    timeout: float = DEFAULT_TIMEOUT,
    max_ai_text_chars: int = 12000,
) -> CompetitorAnalysis:
    """Analyze extracted page content (coffee niche) and return a validated CompetitorAnalysis.

    title/h1/first_paragraph come from parsed page HTML (backend.services.parser_service) and
    have no a-priori upper bound (e.g. a pathological <title> tag) — each is capped to
    max_ai_text_chars before being sent, same budget/intent as the other analyze_* calls.
    """
    title = (title or "")[:max_ai_text_chars]
    h1 = (h1 or "")[:max_ai_text_chars]
    first_paragraph = (first_paragraph or "")[:max_ai_text_chars]
    logger.info(
        "openai analyze_parsed_page: model=%s title_len=%d h1_len=%d paragraph_len=%d",
        model, len(title), len(h1), len(first_paragraph),
    )
    return _run_structured(
        client,
        model=model,
        system=SYSTEM_COFFEE,
        user_content=PARSE_ANALYZE_TEMPLATE.format(title=title, h1=h1, first_paragraph=first_paragraph),
        response_model=CompetitorAnalysis,
        timeout=timeout,
    )


def analyze_url_unified(
    client: OpenAI,
    model: str,
    base64_image: str,
    mime_type: str,
    extracted_text: str,
    *,
    timeout: float = DEFAULT_TIMEOUT,
    max_ai_text_chars: int = 12000,
) -> UrlAnalysis:
    """Единый анализ сайта по скриншоту и тексту в одном запросе. Возвращает валидированный UrlAnalysis."""
    text_for_prompt = (extracted_text or "").strip() or "(Текст страницы не извлечён)"
    if len(text_for_prompt) > max_ai_text_chars:
        text_for_prompt = text_for_prompt[:max_ai_text_chars] + "\n… (обрезано)"
    logger.info(
        "openai analyze_url_unified: model=%s base64_len=%d text_len=%d", model, len(base64_image), len(text_for_prompt)
    )
    prompt_text = URL_UNIFIED_TEMPLATE.format(extracted_text=text_for_prompt)
    user_content = [
        {"type": "text", "text": prompt_text},
        {"type": "image_url", "image_url": {"url": f"data:{mime_type};base64,{base64_image}"}},
    ]
    return _run_structured(
        client,
        model=model,
        system=SYSTEM_URL_UNIFIED,
        user_content=user_content,
        response_model=UrlAnalysis,
        timeout=timeout,
        max_tokens=1024,
    )
