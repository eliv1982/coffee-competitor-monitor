# Мониторинг конкурентов (Coffee Compass)

Мультимодальное приложение для анализа конкурентов (кофейни/кафе): текст, изображения и сайты по URL обрабатываются через OpenAI API. Результаты — структурированная аналитика на русском языке.

## Возможности

- **Анализ текста и PDF** — вставка текста или загрузка PDF → резюме, сильные/слабые стороны, уникальные торговые предложения, рекомендации.
- **Анализ изображений** — загрузка скриншота сайта, баннера, упаковки → описание, маркетинговые инсайты, оценка дизайна.
- **Анализ по URL** — ввод ссылки на сайт → Selenium (Chrome) загружает страницу, делается скриншот и извлекается текст → единый анализ (дизайн, УТП, франшиза при наличии).
- **История запросов** — последние запросы сохраняются, по клику открывается полный ответ.

## Стек

- **Backend:** Python 3.11+, FastAPI, OpenAI API, httpx, BeautifulSoup4, Selenium (для URL).
- **Frontend:** HTML, CSS, JavaScript (без фреймворков).

## Запуск

1. Клонируйте репозиторий и перейдите в каталог проекта.

2. Создайте виртуальное окружение и установите зависимости:

   ```bash
   python -m venv .venv
   .venv\Scripts\activate   # Windows
   # source .venv/bin/activate   # Linux/macOS
   pip install -r requirements.txt
   ```

3. Настройте окружение:

   ```bash
   copy .env.example .env   # Windows
   # cp .env.example .env   # Linux/macOS
   ```

   В `.env` укажите **OPENAI_API_KEY** (получить ключ: [platform.openai.com](https://platform.openai.com/api-keys)). Опционально: `OPENAI_MODEL` (по умолчанию `gpt-4o-mini`). Для анализа по URL нужен установленный **Chrome** (Selenium).

4. Запустите сервер:

   ```bash
   python run.py
   ```
   или
   ```bash
   python -m uvicorn backend.main:app --reload --host 0.0.0.0 --port 8000
   ```

5. Откройте в браузере:

   - Веб-интерфейс: [http://localhost:8000/static/index.html](http://localhost:8000/static/index.html)
   - Swagger API: [http://localhost:8000/docs](http://localhost:8000/docs)
   - Проверка здоровья: [http://localhost:8000/health](http://localhost:8000/health)

## Структура проекта

```
├── backend/
│   ├── main.py              # FastAPI, роутеры, static
│   ├── config.py            # Настройки из .env
│   ├── models/schemas.py    # Pydantic-схемы
│   ├── routers/
│   │   ├── analyze.py       # /analyze_text, /analyze_image
│   │   ├── analyze_url.py   # /analyze_url (Selenium + OpenAI)
│   │   ├── parse_demo.py    # /parse_demo, /parse_demo/batch
│   │   └── history.py       # /history
│   └── services/            # openai, parser, history, pdf
├── static/                  # index.html, app.js, style.css
├── .env.example             # Шаблон настроек (скопировать в .env)
├── .gitignore
├── requirements.txt
├── run.py                   # Запуск веб-версии
├── desktop_main.py          # Точка входа для exe
├── build.py                 # Сборка exe (PyInstaller)
├── competitionmonitor.spec
├── README.md
└── docs.md                  # Подробное описание API
```

## API (кратко)

| Метод | Путь | Описание |
|-------|------|----------|
| GET | `/health` | Проверка работоспособности. |
| POST | `/analyze_text` | Анализ текста (JSON: `{"text": "..."}`, мин. 10 символов). |
| POST | `/analyze_image` | Анализ изображения (multipart: `file`). |
| POST | `/analyze_url` | Анализ сайта по URL (скриншот + текст, Selenium). |
| POST | `/parse_demo` | Парсинг URL (title, h1, абзац) и анализ. |
| GET | `/history` | Список последних записей. |
| DELETE | `/history` | Очистка истории. |

Подробнее: [docs.md](docs.md).

## Сборка exe (desktop)

Автономный exe с встроенным сервером и интерфейсом (PyQt6 + PyInstaller):

```bash
python build.py
```

Готовый exe: `%USERPROFILE%\cm_dist\build_<время>\competitionmonitor\competitionmonitor.exe`. Каждая сборка — в новую папку. Если при сборке возникает ошибка доступа — добавьте папку `%USERPROFILE%\cm_build` в исключения антивируса.

## Лицензия

MIT.
