from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from PySide6.QtWidgets import QApplication, QLabel

from firefly.desktop.chat_window import ChatWindow
from firefly.desktop.companion_imprint import CompanionImprintController
from firefly.runtime import FireflyRuntime
from firefly.workspace import initialize_workspace, load_config, save_config


def make_window(tmp_path: Path) -> ChatWindow:
    workspace = initialize_workspace(tmp_path / ".firefly")
    return ChatWindow(FireflyRuntime(cwd=tmp_path, workspace=workspace), workspace)


def test_companion_imprint_settings_page_is_visible_and_compact(tmp_path: Path) -> None:
    QApplication.instance() or QApplication([])
    window = make_window(tmp_path)
    try:
        labels = [button.text() for button in window.settings_buttons]
        memory_index = labels.index("记忆回廊")
        assert labels[memory_index + 1] == "同行印记"
        assert window.settings_stack.widget(memory_index + 1).objectName() == "settingsScroll"
        window.companion_imprint_settings_button.click()
        assert window.settings_stack.currentIndex() == memory_index + 1
        assert window.companion_imprint_settings_button.parent().width() == 190
        text = "\n".join(label.text() for label in window.settings_stack.currentWidget().findChildren(QLabel))
        assert all(value not in text for value in ("好感值", "关系阶段", "礼物", "纪念日"))
        assert window.companion_imprint_status_label.wordWrap()
        assert window.companion_imprint_endpoint_label.wordWrap()
        assert window.companion_imprint_error_label.wordWrap()
    finally:
        window.deleteLater()


def test_companion_imprint_status_controls_refresh_offscreen(tmp_path: Path) -> None:
    QApplication.instance() or QApplication([])
    window = make_window(tmp_path)
    try:
        controller = window.companion_imprint_controller
        for status, label, running in (
            ("stopped", "已停止", False),
            ("starting", "正在启动", True),
            ("connected", "已连接", True),
            ("error", "需要处理", False),
        ):
            controller.status = status
            controller.error = "路径过长：" + ("x" * 240) if status == "error" else ""
            window.refresh_companion_imprint_panel()
            assert label in window.companion_imprint_status_label.text()
            assert window.companion_imprint_stop_button.isEnabled() is running
            assert window.companion_imprint_save_button.isEnabled() is not running
            assert window.companion_imprint_enable_button.isEnabled() is (status == "connected")
        window.companion_imprint_project_path_input.setText("C:/" + ("very-long-path/" * 40))
        window.refresh_companion_imprint_panel()
        assert window.companion_imprint_error_label.wordWrap()
    finally:
        window.deleteLater()


def test_enabled_companion_imprint_starts_once_and_chat_close_keeps_it_running(tmp_path: Path, monkeypatch) -> None:
    QApplication.instance() or QApplication([])
    workspace = initialize_workspace(tmp_path / ".firefly")
    config = load_config(workspace)
    config["companion_imprint_enabled"] = True
    save_config(config, workspace)
    starts: list[CompanionImprintController] = []
    monkeypatch.setattr(CompanionImprintController, "start", lambda controller: starts.append(controller) or True)
    window = ChatWindow(FireflyRuntime(cwd=tmp_path, workspace=workspace), workspace)
    try:
        QApplication.processEvents()
        assert starts == [window.companion_imprint_controller]
        window.close()
        assert starts == [window.companion_imprint_controller]
    finally:
        window.deleteLater()


def test_managed_sidecar_starts_with_its_panel_available() -> None:
    source = (Path(__file__).resolve().parents[1] / "firefly" / "desktop" / "companion_imprint.py").read_text(
        encoding="utf-8"
    )

    assert '"--headless"' not in source
    assert '"--parent-pid"' in source


def test_desktop_app_shutdowns_companion_imprint_on_application_quit(tmp_path: Path, monkeypatch) -> None:
    import firefly.desktop.app as desktop_app
    import firefly.desktop.chat_window as chat_window_module
    import firefly.desktop.pet_window as pet_window_module
    import firefly.desktop.workers as workers_module
    import firefly.runtime as runtime_module

    class Signal:
        def __init__(self) -> None:
            self.callbacks = []

        def connect(self, callback) -> None:
            self.callbacks.append(callback)

        def emit(self) -> None:
            for callback in self.callbacks:
                callback()

    class Application:
        def __init__(self) -> None:
            self.aboutToQuit = Signal()

        def setApplicationName(self, _name: str) -> None:
            pass

        def setFont(self, _font) -> None:
            pass

        def exec(self) -> int:
            self.aboutToQuit.emit()
            return 0

    class ApplicationFactory:
        @staticmethod
        def instance():
            return application

    class Server:
        def start(self) -> str:
            return "http://127.0.0.1:1/live2d.html"

        def stop(self) -> None:
            pass

    shutdowns = []

    class Chat:
        def __init__(self, _runtime, _workspace) -> None:
            self.companion_imprint_controller = SimpleNamespace(shutdown=lambda: shutdowns.append(True))

        def set_live2d_mood_sender(self, _sender) -> None:
            pass

        def set_approval_surface(self, _surface) -> None:
            pass

        def set_context_snapshotter(self, _snapshotter) -> None:
            pass

        def show_and_raise(self) -> None:
            pass

        def add_upload_files(self, _files) -> None:
            pass

        def any_busy(self) -> bool:
            return False

    class Pet:
        def __init__(self, *_args, **_kwargs) -> None:
            self.speech_bubble = None

        def set_live2d_mood(self, _mood: str) -> None:
            pass

        def show(self) -> None:
            pass

    class Timer:
        def __init__(self, _parent) -> None:
            self.timeout = Signal()

        def start(self, _milliseconds: int) -> None:
            pass

        def stop(self) -> None:
            pass

    class Object:
        def __init__(self, _parent=None) -> None:
            pass

    application = Application()
    monkeypatch.setattr(desktop_app, "QApplication", ApplicationFactory)
    monkeypatch.setattr(desktop_app, "QFont", lambda *_args: object())
    monkeypatch.setattr(desktop_app, "QTimer", Timer)
    monkeypatch.setattr(desktop_app, "QObject", Object)
    monkeypatch.setattr(desktop_app, "Slot", lambda *_args: lambda function: function)
    monkeypatch.setattr(desktop_app, "LocalServer", Server)
    monkeypatch.setattr(desktop_app, "initialize_workspace", lambda _workspace: tmp_path)
    monkeypatch.setattr(desktop_app, "configure_desktop_runtime", lambda: None)
    monkeypatch.setattr(desktop_app, "acquire_desktop_lock", lambda: object())
    monkeypatch.setattr(chat_window_module, "ChatWindow", Chat)
    monkeypatch.setattr(pet_window_module, "PetWindow", Pet)
    monkeypatch.setattr(runtime_module, "FireflyRuntime", lambda **_kwargs: object())
    monkeypatch.setattr(workers_module, "ChatWorker", object)

    assert desktop_app.main(workspace=tmp_path) == 0
    assert shutdowns == [True]
