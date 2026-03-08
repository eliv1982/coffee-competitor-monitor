"""OpenAI API calls for text and image analysis (ниша: кофейни)."""
import json
import logging
import re
from typing import Any

from openai import OpenAI

from backend.models.schemas import CompetitorAnalysis, ImageAnalysis

logger = logging.getLogger("backend.services.openai")


SYSTEM_COFFEE = """Ты — эксперт по анализу кофеен и кофейного бизнеса. Отвечай только валидным JSON на русском языке, без markdown-блоков и пояснений вне JSON."""

# Анализ текста — строго по контексту загруженного содержимого
TEXT_USER_TEMPLATE = """Проанализируй ТОЛЬКО тот контент, который приведён ниже. Оценки и выводы должны относиться исключительно к нему.

Важно: если в тексте речь о карьере, вакансиях, команде — анализируй карьеру и команду; если о меню и ценах — анализируй меню и цены. Не предлагай «добавить меню» или «уточнить цены», если в тексте об этом нет речи. Не придумывай темы, которых нет в тексте.

Верни один JSON-объект:
- strengths: массив строк — сильные стороны (по контексту текста)
- weaknesses: массив строк — слабые стороны (по контексту текста)
- unique_offers: массив строк — уникальные предложения (если есть в тексте)
- unique_selling_points: массив строк — уникальные торговые предложения (если есть в тексте)
- recommendations: массив строк — рекомендации только по тому, что реально есть в тексте
- summary: строка — краткое резюме (1-2 предложения) именно этого контента
- content_quality: число от 0 до 10 — качество поданного контента
- price_category: строка "низкие"/"средние"/"высокие" только если в тексте есть намёки на цены; иначе пустая строка

Текст:
---
{text}
---"""

# Анализ скриншота — только по тому, что видно на изображении
IMAGE_USER_COFFEE = """Оцени ТОЛЬКО то, что реально видно на скриншоте. Не предлагай контент, которого на скриншоте нет. Верни один JSON без markdown:

- description: строка — что именно изображено на скриншоте (страница о карьере, меню, главная и т.д.)
- design_score: число 0–10 — по видимому дизайну
- animation_potential: true/false — по видимым элементам
- menu_visibility: число 0–10 — только если на скриншоте видно меню или навигацию к нему; иначе 0
- brand_style: строка — по визуалу
- usability_score: число 0–10 — по видимой структуре
- content_quality: число 0–10 — качество того контента, что виден на скриншоте
- marketing_insights: массив строк — инсайты только по видимому
- recommendations: массив строк — рекомендации только по тому, что видно
- visual_style_score: число 0–10
- visual_style_analysis: строка — кратко по визуалу"""

PARSE_ANALYZE_TEMPLATE = """Проанализируй ТОЛЬКО приведённые ниже данные страницы. Выводы — строго по этому контексту: если данные о карьере/вакансиях — анализируй карьеру; если о меню/ценах — анализируй их. Не предлагай «добавить меню» или «уточнить цены», если в данных об этом нет.
Если данных мало (только title или короткий текст) — сделай краткий вывод по названию/бренду и укажи в summary, что основное содержимое страницы не удалось извлечь (возможно, сайт подгружает контент через JS). Не пиши «данные отсутствуют, анализ провести нельзя» — всегда дай хотя бы краткий анализ по тому, что есть.
Верни один JSON:
- strengths: массив сильных сторон (по контексту)
- weaknesses: массив слабых сторон (по контексту)
- unique_offers: массив уникальных предложений (если есть в данных)
- unique_selling_points: массив уникальных торговых предложений (если есть)
- recommendations: массив рекомендаций только по имеющимся данным
- summary: краткое резюме именно этого контента
- content_quality: число 0-10
- price_category: "низкие"/"средние"/"высокие" только при намёках на цены в данных; иначе пустая строка

Данные страницы:
title: {title}
h1: {h1}
first_paragraph: {first_paragraph}

Верни только валидный JSON без markdown."""

# === Анализ по скриншоту (для /analyze_url и /analyze_image) ===
SYSTEM_UI_UX = "You are an expert in UI/UX design and coffee shop marketing. Respond with valid JSON only, no markdown or code blocks."

IMAGE_ANALYZE_URL_TEMPLATE = """Analyze ONLY what is visible on this screenshot. Do not suggest content that is not visible. If the page shows careers/vacancies, analyze that; if it shows menu/prices, analyze that. Provide a JSON:
- design_score: integer 0-10 (from what is visible)
- animation_potential: boolean (only if visible)
- usability_score: integer 0-10 (from visible layout)
- content_quality: integer 0-10 (of visible content only)
- unique_selling_points: list of strings (only what is visible or clearly stated)
- price_category: "low"/"medium"/"high" only if prices or clear price hints are visible; otherwise empty string
- additional_notes: string (observations about what is actually on the screenshot)"""

