# Документация API — Мониторинг конкурентов

## 1. Структура проекта

```
Coffee Compass/
├── backend/
│   ├── main.py              # FastAPI: роутеры, /health, static
│   ├── config.py            # Settings (OpenAI, api_host/port, parser, Selenium)
│   ├── models/schemas.py    # Запросы/ответы анализа, истории
│   ├── routers/
│   │   ├── analyze.py       # POST /analyze_text, POST /analyze_image
│   │   ├── analyze_url.py   # POST /analyze_url (Selenium + скриншот + текст)
│   │   ├── parse_demo.py    # POST /parse_demo, /parse_demo/batch
│   │   └── history.py       # GET /history, DELETE /history
│   └── services/            # openai_service, parser_service, history_service, pdf_service
├── static/                  # index.html, app.js, style.css
├── run.py                   # Запуск веб-версии
├── desktop_main.py         # Точка входа для exe
├── build.py, competitionmonitor.spec
├── requirements.txt, .env.example, .gitignore
├── README.md
└── docs.md
```

Файл `history.json` создаётся при первом обращении к истории; в репозиторий не входит (см. .gitignore).

## 2. Эндпоинты

| Метод | Путь | Описание |
|-------|------|----------|
| GET | `/` | Информация об API (message, docs, static). |
| GET | `/health` | Проверка работоспособности (status, service, version). |
| POST | `/analyze_text` | Анализ текста конкурента. |
| POST | `/analyze_image` | Анализ изображения конкурента. |
| POST | `/analyze_url` | Анализ сайта по URL: Selenium загружает страницу, скриншот + текст → единый анализ (дизайн, УТП, франшиза). |
| POST | `/parse_demo` | Парсинг и анализ сайта по URL (title, h1, абзац). |
| GET | `/history` | Получение истории запросов. |
| DELETE | `/history` | Очистка истории. |

## 3. Формат ответов API

Все ответы анализа — в обёртке `success` / `analysis` или `data` / `error`:

- **Успех:** `success: true`, `analysis` или `data` заполнены, `error: null`.
- **Ошибка:** `success: false`, `error: "сообщение"`, `analysis`/`data` могут быть `null`.

## 4. Примеры запросов

### 4.1. POST /analyze_text

**Запрос:** минимум 10 символов.

```bash
curl -X POST "http://localhost:8000/analyze_text" \
  -H "Content-Type: application/json" \
  -d '{"text": "Наша компания предлагает уникальные решения для бизнеса. Мы работаем на рынке 10 лет."}'
```

**Ответ (200):**

```json
{
  "success": true,
  "analysis": {
    "strengths": ["Долгий опыт работы на рынке (10 лет)", "..."],
    "weaknesses": ["Отсутствие конкретных цен", "..."],
    "unique_offers": ["Уникальные решения для бизнеса", "..."],
    "recommendations": ["Добавить конкретные цифры и кейсы", "..."],
    "summary": "Краткое резюме анализа."
  },
  "error": null
}
```

### 4.2. POST /analyze_image

**Запрос:** multipart, поле `file`. Разрешены: JPEG, PNG, GIF, WebP.

```bash
curl -X POST "http://localhost:8000/analyze_image" -F "file=@banner.jpg"
```

**Ответ (200):**

```json
{
  "success": true,
  "analysis": {
    "description": "Описание изображения",
    "marketing_insights": ["инсайт 1", "инсайт 2"],
    "visual_style_score": 7,
    "visual_style_analysis": "Текстовая оценка визуального стиля",
    "recommendations": ["Рекомендация 1", "..."]
  },
  "error": null
}
```

### 4.3. POST /parse_demo

**Запрос:**

```json
{ "url": "https://example.com" }
```

**Ответ (200):**

```json
{
  "success": true,
  "data": {
    "url": "https://example.com",
    "title": "Example Domain",
    "h1": "Example Domain",
    "first_paragraph": "Текст первого абзаца...",
    "analysis": {
      "strengths": [],
      "weaknesses": [],
      "unique_offers": [],
      "recommendations": [],
      "summary": "..."
    },
    "error": null
  },
  "error": null
}
```

При ошибке извлечения контента: `success: false`, `error: "Не удалось извлечь контент..."`.

### 4.4. POST /analyze_url

**Запрос:** JSON с полем `url`. Требуется установленный Chrome (Selenium).

```json
{ "url": "https://example.com" }
```

**Ответ (200):** единый анализ по скриншоту и тексту страницы (дизайн, уникальные предложения, условия франшизы при наличии).

```json
{
  "success": true,
  "analysis": {
    "design_assessment": "Оценка дизайна сайта...",
    "unique_offers": ["УТП 1", "..."],
    "franchise_conditions": "Условия франшизы или «не указано»",
    "recommendations": ["..."],
    "summary": "Краткое резюме."
  },
  "error": null
}
```

При ошибке (неверный URL, таймаут Selenium): `success: false`, `error: "сообщение"`.

### 4.5. GET /history

**Ответ (200):**

```json
{
  "items": [
    {
      "id": "uuid",
      "timestamp": "2025-03-07T12:00:00",
      "request_type": "text",
      "request_summary": "Начало введённого текста...",
      "response_summary": "Краткое резюме ответа"
    }
  ],
  "total": 1
}
```

Типы записей: `text`, `image`, `url`, `parse`.

### 4.6. DELETE /history

**Ответ (200):**

```json
{
  "success": true,
  "message": "История очищена"
}
```

### 4.7. GET /health

**Ответ (200):**

```json
{
  "status": "healthy",
  "service": "Competitor Monitor",
  "version": "1.0.0"
}
```

## 5. Мультимодальные функции

- **Текст:** `/analyze_text` — минимум 10 символов. Структурированный анализ (strengths, weaknesses, unique_offers, recommendations, summary). Поддерживается загрузка PDF.
- **Изображения:** `/analyze_image` — JPEG, PNG, GIF, WebP. Описание, маркетинговые инсайты, оценка визуального стиля (0–10), рекомендации.
- **Сайт по URL:** `/analyze_url` — Selenium (Chrome) открывает страницу, делается скриншот и извлекается текст; модель даёт единый анализ (дизайн, УТП, условия франшизы). Ответ на русском.
- **Парсинг URL:** `/parse_demo` — извлекаются title, h1, первый абзац (таймаут и User-Agent из конфига), затем анализ контента моделью.

Конфигурация: `.env` — `OPENAI_API_KEY`, `OPENAI_MODEL` (по умолчанию `gpt-4o-mini`), при необходимости `PARSER_TIMEOUT`, `PARSER_USER_AGENT`, `PARSER_USE_SELENIUM`, `API_HOST`, `API_PORT`.

## 6. Ошибки

- **503** — не задан `OPENAI_API_KEY` для эндпоинтов, использующих OpenAI.
- **400** — пустой или слишком короткий текст, пустой файл, неподдерживаемый тип изображения.
- В ответах с `success: false` текст ошибки в поле `error`. В HTTP-ошибках FastAPI возвращает `detail` в JSON.
