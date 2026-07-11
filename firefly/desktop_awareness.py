"""Small desktop-awareness helpers for Firefly."""

from __future__ import annotations

import ctypes
import ctypes.wintypes
import os
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path

GW_HWNDNEXT = 2
FIREFLY_WINDOW_TITLE_PARTS = ("Firefly Agent", "Firefly", "Codex")
EXCLUDED_PROCESS_NAMES = {"textinputhost.exe"}
PROCESS_QUERY_LIMITED_INFORMATION = 0x1000


class RECT(ctypes.Structure):
    _fields_ = [
        ("left", ctypes.c_long),
        ("top", ctypes.c_long),
        ("right", ctypes.c_long),
        ("bottom", ctypes.c_long),
    ]


@dataclass
class DesktopSnapshot:
    title: str
    image_path: Path | None
    hwnd: int = 0


def foreground_window_handle() -> int:
    try:
        user32 = ctypes.windll.user32
        user32.GetForegroundWindow.restype = ctypes.wintypes.HWND
        return int(user32.GetForegroundWindow() or 0)
    except (AttributeError, OSError):
        return 0


def window_process_id(hwnd: int) -> int:
    try:
        user32 = ctypes.windll.user32
        user32.GetWindowThreadProcessId.argtypes = [ctypes.wintypes.HWND, ctypes.POINTER(ctypes.wintypes.DWORD)]
        pid = ctypes.wintypes.DWORD()
        user32.GetWindowThreadProcessId(ctypes.wintypes.HWND(hwnd), ctypes.byref(pid))
        return int(pid.value)
    except (AttributeError, OSError, ValueError):
        return 0


def window_process_name(hwnd: int) -> str:
    pid = window_process_id(hwnd)
    if not pid:
        return ""
    try:
        kernel32 = ctypes.windll.kernel32
        kernel32.OpenProcess.argtypes = [ctypes.wintypes.DWORD, ctypes.wintypes.BOOL, ctypes.wintypes.DWORD]
        kernel32.OpenProcess.restype = ctypes.wintypes.HANDLE
        kernel32.QueryFullProcessImageNameW.argtypes = [
            ctypes.wintypes.HANDLE,
            ctypes.wintypes.DWORD,
            ctypes.c_wchar_p,
            ctypes.POINTER(ctypes.wintypes.DWORD),
        ]
        kernel32.QueryFullProcessImageNameW.restype = ctypes.wintypes.BOOL
        kernel32.CloseHandle.argtypes = [ctypes.wintypes.HANDLE]
        handle = kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
        if not handle:
            return ""
        try:
            size = ctypes.wintypes.DWORD(32768)
            buffer = ctypes.create_unicode_buffer(size.value)
            if not kernel32.QueryFullProcessImageNameW(handle, 0, buffer, ctypes.byref(size)):
                return ""
            return Path(buffer.value).name.casefold()
        finally:
            kernel32.CloseHandle(handle)
    except (AttributeError, OSError, ValueError):
        return ""


def window_is_visible(hwnd: int) -> bool:
    try:
        user32 = ctypes.windll.user32
        user32.IsWindowVisible.argtypes = [ctypes.wintypes.HWND]
        return bool(user32.IsWindowVisible(ctypes.wintypes.HWND(hwnd)))
    except (AttributeError, OSError, ValueError):
        return False


def window_rect(hwnd: int) -> tuple[int, int, int, int] | None:
    try:
        user32 = ctypes.windll.user32
        user32.GetWindowRect.argtypes = [ctypes.wintypes.HWND, ctypes.POINTER(RECT)]
        rect = RECT()
        if not user32.GetWindowRect(ctypes.wintypes.HWND(hwnd), ctypes.byref(rect)):
            return None
        if rect.right <= rect.left or rect.bottom <= rect.top:
            return None
        return rect.left, rect.top, rect.right, rect.bottom
    except (AttributeError, OSError, ValueError):
        return None


