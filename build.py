"""
Сборка desktop-приложения Competition Monitor (PyQt6 + PyInstaller).

Каждая сборка создаётся в новой папке %USERPROFILE%\\cm_dist\\build_<время>\\competitionmonitor\\
(старый exe можно не закрывать). Временные файлы: %USERPROFILE%\\cm_build.
"""
import argparse
import os
import subprocess
import sys
import time
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent
SPEC_FILE = PROJECT_ROOT / "competitionmonitor.spec"
DIST_NAME = "competitionmonitor"


def main():
    parser = argparse.ArgumentParser(description="Сборка competitionmonitor.exe")
    parser.add_argument(
        "--workpath",
        type=str,
        default=None,
        help="Папка для временных файлов PyInstaller (без пробелов). По умолчанию: %%USERPROFILE%%\\pyinstaller_build. Добавьте её в исключения Defender.",
    )
    parser.add_argument(
        "--distpath",
        type=str,
        default=None,
        help="Папка для готового exe. По умолчанию: dist в корне проекта.",
    )
    args = parser.parse_args()

    os.chdir(PROJECT_ROOT)
    if not SPEC_FILE.exists():
        print(f"Ошибка: не найден {SPEC_FILE}")
        sys.exit(1)

    # Пути БЕЗ пробелов (проект "Coffee Compass" — с пробелом, антивирус часто блокирует)
    profile = Path(os.environ.get("USERPROFILE", "."))
    if args.workpath:
        workpath = Path(args.workpath).resolve()
    else:
        workpath = profile / "cm_build"
    workpath.mkdir(parents=True, exist_ok=True)

    if args.distpath:
        distpath = Path(args.distpath).resolve()
    else:
        # Подпапка с меткой времени — PyInstaller не удаляет старую (exe может быть запущен)
        base_dist = profile / "cm_dist"
        base_dist.mkdir(parents=True, exist_ok=True)
        distpath = base_dist / f"build_{int(time.time())}"
    distpath.mkdir(parents=True, exist_ok=True)

    print("=" * 60)
    print("Сборка competitionmonitor.exe")
    print("=" * 60)
    print(f"Временные файлы (workpath): {workpath}")
    print(f"Готовый exe будет в:        {distpath / DIST_NAME}")
    print()
    print("Каждая сборка создаётся в новой папке (build_<время>), старый exe можно не закрывать.")
    print("Если ошибка «Отказано в доступе» в workpath — добавьте в Pro32 исключения:")
    print(f"  {workpath}")
    print("=" * 60)

    cmd = [
        sys.executable, "-m", "PyInstaller",
        str(SPEC_FILE),
        f"--workpath={workpath}",
        f"--distpath={distpath}",
        "--clean",
        "--noconfirm",
    ]
    env = os.environ.copy()
    env["PYTHONPATH"] = str(PROJECT_ROOT)
    r = subprocess.run(cmd, env=env)
    if r.returncode != 0:
        print("Сборка завершилась с ошибкой. Проверьте исключения Defender для workpath.")
        sys.exit(r.returncode)

    exe_path = distpath / DIST_NAME / ("competitionmonitor.exe" if sys.platform == "win32" else "competitionmonitor")
    print()
    print("Сборка успешна (папка-дистрибутив, onedir — не единый exe-файл).")
    print(f"Запуск: {exe_path}")
    print()
    print(".env НЕ входит в сборку (проверяется assert'ом в competitionmonitor.spec).")
    print("Настройте OPENAI_API_KEY переменной окружения ОС или файлом:")
    print(r"  %APPDATA%\CompetitionMonitor\.env")
    return 0


if __name__ == "__main__":
    sys.exit(main())
