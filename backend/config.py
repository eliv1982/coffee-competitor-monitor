"""Configuration for the Competitor Monitoring backend."""
from pathlib import Path

from pydantic_settings import BaseSettings

# Корень проекта (папка, в которой лежат backend/, static/, .env)
_PROJECT_ROOT = Path(__file__).resolve().parent.parent
_ENV_FILE = _PROJECT_ROOT / ".env"


class Settings(BaseSettings):
    """Application settings loaded from environment."""

    openai_api_key: str = ""
    openai_model: str = "gpt-4o-mini"
    # Опционально: другой провайдер (OpenAI-совместимый API). Примеры:
    # Groq: https://api.groq.com/openai/v1  (бесплатный tier, быстрый)
    # OpenRouter: https://openrouter.ai/api/v1 (много моделей)
    # Ollama (локально): http://localhost:11434/v1  (ключ можно оставить пустым или ollama)
    openai_base_url: str = ""
    history_file: Path = Path("history.json")
    max_history_entries: int = 10

    api_host: str = "0.0.0.0"
    api_port: int = 8000

    parser_timeout: float = 30.0
    parser_user_agent: str = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
    # URL конкурентов для автоматического сбора (через запятую в .env или список в коде)
    competitor_urls: str = ""
    # Использовать Selenium для парсинга (для JS-сайтов). Иначе — httpx.
    parser_use_selenium: bool = False

    log_level: str = "DEBUG"
    log_file: str | None = None  # например logs/app.log

    class Config:
        env_file = str(_ENV_FILE) if _ENV_FILE.exists() else ".env"
        env_file_encoding = "utf-8"


def get_settings() -> Settings:
    """Return application settings."""
    return Settings()


def get_competitor_urls_list(settings: Settings | None = None) -> list[str]:
    """Список URL конкурентов из настроек (разделитель — запятая)."""
    s = settings or get_settings()
    if not (s.competitor_urls or "").strip():
        return []
    return [u.strip() for u in s.competitor_urls.split(",") if u.strip()]
