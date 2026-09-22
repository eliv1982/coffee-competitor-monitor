"""Shared pytest fixtures. Offline/deterministic only — no live OpenAI or real network access.

Sets COMPETITION_MONITOR_ENV_FILE to an empty temp file *before* backend.config is imported
anywhere, so tests never read the developer's real project-root .env (which may hold a real
OPENAI_API_KEY) — see backend/config.py:_resolve_env_file for the lookup order. Individual
tests still layer specific values with monkeypatch.setenv, which always outranks any .env file.
"""
import os
import tempfile
from pathlib import Path

_fd, _EMPTY_ENV_PATH = tempfile.mkstemp(suffix=".env", prefix="cm_test_")
os.close(_fd)
os.environ.setdefault("COMPETITION_MONITOR_ENV_FILE", _EMPTY_ENV_PATH)

import pytest
from fastapi.testclient import TestClient

REPO_ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture()
def app_env(tmp_path, monkeypatch):
    """Baseline hermetic settings for a test: fake API key, isolated history file, quiet logs."""
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test-000000000000000000000000000000")
    monkeypatch.setenv("HISTORY_FILE", str(tmp_path / "history.json"))
    monkeypatch.setenv("LOG_LEVEL", "WARNING")
    monkeypatch.setenv("COMPETITOR_URLS", "")
    monkeypatch.setenv("PARSER_USE_SELENIUM", "false")
    return tmp_path


@pytest.fixture()
def client(app_env):
    from backend.main import app

    # base_url matters here, not just style: backend.local_guard rejects requests whose Host
    # header isn't a recognized local host, and TestClient's own default base_url
    # ("http://testserver") would otherwise fail that check on every request.
    with TestClient(app, base_url="http://127.0.0.1") as c:
        yield c
