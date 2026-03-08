"""Simple file-based history storage (last N entries)."""
import json
import logging
import uuid
from datetime import datetime
from pathlib import Path

from backend.models.schemas import HistoryItem, HistoryResponse

logger = logging.getLogger("backend.services.history")


def _ensure_history_file(path: Path) -> list[dict]:
    if path.exists():
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            entries = data if isinstance(data, list) else []
            logger.debug("history _ensure_history_file: path=%s entries=%d", path, len(entries))
            return entries
        except (json.JSONDecodeError, OSError) as e:
            logger.warning("history _ensure_history_file failed: path=%s error=%s", path, e)
            return []
    logger.debug("history _ensure_history_file: file not found path=%s", path)
    return []


def add_entry(
    history_path: Path,
    max_entries: int,
    request_type: str,
    request_summary: str,
    response_summary: str,
    response_full: dict | None = None,
) -> str:
    """Append one history entry and trim to max_entries. response_full — полный результат для просмотра. Returns entry id."""
    entries = _ensure_history_file(history_path)
    entry_id = str(uuid.uuid4())
    ts = datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%S")
    entry = {
        "id": entry_id,
        "timestamp": ts,
        "request_type": request_type,
        "request_summary": (request_summary or "")[:500],
        "response_summary": (response_summary or "")[:300],
    }
    if response_full is not None:
        entry["result"] = response_full
    entries.insert(0, entry)
    entries = entries[:max_entries]
    history_path.write_text(json.dumps(entries, ensure_ascii=False, indent=2), encoding="utf-8")
    logger.info("history add_entry: id=%s type=%s total_entries=%d", entry_id, request_type, len(entries))
    logger.debug("history add_entry request_summary=%s", (request_summary or "")[:100])
    return entry_id


def _normalize_entry(e: dict) -> dict:
    """Привести запись к формату HistoryItem (поддержка старых полей и result)."""
    out = {
        "id": e.get("id") or "",
        "timestamp": e.get("timestamp") or e.get("created_at") or "",
        "request_type": e.get("request_type") or e.get("type") or "",
        "request_summary": e.get("request_summary") or e.get("input_summary") or "",
        "response_summary": e.get("response_summary") or e.get("response_preview") or "",
    }
    if "result" in e and e["result"] is not None:
        out["result"] = e["result"]
    return out


def get_history(history_path: Path, max_entries: int = 10) -> HistoryResponse:
    """Return last max_entries history entries."""
    raw = _ensure_history_file(history_path)[:max_entries]
    items = [HistoryItem(**_normalize_entry(e)) for e in raw]
    logger.debug("history get_history: path=%s returned=%d", history_path, len(items))
    return HistoryResponse(items=items, total=len(items))


def clear_history(history_path: Path) -> None:
    """Clear all history entries."""
    history_path.write_text("[]", encoding="utf-8")
    logger.info("history clear_history: path=%s", history_path)
