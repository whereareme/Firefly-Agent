"""Windows autostart helpers for Firefly."""

from __future__ import annotations

import platform
import subprocess
import sys
from pathlib import Path

APP_NAME = "Firefly Agent"
RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"


def autostart_supported() -> bool:
    return platform.system() == "Windows"


def firefly_desktop_command_parts(cwd: str | Path) -> tuple[str, list[str]]:
    if getattr(sys, "frozen", False):
        return sys.executable, ["desktop", "--cwd", str(Path(cwd).resolve())]
    script = Path(sys.executable).with_name("firefly.exe")
    if script.exists():
        return str(script), ["desktop", "--cwd", str(Path(cwd).resolve())]
    return sys.executable, ["-c", "from firefly.cli import app; app()", "desktop", "--cwd", str(Path(cwd).resolve())]


def autostart_command(cwd: str | Path) -> str:
    program, arguments = firefly_desktop_command_parts(cwd)
    parts = [program, *arguments]
    return subprocess.list2cmdline(parts)


def is_autostart_enabled() -> bool:
    if not autostart_supported():
        return False
    import winreg

    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY) as key:
            winreg.QueryValueEx(key, APP_NAME)
            return True
    except FileNotFoundError:
        return False


def set_autostart(enabled: bool, cwd: str | Path) -> None:
    if not autostart_supported():
        raise RuntimeError("当前系统不支持开机自启设置")
    import winreg

    with winreg.CreateKey(winreg.HKEY_CURRENT_USER, RUN_KEY) as key:
        if enabled:
            winreg.SetValueEx(key, APP_NAME, 0, winreg.REG_SZ, autostart_command(cwd))
        else:
            try:
                winreg.DeleteValue(key, APP_NAME)
            except FileNotFoundError:
                pass
