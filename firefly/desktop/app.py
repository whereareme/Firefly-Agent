"""Desktop launcher for Firefly."""

from __future__ import annotations

import json
import hashlib
import mimetypes
import os
import sys
import tempfile
import threading
import time
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urlparse

from firefly.live2d.module import Live2DModule
from firefly.workspace import initialize_workspace, load_config

try:
    from PySide6.QtCore import QObject, QThread, QTimer, Qt, Slot
    from PySide6.QtGui import QFont
    from PySide6.QtWidgets import QApplication, QMessageBox
except ImportError as error:  # pragma: no cover - depends on local desktop env.
    QT_IMPORT_ERROR: ImportError | None = error
else:
    QT_IMPORT_ERROR = None

PACKAGE_ROOT = Path(__file__).resolve().parents[1]
WEB_ROOT = PACKAGE_ROOT / "desktop" / "web"
LIVE2D_ROOT = PACKAGE_ROOT / "assets" / "live2d"


def write_firefly_watch_log(workspace: Path, event: str, **fields: object) -> None:
    try:
        log_dir = workspace / "logs"
        log_dir.mkdir(parents=True, exist_ok=True)
        payload: dict[str, object] = {"time": time.strftime("%Y-%m-%d %H:%M:%S"), "event": event}
        for key, value in fields.items():
            if value is None or isinstance(value, (str, int, float, bool)):
                payload[key] = value
        with (log_dir / "firefly_watch.log").open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(payload, ensure_ascii=False) + "\n")
    except OSError:
        pass


def complete_watch_turn(state: dict[str, Any]) -> bool:
    state["completed_token"] = state.get("token")
    return not bool(state.get("timed_out"))


def timeout_watch_turn(state: dict[str, Any], token: int) -> bool:
    thread = state.get("thread")
    if token != state.get("token") or thread is None:
        return False
    state["completed_token"] = token
    state["timed_out"] = True
    if thread.isRunning():
        thread.requestInterruption()
    return True


def watch_turn_finished_without_result(state: dict[str, Any], token: int) -> bool:
    return token == state.get("token") and state.get("completed_token") != token


class FireflyDesktopServer(ThreadingHTTPServer):
    def __init__(self, server_address: tuple[str, int], handler_class: type[BaseHTTPRequestHandler]) -> None:
        super().__init__(server_address, handler_class)
        self.live2d = Live2DModule(LIVE2D_ROOT)


class FireflyDesktopHandler(BaseHTTPRequestHandler):
    server: FireflyDesktopServer

    def log_message(self, format: str, *args: object) -> None:
        return None

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        path = unquote(parsed.path)
        if path == "/api/live2d/config":
            self._json(self.server.live2d.client_config())
            return
        if path.startswith("/assets/live2d/"):
            self._serve_file(LIVE2D_ROOT, path.removeprefix("/assets/live2d/"))
            return
        requested = "live2d.html" if path in {"", "/"} else path.lstrip("/")
        self._serve_file(WEB_ROOT, requested)

    def _json(self, payload: dict[str, Any]) -> None:
        data = json.dumps(payload, ensure_ascii=False, indent=2).encode("utf-8")
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _serve_file(self, root: Path, requested: str) -> None:
        root = root.resolve()
        candidate = (root / requested).resolve()
        if not candidate.exists() or not candidate.is_file() or not candidate.is_relative_to(root):
            self.send_error(HTTPStatus.NOT_FOUND, "File not found")
            return
        content_type = mimetypes.guess_type(candidate.name)[0] or "application/octet-stream"
        data = candidate.read_bytes()
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)


class LocalServer:
    def __init__(self) -> None:
        self.server: FireflyDesktopServer | None = None
        self.thread: threading.Thread | None = None
        self.url = ""

    def start(self) -> str:
        self.server = FireflyDesktopServer(("127.0.0.1", 0), FireflyDesktopHandler)
        host, port = self.server.server_address
        self.url = f"http://{host}:{port}/live2d.html"
        self.thread = threading.Thread(target=self.server.serve_forever, name="firefly-live2d", daemon=True)
        self.thread.start()
        return self.url

    def stop(self) -> None:
        if self.server is None:
            return
        self.server.shutdown()
        self.server.server_close()
        if self.thread and self.thread.is_alive():
            self.thread.join(timeout=2)


