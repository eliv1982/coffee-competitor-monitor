# -*- mode: python ; coding: utf-8 -*-
# Сборка: из корня проекта: pyinstaller competitionmonitor.spec --workpath <папка> --distpath dist --clean --noconfirm
# Пути в spec считаются относительно текущей директории (корень проекта).

import os
from PyInstaller.utils.hooks import collect_all

# Данные: относительные пути от корня проекта
_here = os.path.abspath(SPECPATH)
datas = [
    (os.path.join(_here, 'backend'), 'backend'),
    (os.path.join(_here, 'static'), 'static'),
]
if os.path.isfile(os.path.join(_here, '.env')):
    datas.append((os.path.join(_here, '.env'), '.'))

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
    'backend.routers', 'backend.routers.analyze', 'backend.routers.analyze_url',
    'backend.routers.history', 'backend.routers.parse_demo',
    'backend.services', 'backend.services.history_service', 'backend.services.openai_service',
    'backend.services.parser_service', 'backend.services.pdf_service',
    'backend.models', 'backend.models.schemas',
    # остальные зависимости бэкенда
    'openai', 'httpx', 'bs4', 'pypdf', 'multipart',
    # Selenium (иначе exe: No module named 'selenium.webdriver.chrome.webdriver')
    'selenium', 'selenium.webdriver', 'selenium.webdriver.chrome',
    'selenium.webdriver.chrome.webdriver', 'selenium.webdriver.chrome.service',
    'selenium.webdriver.chrome.options', 'selenium.webdriver.remote.webdriver',
    'webdriver_manager', 'webdriver_manager.chrome',
]
binaries = []
tmp = collect_all('PyQt6')
datas += tmp[0]; binaries += tmp[1]; hiddenimports += tmp[2]
tmp = collect_all('PyQt6.QtWebEngineCore')
datas += tmp[0]; binaries += tmp[1]; hiddenimports += tmp[2]
tmp = collect_all('PyQt6.QtWebEngineWidgets')
datas += tmp[0]; binaries += tmp[1]; hiddenimports += tmp[2]

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
