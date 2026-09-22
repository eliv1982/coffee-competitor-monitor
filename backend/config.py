"""Configuration for the Competitor Monitoring backend."""
import os
import sys
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

# Корень проекта (папка, в которой лежат backend/, static/)
_PROJECT_ROOT = Path(__file__).resolve().parent.parent


def get_app_data_dir() -> Path:
    """
    Per-user writable data directory (desktop mode): history.json, логи и
    пользовательский .env (см. _resolve_env_file). НЕ внутри каталога сборки
    PyInstaller — переживает переустановку/пересборку exe.
    Windows: %APPDATA%\\CompetitionMonitor
    Linux/macOS (для разработки): $XDG_DATA_HOME/CompetitionMonitor или ~/.local/share/CompetitionMonitor
    """
    if sys.platform == "win32":
        base = Path(os.environ.get("APPDATA") or (Path.home() / "AppData" / "Roaming"))
    else:
        base = Path(os.environ.get("XDG_DATA_HOME") or (Path.home() / ".local" / "share"))
    return base / "CompetitionMonitor"


def _is_frozen() -> bool:
    return bool(getattr(sys, "frozen", False))


def _resolve_env_file() -> str:
    """
    Источник конфигурации (обычные переменные окружения ОС в любом случае имеют
    приоритет — pydantic-settings читает их поверх .env-файла):

    1) COMPETITION_MONITOR_ENV_FILE — явный путь, если задан и существует.
    2) %APPDATA%\\CompetitionMonitor\\.env — пользовательский конфиг вне каталога
       сборки; актуально для desktop-версии (.env НИКОГДА не упаковывается в
       PyInstaller-дистрибутив — см. competitionmonitor.spec и docs.md).
    3) .env в корне проекта — для запуска из исходников (python run.py).
    """
    explicit = os.environ.get("COMPETITION_MONITOR_ENV_FILE")
    if explicit and Path(explicit).is_file():
        return explicit
    appdata_env = get_app_data_dir() / ".env"
    if appdata_env.is_file():
        return str(appdata_env)
    return str(_PROJECT_ROOT / ".env")


def _default_history_file() -> Path:
    if _is_frozen():
        return get_app_data_dir() / "history.json"
    return Path("history.json")


class Settings(BaseSettings):
    """Application settings loaded from environment / .env."""

    model_config = SettingsConfigDict(env_file=_resolve_env_file(), env_file_encoding="utf-8", extra="ignore")

    # --- OpenAI ---
    # Только официальный OpenAI API (api.openai.com) — сторонние OpenAI-совместимые
    # эндпоинты (Groq/OpenRouter/Ollama и т.п.) сознательно не поддерживаются в этом
    # проекте, см. docs.md.
    openai_api_key: str = ""
    openai_model: str = "gpt-4o-mini"
    openai_timeout: float = 60.0
    # Верхняя граница текста, отправляемого в OpenAI за один запрос (защита от неразумных расходов).
    max_ai_text_chars: int = 12000

    # --- История ---
    history_file: Path = Field(default_factory=_default_history_file)
    max_history_entries: int = 10

    # --- Сервер ---
    # По умолчанию — только localhost. Внешний/LAN-доступ (0.0.0.0 и т.п.) — осознанный
    # opt-in через явную переменную окружения API_HOST; аутентификации при этом нет,
    # поэтому такой режим не предназначен для сетей, где присутствуют недоверенные хосты.
    api_host: str = "127.0.0.1"
    api_port: int = 8000
    # CORS выключен по умолчанию: фронтенд раздаётся тем же FastAPI-процессом (тот же origin).
    # Список источников через запятую — только если фронтенд явно обслуживается с другого origin.
    cors_allow_origins: str = ""

    # --- Парсер (httpx/Selenium) ---
    parser_timeout: float = 30.0
    parser_connect_timeout: float = 10.0
    parser_user_agent: str = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
    # URL конкурентов для автоматического сбора (через запятую в .env)
    competitor_urls: str = ""
    # Использовать Selenium для парсинга (для JS-сайтов). Иначе — httpx.
    parser_use_selenium: bool = False
    max_redirects: int = 5
    # Верхняя граница размера тела ответа удалённого сайта, которое мы читаем.
    max_remote_response_bytes: int = 5 * 1024 * 1024

    # Chrome/Selenium запускается в песочнице по умолчанию. `--no-sandbox` — заведомо
    # небезопасный флаг, нужный только в отдельных ограниченных средах (например,
    # контейнер без непривилегированного пользователя); включайте осознанно.
    selenium_allow_no_sandbox: bool = False

    # --- Лимиты входных данных (локальный инструмент, но без них — DoS/расходы на модель) ---
    max_text_chars: int = 20_000
    max_pdf_bytes: int = 15 * 1024 * 1024
    max_image_bytes: int = 8 * 1024 * 1024
    max_pdf_pages: int = 50
    max_pdf_extracted_chars: int = 50_000
    # Грубая верхняя граница тела запроса к /analyze_text (проверяется по Content-Length
    # до чтения тела, когда заголовок присутствует).
    max_request_body_bytes: int = 20 * 1024 * 1024

    # --- Логирование ---
    log_level: str = "INFO"
    log_file: str | None = None  # например logs/app.log


def get_settings() -> Settings:
    """Return application settings."""
    return Settings()


def get_competitor_urls_list(settings: Settings | None = None) -> list[str]:
    """Список URL конкурентов из настроек (разделитель — запятая)."""
    s = settings or get_settings()
    if not (s.competitor_urls or "").strip():
        return []
    return [u.strip() for u in s.competitor_urls.split(",") if u.strip()]


def get_cors_origins_list(settings: Settings | None = None) -> list[str]:
    """Явный список разрешённых CORS-origin (пусто = CORS не включается)."""
    s = settings or get_settings()
    if not (s.cors_allow_origins or "").strip():
        return []
    return [o.strip() for o in s.cors_allow_origins.split(",") if o.strip()]
