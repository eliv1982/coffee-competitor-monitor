"""Централизованная настройка логирования.

Уровень по умолчанию — INFO (см. backend.config.Settings.log_level); DEBUG
можно включить через LOG_LEVEL для локальной отладки. По умолчанию в лог не
пишутся тексты пользовательского ввода/ответов ИИ (только длины) и полные
URL с query-строкой (см. backend.services.url_safety.redact_url) — только
хост и путь. Доступ uvicorn (access log) отключается отдельно при запуске
(run.py / desktop_main.py, access_log=False): его формат по умолчанию
включает query-строку запроса, а собственный middleware в backend.main уже
логирует каждый запрос безопасным образом.
"""
import logging
import sys
from pathlib import Path


class ShortNameFormatter(logging.Formatter):
    """Форматтер, показывающий короткое имя логгера (последняя часть после точки)."""

    def format(self, record):
        name = record.name
        if name.startswith("backend."):
            record.short_name = name.split(".")[-1]  # routers.analyze -> analyze
        elif name in ("uvicorn.error", "uvicorn.access"):
            record.short_name = "uvicorn"
        else:
            record.short_name = name
        return super().format(record)


def setup_logging(
    level: str = "INFO",
    log_file: str | Path | None = None,
) -> None:
    """
    Настраивает корневой логгер и логгеры uvicorn/fastapi.
    level: DEBUG, INFO, WARNING, ERROR, CRITICAL
    log_file: путь к файлу логов (если None — только консоль).
    """
    log_level = getattr(logging, level.upper(), logging.INFO)

    formatter = ShortNameFormatter(
        fmt="%(asctime)s | %(levelname)-8s | %(short_name)s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    root = logging.getLogger()
    root.setLevel(log_level)
    # Убираем дублирование: если у root уже есть handlers, сбрасываем
    for h in root.handlers[:]:
        root.removeHandler(h)

    console = logging.StreamHandler(sys.stdout)
    console.setLevel(log_level)
    console.setFormatter(formatter)
    console.terminator = "\n"
    root.addHandler(console)

    file_handler = None
    if log_file:
        path = Path(log_file)
        path.parent.mkdir(parents=True, exist_ok=True)
        file_handler = logging.FileHandler(path, encoding="utf-8")
        file_handler.setLevel(log_level)
        file_handler.setFormatter(formatter)
        root.addHandler(file_handler)

    # Детальное логирование uvicorn и FastAPI
    for name in ("uvicorn", "uvicorn.error", "uvicorn.access", "fastapi"):
        logger = logging.getLogger(name)
        logger.setLevel(log_level)
        if not logger.handlers:
            logger.addHandler(console)
            if file_handler:
                logger.addHandler(file_handler)

    # Логгер приложения — вывод в консоль и при необходимости в файл
    backend_logger = logging.getLogger("backend")
    backend_logger.setLevel(log_level)
    backend_logger.propagate = True
    # Убеждаемся, что у root есть обработчик (уже добавлен выше)
    # Дополнительно вешаем консоль на backend, если вывод не идёт (на случай особых настроек окружения)
    if not backend_logger.handlers:
        backend_logger.addHandler(console)
        if file_handler:
            backend_logger.addHandler(file_handler)
        backend_logger.propagate = False
