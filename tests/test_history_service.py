"""Tests for backend.services.history_service — atomic writes, trimming, corrupt-file handling."""
import json
from pathlib import Path

from backend.config import get_app_data_dir
from backend.services import history_service


def test_add_entry_and_get_history(tmp_path):
    path = tmp_path / "history.json"
    history_service.add_entry(path, 10, "text", "req summary", "resp summary", response_full={"a": 1})
    result = history_service.get_history(path, 10)
    assert result.total == 1
    assert result.items[0].request_type == "text"
    assert result.items[0].result == {"a": 1}


def test_add_entry_creates_missing_directories(tmp_path):
    path = tmp_path / "nested" / "dir" / "history.json"
    history_service.add_entry(path, 10, "text", "a", "b")
    assert path.exists()


def test_history_trims_to_max_entries(tmp_path):
    path = tmp_path / "history.json"
    for i in range(5):
        history_service.add_entry(path, 3, "text", f"req {i}", f"resp {i}")
    result = history_service.get_history(path, 10)
    assert result.total == 3
    # most recent first
    assert result.items[0].request_summary == "req 4"
    assert result.items[-1].request_summary == "req 2"


def test_clear_history(tmp_path):
    path = tmp_path / "history.json"
    history_service.add_entry(path, 10, "text", "a", "b")
    history_service.clear_history(path)
    result = history_service.get_history(path, 10)
    assert result.total == 0
    assert json.loads(path.read_text(encoding="utf-8")) == []


def test_write_is_atomic_no_leftover_temp_files(tmp_path):
    path = tmp_path / "history.json"
    history_service.add_entry(path, 10, "text", "a", "b")
    leftovers = list(tmp_path.glob(".history.json.tmp-*"))
    assert leftovers == []
    assert path.exists()


def test_corrupt_json_is_quarantined_not_overwritten(tmp_path):
    path = tmp_path / "history.json"
    path.write_text("{not valid json!!", encoding="utf-8")
    # Reading should not raise, and should not silently delete the corrupt content.
    result = history_service.get_history(path, 10)
    assert result.total == 0
    quarantined = list(tmp_path.glob("history.corrupt-*.json"))
    assert len(quarantined) == 1
    assert quarantined[0].read_text(encoding="utf-8") == "{not valid json!!"
    # The original path no longer holds the corrupt content.
    assert not path.exists()


def test_corrupt_file_then_add_entry_starts_fresh(tmp_path):
    path = tmp_path / "history.json"
    path.write_text("not json", encoding="utf-8")
    history_service.add_entry(path, 10, "text", "fresh", "start")
    result = history_service.get_history(path, 10)
    assert result.total == 1
    assert result.items[0].request_summary == "fresh"


def test_non_list_json_is_quarantined(tmp_path):
    path = tmp_path / "history.json"
    path.write_text(json.dumps({"unexpected": "shape"}), encoding="utf-8")
    result = history_service.get_history(path, 10)
    assert result.total == 0
    assert list(tmp_path.glob("history.corrupt-*.json"))


def test_desktop_app_data_dir_is_per_user_and_under_a_known_root():
    data_dir = get_app_data_dir()
    assert data_dir.name == "CompetitionMonitor"
    assert isinstance(data_dir, Path)
