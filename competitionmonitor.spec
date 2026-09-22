# -*- mode: python ; coding: utf-8 -*-
# Сборка: из корня проекта: pyinstaller competitionmonitor.spec --workpath <папка> --distpath dist --clean --noconfirm
# Пути в spec считаются относительно текущей директории (корень проекта).
#
# ВАЖНО (безопасность): .env НИКОГДА не должен попадать в datas и, соответственно,
# в собранный дистрибутив — иначе API-ключ и прочие секреты окажутся в файлах exe.
# Конфигурация desktop-сборки берётся из переменных окружения ОС и/или пользовательского
# файла вне каталога сборки: %APPDATA%\CompetitionMonitor\.env (см. backend/config.py,
# docs.md, раздел «Desktop-конфигурация»). Проверка ниже (перед Analysis) — это
# регрессионный guard: сборка намеренно падает, если .env когда-либо попадёт в datas.

import os
from PyInstaller.utils.hooks import collect_all

# Данные: относительные пути от корня проекта. .env сюда НЕ добавляется — см. комментарий выше.
_here = os.path.abspath(SPECPATH)
datas = [
    (os.path.join(_here, 'backend'), 'backend'),
    (os.path.join(_here, 'static'), 'static'),
]

hiddenimports = [
    # uvicorn
    'uvicorn.logging', 'uvicorn.loops', 'uvicorn.loops.auto',
    'uvicorn.protocols', 'uvicorn.protocols.http', 'uvicorn.protocols.http.auto',
    'uvicorn.protocols.websockets', 'uvicorn.protocols.websockets.auto',
    'uvicorn.lifespan', 'uvicorn.lifespan.on',
    # fastapi + starlette (иначе exe: ModuleNotFoundError: No module named 'fastapi')
    'fastapi', 'fastapi.responses', 'fastapi.staticfiles', 'fastapi.middleware',
    'starlette', 'starlette.applications', 'starlette.requests', 'starlette.responses',
    'starlette.routing', 'starlette.middleware', 'starlette.middleware.cors',
    'starlette.staticfiles', 'starlette.exceptions',
    # pydantic
    'pydantic', 'pydantic_settings',
    # backend (uvicorn подгружает backend.main по строке)
    'backend', 'backend.main', 'backend.config', 'backend.logging_config',
    'backend.errors', 'backend.limits',
    'backend.routers', 'backend.routers.analyze', 'backend.routers.analyze_url',
    'backend.routers.history', 'backend.routers.parse_demo',
    'backend.services', 'backend.services.history_service', 'backend.services.openai_service',
    'backend.services.parser_service', 'backend.services.pdf_service', 'backend.services.url_safety',
    'backend.models', 'backend.models.schemas',
    # остальные зависимости бэкенда
    'openai', 'httpx', 'bs4', 'pypdf', 'multipart',
    # Selenium (иначе exe: No module named 'selenium.webdriver.chrome.webdriver').
    # Driver-бинарник резолвится Selenium Manager (встроен в selenium>=4.6) — без webdriver-manager.
    'selenium', 'selenium.webdriver', 'selenium.webdriver.chrome',
    'selenium.webdriver.chrome.webdriver', 'selenium.webdriver.chrome.service',
    'selenium.webdriver.chrome.options', 'selenium.webdriver.remote.webdriver',
]
binaries = []
tmp = collect_all('PyQt6')
datas += tmp[0]; binaries += tmp[1]; hiddenimports += tmp[2]
tmp = collect_all('PyQt6.QtWebEngineCore')
datas += tmp[0]; binaries += tmp[1]; hiddenimports += tmp[2]
tmp = collect_all('PyQt6.QtWebEngineWidgets')
datas += tmp[0]; binaries += tmp[1]; hiddenimports += tmp[2]

# Regression guard: .env (or another known secret/runtime-data filename) must never end up in
# datas, from any source (explicit entries above or anything collect_all() might have pulled
# in) — including nested inside a directory entry, which PyInstaller copies recursively (the
# backend/static entries above ARE directories). A guard that only inspected each datas
# tuple's own top-level name would miss a secret file a few levels inside one of those. Fails
# the build loudly instead of silently shipping a secret. Covered by an equivalent offline
# test in tests/test_packaging.py, including a realistic nested-directory case.
def _is_forbidden_data_name(name):
    lname = name.lower()
    if lname in ('.env', 'history.json'):
        return True
    if lname.endswith('.env'):
        return True
    if lname.startswith('history') and lname.endswith('.json'):
        return True  # also catches quarantined history.corrupt-<timestamp>.json
    return False


for _src, _dst in datas:
    if _is_forbidden_data_name(os.path.basename(str(_src).replace('\\', '/'))):
        raise RuntimeError(
            f"competitionmonitor.spec: запрещённый файл обнаружен в datas: {_src!r} — секрет/"
            "рантайм-данные не должны попадать в PyInstaller-дистрибутив."
        )
    if os.path.isdir(_src):
        for _root, _dirs, _files in os.walk(_src):
            for _fname in _files:
                if _is_forbidden_data_name(_fname):
                    raise RuntimeError(
                        "competitionmonitor.spec: запрещённый файл обнаружен внутри каталога "
                        f"datas: {os.path.join(_root, _fname)!r} — секрет/рантайм-данные не "
                        "должны попадать в PyInstaller-дистрибутив."
                    )

a = Analysis(
    [os.path.join(_here, 'desktop_main.py')],
    pathex=[_here],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='competitionmonitor',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name='competitionmonitor',
)
