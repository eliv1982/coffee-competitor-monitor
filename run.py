"""
Скрипт запуска приложения «Мониторинг конкурентов».
"""
import socket
import sys
import uvicorn

from backend.config import get_settings
from backend.logging_config import setup_logging


def port_in_use(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        return s.connect_ex(("127.0.0.1", port)) == 0


def find_free_port(start: int, max_tries: int = 20) -> int:
    """Найти свободный порт начиная с start."""
    for i in range(max_tries):
        port = start + i
        if not port_in_use(port):
            return port
    return start  # fallback, uvicorn покажет ошибку


if __name__ == "__main__":
    settings = get_settings()
    port = settings.api_port
    if port_in_use(port):
        port = find_free_port(port)
        print(f"Порт {settings.api_port} занят, используем порт {port}.", flush=True)
    setup_logging(level=settings.log_level, log_file=settings.log_file)
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(line_buffering=True)
    print("Запуск сервера Мониторинг конкурентов...", flush=True)
    print(f"Откройте в браузере: http://127.0.0.1:{port}/static/index.html", flush=True)
    print(f"Документация API: http://127.0.0.1:{port}/docs", flush=True)
    print("-" * 50, flush=True)
    uvicorn.run(
        "backend.main:app",
        host=settings.api_host,
        port=port,
        reload=True,
        log_level="info",
    )