# === Анализ по текстовому содержимому (для /analyze_url и /analyzetext) ===
TEXT_ANALYZE_URL_TEMPLATE = """Analyze ONLY the text below. Match your output to the context: if the text is about careers/vacancies, analyze that; if about menu/products, analyze that. Do not suggest adding menu or prices if the text does not discuss them. Return a JSON with:
- design_score: integer 0-10 (only if text describes design/interior)
- animation_potential: boolean (only if text mentions interactive elements)
- usability_score: integer 0-10 (from text hints)
- content_quality: integer 0-10 (of the given text)
- unique_selling_points: list of strings (only what is in the text)
- price_category: "low"/"medium"/"high" only if text mentions prices; otherwise empty
- target_audience: string (only if inferable from text)
- strengths: list of strings (from this text only)
- weaknesses: list of strings (from this text only)

Website text:
{extracted_text}"""

# === Единый анализ по URL (скриншот + текст в одном запросе, ответ только на русском) ===
SYSTEM_URL_UNIFIED = "Ты эксперт по анализу сайтов кофеен. Отвечай только валидным JSON без markdown. Все текстовые поля в ответе — строго на русском языке."

URL_UNIFIED_TEMPLATE = """По скриншоту сайта и извлечённому тексту страницы сделай единый анализ кофейни/кафе. Учитывай и визуал (скриншот), и текст. Весь ответ — только на русском языке.

Верни один JSON со следующими полями (все строки и списки — по-русски):
- summary: краткое резюме анализа сайта (2–4 предложения)
- design_score: число 0–10 (оценка дизайна по скриншоту)
- usability_score: число 0–10 (удобство навигации/интерфейса)
- content_quality: число 0–10 (качество контента)
- unique_selling_points: массив строк — уникальные торговые предложения для гостей заведения: акции, программа лояльности, подарочные предложения, фишка бренда (например «подарок при заказе двух напитков»). НЕ включай сюда условия франшизы (инвестиции, окупаемость, прибыль) — их укажи в franchise_info.
- franchise_info: массив строк — только если на странице есть блок про франшизу: инвестиции, окупаемость, прибыль, условия для партнёров. Если страница не про франшизу — пустой массив [].
- price_category: "низкие" / "средние" / "высокие" или пустая строка, если цен нет
- target_audience: целевая аудитория (если понятно из контента)
- strengths: массив строк — сильные стороны сайта
- weaknesses: массив строк — слабые стороны или что можно улучшить
- recommendations: массив строк — краткие рекомендации

Текст со страницы (для контекста):
{extracted_text}

Проанализируй скриншот и текст вместе и верни один объединённый JSON. Все поля — на русском."""


def _extract_json_from_content(content: str) -> dict[str, Any] | None:
    """Try to parse JSON from model output (strip markdown code blocks if present)."""
    text = content.strip()
    logger.debug("Extracting JSON from content len=%d", len(text))
    code_match = re.search(r"```(?:json)?\s*([\s\S]*?)\s*```", text)
    if code_match:
        try:
            return json.loads(code_match.group(1).strip())
        except json.JSONDecodeError:
            pass
    obj_match = re.search(r"(\{[\s\S]*\})", text)
    if obj_match:
        try:
            return json.loads(obj_match.group(1))
        except json.JSONDecodeError:
            pass
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        logger.debug("JSON decode failed for raw text")
        return None


def _norm_score(value: Any, default: int = 0) -> int:
    """Normalize a value to 0-10 integer."""
    if isinstance(value, int):
        return max(0, min(10, value))
    try:
        return max(0, min(10, int(float(value))))
    except (TypeError, ValueError):
        return default


def analyze_text(client: OpenAI, model: str, text: str) -> CompetitorAnalysis:
    """Run text analysis (coffee niche) and return CompetitorAnalysis."""
    logger.info("openai analyze_text: model=%s text_len=%d", model, len(text))
    response = client.chat.completions.create(
        model=model,
        messages=[
            {"role": "system", "content": SYSTEM_COFFEE},
            {"role": "user", "content": TEXT_USER_TEMPLATE.format(text=text)},
        ],
        temperature=0.3,
    )
    raw = response.choices[0].message.content or ""
    logger.debug("openai analyze_text raw response len=%d", len(raw))
    data = _extract_json_from_content(raw)
    if data:
        return CompetitorAnalysis(
            strengths=data.get("strengths", []) or [],
            weaknesses=data.get("weaknesses", []) or [],
            unique_offers=data.get("unique_offers", []) or [],
            unique_selling_points=data.get("unique_selling_points", []) or [],
            recommendations=data.get("recommendations", []) or [],
            summary=data.get("summary", "") or "",
            content_quality=_norm_score(data.get("content_quality")),
            price_category=(data.get("price_category") or "").strip() or "",
        )
    logger.warning("openai analyze_text: could not parse JSON, using raw summary")
    return CompetitorAnalysis(summary=raw[:500] if raw else "Не удалось разобрать ответ модели.")


