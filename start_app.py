"""Run Pocket Money in a native desktop window."""

import os
import csv
import secrets
import subprocess
import sys
import threading
import time
import urllib.request
from pathlib import Path

import uvicorn
import webview
from database import SessionLocal
import models


PROJECT_DIR = Path(__file__).resolve().parent
RESOURCE_DIR = Path(getattr(sys, "_MEIPASS", PROJECT_DIR))
IS_FROZEN = bool(getattr(sys, "frozen", False))
BACKEND_DIR = RESOURCE_DIR if IS_FROZEN else PROJECT_DIR / "backend"
ICON_PATH = RESOURCE_DIR / "assets" / "pocket-money.ico"
MUTEX_HANDLE = None


def harden_data_directory(data_dir: Path) -> None:
    """Limit the local finance database to this Windows user and SYSTEM."""
    if os.name != "nt":
        return
    hidden = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    try:
        identity = subprocess.run(
            ["whoami", "/user", "/fo", "csv", "/nh"],
            capture_output=True,
            text=True,
            check=True,
            creationflags=hidden,
        ).stdout.strip()
        row = next(csv.reader([identity]))
        sid = next(value.strip() for value in row if value.strip().upper().startswith("S-1-"))
        subprocess.run(
            [
                "icacls", str(data_dir), "/inheritance:r", "/grant:r",
                f"*{sid}:(OI)(CI)F", "*S-1-5-18:(OI)(CI)F",
            ],
            capture_output=True,
            check=True,
            creationflags=hidden,
        )
    except (OSError, subprocess.SubprocessError, StopIteration, csv.Error):
        # DPAPI still protects tokens even if Windows refuses an ACL update.
        pass


def ensure_single_instance() -> None:
    """Prevent two app copies from starting after a double-click."""
    global MUTEX_HANDLE
    if os.name != "nt":
        return
    import ctypes

    kernel32 = ctypes.windll.kernel32
    MUTEX_HANDLE = kernel32.CreateMutexW(None, False, "PocketMoneyNativeDesktopV1")
    if kernel32.GetLastError() == 183:
        raise SystemExit(0)


def wait_until_ready(url: str) -> None:
    for _ in range(80):
        try:
            urllib.request.urlopen(f"{url}api/health", timeout=0.3).close()
            return
        except Exception:
            time.sleep(0.1)
    raise RuntimeError("Pocket Money server did not start")


if __name__ == "__main__":
    ensure_single_instance()
    local_data_dir = Path(os.environ.get("LOCALAPPDATA", Path.home())) / "PocketMoney"
    local_data_dir.mkdir(parents=True, exist_ok=True)
    harden_data_directory(local_data_dir)

    if IS_FROZEN:
        os.environ["POCKET_MONEY_DATA_DIR"] = str(local_data_dir)
        os.environ["POCKET_MONEY_RESOURCE_DIR"] = str(RESOURCE_DIR)

    bootstrap_token = secrets.token_urlsafe(32)
    os.environ["POCKET_MONEY_BOOTSTRAP_TOKEN"] = bootstrap_token

    os.chdir(BACKEND_DIR)
    if not IS_FROZEN:
        sys.path.insert(0, str(BACKEND_DIR))
    from main import app

    # Кожен запуск десктопного додатка починається з неавторизованого стану:
    # навіть якщо користувач просто закрив вікно, не натиснувши «Вийти»,
    # наступний запуск вимагатиме повторний PIN.
    with SessionLocal() as _db:
        _account = _db.query(models.Account).first()
        if _account:
            _account.is_authenticated = False
            _db.commit()

    port = 8765
    app_url = f"http://127.0.0.1:{port}/?bootstrap={bootstrap_token}"
    server = uvicorn.Server(uvicorn.Config(
        app,
        host="127.0.0.1",
        port=port,
        log_config=None,
        access_log=False,
    ))
    server_thread = threading.Thread(target=server.run, daemon=True)
    server_thread.start()
    wait_until_ready(f"http://127.0.0.1:{port}/")

    webview.create_window(
        "Pocket Money",
        app_url,
        width=1280,
        height=820,
        min_size=(360, 620),
        maximized=True,
        background_color="#f6f7fb",
    )
    webview.start(
        gui="edgechromium",
        private_mode=False,
        storage_path=str(local_data_dir / "NativeProfile"),
        icon=str(ICON_PATH),
    )
    server.should_exit = True
