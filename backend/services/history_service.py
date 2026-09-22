"""File-based history storage (last N entries).

Writes are atomic (write to a temp file in the same directory, then os.replace)
and guarded by an in-process lock — this app runs as a single process (one
uvicorn worker, web or desktop), so a threading.Lock is enough to serialize
concurrent requests; it is not a substitute for a cross-process file lock.
A history file that fails to parse as JSON is quarantined (renamed aside)
rather than silently overwritten, so the corrupt content is preserved for
inspection.
"""
import json
import logging
import threading
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path

from backend.models.schemas import HistoryItem, HistoryResponse

logger = logging.getLogger("backend.services.history")

_lock = threading.RLock()


def _quarantine_corrupt_file(path: Path) -> None:
    """Rename an unreadable history file aside instead of losing/overwriting it."""
    try:
        quarantine_path = path.with_name(f"{path.stem}.corrupt-{int(time.time())}{path.suffix}")
        path.replace(quarantine_path)
        logger.warning("history: quarantined corrupt file %s -> %s", path.name, quarantine_path.name)
    except OSError as e:
        logger.warning("history: failed to quarantine corrupt file %s: %s", path, e)


def _read_entries(path: Path) -> list[dict]:
    if not path.exists():
        return []
    try:
        raw = path.read_text(encoding="utf-8")
    except OSError as e:
        logger.warning("history: failed to read %s: %s", path, e)
        return []
    if not raw.strip():
        return []
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as e:
        logger.warning("history: corrupt JSON in %s: %s", path, e)
        _quarantine_corrupt_file(path)
        return []
    if not isinstance(data, list):
        logger.warning("history: unexpected content shape in %s (not a list), quarantining", path)
        _quarantine_corrupt_file(path)
        return []
    return data


def _write_entries_atomic(path: Path, entries: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_name(f".{path.name}.tmp-{uuid.uuid4().hex}")
    try:
        tmp_path.write_text(json.dumps(entries, ensure_ascii=False, indent=2), encoding="utf-8")
        tmp_path.replace(path)  # atomic on Windows and POSIX within the same directory
    finally:
        if tmp_path.exists():
            try:
                tmp_path.unlink()
            except OSError:
                pass


def add_entry(
    history_path: Path,
    max_entries: int,
    request_type: str,
    request_summary: str,
    response_summary: str,
    response_full: dict | None = None,
) -> str:
    """Append one history entry and trim to max_entries. response_full — полный результат для просмотра. Returns entry id."""
    with _lock:
        entries = _read_entries(history_path)
        entry_id = str(uuid.uuid4())
        ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S")
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
        _write_entries_atomic(history_path, entries)
        logger.info("history add_entry: id=%s type=%s total_entries=%d", entry_id, request_type, len(entries))
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
    with _lock:
        raw = _read_entries(history_path)[:max_entries]
    items = [HistoryItem(**_normalize_entry(e)) for e in raw]
    logger.debug("history get_history: path=%s returned=%d", history_path, len(items))
    return HistoryResponse(items=items, total=len(items))


def clear_history(history_path: Path) -> None:
    """Clear all history entries."""
    with _lock:
        _write_entries_atomic(history_path, [])
    logger.info("history clear_history: path=%s", history_path)
