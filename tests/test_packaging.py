"""Regression test: competitionmonitor.spec must never package .env into the PyInstaller
distribution (see P0 #1 of the corrective-pass brief — a bundled .env would ship secrets
inside the exe). This execs the REAL, unmodified .spec file with PyInstaller's build classes
(Analysis/PYZ/EXE/COLLECT) and its collect_all() hook stubbed out — no PyInstaller or PyQt6
installation is required to run this test; only the file's own datas-construction logic runs.
"""
import os
import sys
import types
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
SPEC_PATH = REPO_ROOT / "competitionmonitor.spec"


class _StubBuildArtifact:
    """Stand-in for PyInstaller's Analysis/PYZ/EXE/COLLECT classes: just records its args."""

    def __init__(self, *args, **kwargs):
        self.args = args
        self.kwargs = kwargs
        self.pure = []
        self.scripts = []
        self.binaries = kwargs.get("binaries", [])
        self.datas = kwargs.get("datas", [])


def _exec_spec(monkeypatch, source: str | None = None) -> dict:
    """Execute the spec file's source (or a supplied override) in a namespace that mimics
    what PyInstaller injects, and return that namespace so the test can inspect `datas`."""
    fake_hooks = types.ModuleType("PyInstaller.utils.hooks")
    fake_hooks.collect_all = lambda name: ([], [], [])  # (datas, binaries, hiddenimports)
    fake_utils = types.ModuleType("PyInstaller.utils")
    fake_pyinstaller = types.ModuleType("PyInstaller")
    monkeypatch.setitem(sys.modules, "PyInstaller", fake_pyinstaller)
    monkeypatch.setitem(sys.modules, "PyInstaller.utils", fake_utils)
    monkeypatch.setitem(sys.modules, "PyInstaller.utils.hooks", fake_hooks)

    namespace = {
        "__name__": "__competitionmonitor_spec_under_test__",
        "__file__": str(SPEC_PATH),
        "SPECPATH": str(SPEC_PATH.parent),
        "Analysis": _StubBuildArtifact,
        "PYZ": _StubBuildArtifact,
        "EXE": _StubBuildArtifact,
        "COLLECT": _StubBuildArtifact,
    }
    code = source if source is not None else SPEC_PATH.read_text(encoding="utf-8")
    exec(compile(code, str(SPEC_PATH), "exec"), namespace)
    return namespace


def test_spec_file_exists():
    assert SPEC_PATH.is_file()


def test_real_spec_never_includes_env_in_datas(monkeypatch):
    namespace = _exec_spec(monkeypatch)
    datas = namespace["datas"]
    assert datas, "expected at least the backend/static datas entries"
    for src, _dst in datas:
        src_name = Path(str(src)).name
        assert src_name != ".env", f".env found in PyInstaller datas: {src!r}"
        assert not str(src).replace("\\", "/").endswith("/.env")


def test_real_spec_datas_only_contains_expected_entries(monkeypatch):
    """With collect_all() stubbed to return nothing, the explicit datas list should be exactly
    backend/ and static/ — proving nothing else (like .env) is added by the file's own code."""
    namespace = _exec_spec(monkeypatch)
    dsts = sorted(dst for _src, dst in namespace["datas"])
    assert dsts == ["backend", "static"]


def test_guard_clause_rejects_env_if_reintroduced(monkeypatch):
    """Extract the real guard clause (the loop that raises if .env sneaks into datas) from the
    actual spec file and run it against a synthetic datas list that includes .env — proving the
    guard is an effective regression fence, not just a comment, if someone reintroduces the bug."""
    source = SPEC_PATH.read_text(encoding="utf-8")
    marker_start = "# Regression guard:"
    marker_end = "a = Analysis("
    assert marker_start in source, "guard clause marker missing from competitionmonitor.spec"
    assert marker_end in source
    guard_snippet = marker_start + source.split(marker_start, 1)[1].split(marker_end, 1)[0]

    namespace = {"os": os, "datas": [("C:/proj/backend", "backend"), ("C:/proj/.env", ".")]}
    with pytest.raises(RuntimeError):
        exec(compile(guard_snippet, "<guard-clause-under-test>", "exec"), namespace)


