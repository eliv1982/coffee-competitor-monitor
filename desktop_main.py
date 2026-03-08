"""
Точка входа desktop-приложения «Мониторинг конкурентов» (PyQt6 + встроенный сервер).
Запускает FastAPI в фоновом потоке и открывает окно с веб-интерфейсом.
"""
import os
import sys
import threading
import time
import traceback

# Для PyInstaller: добавляем путь к распакованному бандлу
if getattr(sys, "frozen", False):
    bundle_dir = sys._MEIPASS
    sys.path.insert(0, bundle_dir)
    os.chdir(bundle_dir)

# В exe без консоли sys.stdout/sys.stderr могут быть None — uvicorn падает на .isatty()
class _DummyStream:
    def write(self, *args, **kwargs): pass
    def flush(self, *args, **kwargs): pass
    def isatty(self): return False
if sys.stdout is None:
    sys.stdout = _DummyStream()
if sys.stderr is None:
    sys.stderr = _DummyStream()

import uvicorn
from PyQt6.QtCore import QUrl
from PyQt6.QtWebEngineWidgets import QWebEngineView
from PyQt6.QtWidgets import QApplication, QMainWindow, QMessageBox, QToolBar, QStatusBar
from PyQt6.QtGui import QAction

DESKTOP_PORT_START = 8765
# Ошибка запуска сервера (из потока)
_server_start_error: list[str] = []


def _port_in_use(port: int) -> bool:
    import socket
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        return s.connect_ex(("127.0.0.1", port)) == 0


def _find_free_port(start: int = DESKTOP_PORT_START, max_tries: int = 20) -> int:
    for i in range(max_tries):
        p = start + i
        if not _port_in_use(p):
            return p
    return start


def _wait_for_port(port: int, timeout_sec: float = 20.0, step: float = 0.2) -> bool:
    """Ждём, пока порт начнёт принимать соединения."""
    deadline = time.monotonic() + timeout_sec
    while time.monotonic() < deadline:
        if _port_in_use(port):
            return True
        time.sleep(step)
    return False


def run_server():
    """Запуск uvicorn в текущем процессе (для потока). Порт берётся из env (задаётся в main())."""
    global _server_start_error
    try:
        port = int(os.environ.get("COMPETITION_MONITOR_DESKTOP_PORT", str(DESKTOP_PORT_START)))
        uvicorn.run(
            "backend.main:app",
            host="127.0.0.1",
            port=port,
            log_level="warning",
        )
    except Exception as e:
        tb = traceback.format_exc()
        _server_start_error.append(tb)
        if getattr(sys, "frozen", False):
            try:
                err_path = os.path.join(os.environ.get("TEMP", "."), "competitionmonitor_error.txt")
                with open(err_path, "w", encoding="utf-8") as f:
                    f.write(tb)
            except Exception:
                pass


class MainWindow(QMainWindow):
    def __init__(self, base_url: str):
        super().__init__()
        self.base_url = base_url
        self.setWindowTitle("Мониторинг конкурентов — Coffee Compass")
        self.setMinimumSize(900, 700)
        self.resize(1100, 800)

        self.view = QWebEngineView()
        self.view.setUrl(QUrl(f"{base_url}/static/index.html"))
        self.setCentralWidget(self.view)

        toolbar = QToolBar()
        self.addToolBar(toolbar)
        reload_act = QAction("Обновить", self)
        reload_act.triggered.connect(lambda: self.view.reload())
        toolbar.addAction(reload_act)
        home_act = QAction("Главная", self)
        home_act.triggered.connect(lambda: self.view.setUrl(QUrl(f"{self.base_url}/static/index.html")))
        toolbar.addAction(home_act)

        self.statusBar().showMessage("Загрузка…")

        self.view.loadFinished.connect(self._on_load_finished)

    def _on_load_finished(self, ok: bool):
        if ok:
            self.statusBar().showMessage("Готово")
        else:
            self.statusBar().showMessage("Ошибка загрузки")

    def closeEvent(self, event):
        event.accept()


def main():
    global _server_start_error
    port = _find_free_port()
    os.environ["COMPETITION_MONITOR_DESKTOP_PORT"] = str(port)
    base_url = f"http://127.0.0.1:{port}"

    server_thread = threading.Thread(target=run_server, daemon=True)
    server_thread.start()

    if not _wait_for_port(port, timeout_sec=20.0):
        err = "\n".join(_server_start_error) if _server_start_error else "Сервер не ответил за 20 с."
        app = QApplication(sys.argv)
        detail = f"Не удалось запустить встроенный сервер на порту {port}.\n\n{err}"
        if getattr(sys, "frozen", False) and _server_start_error:
            detail += "\n\nПодробности также сохранены в %TEMP%\\competitionmonitor_error.txt"
        QMessageBox.critical(None, "Ошибка запуска", detail)
        sys.exit(1)

    if _server_start_error:
        app = QApplication(sys.argv)
        detail = "Сервер завершился с ошибкой:\n\n" + "\n".join(_server_start_error)
        if getattr(sys, "frozen", False):
            detail += "\n\nПодробности в %TEMP%\\competitionmonitor_error.txt"
        QMessageBox.critical(None, "Ошибка сервера", detail)
        sys.exit(1)

    app = QApplication(sys.argv)
    app.setApplicationName("Competition Monitor")
    win = MainWindow(base_url)
    win.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
