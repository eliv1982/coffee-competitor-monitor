"""FastAPI application: Competitor Monitoring API."""
import logging
import time
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from backend.config import get_cors_origins_list, get_settings
from backend.errors import AppError
from backend.local_guard import install_local_guard
from backend.logging_config import setup_logging
from backend.routers import analyze, analyze_url, history, parse_demo

logger = logging.getLogger("backend.main")

app = FastAPI(
    title="Competitor Monitoring API",
    description="Мультимодальный ассистент: анализ текста и изображений конкурентов",
    version="1.0.0",
)


@app.exception_handler(AppError)
async def app_error_handler(request: Request, exc: AppError):
    """Typed application errors -> their mapped status code. Body is always {"error": "<safe message>"}."""
    logger.warning(
        "AppError: status=%s path=%s detail=%s", exc.status_code, request.url.path, exc.log_message
    )
    return JSONResponse(status_code=exc.status_code, content={"error": exc.message})


@app.exception_handler(RequestValidationError)
async def validation_error_handler(request: Request, exc: RequestValidationError):
    """Keep FastAPI's normal 422 behavior, just log it consistently with everything else."""
    logger.info("RequestValidationError: path=%s errors=%s", request.url.path, exc.errors())
    return JSONResponse(status_code=422, content={"detail": exc.errors()})


@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    """Any unhandled exception -> 500 with a sanitized message. Full traceback goes to the server log only."""
    logger.exception("Unhandled exception on %s %s", request.method, request.url.path)
    return JSONResponse(
        status_code=500,
        content={"error": "Внутренняя ошибка сервера."},
    )


install_local_guard(app)

_cors_origins = get_cors_origins_list()
if _cors_origins:
    # Явный opt-in: фронтенд обслуживается с другого origin (например, отдельный dev-сервер).
    # По умолчанию CORS не включается — /static и API раздаются одним и тем же процессом (тот же origin).
    logger.warning("CORS enabled for explicit origins: %s", _cors_origins)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=_cors_origins,
        allow_methods=["GET", "POST", "DELETE"],
        allow_headers=["Content-Type"],
    )


@app.on_event("startup")
def on_startup():
    """Инициализация логирования при старте приложения."""
    settings = get_settings()
    setup_logging(level=settings.log_level, log_file=settings.log_file)
    logger.info(
        "Приложение запущено: host=%s port=%s log_level=%s log_file=%s",
        settings.api_host,
        settings.api_port,
        settings.log_level,
        settings.log_file,
    )
    if settings.api_host not in ("127.0.0.1", "localhost", "::1"):
        logger.warning(
            "API_HOST=%s: сервер слушает не только localhost. Это осознанный opt-in "
            "(аутентификации нет) — используйте только в доверенной сети.",
            settings.api_host,
        )


@app.middleware("http")
async def log_requests(request: Request, call_next):
    """Логирование каждого HTTP-запроса и ответа."""
    start = time.perf_counter()
    method = request.method
    path = request.url.path
    client = request.client.host if request.client else "unknown"
    logger.debug("Request: %s %s client=%s", method, path, client)
    response = await call_next(request)
    duration_ms = (time.perf_counter() - start) * 1000
    logger.info(
        "Response: %s %s -> %s duration_ms=%.2f client=%s",
        method,
        path,
        response.status_code,
        duration_ms,
        client,
    )
    return response


app.include_router(analyze.router)
app.include_router(analyze_url.router)
app.include_router(parse_demo.router)
app.include_router(history.router)

# Serve static frontend (index.html, assets)
static_dir = Path(__file__).resolve().parent.parent / "static"
if static_dir.exists():
    app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")
    logger.debug("Static files mounted: %s", static_dir)


@app.get("/")
async def root():
    """API info and links."""
    logger.debug("GET /")
    return {
        "message": "Competitor Monitoring API",
        "docs": "/docs",
        "static": "/static/index.html",
    }


@app.get("/health")
async def health_check():
    """Проверка работоспособности сервиса."""
    return {"status": "healthy", "service": "Competitor Monitor", "version": "1.0.0"}


@app.get("/api/ping")
async def ping():
    """Проверка: запрос доходит до этого приложения. Всегда 200 + JSON."""
    return {"ok": True, "message": "Сервер Coffee Compass отвечает."}
