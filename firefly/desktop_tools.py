"""Firefly desktop control tools registered only by the desktop app."""

from __future__ import annotations

import ctypes
import platform
import time
from pathlib import Path

from pydantic import BaseModel, Field

from openharness.tools.base import BaseTool, ToolExecutionContext, ToolResult


def firefly_desktop_tools(config: dict[str, object], workspace: Path) -> tuple[BaseTool, ...]:
    if not bool(config.get("desktop_control_enabled", False)):
        return ()
    return (
        DesktopScreenshotTool(workspace),
        DesktopWindowTool(),
        DesktopMouseTool(),
        DesktopKeyboardTool(),
    )


class DesktopScreenshotInput(BaseModel):
    filename: str = Field(default="", description="Optional file name under Firefly screenshots.")


class DesktopScreenshotTool(BaseTool):
    name = "desktop_screenshot"
    description = "Capture the current desktop screen to a Firefly workspace screenshot file."
    input_model = DesktopScreenshotInput

    def __init__(self, workspace: Path) -> None:
        self.workspace = workspace

    def is_read_only(self, arguments: BaseModel) -> bool:
        del arguments
        return True

    async def execute(self, arguments: DesktopScreenshotInput, context: ToolExecutionContext) -> ToolResult:
        del context
        if not _is_windows():
            return ToolResult("desktop_screenshot is only supported on Windows in this build.", is_error=True)
        try:
            from PySide6.QtGui import QGuiApplication
        except Exception as error:
            return ToolResult(f"PySide6 screenshot support is unavailable: {type(error).__name__}", is_error=True)
        app = QGuiApplication.instance()
        if app is None:
            return ToolResult("desktop_screenshot requires an active Qt application.", is_error=True)
        screen = app.primaryScreen()
        if screen is None:
            return ToolResult("No primary screen is available.", is_error=True)
        screenshots = self.workspace / "screenshots"
        screenshots.mkdir(parents=True, exist_ok=True)
        raw_name = arguments.filename.strip() or f"screenshot_{time.strftime('%Y%m%d_%H%M%S')}.png"
        target = screenshots / Path(raw_name).name
        if target.suffix.lower() != ".png":
            target = target.with_suffix(".png")
        pixmap = screen.grabWindow(0)
        if not pixmap.save(str(target), "PNG"):
            return ToolResult(f"Could not write screenshot: {target}", is_error=True)
        return ToolResult(f"Screenshot saved: {target}", metadata={"path": str(target)})


class DesktopWindowInput(BaseModel):
    action: str = Field(default="list", description="list or focus")
    title: str = Field(default="", description="Window title substring for focus.")
    hwnd: int = Field(default=0, description="Window handle for focus.")


class DesktopWindowTool(BaseTool):
    name = "desktop_window"
    description = "List visible desktop windows or focus one by title or handle."
    input_model = DesktopWindowInput

    def is_read_only(self, arguments: DesktopWindowInput) -> bool:
        return arguments.action == "list"

    async def execute(self, arguments: DesktopWindowInput, context: ToolExecutionContext) -> ToolResult:
        del context
        if not _is_windows():
            return ToolResult("desktop_window is only supported on Windows in this build.", is_error=True)
        if arguments.action == "list":
            windows = _list_windows()
            lines = [f"{item['hwnd']}: {item['title']}" for item in windows[:80]]
            return ToolResult("\n".join(lines) if lines else "No visible windows found.")
        if arguments.action != "focus":
            return ToolResult("desktop_window action must be list or focus.", is_error=True)
        hwnd = arguments.hwnd or _find_window(arguments.title)
        if not hwnd:
            return ToolResult("Window not found.", is_error=True)
        ctypes.windll.user32.SetForegroundWindow(hwnd)
        return ToolResult(f"Focused window: {hwnd}")


class DesktopMouseInput(BaseModel):
    action: str = Field(description="move, click, double_click, right_click, or scroll")
    x: int = 0
    y: int = 0
    delta: int = 0


class DesktopMouseTool(BaseTool):
    name = "desktop_mouse"
    description = "Move, click, right-click, double-click, or scroll the Windows mouse pointer."
    input_model = DesktopMouseInput

    async def execute(self, arguments: DesktopMouseInput, context: ToolExecutionContext) -> ToolResult:
        del context
        if not _is_windows():
            return ToolResult("desktop_mouse is only supported on Windows in this build.", is_error=True)
        user32 = ctypes.windll.user32
        if arguments.action in {"move", "click", "double_click", "right_click"}:
            user32.SetCursorPos(int(arguments.x), int(arguments.y))
        if arguments.action == "move":
            return ToolResult(f"Moved mouse to {arguments.x},{arguments.y}")
        if arguments.action == "click":
            _mouse_event(0x0002)
            _mouse_event(0x0004)
            return ToolResult(f"Clicked at {arguments.x},{arguments.y}")
        if arguments.action == "double_click":
            for _ in range(2):
                _mouse_event(0x0002)
                _mouse_event(0x0004)
            return ToolResult(f"Double-clicked at {arguments.x},{arguments.y}")
        if arguments.action == "right_click":
            _mouse_event(0x0008)
            _mouse_event(0x0010)
            return ToolResult(f"Right-clicked at {arguments.x},{arguments.y}")
        if arguments.action == "scroll":
            _mouse_event(0x0800, data=int(arguments.delta or 120))
            return ToolResult(f"Scrolled by {arguments.delta or 120}")
        return ToolResult("desktop_mouse action must be move, click, double_click, right_click, or scroll.", is_error=True)