def pixmap_is_mostly_black(pixmap: object) -> bool:
    try:
        if pixmap.isNull():
            return True
        image = pixmap.toImage()
        width = image.width()
        height = image.height()
        if width <= 0 or height <= 0:
            return True
        step_x = max(1, width // 8)
        step_y = max(1, height // 8)
        total = 0
        dark = 0
        for y in range(step_y // 2, height, step_y):
            for x in range(step_x // 2, width, step_x):
                color = image.pixelColor(x, y)
                total += 1
                if color.alpha() > 0 and max(color.red(), color.green(), color.blue()) < 8:
                    dark += 1
        return total > 0 and dark / total > 0.95
    except AttributeError:
        return True


def title_matches_any(title: str, parts: tuple[str, ...]) -> bool:
    normalized = title.casefold()
    return any(part.casefold() in normalized for part in parts if part.strip())


def window_is_excluded(hwnd: int, title: str, excluded_title_parts: tuple[str, ...], exclude_own_process: bool) -> bool:
    if exclude_own_process and window_process_id(hwnd) == os.getpid():
        return True
    if window_process_name(hwnd) in EXCLUDED_PROCESS_NAMES:
        return True
    return title_matches_any(title, excluded_title_parts)


def window_is_capturable(hwnd: int) -> bool:
    rect = window_rect(hwnd)
    return bool(rect and window_is_visible(hwnd) and rect[2] - rect[0] >= 64 and rect[3] - rect[1] >= 64)


def next_visible_window_after(
    hwnd: int,
    *,
    excluded_title_parts: tuple[str, ...] = (),
    exclude_own_process: bool = False,
) -> int:
    try:
        user32 = ctypes.windll.user32
        user32.GetWindow.argtypes = [ctypes.wintypes.HWND, ctypes.c_uint]
        user32.GetWindow.restype = ctypes.wintypes.HWND
        candidate = int(user32.GetWindow(ctypes.wintypes.HWND(hwnd), GW_HWNDNEXT) or 0)
    except (AttributeError, OSError, ValueError):
        return 0

    visited: set[int] = set()
    while candidate and candidate not in visited:
        visited.add(candidate)
        title = current_window_title(candidate)
        if (
            window_is_capturable(candidate)
            and not window_is_excluded(candidate, title, excluded_title_parts, exclude_own_process)
        ):
            return candidate
        try:
            candidate = int(user32.GetWindow(ctypes.wintypes.HWND(candidate), GW_HWNDNEXT) or 0)
        except (OSError, ValueError):
            return 0
    return 0


def select_snapshot_window(
    *,
    excluded_title_parts: tuple[str, ...] = (),
    exclude_own_process: bool = False,
) -> int:
    hwnd = foreground_window_handle()
    if not hwnd:
        return 0
    title = current_window_title(hwnd)
    if not window_is_capturable(hwnd) or window_is_excluded(hwnd, title, excluded_title_parts, exclude_own_process):
        return next_visible_window_after(
            hwnd,
            excluded_title_parts=excluded_title_parts,
            exclude_own_process=exclude_own_process,
        )
    return hwnd


def current_window_title(hwnd: int | None = None) -> str:
    try:
        user32 = ctypes.windll.user32
        user32.GetWindowTextLengthW.argtypes = [ctypes.wintypes.HWND]
        user32.GetWindowTextW.argtypes = [ctypes.wintypes.HWND, ctypes.c_wchar_p, ctypes.c_int]
        if hwnd is None:
            hwnd = foreground_window_handle()
        if not hwnd:
            return ""
        length = user32.GetWindowTextLengthW(hwnd)
        if length <= 0:
            return ""
        buffer = ctypes.create_unicode_buffer(length + 1)
        user32.GetWindowTextW(hwnd, buffer, length + 1)
        return buffer.value.strip()
    except (AttributeError, OSError):
        return ""


def _snapshot_image_path(workspace: Path, prefix: str, *, persist: bool = True) -> Path:
    filename = f"{prefix}_{time.strftime('%Y%m%d_%H%M%S')}_{time.time_ns() % 1_000_000:06d}.png"
    if not persist:
        return Path(tempfile.gettempdir()) / filename
    screenshots = workspace / "screenshots"
    screenshots.mkdir(parents=True, exist_ok=True)
    return screenshots / filename


def capture_desktop_snapshot(
    workspace: Path,
    prefix: str = "context",
    *,
    excluded_title_parts: tuple[str, ...] = (),
    exclude_own_process: bool = False,
    hwnd: int | None = None,
    full_screen: bool = False,
    persist: bool = True,
) -> DesktopSnapshot:
    hwnd = hwnd or select_snapshot_window(excluded_title_parts=excluded_title_parts, exclude_own_process=exclude_own_process)
    if not hwnd and not full_screen:
        return DesktopSnapshot(title="", image_path=None, hwnd=0)
    title = current_window_title(hwnd) if hwnd else "当前屏幕"
    image_path: Path | None = None
    try:
        from PySide6.QtCore import QPoint, QRect
        from PySide6.QtGui import QGuiApplication

        app = QGuiApplication.instance()
        screen = app.primaryScreen() if app is not None else None
        rect = window_rect(hwnd) if hwnd and not full_screen else None
        if app is not None and rect is not None:
            screen = QGuiApplication.screenAt(QPoint((rect[0] + rect[2]) // 2, (rect[1] + rect[3]) // 2)) or screen
        if screen is not None:
            target = _snapshot_image_path(workspace, prefix, persist=persist)
            pixmap = screen.grabWindow(0) if full_screen or not hwnd else screen.grabWindow(hwnd)
            if pixmap.isNull() or pixmap_is_mostly_black(pixmap):
                full = screen.grabWindow(0)
                if rect is not None and not full.isNull():
                    geometry = screen.geometry()
                    crop = QRect(rect[0] - geometry.x(), rect[1] - geometry.y(), rect[2] - rect[0], rect[3] - rect[1])
                    crop = crop.intersected(QRect(0, 0, full.width(), full.height()))
                    pixmap = full.copy(crop) if not crop.isEmpty() else full
                else:
                    pixmap = full
            if not pixmap.isNull() and pixmap.save(str(target), "PNG"):
                image_path = target
    except Exception:
        image_path = None
    return DesktopSnapshot(title=title, image_path=image_path, hwnd=hwnd)


def snapshot_prompt(snapshot: DesktopSnapshot, purpose: str, last_reply: str = "") -> str:
    title = snapshot.title or "未识别"
    image = f"\n截图附件: {snapshot.image_path}\n截图已作为图片附件发送；请优先根据图片内容判断，不要只复述路径。" if snapshot.image_path else ""
    if purpose.lstrip().startswith("萤火巡望："):
        previous = "\n不要延续上一轮气泡的话题。" if last_reply.strip() else ""
    else:
        previous = f"\n上一轮气泡: {last_reply[:160]}\n不要重复上一轮气泡。" if last_reply.strip() else ""
    return f"{purpose}\n当前窗口标题: {title}{image}{previous}"