def analyze_image_from_base64(
    client: OpenAI, model: str, base64_image: str, mime_type: str = "image/jpeg"
) -> ImageAnalysis:
    """Run image analysis (coffee shop site/landing screenshot)."""
    logger.info("openai analyze_image: model=%s mime=%s base64_len=%d", model, mime_type, len(base64_image))
    response = client.chat.completions.create(
        model=model,
        messages=[
            {"role": "system", "content": SYSTEM_COFFEE},
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": IMAGE_USER_COFFEE},
                    {
                        "type": "image_url",
                        "image_url": {"url": f"data:{mime_type};base64,{base64_image}"},
                    },
                ],
            },
        ],
        max_tokens=1024,
        temperature=0.3,
    )
    raw = response.choices[0].message.content or ""
    logger.debug("openai analyze_image raw response len=%d", len(raw))
    data = _extract_json_from_content(raw)
    if data:
        def bool_val(v: Any) -> bool:
            if isinstance(v, bool):
                return v
            if isinstance(v, str):
                return v.strip().lower() in ("true", "1", "yes", "да")
            return bool(v)

        design = _norm_score(data.get("design_score") or data.get("visual_style_score"))
        visual = _norm_score(data.get("visual_style_score") or data.get("design_score"))
        return ImageAnalysis(
            description=data.get("description", "") or "",
            marketing_insights=data.get("marketing_insights", []) or [],
            visual_style_score=visual,
            visual_style_analysis=data.get("visual_style_analysis", "") or "",
            recommendations=data.get("recommendations", []) or [],
            design_score=design,
            animation_potential=bool_val(data.get("animation_potential")),
            menu_visibility=_norm_score(data.get("menu_visibility")),
            brand_style=(data.get("brand_style") or "").strip() or "",
            usability_score=_norm_score(data.get("usability_score")),
            content_quality=_norm_score(data.get("content_quality")),
        )
    logger.warning("openai analyze_image: could not parse JSON")
    return ImageAnalysis(description=raw[:300] if raw else "Не удалось разобрать ответ модели.")


def analyze_parsed_page(
    client: OpenAI, model: str, title: str, h1: str, first_paragraph: str
) -> CompetitorAnalysis:
    """Analyze extracted page content (coffee niche)."""
    logger.info("openai analyze_parsed_page: model=%s title_len=%d h1_len=%d paragraph_len=%d", model, len(title), len(h1), len(first_paragraph))
    response = client.chat.completions.create(
        model=model,
        messages=[
            {"role": "system", "content": SYSTEM_COFFEE},
            {
                "role": "user",
                "content": PARSE_ANALYZE_TEMPLATE.format(
                    title=title, h1=h1, first_paragraph=first_paragraph
                ),
            },
        ],
        temperature=0.3,
    )
    raw = response.choices[0].message.content or ""
    logger.debug("openai analyze_parsed_page raw response len=%d", len(raw))
    data = _extract_json_from_content(raw)
    if data and isinstance(data, dict):
        return CompetitorAnalysis(
            strengths=data.get("strengths", []) or [],
            weaknesses=data.get("weaknesses", []) or [],
            unique_offers=data.get("unique_offers", []) or [],
            unique_selling_points=data.get("unique_selling_points", []) or [],
            recommendations=data.get("recommendations", []) or [],
            summary=data.get("summary", "") or "",
            content_quality=_norm_score(data.get("content_quality")),
            price_category=(data.get("price_category") or "").strip() or "",
        )
    logger.warning("openai analyze_parsed_page: could not parse JSON")
    return CompetitorAnalysis(summary=raw[:500] if raw else "Не удалось разобрать ответ модели.")


def _bool_val(v: Any) -> bool:
    if isinstance(v, bool):
        return v
    if isinstance(v, str):
        return v.strip().lower() in ("true", "1", "yes", "да")
    return bool(v)


