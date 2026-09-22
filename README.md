# Мониторинг конкурентов (Coffee Compass)

Локальный веб- и Windows-desktop инструмент для анализа конкурентов кофеен/кафе: текст, PDF,
изображения и сайты по URL обрабатываются через OpenAI API (мультимодальный анализ). Результаты —
структурированная аналитика на русском языке.

> **Область применения:** локальный инструмент для одного/нескольких доверенных пользователей.
> Аутентификации нет; интерфейс и ответы модели — на русском языке. Не предназначен для
> развёртывания в публичном интернете или для недоверенных пользователей. Подробности — [docs.md](docs.md).

## Возможности

- **Анализ текста и PDF** — вставка текста или загрузка PDF → резюме, сильные/слабые стороны, уникальные торговые предложения, рекомендации.
- **Анализ изображений** — загрузка скриншота сайта, баннера, упаковки → описание, маркетинговые инсайты, оценка дизайна.
- **Анализ по URL** — ввод ссылки на сайт → Selenium (Chrome) загружает страницу, делается скриншот и извлекается текст → единый анализ (дизайн, УТП, франшиза при наличии).
- **История запросов** — последние запросы сохраняются, по клику открывается полный ответ.

## Стек

- **Backend:** Python 3.11+, FastAPI, OpenAI API (структурированный вывод через Pydantic), httpx, BeautifulSoup4, Selenium (для URL).
- **Frontend:** HTML, CSS, JavaScript (без фреймворков), раздаётся тем же процессом FastAPI (`/static`).
- **Desktop:** PyQt6 + встроенный uvicorn-сервер в фоновом потоке, упаковка — PyInstaller (см. «Сборка exe»).

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

   В `.env` укажите **OPENAI_API_KEY** (получить ключ: [platform.openai.com](https://platform.openai.com/api-keys)). Опционально: `OPENAI_MODEL` (по умолчанию `gpt-4o-mini`). Для анализа по URL нужен установленный **Chrome** (Selenium Manager сам подбирает драйвер — отдельно ставить chromedriver не нужно).

   Содержимое запросов (введённый текст, PDF, изображения, скриншоты сайтов) отправляется в
   официальный OpenAI API для анализа (сторонние OpenAI-совместимые провайдеры сознательно не
   поддерживаются — см. [docs.md](docs.md)); история последних запросов хранится локально
   в незашифрованном JSON-файле (`history.json` при запуске из исходников, подробнее — [docs.md](docs.md)).

4. Запустите сервер (по умолчанию слушает только `127.0.0.1`; см. `API_HOST` в `.env.example`,
   если осознанно нужен доступ из локальной сети — без аутентификации, только в доверенной сети):

   ```bash
   python run.py
   ```
   или
   ```bash
   python -m uvicorn backend.main:app --reload --host 127.0.0.1 --port 8000
   ```

5. Откройте в браузере:

   - Веб-интерфейс: [http://localhost:8000/static/index.html](http://localhost:8000/static/index.html)
   - Swagger API: [http://localhost:8000/docs](http://localhost:8000/docs)
   - Проверка здоровья: [http://localhost:8000/health](http://localhost:8000/health)

## Структура проекта

```
├── backend/
│   ├── main.py              # FastAPI, роутеры, static, обработчики ошибок, CORS
│   ├── config.py            # Настройки (.env/переменные окружения), лимиты, пути данных
│   ├── errors.py            # Типизированные ошибки -> коды HTTP
│   ├── limits.py            # Лимиты и проверка сигнатур загружаемых файлов
│   ├── local_guard.py       # Host-заголовок и same-origin защита (локальный API без auth)
│   ├── models/schemas.py    # Pydantic-схемы запросов/ответов и структурированного вывода ИИ
│   ├── routers/
│   │   ├── analyze.py       # /analyze_text, /analyze_image
│   │   ├── analyze_url.py   # /analyze_url (Selenium + OpenAI)
│   │   ├── parse_demo.py    # /parse_demo, /parse_demo/batch
│   │   └── history.py       # /history
│   └── services/            # openai, parser, url_safety (SSRF-защита), history, pdf
├── static/                  # index.html, app.js, style.css (тот же origin, что и API)
├── tests/                   # Офлайн pytest-набор (без реальных OpenAI/сети/Selenium)
├── .github/workflows/ci.yml # CI: compile-check + pytest на push/PR
├── .env.example             # Шаблон настроек (скопировать в .env)
├── .gitignore
├── requirements.txt         # Полный набор (включая desktop-сборку)
├── requirements-test.txt    # Только backend + тесты (без PyQt6/PyInstaller, для CI)
├── run.py                   # Запуск веб-версии
├── desktop_main.py          # Точка входа для exe (всегда 127.0.0.1)
├── build.py                 # Сборка exe (PyInstaller)
├── competitionmonitor.spec  # .env/history.json НИКОГДА не упаковываются, даже вложенными (см. tests/test_packaging.py)
├── LICENSE                  # MIT
├── README.md
└── docs.md                  # Подробное описание API, лимитов и политики безопасности URL
```

## API (кратко)

| Метод | Путь | Описание |
|-------|------|----------|
| GET | `/health` | Проверка работоспособности. |
| POST | `/analyze_text` | Анализ текста (JSON `{"text": "..."}`, мин. 10 символов, или multipart с PDF). |
| POST | `/analyze_image` | Анализ изображения (multipart: `file`; JPEG/PNG/GIF/WebP). |
| POST | `/analyze_url` | Анализ сайта по URL (скриншот + текст, Selenium). |
| POST | `/parse_demo` | Парсинг URL (title, h1, абзац) и анализ. |
| POST | `/parse_demo/batch` | Парсинг и анализ всех URL из `COMPETITOR_URLS`. |
| GET | `/history` | Список последних записей. |
| DELETE | `/history` | Очистка истории. |

Ошибки возвращаются реальным HTTP-статусом (400/403/413/415/422/502/503/504/500) с телом
`{"error": "..."}`, а не 200 с ошибкой внутри (403 — недопустимый браузерный `Origin`, см.
docs.md §7). Подробнее, включая примеры запросов/ответов, лимиты и политику безопасности URL:
[docs.md](docs.md).

## Тесты

```bash
pip install -r requirements-test.txt
pytest tests/ -v
```

Набор полностью офлайн: DNS и HTTP-сеть замоканы, вызовы OpenAI и Selenium — тоже. Живых
запросов к OpenAI или сторонним сайтам тесты не делают.

## Сборка exe (desktop)

Автономная **папка-дистрибутив** (onedir; не единый exe-файл) со встроенным сервером и
интерфейсом (PyQt6 + PyInstaller):

```bash
python build.py
```

Готово: `%USERPROFILE%\cm_dist\build_<время>\competitionmonitor\competitionmonitor.exe` (рядом —
папка `_internal` с зависимостями). Каждая сборка — в новую папку. Если при сборке возникает
ошибка доступа — добавьте папку `%USERPROFILE%\cm_build` в исключения антивируса.

`.env` никогда не входит в сборку (см. `competitionmonitor.spec` и `tests/test_packaging.py`).
Настройте `OPENAI_API_KEY` переменной окружения ОС либо файлом
`%APPDATA%\CompetitionMonitor\.env` (подробнее — [docs.md](docs.md), раздел «Desktop-конфигурация»).
Требуется установленный Chrome — Selenium Manager сам подбирает драйвер при первом запуске.

## Лицензия

MIT — см. [LICENSE](LICENSE).
