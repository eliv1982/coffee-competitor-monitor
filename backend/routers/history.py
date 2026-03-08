"""Endpoints: /history (GET, DELETE)."""
import logging
from fastapi import APIRouter

from backend.config import get_settings
from backend.models.schemas import HistoryResponse
from backend.services import history_service

logger = logging.getLogger("backend.routers.history")

router = APIRouter(prefix="", tags=["history"])


@router.get("/history", response_model=HistoryResponse)
def get_history_endpoint():
    """Получить историю последних запросов."""
    logger.debug("GET /history")
    settings = get_settings()
    result = history_service.get_history(
        settings.history_file, settings.max_history_entries
    )
    logger.info("GET /history: total=%d", result.total)
    return result


@router.delete("/history")
def clear_history_endpoint():
    """Очистить историю запросов."""
    logger.info("DELETE /history")
    settings = get_settings()
    history_service.clear_history(settings.history_file)
    logger.debug("DELETE /history: cleared")
    return {"success": True, "message": "История очищена"}