def analyze_screenshot_for_url(
    client: OpenAI, model: str, base64_image: str, mime_type: str = "image/png"
) -> dict[str, Any]:
    """
    Анализ скриншота сайта кофейни (промпт UI/UX).
    Возвращает dict: design_score, animation_potential, usability_score, content_quality,
    unique_selling_points, price_category, additional_notes.
    """
    logger.info("openai analyze_screenshot_for_url: model=%s base64_len=%d", model, len(base64_image))
    response = client.chat.completions.create(
        model=model,
        messages=[
            {"role": "system", "content": SYSTEM_UI_UX},
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": IMAGE_ANALYZE_URL_TEMPLATE},
                    {"type": "image_url", "image_url": {"url": f"data:{mime_type};base64,{base64_image}"}},
                ],
            },
        ],
        max_tokens=1024,
        temperature=0.3,
    )
    raw = response.choices[0].message.content or ""
    data = _extract_json_from_content(raw)
    if data and isinstance(data, dict):
        return {
            "design_score": _norm_score(data.get("design_score")),
            "animation_potential": _bool_val(data.get("animation_potential")),
            "usability_score": _norm_score(data.get("usability_score")),
            "content_quality": _norm_score(data.get("content_quality")),
            "unique_selling_points": data.get("unique_selling_points") or [],
            "price_category": (data.get("price_category") or "").strip() or "",
            "additional_notes": (data.get("additional_notes") or "").strip() or "",
        }
    return {"additional_notes": raw[:500] if raw else "Не удалось разобрать ответ по скриншоту."}


def analyze_text_for_url(client: OpenAI, model: str, extracted_text: str) -> dict[str, Any]:
    """
    Анализ извлечённого текста сайта кофейни (промпт analyst).
    Возвращает dict: design_score, animation_potential, usability_score, content_quality,
    unique_selling_points, price_category, target_audience, strengths, weaknesses.
    """
    if not (extracted_text or "").strip():
        return {"strengths": [], "weaknesses": [], "target_audience": ""}
    logger.info("openai analyze_text_for_url: model=%s text_len=%d", model, len(extracted_text))
    response = client.chat.completions.create(
        model=model,
        messages=[
            {"role": "system", "content": "You are an analyst specializing in coffee shop businesses. Respond with valid JSON only, no markdown."},
            {"role": "user", "content": TEXT_ANALYZE_URL_TEMPLATE.format(extracted_text=extracted_text.strip())},
        ],
        temperature=0.3,
    )
    raw = response.choices[0].message.content or ""
    data = _extract_json_from_content(raw)
    if data and isinstance(data, dict):
        return {
            "design_score": _norm_score(data.get("design_score")),
            "animation_potential": _bool_val(data.get("animation_potential")),
            "usability_score": _norm_score(data.get("usability_score")),
            "content_quality": _norm_score(data.get("content_quality")),
            "unique_selling_points": data.get("unique_selling_points") or [],
            "price_category": (data.get("price_category") or "").strip() or "",
            "target_audience": (data.get("target_audience") or "").strip() or "",
            "strengths": data.get("strengths") or [],
            "weaknesses": data.get("weaknesses") or [],
        }
    return {"strengths": [], "weaknesses": [], "target_audience": "", "additional_notes": raw[:300] if raw else ""}


def analyze_url_unified(
    client: OpenAI,
    model: str,
    base64_image: str,
    mime_type: str,
    extracted_text: str,
) -> dict[str, Any]:
    """
    Единый анализ сайта по скриншоту и тексту в одном запросе. Весь ответ модели — на русском.
    Возвращает dict: summary, design_score, usability_score, content_quality, unique_selling_points,
    price_category, target_audience, strengths, weaknesses, recommendations.
    """
    text_for_prompt = (extracted_text or "").strip() or "(Текст страницы не извлечён)"
    if len(text_for_prompt) > 12000:
        text_for_prompt = text_for_prompt[:12000] + "\n… (обрезано)"
    logger.info("openai analyze_url_unified: model=%s base64_len=%d text_len=%d", model, len(base64_image), len(text_for_prompt))
    prompt_text = URL_UNIFIED_TEMPLATE.format(extracted_text=text_for_prompt)
    response = client.chat.completions.create(
        model=model,
        messages=[
            {"role": "system", "content": SYSTEM_URL_UNIFIED},
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": prompt_text},
                    {"type": "image_url", "image_url": {"url": f"data:{mime_type};base64,{base64_image}"}},
                ],
            },
        ],
        max_tokens=1024,
        temperature=0.3,
    )
    raw = response.choices[0].message.content or ""
    data = _extract_json_from_content(raw)
    if data and isinstance(data, dict):
        return {
            "summary": (data.get("summary") or "").strip() or "",
            "design_score": _norm_score(data.get("design_score")),
            "usability_score": _norm_score(data.get("usability_score")),
            "content_quality": _norm_score(data.get("content_quality")),
            "unique_selling_points": data.get("unique_selling_points") or [],
            "franchise_info": data.get("franchise_info") or [],
            "price_category": (data.get("price_category") or "").strip() or "",
            "target_audience": (data.get("target_audience") or "").strip() or "",
            "strengths": data.get("strengths") or [],
            "weaknesses": data.get("weaknesses") or [],
            "recommendations": data.get("recommendations") or [],
        }
    return {"summary": raw[:500] if raw else "Не удалось разобрать ответ модели.", "strengths": [], "weaknesses": [], "recommendations": []}