def configure_desktop_runtime() -> None:
    os.environ.setdefault("QTWEBENGINE_CHROMIUM_FLAGS", "--use-angle=swiftshader --enable-unsafe-swiftshader --disable-gpu-compositing --no-proxy-server")
    os.environ.setdefault("QT_OPENGL", "software")


def main(
    *,
    cwd: str | None = None,
    workspace: str | Path | None = None,
    model: str | None = None,
    provider_profile: str | None = None,
) -> int:
    configure_desktop_runtime()
    if QT_IMPORT_ERROR is not None:
        print("PySide6 with QtWebEngine is required for `firefly desktop`.", file=sys.stderr)
        print("Install it in the project environment with `uv pip install PySide6`.", file=sys.stderr)
        print(f"Import error: {QT_IMPORT_ERROR}", file=sys.stderr)
        return 1

    try:
        from firefly.desktop.chat_window import ChatWindow, strip_generated_image_notice
        from firefly.desktop.pet_window import PetWindow
        from firefly.desktop.workers import ChatWorker
        from firefly.desktop_awareness import (
            FIREFLY_WINDOW_TITLE_PARTS,
            DesktopSnapshot,
            capture_desktop_snapshot,
            select_snapshot_window,
            snapshot_prompt,
        )
        from firefly.runtime import FireflyRuntime
    except ImportError as error:
        print(f"OpenHarness dependencies are not installed: {error}", file=sys.stderr)
        print("Install this repo first, for example with `uv sync`.", file=sys.stderr)
        return 1

    workspace_root = initialize_workspace(workspace)
    app = QApplication.instance() or QApplication(sys.argv)
    app.setApplicationName("Firefly Agent")
    app.setFont(QFont("Microsoft YaHei UI", 10))
    server = LocalServer()
    try:
        url = server.start()
    except OSError as error:
        QMessageBox.critical(None, "Firefly Agent", f"本地 Live2D 服务启动失败：{error}")
        return 1
    app.aboutToQuit.connect(server.stop)

    runtime = FireflyRuntime(cwd=cwd, workspace=workspace_root, model=model, provider_profile=provider_profile)
    chat_window = ChatWindow(runtime, workspace_root)

    def open_chat_with_files(files: list[str] | None = None) -> None:
        chat_window.show_and_raise()
        if files:
            chat_window.add_upload_files(files)

    pet_window = PetWindow(url, open_chat_with_files, open_chat_with_files, restart_cwd=cwd or Path.cwd(), workspace=workspace_root)
    chat_window.set_live2d_mood_sender(pet_window.set_live2d_mood)
    chat_window.set_approval_surface(pet_window)

    def capture_awareness_snapshot(prefix: str, *, persist: bool | None = None):
        if persist is None:
            persist = prefix != "chat_context"
        full_screen = prefix == "chat_context"
        target_hwnd = 0 if full_screen else select_snapshot_window(excluded_title_parts=FIREFLY_WINDOW_TITLE_PARTS, exclude_own_process=True)
        if not full_screen and not target_hwnd:
            return DesktopSnapshot(title="", image_path=None, hwnd=0)
        widgets = [getattr(pet_window, "speech_bubble", None), chat_window]
        if prefix != "firefly_watch":
            widgets.append(pet_window)
        visible = [widget for widget in widgets if widget is not None and widget.isVisible()]
        for widget in visible:
            widget.hide()
        app.processEvents()
        QThread.msleep(120)
        app.processEvents()
        try:
            return capture_desktop_snapshot(
                workspace_root,
                prefix,
                excluded_title_parts=FIREFLY_WINDOW_TITLE_PARTS,
                exclude_own_process=True,
                hwnd=target_hwnd or None,
                full_screen=full_screen,
                persist=persist,
            )
        finally:
            for widget in reversed(visible):
                widget.show()
            if getattr(pet_window, "speech_bubble", None) is not None:
                pet_window.position_speech_bubble()
            app.processEvents()

    chat_window.set_context_snapshotter(capture_awareness_snapshot)

    watch_state: dict[str, Any] = {
        "last": time.monotonic(),
        "last_digest": "",
        "last_target": "",
        "thread": None,
        "worker": None,
        "token": 0,
        "completed_token": 0,
        "timed_out": False,
    }
    watch_timer = QTimer(app)

    def remove_firefly_watch_snapshot(path: Path | None) -> None:
        if path is None:
            return
        try:
            if path.name.startswith("firefly_watch_") and path.parent.resolve() == Path(tempfile.gettempdir()).resolve():
                path.unlink(missing_ok=True)
        except OSError:
            pass

    def cleanup_watch_worker(token: int | None = None) -> None:
        if token is not None and token != watch_state.get("token"):
            return
        watch_state["thread"] = None
        watch_state["worker"] = None
        watch_state["last"] = time.monotonic()
        watch_state["token"] = int(watch_state.get("token") or 0) + 1
        watch_state["timed_out"] = False

    def show_firefly_watch_reply(message: str, reply: str, skills: object = None) -> None:
        del message, skills
        if not complete_watch_turn(watch_state):
            write_firefly_watch_log(workspace_root, "late_reply", reply_chars=len(reply.strip()))
            return
        cleaned = strip_generated_image_notice(reply)
        write_firefly_watch_log(workspace_root, "reply", reply_chars=len(cleaned.strip()))
        pet_window.last_agent_reply = cleaned
        pet_window.show_speech(cleaned, 15_000)
        bubble = pet_window.speech_bubble
        screen = bubble.screen() or pet_window.screen() or QApplication.primaryScreen()
        screen_geometry = screen.geometry() if screen is not None else None
        available_geometry = screen.availableGeometry() if screen is not None else None
        write_firefly_watch_log(
            workspace_root,
            "bubble",
            reply_chars=len(cleaned.strip()),
            main_thread=QThread.currentThread() == app.thread(),
            visible=bubble.isVisible(),
            x=bubble.x(),
            y=bubble.y(),
            w=bubble.width(),
            h=bubble.height(),
            pet_x=pet_window.x(),
            pet_y=pet_window.y(),
            pet_w=pet_window.width(),
            pet_h=pet_window.height(),
            screen_name=screen.name() if screen is not None else "",
            screen_x=screen_geometry.x() if screen_geometry is not None else None,
            screen_y=screen_geometry.y() if screen_geometry is not None else None,
            screen_w=screen_geometry.width() if screen_geometry is not None else None,
            screen_h=screen_geometry.height() if screen_geometry is not None else None,
            avail_x=available_geometry.x() if available_geometry is not None else None,
            avail_y=available_geometry.y() if available_geometry is not None else None,
            avail_w=available_geometry.width() if available_geometry is not None else None,
            avail_h=available_geometry.height() if available_geometry is not None else None,
        )

    def show_firefly_watch_error(error: str) -> None:
        if not complete_watch_turn(watch_state):
            write_firefly_watch_log(workspace_root, "late_failure", error_chars=len(str(error)))
            return
        write_firefly_watch_log(workspace_root, "failed", error_chars=len(str(error)))
        pet_window.show_speech("萤火巡望暂时没连上回应核心。", 5000)

    class WatchUiBridge(QObject):
        @Slot(str, str, object)
        def handle_reply(self, message: str, reply: str, skills: object = None) -> None:
            show_firefly_watch_reply(message, reply, skills)

        @Slot(str)
        def handle_error(self, error: str) -> None:
            show_firefly_watch_error(error)

    watch_ui_bridge = WatchUiBridge(app)

    def timeout_firefly_watch(token: int) -> None:
        if not timeout_watch_turn(watch_state, token):
            return
        write_firefly_watch_log(workspace_root, "timeout")
        pet_window.show_speech("萤火巡望这轮回应超时，先跳过。", 5000)
        pet_window.set_live2d_mood_from_watch("sweat")

    def finish_firefly_watch_thread(token: int, snapshot_path: Path | None) -> None:
        if token != watch_state.get("token"):
            return
        if watch_turn_finished_without_result(watch_state, token):
            write_firefly_watch_log(workspace_root, "dropped")
            remove_firefly_watch_snapshot(snapshot_path)
            pet_window.show_speech("萤火巡望这轮没有拿到回应，先跳过。", 5000)
            pet_window.set_live2d_mood_from_watch("sweat")
        cleanup_watch_worker(token)

    def stop_firefly_watch() -> None:
        watch_timer.stop()
        thread = watch_state.get("thread")
        if thread is not None:
            thread.quit()
            thread.wait(1500)

    def tick_firefly_watch() -> None:
        watch_snapshot_path: Path | None = None
        try:
            config = load_config(workspace_root)
            if not bool(config.get("firefly_watch_enabled", False)) or watch_state["thread"] is not None or chat_window.any_busy():
                return
            try:
                interval = max(30, int(config.get("firefly_watch_interval_sec") or 300))
            except (TypeError, ValueError):
                interval = 300
            now = time.monotonic()
            if now - float(watch_state.get("last") or now) < interval:
                return
            write_firefly_watch_log(workspace_root, "due", interval_sec=interval)
            watch_state["last"] = now
            snapshot = capture_awareness_snapshot("firefly_watch", persist=False)
            watch_snapshot_path = snapshot.image_path
            if not snapshot.hwnd or snapshot.image_path is None:
                write_firefly_watch_log(workspace_root, "capture_empty", hwnd=bool(snapshot.hwnd), image=bool(snapshot.image_path))
                remove_firefly_watch_snapshot(watch_snapshot_path)
                return
            attachments = [str(snapshot.image_path)] if snapshot.image_path is not None else []
            digest = ""
            if snapshot.image_path is not None:
                try:
                    digest = hashlib.sha1(snapshot.image_path.read_bytes()).hexdigest()
                except OSError:
                    pass
            target = f"{snapshot.hwnd}:{snapshot.title}"
            changed = target != watch_state.get("last_target") or (digest and digest != watch_state.get("last_digest"))
            if not changed:
                write_firefly_watch_log(workspace_root, "unchanged", hwnd=snapshot.hwnd)
                remove_firefly_watch_snapshot(watch_snapshot_path)
                return
            watch_state["last_digest"] = digest
            watch_state["last_target"] = target
            prompt = snapshot_prompt(
                snapshot,
                "萤火巡望：你正在从 Live2D 身边看用户当前窗口。只基于当前截图和窗口标题互动，不引用长期记忆或聊天历史。请用一句自然、简短、不过度打扰的话和用户互动；如果画面没有值得提醒的新变化，就不要硬找话题。",
                getattr(pet_window, "last_agent_reply", ""),
            )
            thread = QThread(app)
            worker = ChatWorker(runtime, prompt, [], attachments, remember=False, use_memory_context=False)
            watch_state["token"] = int(watch_state.get("token") or 0) + 1
            token = int(watch_state["token"])
            watch_state["thread"] = thread
            watch_state["worker"] = worker
            watch_state["timed_out"] = False
            worker.moveToThread(thread)
            thread.started.connect(worker.run)
            write_firefly_watch_log(workspace_root, "worker_started", hwnd=snapshot.hwnd, image_bytes=snapshot.image_path.stat().st_size)
            worker.finished.connect(watch_ui_bridge.handle_reply, Qt.QueuedConnection)
            worker.failed.connect(watch_ui_bridge.handle_error, Qt.QueuedConnection)
            worker.finished.connect(lambda _message, _reply, _skills, path=watch_snapshot_path: remove_firefly_watch_snapshot(path))
            worker.failed.connect(lambda _error, path=watch_snapshot_path: remove_firefly_watch_snapshot(path))
            worker.finished.connect(lambda _message, _reply, _skills, token=token: cleanup_watch_worker(token))
            worker.failed.connect(lambda _error, token=token: cleanup_watch_worker(token))
            worker.finished.connect(worker.deleteLater)
            worker.failed.connect(worker.deleteLater)
            worker.finished.connect(thread.quit)
            worker.failed.connect(thread.quit)
            thread.finished.connect(thread.deleteLater)
            thread.finished.connect(lambda token=token, path=watch_snapshot_path: finish_firefly_watch_thread(token, path))
            try:
                timeout_ms = (max(30, int(config.get("chat_timeout_sec") or 90)) + 15) * 1000
            except (TypeError, ValueError):
                timeout_ms = 105_000
            QTimer.singleShot(timeout_ms, lambda token=token: timeout_firefly_watch(token))
            watch_snapshot_path = None
            thread.start()
        except Exception:
            write_firefly_watch_log(workspace_root, "exception")
            remove_firefly_watch_snapshot(watch_snapshot_path)
            pet_window.set_live2d_mood_from_watch("sweat")

    watch_timer.timeout.connect(tick_firefly_watch)
    watch_timer.start(5_000)
    app.aboutToQuit.connect(stop_firefly_watch)
    pet_window.show()
    return app.exec()