class DesktopKeyboardInput(BaseModel):
    text: str = Field(default="", description="ASCII text to type.")
    keys: list[str] = Field(default_factory=list, description="Key names or one shortcut list such as ['ctrl', 'l'].")


class DesktopKeyboardTool(BaseTool):
    name = "desktop_keyboard"
    description = "Type ASCII text or press a Windows keyboard shortcut."
    input_model = DesktopKeyboardInput

    async def execute(self, arguments: DesktopKeyboardInput, context: ToolExecutionContext) -> ToolResult:
        del context
        if not _is_windows():
            return ToolResult("desktop_keyboard is only supported on Windows in this build.", is_error=True)
        if arguments.keys:
            return _press_shortcut(arguments.keys)
        if arguments.text:
            for char in arguments.text:
                result = _type_char(char)
                if result is not None:
                    return result
            return ToolResult(f"Typed {len(arguments.text)} characters.")
        return ToolResult("Provide text or keys.", is_error=True)


def _is_windows() -> bool:
    return platform.system().lower() == "windows"


def _list_windows() -> list[dict[str, object]]:
    user32 = ctypes.windll.user32
    windows: list[dict[str, object]] = []

    def callback(hwnd: int, _lparam: int) -> bool:
        if not user32.IsWindowVisible(hwnd):
            return True
        length = user32.GetWindowTextLengthW(hwnd)
        if length <= 0:
            return True
        buffer = ctypes.create_unicode_buffer(length + 1)
        user32.GetWindowTextW(hwnd, buffer, length + 1)
        title = buffer.value.strip()
        if title:
            windows.append({"hwnd": hwnd, "title": title})
        return True

    enum_proc = ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_int, ctypes.c_int)(callback)
    user32.EnumWindows(enum_proc, 0)
    return windows


def _find_window(title: str) -> int:
    needle = title.strip().lower()
    if not needle:
        return 0
    for item in _list_windows():
        if needle in str(item["title"]).lower():
            return int(item["hwnd"])
    return 0


def _mouse_event(flags: int, data: int = 0) -> None:
    ctypes.windll.user32.mouse_event(flags, 0, 0, data, 0)


def _press_key(vk: int) -> None:
    ctypes.windll.user32.keybd_event(vk, 0, 0, 0)


def _release_key(vk: int) -> None:
    ctypes.windll.user32.keybd_event(vk, 0, 0x0002, 0)


def _press_shortcut(keys: list[str]) -> ToolResult:
    vks = [_vk_for_key(key) for key in keys]
    if any(vk == 0 for vk in vks):
        return ToolResult(f"Unsupported key in shortcut: {keys}", is_error=True)
    for vk in vks:
        _press_key(vk)
    for vk in reversed(vks):
        _release_key(vk)
    return ToolResult(f"Pressed shortcut: {'+'.join(keys)}")


def _type_char(char: str) -> ToolResult | None:
    code = ctypes.windll.user32.VkKeyScanW(ord(char))
    if code == -1:
        return ToolResult(f"Unsupported character for desktop_keyboard: {char!r}", is_error=True)
    vk = code & 0xFF
    shift_state = (code >> 8) & 0xFF
    modifiers = []
    if shift_state & 1:
        modifiers.append(0x10)
    if shift_state & 2:
        modifiers.append(0x11)
    if shift_state & 4:
        modifiers.append(0x12)
    for modifier in modifiers:
        _press_key(modifier)
    _press_key(vk)
    _release_key(vk)
    for modifier in reversed(modifiers):
        _release_key(modifier)
    return None


def _vk_for_key(key: str) -> int:
    upper = key.strip().upper()
    mapping = {
        "CTRL": 0x11,
        "CONTROL": 0x11,
        "ALT": 0x12,
        "SHIFT": 0x10,
        "ENTER": 0x0D,
        "TAB": 0x09,
        "ESC": 0x1B,
        "ESCAPE": 0x1B,
        "BACKSPACE": 0x08,
        "DELETE": 0x2E,
        "SPACE": 0x20,
        "LEFT": 0x25,
        "UP": 0x26,
        "RIGHT": 0x27,
        "DOWN": 0x28,
    }
    if upper in mapping:
        return mapping[upper]
    if len(upper) == 1:
        return ord(upper)
    if upper.startswith("F") and upper[1:].isdigit():
        number = int(upper[1:])
        if 1 <= number <= 24:
            return 0x70 + number - 1
    return 0