def test_guard_clause_allows_clean_datas(monkeypatch):
    source = SPEC_PATH.read_text(encoding="utf-8")
    marker_start = "# Regression guard:"
    marker_end = "a = Analysis("
    guard_snippet = marker_start + source.split(marker_start, 1)[1].split(marker_end, 1)[0]

    namespace = {"os": os, "datas": [("C:/proj/backend", "backend"), ("C:/proj/static", "static")]}
    exec(compile(guard_snippet, "<guard-clause-under-test>", "exec"), namespace)  # must not raise


def _extract_guard_snippet() -> str:
    source = SPEC_PATH.read_text(encoding="utf-8")
    marker_start = "# Regression guard:"
    marker_end = "a = Analysis("
    return marker_start + source.split(marker_start, 1)[1].split(marker_end, 1)[0]


def test_guard_clause_detects_env_nested_several_directories_deep(tmp_path):
    """The real datas entries (backend/, static/) are DIRECTORIES, which PyInstaller copies
    recursively — a guard that only checked each datas tuple's own top-level name (the
    original version) would miss a secret file nested inside one. This builds a realistic
    nested tree on disk (not a stubbed collect_all()) and proves the walk actually catches it."""
    project = tmp_path / "backend"
    nested = project / "services" / "local_config_backup"
    nested.mkdir(parents=True)
    (project / "main.py").write_text("# not a secret", encoding="utf-8")
    (project / "services" / "parser_service.py").write_text("# not a secret", encoding="utf-8")
    (nested / ".env").write_text("OPENAI_API_KEY=sk-should-not-ship", encoding="utf-8")

    namespace = {"os": os, "datas": [(str(project), "backend")]}
    with pytest.raises(RuntimeError):
        exec(compile(_extract_guard_snippet(), "<guard-clause-under-test>", "exec"), namespace)


def test_guard_clause_detects_history_json_nested_in_a_directory(tmp_path):
    project = tmp_path / "static"
    nested = project / "assets" / "backup"
    nested.mkdir(parents=True)
    (project / "index.html").write_text("<html></html>", encoding="utf-8")
    (nested / "history.json").write_text("[]", encoding="utf-8")

    namespace = {"os": os, "datas": [(str(project), "static")]}
    with pytest.raises(RuntimeError):
        exec(compile(_extract_guard_snippet(), "<guard-clause-under-test>", "exec"), namespace)


def test_guard_clause_detects_quarantined_corrupt_history_file_nested(tmp_path):
    """history_service quarantines a corrupt history file as history.corrupt-<timestamp>.json
    (see backend/services/history_service.py) — the guard's pattern match must also catch that
    variant, not just the exact name "history.json"."""
    project = tmp_path / "backend"
    nested = project / "data"
    nested.mkdir(parents=True)
    (nested / "history.corrupt-1700000000.json").write_text("{not valid json", encoding="utf-8")

    namespace = {"os": os, "datas": [(str(project), "backend")]}
    with pytest.raises(RuntimeError):
        exec(compile(_extract_guard_snippet(), "<guard-clause-under-test>", "exec"), namespace)


def test_guard_clause_allows_realistic_clean_nested_tree(tmp_path):
    """A normal, secret-free nested source tree (mirroring the real backend/ layout) must not
    trip the guard — proves the recursive walk doesn't over-trigger on ordinary files."""
    project = tmp_path / "backend"
    nested = project / "services"
    nested.mkdir(parents=True)
    (project / "main.py").write_text("# ok", encoding="utf-8")
    (project / "config.py").write_text("# ok", encoding="utf-8")
    (nested / "parser_service.py").write_text("# ok", encoding="utf-8")
    (nested / "history_service.py").write_text("# ok", encoding="utf-8")

    namespace = {"os": os, "datas": [(str(project), "backend")]}
    exec(compile(_extract_guard_snippet(), "<guard-clause-under-test>", "exec"), namespace)  # must not raise


def test_real_spec_guard_walks_real_backend_and_static_directories(monkeypatch):
    """Executes the REAL, unmodified spec file end to end (not just the extracted snippet)
    against the actual project's backend/ and static/ directories on disk — the real
    regression scenario, proving the shipped project tree itself is currently clean."""
    _exec_spec(monkeypatch)  # must not raise


def test_env_is_gitignored_and_untracked():
    """Defense in depth outside PyInstaller entirely: .env must never be committed."""
    gitignore = (REPO_ROOT / ".gitignore").read_text(encoding="utf-8")
    assert ".env" in gitignore.splitlines()
