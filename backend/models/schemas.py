"""Pydantic schemas for API requests and responses (aligned with Competitor Monitor API)."""
from typing import Any

from pydantic import BaseModel, Field


# === Requests ===

class TextAnalysisRequest(BaseModel):
    """Запрос на анализ текста."""

    text: str = Field(..., min_length=10, description="Текст для анализа (минимум 10 символов)")


class ParseDemoRequest(BaseModel):
    """Запрос на парсинг URL."""

    url: str = Field(..., min_length=1, description="URL для парсинга")


class AnalyzeUrlRequest(BaseModel):
    """Запрос на анализ сайта по URL (скриншот + текст через Selenium)."""

    url: str = Field(..., min_length=1, description="URL сайта для анализа")


# === Analysis models (inner payload) ===

class CompetitorAnalysis(BaseModel):
    """Структурированный анализ конкурента (ниша: кофейни)."""

    strengths: list[str] = Field(default_factory=list, description="Сильные стороны")
    weaknesses: list[str] = Field(default_factory=list, description="Слабые стороны")
    unique_offers: list[str] = Field(default_factory=list, description="Уникальные предложения")
    unique_selling_points: list[str] = Field(default_factory=list, description="Уникальные торговые предложения")
    recommendations: list[str] = Field(default_factory=list, description="Рекомендации")
    summary: str = Field("", description="Общее резюме")
    content_quality: int = Field(0, ge=0, le=10, description="Качество контента: описания кофе, меню (0-10)")
    price_category: str = Field("", description="Ценовая категория: низкие / средние / высокие цены")


class ImageAnalysis(BaseModel):
    """Анализ изображения (скриншот сайта/лендинга кофейни)."""

    description: str = Field("", description="Описание изображения")
    marketing_insights: list[str] = Field(default_factory=list, description="Маркетинговые инсайты")
    visual_style_score: int = Field(0, ge=0, le=10, description="Оценка визуального стиля (0-10)")
    visual_style_analysis: str = Field("", description="Анализ визуального стиля")
    recommendations: list[str] = Field(default_factory=list, description="Рекомендации")
    design_score: int = Field(0, ge=0, le=10, description="Оценка дизайна сайта/лендинга (0-10)")
    animation_potential: bool = Field(False, description="Есть ли анимация/интерактив на странице")
    menu_visibility: int = Field(0, ge=0, le=10, description="Насколько легко найти меню (0-10)")
    brand_style: str = Field("", description="Стиль бренда: минимализм, уютный, технологичный и т.д.")
    usability_score: int = Field(0, ge=0, le=10, description="Удобство использования (0-10)")
    content_quality: int = Field(0, ge=0, le=10, description="Качество контента на странице (0-10)")


class ParsedContent(BaseModel):
    """Результат парсинга страницы."""

    url: str = ""
    title: str | None = None
    h1: str | None = None
    first_paragraph: str | None = None
    analysis: CompetitorAnalysis | None = None
    error: str | None = None


# === Wrapped API responses ===

class TextAnalysisResponse(BaseModel):
    """Ответ на анализ текста."""

    success: bool = True
    analysis: CompetitorAnalysis | None = None
    error: str | None = None


class ImageAnalysisResponse(BaseModel):
    """Ответ на анализ изображения."""

    success: bool = True
    analysis: ImageAnalysis | None = None
    error: str | None = None


class ParseDemoResponse(BaseModel):
    """Ответ на парсинг и анализ по URL."""

    success: bool = True
    data: ParsedContent | None = None
    error: str | None = None


# === History ===

class HistoryItem(BaseModel):
    """Элемент истории (result — полный ответ для просмотра в интерфейсе)."""

    id: str
    timestamp: str  # ISO datetime
    request_type: str  # "text" | "image" | "parse" | "analyze_url"
    request_summary: str
    response_summary: str
    result: dict | None = None  # полный результат анализа для отображения при клике


class HistoryResponse(BaseModel):
    """Ответ со списком истории."""

    items: list[HistoryItem] = Field(default_factory=list)
    total: int = 0
