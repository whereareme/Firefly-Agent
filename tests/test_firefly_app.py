from __future__ import annotations

import os
from pathlib import Path
from tempfile import TemporaryDirectory
import sys
import asyncio
import zipfile
import base64
import json
import tempfile
import threading
from types import SimpleNamespace
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from firefly.autostart import autostart_command, firefly_desktop_command_parts
from firefly.cli import LIVE2D_ROOT
from firefly.context import (
    build_library_context,
    build_permission_context,
    build_skill_context,
    build_upload_context,
    build_web_context,
    firefly_settings_transform,
    iter_library_files,
    library_write_allowed,
    openharness_environment,
    read_file_sample,
    read_text_sample,
    should_search_web,
    skill_registry_summary,
    skills_root,
)
from firefly import desktop_tools as desktop_tools_module
from firefly.desktop_tools import DesktopScreenshotInput, DesktopScreenshotTool, DesktopWindowInput, DesktopWindowTool
from firefly.desktop.chat_rendering import ChatBubble, chat_bubble_colors, format_chat_text, render_chat_html, render_chat_inline
from firefly.desktop.chat_window import ModelSelector, chat_bubble_max_width, conversation_activity_time, conversation_title, format_message_time, local_file_paths_from_mime_data, local_permission_mode_command, remove_temporary_context_snapshot, reply_image_paths, strip_generated_image_notice
from firefly.desktop.music import DEFAULT_STARFIRE_SONG, DEFAULT_STARFIRE_SONG_URL, starfire_music_tracks
from firefly.desktop.settings_panel import SettingsComboBox, SettingsPanelMixin, SlidingToggle, fetch_openai_compatible_models
from firefly.desktop.styles import chat_style_for_mode, chat_viewport_style_for_mode, normalized_theme_mode
from firefly.desktop.workers import ChatWorker, TaskWorker
from firefly.desktop_awareness import DesktopSnapshot, select_snapshot_window, snapshot_prompt
from firefly.library_index import refresh_library_index, search_library_index
from firefly.live2d.module import Live2DModule
from firefly.memory import build_memory_context, extract_memory_lines, is_identity_setting, remember_session_memory, remember_turn, should_store_memory
from firefly.persona import CharacterModule
from firefly.prompts import DEFAULT_PERSONA_PATH
import firefly.runtime as firefly_runtime
from firefly.runtime import (
    FireflyRuntime,
    _history_block,
    _user_message_with_attachments,
    image_generation_followup_prompt,
    image_generation_prompt,
    image_generation_reply,
    generate_firefly_sticker,
    should_direct_image_generation,
)
from firefly.session_storage import load_desktop_conversations, save_desktop_conversations
from firefly.session_storage import NullSessionBackend
from firefly.stickers import DEFAULT_STICKER_EMOTIONS, STICKER_EMOTIONS, extract_sticker_emotion, sticker_prompt, sticker_reply_instruction
from firefly.workspace import initialize_workspace, load_config, workspace_health
from openharness.config.settings import Settings
from openharness.tools.base import ToolResult


def test_firefly_persona_loads() -> None:
    character = CharacterModule(DEFAULT_PERSONA_PATH)

    assert character.persona.name == "流萤"
    assert character.prompt_sections()
    assert "模板化收尾" in character.system_prompt()
    assert "连续对话" in character.system_prompt()
    assert "emoji 可以少量使用" in character.system_prompt()
    assert "流萤是云子" in character.system_prompt()
    assert character.validate_reply("作为一个AI") == ["contains forbidden phrase: 作为一个AI"]


def test_firefly_chat_timestamps_format_for_bubbles_and_conversations() -> None:
    assert format_message_time("2026-07-11T10:24:00+08:00") == "10:24"
    assert conversation_activity_time({"messages": [{"timestamp": "not-a-time"}]}) == ""


def test_firefly_sticker_helpers_parse_model_labels() -> None:
    assert DEFAULT_STICKER_EMOTIONS == ("happy", "shy", "surprised", "worried", "sleepy", "speechless")
    assert set(DEFAULT_STICKER_EMOTIONS) == set(STICKER_EMOTIONS)
    assert extract_sticker_emotion("好的。[[sticker:happy]]") == ("好的。", "happy")
    assert extract_sticker_emotion("普通回复") == ("普通回复", None)
    assert "无文字" in sticker_prompt("shy")
    assert "互动表情规则" in sticker_reply_instruction()


def test_firefly_sticker_generation_reuses_cached_file(tmp_path) -> None:
    workspace = initialize_workspace(tmp_path / ".firefly")
    cached = workspace / "stickers" / "firefly_happy.png"
    cached.parent.mkdir()
    cached.write_bytes(b"png")

    assert generate_firefly_sticker("happy", workspace=workspace) == str(cached)


def test_firefly_task_worker_reports_results_and_errors() -> None:
    results: list[object] = []
    errors: list[str] = []
    successful = TaskWorker(lambda: 42)
    successful.finished.connect(results.append)
    successful.run()

    def fail() -> None:
        raise RuntimeError("offline")

    failed = TaskWorker(fail)
    failed.failed.connect(errors.append)
    failed.run()

    assert results == [42]
    assert errors == ["RuntimeError: offline"]


def test_firefly_model_sync_uses_profile_fallback_on_fetch_error(monkeypatch) -> None:
    def fail_fetch(_base_url: str, _api_key: str) -> list[str]:
        raise RuntimeError("offline")

    monkeypatch.setattr("firefly.desktop.settings_panel.fetch_openai_compatible_models", fail_fetch)

    models, fallback, remote, message = SettingsPanelMixin.fetch_profile_models(
        "https://example.invalid/v1",
        "secret",
        ["fallback-model"],
    )

    assert models == ["fallback-model"]
    assert fallback == ["fallback-model"]
    assert remote is False
    assert "RuntimeError: offline" in message


def test_firefly_chat_model_selector_switches_profile_and_runtime(monkeypatch) -> None:
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication, QComboBox

    app = QApplication.instance() or QApplication([])
    persisted: list[dict[str, object]] = []

    class FakeAuthManager:
        profile = SimpleNamespace(last_model="steady", default_model="steady", allowed_models=["swift"])

        def list_profiles(self):
            return {"demo": self.profile}

        def use_profile(self, profile: str) -> None:
            assert profile == "demo"

        def update_profile(self, profile: str, **changes: object) -> None:
            assert profile == "demo"
            for key, value in changes.items():
                setattr(self.profile, key, value)

    class Host(SettingsPanelMixin):
        def __init__(self) -> None:
            self.config: dict[str, object] = {"provider_profile": "demo", "model": "steady"}
            self.workspace = Path(".")
            self.chat_model_selector = QComboBox()
            self.model_input = QComboBox()
            self.runtime_updates = 0
            self.status = ""

        def selected_profile_name(self) -> str:
            return "demo"

        def current_profile_model(self) -> str:
            return FakeAuthManager.profile.last_model

        def openharness_profile_statuses(self) -> dict[str, object]:
            return {"demo": {"configured": True}}

        def apply_runtime_config(self) -> None:
            self.runtime_updates += 1

        def set_status_text(self, text: str) -> None:
            self.status = text

    monkeypatch.setattr("firefly.desktop.settings_panel.AuthManager", FakeAuthManager)
    monkeypatch.setattr("firefly.desktop.settings_panel.save_config", lambda config, _workspace: persisted.append(dict(config)))
    host = Host()
    try:
        host.refresh_chat_model_selector()

        assert [host.chat_model_selector.itemText(index) for index in range(host.chat_model_selector.count())] == ["steady", "swift"]
        host.select_chat_model("swift")

        assert FakeAuthManager.profile.last_model == "swift"
        assert host.config["model"] == "swift"
        assert host.model_input.currentText() == "swift"
        assert host.runtime_updates == 1
        assert persisted[-1]["model"] == "swift"
        assert host.status == "已切换到 swift"
    finally:
        host.chat_model_selector.deleteLater()
        host.model_input.deleteLater()
        app.processEvents()


def test_model_save_passes_the_resolved_profile_url_to_companion_imprint(monkeypatch) -> None:
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication, QComboBox, QLabel, QLineEdit

    app = QApplication.instance() or QApplication([])

    class FakeAuthManager:
        def use_profile(self, profile: str) -> None:
            assert profile == "demo"

        def update_profile(self, profile: str, **changes: object) -> None:
            assert profile == "demo"
            assert changes["base_url"] is None

    class Controller:
        calls: list[tuple[str, str]] = []

        def provider_changed(self, profile: str, base_url: str) -> None:
            self.calls.append((profile, base_url))

    class Host(SettingsPanelMixin):
        def __init__(self) -> None:
            self.config: dict[str, object] = {"provider_profile": "demo", "model": "steady"}
            self.workspace = Path(".")
            self.model_input = QComboBox()
            self.model_input.addItem("steady")
            self.base_url_input = QLineEdit("")
            self.api_key_input = QLineEdit("")
            self.model_status_label = QLabel()
            self.companion_imprint_controller = Controller()

        def selected_profile_name(self) -> str:
            return "demo"

        def current_image_model_text(self) -> str:
            return ""

        def current_profile_base_url(self) -> str:
            return "https://provider-default.example/v1"

        def apply_runtime_config(self) -> None:
            pass

        def refresh_chat_model_selector(self) -> None:
            pass

        def update_model_connection_state(self) -> None:
            pass

    monkeypatch.setattr("firefly.desktop.settings_panel.AuthManager", FakeAuthManager)
    monkeypatch.setattr("firefly.desktop.settings_panel.save_config", lambda _config, _workspace: None)
    host = Host()
    try:
        host.save_model_settings()

        assert host.companion_imprint_controller.calls == [("demo", "https://provider-default.example/v1")]
    finally:
        for widget in (host.model_input, host.base_url_input, host.api_key_input, host.model_status_label):
            widget.deleteLater()
        app.processEvents()


def test_firefly_light_theme_model_popup_is_not_dark() -> None:
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication

    app = QApplication.instance() or QApplication([])
    selector = ModelSelector()
    selector.addItems(["steady", "swift"])
    selector.setStyleSheet(chat_style_for_mode("light"))
    selector.show()
    selector.showPopup()
    app.processEvents()
    try:
        assert selector.view().viewport().grab().toImage().pixelColor(5, 5).lightness() > 150
        assert "#172520" in selector.view().styleSheet()
        selector.hidePopup()
        selector.setProperty("darkTheme", True)
        selector.showPopup()
        app.processEvents()
        assert "#ecf8f5" in selector.view().styleSheet()
    finally:
        selector.hidePopup()
        selector.deleteLater()
        app.processEvents()


def test_firefly_permission_toggle_draws_a_moving_knob() -> None:
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication

    app = QApplication.instance() or QApplication([])
    toggle = SlidingToggle()
    toggle.setChecked(True)
    toggle.show()
    app.processEvents()
    try:
        image = toggle.grab().toImage()
        assert image.pixelColor(27, 11).lightness() > 220
        assert image.pixelColor(9, 11).green() > image.pixelColor(9, 11).red()
    finally:
        toggle.deleteLater()
        app.processEvents()


def test_firefly_live2d_manifest_is_complete() -> None:
    config = Live2DModule(LIVE2D_ROOT).client_config()

    assert config["enabled"] is True
    assert config["modelName"] == "FileReferences_Moc_0"
    assert config["missingAssets"] == []
    assert config["motionDurations"]["表情组:使一颗心免于哀伤（点击）"] > 200
    assert config["motionSounds"]["表情组:使一颗心免于哀伤（点击）"].endswith(".mp3")
    assert config["motionSoundDelays"]["表情组:使一颗心免于哀伤（点击）"] == 500
    assert "表情组:点燃星海（点击）" not in config["motionSounds"]
    assert "表情组:点燃星海（点击）" not in config["motionSoundDelays"]
    assert config["motionGroups"]["其他组#2"] == ["", ""]
    assert config["motionGroups"]["其他组#3"] == ["", ""]


def test_firefly_live2d_renderer_maps_all_motions() -> None:
    root = Path(__file__).resolve().parents[1]
    renderer = (root / "firefly" / "desktop" / "web" / "live2d_renderer.js").read_text(encoding="utf-8")
    model = json.loads((root / "firefly" / "assets" / "live2d" / "firefly" / "FileReferences_Moc_0.model3.json").read_text(encoding="utf-8"))

    for group, motions in model["FileReferences"]["Motions"].items():
        for motion in motions:
            assert f'"{group}:{motion["Name"]}"' in renderer
    idle_block = renderer.split("function playIdleAction()", 1)[1].split("function scheduleIdleMotion()", 1)[0]
    assert "使一颗心免于哀伤（点击）" not in idle_block
    assert 'playAccessoryMotion("表情组", ["点燃星海（点击）"], "expression00.exp3")' in idle_block
    assert "Math.floor(Math.random() * actions.length)" in idle_block
    assert 'music: { expression: "expression00.exp3", motions: [["表情组", ["使一颗心免于哀伤（点击）"]]], resetMs: 205000 }' in renderer
    assert 'playAccessoryMotion("表情组", ["呆愣（按键）"], "expression9.exp3")' in renderer
    assert 'manager.once("motionFinish", resolve)' in renderer
    assert "motion?.durationMs" in renderer
    assert "new Audio(assetUrl(sound))" in renderer
    assert "window.PIXI.live2d.config.sound = false" in renderer
    assert "30000 + Math.random() * 90000" in renderer
    assert "resetMoodLater.token = null" in renderer


def test_firefly_live2d_menu_has_music_action() -> None:
    text = (Path(__file__).resolve().parents[1] / "firefly" / "desktop" / "pet_window.py").read_text(encoding="utf-8")

    assert "星火旋律" in text
    assert 'self.play_starfire_music("sequence")' in text
    assert 'self.play_starfire_music("random")' in text
    assert 'self.play_starfire_music("previous")' in text
    assert 'self.play_starfire_music("next")' in text
    assert "window.fireAgentLive2D?.music" in text
    assert '"builtin": builtin' in text
    assert 'set_live2d_mood("idle")' in text
    assert "mouseDoubleClickEvent" in text
    assert "doubleClickInterval" in text
    assert "_ignore_release_after_double_click" in text


def test_firefly_live2d_non_music_stops_sound() -> None:
    renderer = (Path(__file__).resolve().parents[1] / "firefly" / "desktop" / "web" / "live2d_renderer.js").read_text(encoding="utf-8")

    assert 'if (nextMood !== "music") stopLive2DSound();' in renderer
    assert 'if (nextMood === "idle") stopLive2DMotion();' in renderer
    assert "manager.stopAllMotions()" in renderer
    assert "live2DAudioToken += 1" in renderer
    assert "if (token !== live2DAudioToken) return;" in renderer
    assert "suppressMotionSoundOnce" in renderer
    assert "suppressMotionSoundOnce = true;" in renderer
    assert "stopLive2DMotion();\n  playMoodAction(\"music\");" in renderer
    assert "if (track.builtin) return true;" not in renderer


def test_firefly_starfire_music_tracks_include_builtin_and_directory() -> None:
    with TemporaryDirectory() as tmp:
        music_dir = Path(tmp) / "music"
        music_dir.mkdir()
        custom = music_dir / "extra.mp3"
        ignored = music_dir / "cover.png"
        custom.write_bytes(b"mp3")
        ignored.write_bytes(b"png")

        tracks = starfire_music_tracks({"starfire_music_dir": str(music_dir)})

        assert DEFAULT_STARFIRE_SONG.name == "FileReferences_Motions_表情组_1_Sound_0.mp3"
        assert DEFAULT_STARFIRE_SONG_URL.startswith("/assets/live2d/")
        assert tracks[0] == DEFAULT_STARFIRE_SONG.resolve()
        assert custom.resolve() in tracks
        assert ignored.resolve() not in tracks


def test_firefly_starfire_music_empty_dir_only_uses_builtin() -> None:
    assert starfire_music_tracks({"starfire_music_dir": ""}) == [DEFAULT_STARFIRE_SONG.resolve()]


def test_firefly_watch_does_not_interrupt_music_mood() -> None:
    root = Path(__file__).resolve().parents[1]
    pet = (root / "firefly" / "desktop" / "pet_window.py").read_text(encoding="utf-8")
    app = (root / "firefly" / "desktop" / "app.py").read_text(encoding="utf-8")

    assert "_music_protected" in pet
    assert "set_live2d_mood_from_watch" in pet
    assert 'self.set_live2d_mood_from_watch("happy")' in pet
    assert 'self.set_live2d_mood_from_watch("sweat")' in pet
    assert 'pet_window.set_live2d_mood_from_watch("sweat")' in app


def test_firefly_watch_bubble_strips_generated_image_notice() -> None:
    pet = (Path(__file__).resolve().parents[1] / "firefly" / "desktop" / "pet_window.py").read_text(encoding="utf-8")

    assert "clean_live2d_reply(reply)" in pet


def test_firefly_watch_bubble_filters_internal_reasoning() -> None:
    from firefly.desktop.pet_window import clean_live2d_reply

    leaked = 'thought The user says: "看看窗口". The image is a screenshot. Let\'s double-check formatting requirements.'

    assert clean_live2d_reply(leaked) == ""
    assert clean_live2d_reply("开拓者在看动画呀。[[sticker:happy]]") == "开拓者在看动画呀。"


def test_firefly_watch_log_records_status_only(tmp_path) -> None:
    from firefly.desktop.app import write_firefly_watch_log

    write_firefly_watch_log(tmp_path, "reply", reply_chars=0, raw={"reply": "hidden"})

    text = (tmp_path / "logs" / "firefly_watch.log").read_text(encoding="utf-8")
    assert '"event": "reply"' in text
    assert '"reply_chars": 0' in text
    assert "hidden" not in text


def test_firefly_temporary_chat_context_snapshot_is_removed(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(tempfile, "tempdir", str(tmp_path))
    snapshot = tmp_path / "chat_context_demo.png"
    snapshot.write_bytes(b"png")

    remove_temporary_context_snapshot(snapshot)

    assert not snapshot.exists()


def test_firefly_watch_reply_avoids_live2d_webengine_js() -> None:
    app = (Path(__file__).resolve().parents[1] / "firefly" / "desktop" / "app.py").read_text(encoding="utf-8")

    assert "pet_window.show_speech(cleaned, 15_000)" in app
    assert '"bubble"' in app
    assert "x=bubble.x()" in app
    assert "main_thread=QThread.currentThread() == app.thread()" in app
    assert "pet_window.show_agent_reply(message, reply, skills)" not in app
    assert 'if prefix != "firefly_watch":' in app
    assert 'chat_window.append_message("assistant", f"萤火巡望：' not in app
    assert "chat_window.persist_conversations()" not in app.split("def show_firefly_watch_reply", 1)[1].split(
        "def show_firefly_watch_error", 1
    )[0]


def test_firefly_watch_ui_updates_use_main_thread_bridge() -> None:
    app = (Path(__file__).resolve().parents[1] / "firefly" / "desktop" / "app.py").read_text(encoding="utf-8")

    assert "class WatchUiBridge(QObject):" in app
    assert "def handle_reply(self, message: str, reply: str, skills: object = None) -> None:" in app
    assert "worker.finished.connect(watch_ui_bridge.handle_reply, Qt.QueuedConnection)" in app
    assert "worker.failed.connect(watch_ui_bridge.handle_error, Qt.QueuedConnection)" in app


def test_firefly_watch_worker_has_hard_timeout() -> None:
    app = (Path(__file__).resolve().parents[1] / "firefly" / "desktop" / "app.py").read_text(encoding="utf-8")

    assert "timeout_firefly_watch" in app
    assert 'write_firefly_watch_log(workspace_root, "timeout")' in app
    assert "finish_firefly_watch_thread" in app
    assert 'write_firefly_watch_log(workspace_root, "dropped")' in app
    assert '"completed_token": 0' in app
    assert "QTimer.singleShot(timeout_ms" in app


def test_firefly_watch_timeout_interrupts_and_rejects_late_results() -> None:
    from firefly.desktop.app import complete_watch_turn, timeout_watch_turn, watch_turn_finished_without_result

    class ThreadStub:
        interrupted = False

        def isRunning(self) -> bool:
            return True

        def requestInterruption(self) -> None:
            self.interrupted = True

    thread = ThreadStub()
    state = {"token": 3, "completed_token": 0, "timed_out": False, "thread": thread}

    assert timeout_watch_turn(state, 2) is False
    assert timeout_watch_turn(state, 3) is True
    assert thread.interrupted is True
    assert complete_watch_turn(state) is False
    assert watch_turn_finished_without_result(state, 3) is False


def test_firefly_live2d_bubble_does_not_hard_truncate() -> None:
    text = (Path(__file__).resolve().parents[1] / "firefly" / "desktop" / "pet_window.py").read_text(encoding="utf-8")

    assert "message[:90]" not in text
    assert "setBubbleWidth" in text
    assert "setTailTarget" in text
    assert "QPainterPath" in text
    assert "_speech_token" in text
    assert "_raise_speech_bubble" in text
    assert "QTimer.singleShot(80, self._raise_speech_bubble)" in text
    assert "Qt.WindowDoesNotAcceptFocus" in text
    assert "resetHeightConstraint" in text
    assert "SetWindowPos" not in text
    assert "HWND_TOPMOST" not in text


def test_firefly_live2d_bubble_resets_height_after_long_reply() -> None:
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication

    from firefly.desktop.pet_window import Live2DSpeechBubble

    app = QApplication.instance() or QApplication([])
    bubble = Live2DSpeechBubble()
    try:
        bubble.setFixedHeight(260)
        bubble.resetHeightConstraint()
        bubble.setText("短句")
        bubble.setBubbleWidth(260)

        assert bubble.minimumHeight() == 0
        assert bubble.height() < 260
    finally:
        bubble.deleteLater()
        app.processEvents()


def test_firefly_asset_attribution_exists() -> None:
    attribution = Path(__file__).resolve().parents[1] / "firefly" / "assets" / "ATTRIBUTION.md"
    text = attribution.read_text(encoding="utf-8")

    assert "Scighost/Firefly" in text
    assert "live2dcubismcore.min.js" in text


def test_firefly_workspace_initializes() -> None:
    with TemporaryDirectory() as tmp:
        workspace = initialize_workspace(Path(tmp) / ".firefly")
        health = workspace_health(workspace)

        assert workspace.name == ".firefly"
        assert all(health.values())
        config = load_config(workspace)
        assert config["llm_base_url"]
        assert config["theme_mode"] == "system"
        assert config["firefly_watch_enabled"] is False
        assert config["chat_window_context_enabled"] is False
        assert config["sticker_interaction_enabled"] is True
        assert config["chat_timeout_sec"] == 300
        assert config["starfire_music_dir"] == ""
        assert config["starfire_music_mode"] == "sequence"


def test_firefly_theme_styles_resolve_modes() -> None:
    dark_style = chat_style_for_mode("dark")
    assert normalized_theme_mode("unknown") == "system"
    assert "#10201d" in dark_style
    assert "QComboBox QAbstractItemView" in dark_style
    assert "QLabel#chatBubbleTextAssistant {\n    color: #10231f;" in dark_style
    assert "QLabel#chatBubbleTextUser {\n    color: #f1fbf8;" in dark_style
    assert chat_viewport_style_for_mode("light") == "background: #fbfffe;"
    assert chat_bubble_colors(is_user=True, dark_theme=True)[0] == "#1f6f68"


def test_firefly_inline_code_uses_text_accent_without_fill() -> None:
    rendered = render_chat_inline("按 `Win + Tab` 打开")

    assert "border-bottom" in rendered
    assert "background:" not in rendered


def test_firefly_plain_chat_text_hides_common_markdown_marks() -> None:
    text = format_chat_text("## 外观\n- **眼睛**：蓝粉渐变\n- 按 `Win + Tab` 打开")

    assert text == "外观\n- 眼睛：蓝粉渐变\n- 按 Win + Tab 打开"


def test_firefly_chat_messages_render_markdown_as_rich_text() -> None:
    text = (Path(__file__).resolve().parents[1] / "firefly" / "desktop" / "chat_window.py").read_text(encoding="utf-8")

    assert "render_chat_html(" in text
    assert "body.setTextFormat(Qt.RichText)" in text
    assert "body.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)" in text
    assert "body.setOpenExternalLinks(True)" in text


def test_firefly_chat_html_preserves_markdown_blocks() -> None:
    rendered = render_chat_html("## 标题\n\n- **重点**\n\n```python\nprint('ok')\n```")

    assert "标题" in rendered
    assert "<b>重点</b>" in rendered
    assert "<pre" in rendered
    assert "print(&#x27;ok&#x27;)" in rendered


def test_firefly_single_line_chat_html_has_no_paragraph_margin() -> None:
    rendered = render_chat_html("哈喽")

    assert "<p" not in rendered
    assert "哈喽" in rendered


def test_firefly_chat_bubbles_scale_with_window_width() -> None:
    assert chat_bubble_max_width(860) == 559
    assert chat_bubble_max_width(1920) == 1248


def test_firefly_conversation_title_stays_single_line() -> None:
    title = conversation_title("哈哈\n\n临场感知：请结合当前窗口内容判断是否需要补充说明。", limit=18)

    assert title == "哈哈"


def test_firefly_model_sync_fetches_openai_compatible_models() -> None:
    seen: dict[str, str | None] = {}

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            seen["path"] = self.path
            seen["auth"] = self.headers.get("Authorization")
            body = json.dumps({"data": [{"id": "gemini-3.1-pro-low"}, {"id": "gpt-5.4"}]}).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *_args: object) -> None:
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        models = fetch_openai_compatible_models(f"http://127.0.0.1:{server.server_port}/v1", "sk-test")
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)

    assert models == ["gemini-3.1-pro-low", "gpt-5.4"]
    assert seen == {"path": "/v1/models", "auth": "Bearer sk-test"}


def test_firefly_desktop_conversations_survive_restart() -> None:
    with TemporaryDirectory() as tmp:
        workspace = initialize_workspace(Path(tmp) / ".firefly")
        conversations = [
            {
                "title": "知更鸟",
                "history": [{"role": "user", "content": "新形态？"}],
                "messages": [{"role": "user", "content": "新形态？"}, {"role": "assistant", "content": "我查一下。"}],
            },
            {"title": "对话 2", "history": [], "messages": []},
        ]

        save_desktop_conversations(workspace, conversations, 1)
        loaded, current_index = load_desktop_conversations(workspace)

        assert current_index == 1
        assert loaded == conversations


def test_firefly_chat_window_opens_saved_conversation() -> None:
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtCore import Qt
    from PySide6.QtWidgets import QApplication, QLabel

    from firefly.desktop.chat_window import ChatWindow
    from firefly.runtime import FireflyRuntime

    app = QApplication.instance() or QApplication([])
    with TemporaryDirectory() as tmp:
        workspace = initialize_workspace(Path(tmp) / ".firefly")
        conversations = [
            {
                "title": "上次对话",
                "history": [],
                "messages": [
                    {"role": "user", "content": "继续这个"},
                    {"role": "status", "content": "本轮使用 Skill: /image_generation"},
                ],
            },
            {"title": "最新对话", "history": [], "messages": [{"role": "user", "content": "不是这个"}]},
        ]
        save_desktop_conversations(workspace, conversations, 0)

        window = ChatWindow(FireflyRuntime(cwd=tmp, workspace=workspace), workspace)
        try:
            assert window.current_conversation_index == 0
            assert window.messages == conversations[0]["messages"]
            assert not window.findChildren(QLabel, "chatStatusMessage")
            assert window.conversation_list.horizontalScrollBarPolicy() == Qt.ScrollBarAlwaysOff
            assert window.main_splitter.count() == 2
            assert window.nav_collapsed is True
            assert window.nav_bar.maximumWidth() == 54
            assert isinstance(window.chat_model_selector, ModelSelector)
            window.toggle_nav_bar()
            app.processEvents()
            assert window.settings_nav_button.geometry().right() < window.nav_bar.contentsRect().right()
            assert window.file_card_widget(str(Path(tmp) / "answer.txt"), is_user=False).findChildren(QLabel, "speakerAvatarAssistant")
            assert window.file_list.columnCount() == 3
            assert all(not button.icon().isNull() for button in window.settings_buttons)
            assert isinstance(window.desktop_control_enabled_check, SlidingToggle)
            assert isinstance(window.theme_mode_input, SettingsComboBox)
            assert isinstance(window.web_search_enabled_check, SlidingToggle)
            assert isinstance(window.memory_enabled_check, SlidingToggle)
            assert isinstance(window.sticker_interaction_enabled_check, SlidingToggle)
            assert isinstance(window.skills_enabled_check, SlidingToggle)
            assert isinstance(window.library_index_check, SlidingToggle)
            window.add_library_location_item("C:/library", read=True, write=False)
            directory_item = window.location_list.topLevelItem(0)
            assert isinstance(window.location_list.itemWidget(directory_item, 1), SlidingToggle)
            assert isinstance(window.location_list.itemWidget(directory_item, 2), SlidingToggle)
            assert [button.objectName() for button in window.permission_mode_buttons.values()] == [
                "permissionModeFirst",
                "permissionModeMiddle",
                "permissionModeLast",
            ]
        finally:
            window.deleteLater()
            app.processEvents()


def test_firefly_assistant_avatar_aligns_with_bubble_tail() -> None:
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication, QLabel

    from firefly.desktop.chat_window import ChatWindow
    from firefly.runtime import FireflyRuntime

    app = QApplication.instance() or QApplication([])
    with TemporaryDirectory() as tmp:
        workspace = initialize_workspace(Path(tmp) / ".firefly")
        window = ChatWindow(FireflyRuntime(cwd=tmp, workspace=workspace), workspace)
        try:
            window.resize(900, 680)
            window.show()
            window.append_message("assistant", "第一行\n第二行\n第三行")
            app.processEvents()
            avatar = window.findChildren(QLabel, "speakerAvatarAssistant")[-1]
            bubble = window.findChildren(ChatBubble)[-1]

            assert avatar.parentWidget() is bubble.parentWidget()
            assert avatar.geometry().bottom() == bubble.geometry().bottom()
        finally:
            window.close()
            window.deleteLater()
            app.processEvents()


def test_firefly_generated_image_stays_inside_assistant_message() -> None:
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication, QLabel

    from firefly.desktop.chat_window import ChatWindow
    from firefly.runtime import FireflyRuntime

    app = QApplication.instance() or QApplication([])
    with TemporaryDirectory() as tmp:
        workspace = initialize_workspace(Path(tmp) / ".firefly")
        image = Path(tmp) / "generated_images" / "image.png"
        image.parent.mkdir()
        image.write_bytes(
            base64.b64decode(
                "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+/p9sAAAAASUVORK5CYII="
            )
        )

        window = ChatWindow(FireflyRuntime(cwd=tmp, workspace=workspace), workspace)
        try:
            window.handle_reply("看看你", f"我正在整理资料。\n生成的图片已保存到 `{image}`。")

            assert [message["role"] for message in window.messages] == ["assistant"]
            assert "我正在整理资料。" in window.messages[0]["content"]
            assert "generated_images" in window.messages[0]["content"]
            assert not [message for message in window.messages if message["role"] == "assistant_file"]
            assert len(window.findChildren(QLabel, "speakerAvatarAssistant")) == 1
        finally:
            window.deleteLater()
            app.processEvents()


def test_firefly_missing_image_card_shows_fallback_label() -> None:
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication, QLabel

    from firefly.desktop.chat_window import ChatWindow
    from firefly.runtime import FireflyRuntime

    app = QApplication.instance() or QApplication([])
    with TemporaryDirectory() as tmp:
        workspace = initialize_workspace(Path(tmp) / ".firefly")
        window = ChatWindow(FireflyRuntime(cwd=tmp, workspace=workspace), workspace)
        try:
            widget = window.file_card_widget(str(Path(tmp) / "missing.png"), is_user=False)

            assert any(label.text() == "图片预览失败" for label in widget.findChildren(QLabel))
        finally:
            window.deleteLater()
            app.processEvents()


def test_firefly_chat_window_clears_stale_worker_thread() -> None:
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtCore import QThread
    from PySide6.QtWidgets import QApplication

    from firefly.desktop.chat_window import ChatWindow
    from firefly.runtime import FireflyRuntime

    app = QApplication.instance() or QApplication([])
    with TemporaryDirectory() as tmp:
        workspace = initialize_workspace(Path(tmp) / ".firefly")
        window = ChatWindow(FireflyRuntime(cwd=tmp, workspace=workspace), workspace)
        try:
            window.thread = QThread(window)
            window.send_button.setEnabled(False)
            window.upload_button.setEnabled(False)

            assert window.busy() is False
            assert window.thread is None
            assert window.send_button.isEnabled()
            assert window.upload_button.isEnabled()
        finally:
            window.deleteLater()
            app.processEvents()


def test_firefly_chat_window_routes_background_reply_to_original_conversation() -> None:
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication

    from firefly.desktop.chat_window import ChatWindow
    from firefly.desktop.workers import ChatWorker
    from firefly.runtime import FireflyRuntime

    app = QApplication.instance() or QApplication([])
    with TemporaryDirectory() as tmp:
        workspace = initialize_workspace(Path(tmp) / ".firefly")
        window = ChatWindow(FireflyRuntime(cwd=tmp, workspace=workspace), workspace)
        try:
            window.conversations.append({"title": "对话 2", "history": [], "messages": []})
            source = window.conversations[0]
            window.load_conversation(1)

            worker = ChatWorker(window.runtime, "第一条", [], [])
            window.worker_conversations[id(worker)] = (id(source), source)
            worker.finished.connect(window.handle_reply)
            worker.finished.emit("第一条", "后台回复", None)

            assert window.current_conversation_index == 1
            assert window.messages == []
            assert source["messages"][0]["role"] == "assistant"
            assert source["messages"][0]["content"] == "后台回复"
            assert source["messages"][0]["timestamp"]
            assert source["history"][-2:] == [
                {"role": "user", "content": "第一条"},
                {"role": "assistant", "content": "后台回复"},
            ]
        finally:
            window.deleteLater()
            app.processEvents()


def test_firefly_chat_window_can_switch_while_other_conversation_is_busy() -> None:
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtCore import QThread
    from PySide6.QtWidgets import QApplication

    from firefly.desktop.chat_window import ChatWindow
    from firefly.runtime import FireflyRuntime

    app = QApplication.instance() or QApplication([])
    with TemporaryDirectory() as tmp:
        workspace = initialize_workspace(Path(tmp) / ".firefly")
        window = ChatWindow(FireflyRuntime(cwd=tmp, workspace=workspace), workspace)
        thread = QThread(window)
        try:
            source_key = id(window.conversations[0])
            thread.start()
            window.thread = thread
            window.active_threads[source_key] = thread

            window.new_conversation()

            assert window.current_conversation_index == 1
            assert window.busy() is False
            assert window.send_button.isEnabled()
            window.switch_conversation(0)
            assert window.busy() is True
            assert not window.send_button.isEnabled()
        finally:
            thread.quit()
            thread.wait(1000)
            window.cleanup_worker(id(window.conversations[0]))
            window.deleteLater()
            app.processEvents()


def test_firefly_chat_window_starts_worker_before_syncing_busy_state() -> None:
    text = (Path(__file__).resolve().parents[1] / "firefly" / "desktop" / "chat_window.py").read_text(encoding="utf-8")
    send_message = text.split("def send_message", 1)[1].split("def handle_local_permission_command", 1)[0]

    assert send_message.index("thread.start()") < send_message.index("self.sync_composer_state()")


def test_firefly_autostart_command_uses_firefly_script(monkeypatch) -> None:
    with TemporaryDirectory() as tmp:
        root = Path(tmp)
        scripts = root / "Scripts"
        scripts.mkdir()
        python = scripts / "python.exe"
        firefly = scripts / "firefly.exe"
        python.write_text("", encoding="utf-8")
        firefly.write_text("", encoding="utf-8")
        monkeypatch.setattr(sys, "executable", str(python))

        command = autostart_command(root / "repo")
        program, arguments = firefly_desktop_command_parts(root / "repo")

        assert str(firefly) in command
        assert "desktop" in command
        assert "--cwd" in command
        assert program == str(firefly)
        assert arguments[:3] == ["desktop", "--cwd", str((root / "repo").resolve())]


def test_firefly_reply_image_paths_resolves_generated_file() -> None:
    with TemporaryDirectory() as tmp:
        root = Path(tmp)
        image = root / "generated_images" / "image.png"
        image.parent.mkdir()
        image.write_bytes(b"png")

        text = f"图片已保存到 `{image.relative_to(root)}`，missing/generated.png 不存在。"

        assert reply_image_paths(text, root) == [image.resolve()]


def test_firefly_strips_generated_image_save_notice() -> None:
    reply = "新的照片我已经重新保存在 generated_images\\image.png 了。\n你看这次的色调更亮。"

    assert strip_generated_image_notice(reply) == "你看这次的色调更亮。"


def test_firefly_strips_only_generated_image_save_notice() -> None:
    reply = "生成的图片已保存到 `D:\\Users\\Admin\\Documents\\Firefly_agent\\firefly_agent(re)\\generated_images\\image.png`。"

    assert strip_generated_image_notice(reply) == ""


def test_firefly_strips_wrapped_generated_image_save_notice() -> None:
    reply = "我已经把照片保存在你电脑里的 generated_images/\nfirefly_knight.png 了。\n接下来继续。"

    assert strip_generated_image_notice(reply) == "接下来继续。"


def test_firefly_upload_mime_data_finds_dragged_files() -> None:
    from PySide6.QtCore import QMimeData, QUrl

    with TemporaryDirectory() as tmp:
        path = Path(tmp) / "note.txt"
        path.write_text("hi", encoding="utf-8")
        mime = QMimeData()
        mime.setUrls([QUrl.fromLocalFile(str(path))])

        assert [Path(item) for item in local_file_paths_from_mime_data(mime)] == [path]

        mime = QMimeData()
        mime.setText(str(path))

        assert [Path(item) for item in local_file_paths_from_mime_data(mime)] == [path]


def test_firefly_desktop_snapshot_prompt_mentions_window_attachment_and_last_reply() -> None:
    prompt = snapshot_prompt(DesktopSnapshot(title="测试窗口", image_path=Path("screen.png")), "临场感知", "上一句")

    assert "测试窗口" in prompt
    assert "screen.png" in prompt
    assert "图片附件" in prompt
    assert "上一句" in prompt
    assert "不要重复" in prompt


def test_firefly_watch_snapshot_prompt_does_not_echo_last_reply() -> None:
    prompt = snapshot_prompt(DesktopSnapshot(title="测试窗口", image_path=Path("screen.png")), "萤火巡望：看一眼", "指纹认证")

    assert "指纹认证" not in prompt
    assert "不要延续上一轮气泡的话题" in prompt


def test_firefly_desktop_snapshot_window_skips_firefly_title(monkeypatch) -> None:
    import firefly.desktop_awareness as awareness

    monkeypatch.setattr(awareness, "foreground_window_handle", lambda: 101)
    monkeypatch.setattr(
        awareness,
        "current_window_title",
        lambda hwnd=None: {101: "Firefly Agent", 202: "Visual Studio Code"}.get(hwnd or 0, ""),
    )
    monkeypatch.setattr(awareness, "next_visible_window_after", lambda hwnd, **kwargs: 202)

    assert select_snapshot_window(excluded_title_parts=("Firefly Agent",)) == 202


def test_firefly_desktop_snapshot_window_skips_own_process(monkeypatch) -> None:
    import firefly.desktop_awareness as awareness

    monkeypatch.setattr(awareness.os, "getpid", lambda: 1234)
    monkeypatch.setattr(awareness, "foreground_window_handle", lambda: 101)
    monkeypatch.setattr(awareness, "current_window_title", lambda hwnd=None: "Firefly" if hwnd == 101 else "Editor")
    monkeypatch.setattr(awareness, "window_process_id", lambda hwnd: 1234 if hwnd == 101 else 9876)
    monkeypatch.setattr(awareness, "next_visible_window_after", lambda hwnd, **kwargs: 202)

    assert select_snapshot_window(exclude_own_process=True) == 202


def test_firefly_desktop_snapshot_window_skips_text_input_host(monkeypatch) -> None:
    import firefly.desktop_awareness as awareness

    monkeypatch.setattr(awareness, "foreground_window_handle", lambda: 101)
    monkeypatch.setattr(awareness, "current_window_title", lambda hwnd=None: "使用指纹，以更快速和更安全的方式登录")
    monkeypatch.setattr(awareness, "window_is_capturable", lambda hwnd: True)
    monkeypatch.setattr(awareness, "window_process_name", lambda hwnd: "textinputhost.exe" if hwnd == 101 else "explorer.exe")
    monkeypatch.setattr(awareness, "next_visible_window_after", lambda hwnd, **kwargs: 202)

    assert select_snapshot_window() == 202


def test_firefly_desktop_snapshot_window_skips_tiny_foreground(monkeypatch) -> None:
    import firefly.desktop_awareness as awareness

    monkeypatch.setattr(awareness, "foreground_window_handle", lambda: 101)
    monkeypatch.setattr(awareness, "current_window_title", lambda hwnd=None: "Tiny")
    monkeypatch.setattr(awareness, "window_rect", lambda hwnd: (0, 0, 16, 16) if hwnd == 101 else (0, 0, 800, 600))
    monkeypatch.setattr(awareness, "window_is_visible", lambda hwnd: True)
    monkeypatch.setattr(awareness, "next_visible_window_after", lambda hwnd, **kwargs: 202)

    assert select_snapshot_window() == 202


def test_firefly_desktop_snapshot_empty_window_does_not_capture_screen(monkeypatch, tmp_path) -> None:
    import firefly.desktop_awareness as awareness

    monkeypatch.setattr(awareness, "select_snapshot_window", lambda **kwargs: 0)

    snapshot = awareness.capture_desktop_snapshot(tmp_path)

    assert snapshot.hwnd == 0
    assert snapshot.title == ""
    assert snapshot.image_path is None


def test_firefly_watch_snapshot_path_is_temporary(tmp_path) -> None:
    import tempfile
    import firefly.desktop_awareness as awareness

    temp_path = awareness._snapshot_image_path(tmp_path, "firefly_watch", persist=False)

    assert temp_path.parent == Path(tempfile.gettempdir())
    assert temp_path.name.startswith("firefly_watch_")
    assert not (tmp_path / "screenshots").exists()


def test_firefly_watch_worker_deletes_temp_snapshot() -> None:
    app = (Path(__file__).resolve().parents[1] / "firefly" / "desktop" / "app.py").read_text(encoding="utf-8")

    assert "worker.finished.connect(lambda _message, _reply, _skills, path=watch_snapshot_path: remove_firefly_watch_snapshot(path))" in app
    assert "worker.failed.connect(lambda _error, path=watch_snapshot_path: remove_firefly_watch_snapshot(path))" in app
    assert 'watch_state["last"] = time.monotonic()' in app
    assert 'worker.finished.connect(lambda _message, _reply, _skills, token=token: cleanup_watch_worker(token))' in app
    assert 'if token is not None and token != watch_state.get("token"):' in app


def test_firefly_chat_context_uses_explicit_screen_capture_path() -> None:
    root = Path(__file__).resolve().parents[1]
    app = (root / "firefly" / "desktop" / "app.py").read_text(encoding="utf-8")
    chat = (root / "firefly" / "desktop" / "chat_window.py").read_text(encoding="utf-8")
    awareness = (root / "firefly" / "desktop_awareness.py").read_text(encoding="utf-8")

    assert 'full_screen = prefix == "chat_context"' in app
    assert "full_screen=full_screen" in app
    assert "if snapshot.image_path is not None" in chat
    assert "不要声称看到了窗口、图片或界面" in chat
    assert "full_screen: bool = False" in awareness


def test_firefly_desktop_snapshot_excludes_codex_title() -> None:
    import firefly.desktop_awareness as awareness

    assert awareness.title_matches_any("Codex - Firefly_agent", awareness.FIREFLY_WINDOW_TITLE_PARTS)


def test_firefly_desktop_snapshot_detects_black_pixmap() -> None:
    import firefly.desktop_awareness as awareness

    class Color:
        def alpha(self) -> int:
            return 255

        def red(self) -> int:
            return 0

        def green(self) -> int:
            return 0

        def blue(self) -> int:
            return 0

    class Image:
        def width(self) -> int:
            return 80

        def height(self) -> int:
            return 80

        def pixelColor(self, _x: int, _y: int) -> Color:
            return Color()

    class Pixmap:
        def isNull(self) -> bool:
            return False

        def toImage(self) -> Image:
            return Image()

    assert awareness.pixmap_is_mostly_black(Pixmap())


def test_firefly_openharness_memory_roundtrip() -> None:
    with TemporaryDirectory() as tmp:
        root = Path(tmp)
        old_data_dir = os.environ.get("OPENHARNESS_DATA_DIR")
        os.environ["OPENHARNESS_DATA_DIR"] = str(root / "openharness-data")
        try:
            workspace = initialize_workspace(root / ".firefly")
            config = {
                "memory_enabled": True,
                "everos_memory_enabled": False,
                "openharness_memdir_enabled": True,
                "openharness_session_memory_enabled": True,
                "openharness_memory_cwd": str(root),
                "openharness_session_id": "test-session",
            }

            remember_turn("请记住我喜欢蛋炒饭", "我记住了。", config, workspace, root)
            context = build_memory_context("我喜欢什么？", [], config, workspace, root)

            assert "蛋炒饭" in context
            assert "OpenHarness session memory" in context
        finally:
            if old_data_dir is None:
                os.environ.pop("OPENHARNESS_DATA_DIR", None)
            else:
                os.environ["OPENHARNESS_DATA_DIR"] = old_data_dir


def test_firefly_memory_stores_short_identity_settings() -> None:
    assert is_identity_setting("流萤是云子")
    assert is_identity_setting("以后叫你云子")
    assert should_store_memory("流萤是云子")
    assert extract_memory_lines("流萤是云子") == ["流萤是云子"]
    assert not is_identity_setting("流萤是云子吗？")


def test_firefly_watch_worker_can_skip_memory_write() -> None:
    class FakeRuntime:
        remember = None
        use_memory_context = None

        def chat(self, _message, _history, _attachments, remember=True, use_memory_context=True, **_kwargs):
            self.remember = remember
            self.use_memory_context = use_memory_context
            return firefly_runtime.FireflyResponse(text="巡望一句话")

    runtime = FakeRuntime()
    worker = ChatWorker(runtime, "巡望", [], remember=False, use_memory_context=False)  # type: ignore[arg-type]
    worker.run()

    assert runtime.remember is False
    assert runtime.use_memory_context is False


def test_firefly_runtime_can_skip_memory_context(monkeypatch, tmp_path) -> None:
    calls: list[str] = []

    def fake_build_memory_context(*_args, **_kwargs):
        calls.append("memory")
        return "旧记忆"

    async def fake_build_openharness_context(_prompt, _config, _workspace, _cwd):
        return ""

    async def fake_build_runtime(**_kwargs):
        return SimpleNamespace(engine=SimpleNamespace(tool_metadata={}, model="test"))

    async def fake_handle_line(*_args, **_kwargs):
        return True

    async def fake_noop(_bundle):
        return None

    monkeypatch.setattr(firefly_runtime, "build_memory_context", fake_build_memory_context)
    monkeypatch.setattr(firefly_runtime, "build_openharness_context", fake_build_openharness_context)
    monkeypatch.setattr(firefly_runtime, "build_runtime", fake_build_runtime)
    monkeypatch.setattr(firefly_runtime, "handle_line", fake_handle_line)
    monkeypatch.setattr(firefly_runtime, "start_runtime", fake_noop)
    monkeypatch.setattr(firefly_runtime, "close_runtime", fake_noop)

    asyncio.run(
        firefly_runtime.run_firefly_prompt(
            prompt="萤火巡望",
            workspace=tmp_path,
            cwd=tmp_path,
            use_memory_context=False,
        )
    )

    assert calls == []


def test_firefly_runtime_disables_image_tool_without_image_intent(monkeypatch, tmp_path) -> None:
    captured = {}

    async def fake_build_openharness_context(_prompt, _config, _workspace, _cwd):
        return ""

    async def fake_build_runtime(**kwargs):
        settings = kwargs["settings_transform"](Settings())
        captured["allowed_tools"] = settings.permission.allowed_tools
        return SimpleNamespace(engine=SimpleNamespace(tool_metadata={}, model="test"))

    async def fake_handle_line(*_args, **_kwargs):
        return True

    async def fake_noop(_bundle):
        return None

    monkeypatch.setattr(firefly_runtime, "build_openharness_context", fake_build_openharness_context)
    monkeypatch.setattr(firefly_runtime, "build_runtime", fake_build_runtime)
    monkeypatch.setattr(firefly_runtime, "handle_line", fake_handle_line)
    monkeypatch.setattr(firefly_runtime, "start_runtime", fake_noop)
    monkeypatch.setattr(firefly_runtime, "close_runtime", fake_noop)

    asyncio.run(firefly_runtime.run_firefly_prompt(prompt="哈喽，流萤", workspace=tmp_path, cwd=tmp_path))

    assert "image_generation" not in captured["allowed_tools"]


def test_firefly_runtime_uses_desktop_approval_prompts(monkeypatch, tmp_path) -> None:
    captured = {}
    permission_calls = []
    edit_calls = []

    async def fake_build_openharness_context(_prompt, _config, _workspace, _cwd):
        return ""

    async def fake_build_runtime(**kwargs):
        captured["permission_prompt"] = kwargs["permission_prompt"]
        captured["edit_approval_prompt"] = kwargs["edit_approval_prompt"]
        return SimpleNamespace(engine=SimpleNamespace(tool_metadata={}, model="test"))

    async def fake_handle_line(*_args, **_kwargs):
        return True

    async def fake_noop(_bundle):
        return None

    def permission_prompt(tool_name, reason):
        permission_calls.append((tool_name, reason))
        return True

    def edit_approval_prompt(path, diff, added, removed):
        edit_calls.append((path, diff, added, removed))
        return "approve"

    monkeypatch.setattr(firefly_runtime, "build_openharness_context", fake_build_openharness_context)
    monkeypatch.setattr(firefly_runtime, "build_runtime", fake_build_runtime)
    monkeypatch.setattr(firefly_runtime, "handle_line", fake_handle_line)
    monkeypatch.setattr(firefly_runtime, "start_runtime", fake_noop)
    monkeypatch.setattr(firefly_runtime, "close_runtime", fake_noop)

    asyncio.run(
        firefly_runtime.run_firefly_prompt(
            prompt="整理文件",
            workspace=tmp_path,
            cwd=tmp_path,
            permission_prompt=permission_prompt,
            edit_approval_prompt=edit_approval_prompt,
        )
    )

    assert asyncio.run(captured["permission_prompt"]("write_file", "confirm")) is True
    assert permission_calls == []
    assert asyncio.run(captured["permission_prompt"]("bash", "confirm")) is True
    assert permission_calls == [("bash", "confirm")]
    assert asyncio.run(captured["edit_approval_prompt"](str(tmp_path / "note.txt"), "diff", 1, 0)) == "approve"
    assert edit_calls[-1][0].endswith("note.txt")
    assert asyncio.run(captured["edit_approval_prompt"](str(tmp_path.parent / "outside.txt"), "diff", 1, 0)) == "reject"


def test_firefly_remember_false_disables_openharness_persistence(monkeypatch, tmp_path) -> None:
    captured = {}

    async def fake_build_openharness_context(_prompt, _config, _workspace, _cwd):
        return ""

    async def fake_build_runtime(**kwargs):
        settings = kwargs["settings_transform"](Settings())
        captured["session_backend"] = kwargs["session_backend"]
        captured["memory_enabled"] = settings.memory.enabled
        captured["session_memory_enabled"] = settings.memory.session_memory_enabled
        captured["auto_extract_enabled"] = settings.memory.auto_extract_enabled
        return SimpleNamespace(engine=SimpleNamespace(tool_metadata={}, model="test"))

    async def fake_handle_line(*_args, **_kwargs):
        return True

    async def fake_noop(_bundle):
        return None

    monkeypatch.setattr(firefly_runtime, "build_openharness_context", fake_build_openharness_context)
    monkeypatch.setattr(firefly_runtime, "build_runtime", fake_build_runtime)
    monkeypatch.setattr(firefly_runtime, "handle_line", fake_handle_line)
    monkeypatch.setattr(firefly_runtime, "start_runtime", fake_noop)
    monkeypatch.setattr(firefly_runtime, "close_runtime", fake_noop)

    asyncio.run(firefly_runtime.run_firefly_prompt(prompt="萤火巡望", workspace=tmp_path, cwd=tmp_path, remember=False))

    assert isinstance(captured["session_backend"], NullSessionBackend)
    assert captured["memory_enabled"] is False
    assert captured["session_memory_enabled"] is False
    assert captured["auto_extract_enabled"] is False


def test_firefly_memory_context_prefers_everos_over_session(monkeypatch) -> None:
    class FakeEverOSClient:
        def search_context(self, prompt: str) -> str:
            return f"EverOS hit: {prompt}"

    with TemporaryDirectory() as tmp:
        root = Path(tmp)
        workspace = initialize_workspace(root / ".firefly")
        config = {
            "memory_enabled": True,
            "everos_memory_enabled": True,
            "openharness_session_memory_enabled": True,
            "openharness_memory_cwd": str(root),
            "openharness_session_id": "test-session",
        }
        remember_session_memory("session prompt", "session reply", config, workspace, root)
        monkeypatch.setattr("firefly.memory.create_everos_client", lambda _config, _workspace: FakeEverOSClient())

        context = build_memory_context("查记忆", [], config, workspace, root)

        assert context == "EverOS hit: 查记忆"
        assert "OpenHarness session memory" not in context


def test_firefly_library_context_reads_allowed_directory() -> None:
    with TemporaryDirectory() as tmp:
        root = Path(tmp)
        workspace = initialize_workspace(root / ".firefly")
        docs = root / "docs"
        docs.mkdir()
        (docs / "note.md").write_text("萤火计划需要先接 OpenHarness 资料舱。", encoding="utf-8")

        config = {"library_locations": [str(docs)], "library_allow_read": True}
        context = build_library_context("萤火计划", config, workspace)

        assert "资料舱上下文" in context
        assert "萤火计划" in context

        disabled = build_library_context("萤火计划", {**config, "library_allow_read": False}, workspace)
        assert disabled == ""


def test_firefly_library_index_refresh_search_and_delete() -> None:
    with TemporaryDirectory() as tmp:
        root = Path(tmp)
        workspace = initialize_workspace(root / ".firefly")
        docs = root / "docs"
        docs.mkdir()
        note = docs / "note.md"
        note.write_text("萤火计划需要本地全文索引。", encoding="utf-8")
        docx = docs / "report.docx"
        with zipfile.ZipFile(docx, "w") as archive:
            archive.writestr(
                "word/document.xml",
                "<w:document xmlns:w='http://schemas.openxmlformats.org/wordprocessingml/2006/main'>"
                "<w:body><w:p><w:r><w:t>索引里的 Word 内容</w:t></w:r></w:p></w:body></w:document>",
            )
        config = {"library_locations": [str(docs)], "library_allow_read": True, "library_index_enabled": True}

        summary = refresh_library_index(config, workspace)
        context = search_library_index("萤火计划 Word", config, workspace)

        assert summary["files"] == 2
        assert "萤火计划" in context
        assert "Word 内容" in context

        docx.unlink()
        summary = refresh_library_index(config, workspace)

        assert summary["files"] == 1
        assert summary["removed"] == 1


def test_firefly_library_scan_honors_file_count_limits() -> None:
    with TemporaryDirectory() as tmp:
        root = Path(tmp)
        workspace = initialize_workspace(root / ".firefly")
        docs = root / "docs"
        docs.mkdir()
        for index in range(120):
            (docs / f"note-{index}.md").write_text(f"文件 {index}", encoding="utf-8")
        config = {
            "library_locations": [str(docs)],
            "library_allow_read": True,
            "library_max_scan_files": 100,
            "library_index_max_files": 100,
        }

        scanned = list(iter_library_files(config, workspace))
        summary = refresh_library_index(config, workspace)

        assert len(scanned) == 100
        assert summary["files"] == 100


def test_firefly_library_write_allowlist() -> None:
    with TemporaryDirectory() as tmp:
        root = Path(tmp)
        workspace = initialize_workspace(root / ".firefly")
        docs = root / "docs"
        docs.mkdir()
        config = {
            "library_locations": [str(docs)],
            "library_allow_read": True,
            "library_allow_write": True,
        }

        assert library_write_allowed(docs / "note.md", config, workspace)
        assert not library_write_allowed(root / "outside.md", config, workspace)
        assert not library_write_allowed(docs / "note.md", {**config, "library_allow_write": False}, workspace)
        assert not library_write_allowed(
            docs / "note.md",
            {**config, "library_locations": [{"path": str(docs), "read": True, "write": False}]},
            workspace,
        )
        permission_context = build_permission_context(config, workspace)

        assert "Firefly library write allowlist" in permission_context
        assert str(docs.resolve()) in permission_context
        assert "local confirmation dialog" in permission_context


def test_firefly_local_permission_mode_command_parses_shortcuts() -> None:
    assert local_permission_mode_command("full_auto") == "full_auto"
    assert local_permission_mode_command("/permissions full_auto") == "full_auto"
    assert local_permission_mode_command("/permissions set default") == "default"
    assert local_permission_mode_command("继续") is None


def test_firefly_settings_transform_injects_permissions_and_sandbox() -> None:
    with TemporaryDirectory() as tmp:
        root = Path(tmp)
        workspace = initialize_workspace(root / ".firefly")
        docs = root / "docs"
        docs.mkdir()
        config = {
            "library_locations": [str(docs)],
            "library_allow_read": True,
            "library_allow_write": True,
            "chat_timeout_sec": 45,
            "sandbox_enabled": True,
            "sandbox_backend": "docker",
            "sandbox_fail_if_unavailable": True,
        }

        settings = firefly_settings_transform(config, workspace, root)(Settings())

        patterns = [rule.pattern for rule in settings.permission.path_rules]
        assert str(docs.resolve()) in patterns
        assert "image_generation" in settings.permission.allowed_tools
        assert str(docs.resolve()) in settings.sandbox.filesystem.allow_read
        assert str(docs.resolve()) in settings.sandbox.filesystem.allow_write
        assert settings.sandbox.enabled is True
        assert settings.sandbox.backend == "docker"
        assert settings.sandbox.fail_if_unavailable is True
        assert settings.timeout == 45


def test_firefly_settings_transform_uses_profile_image_model() -> None:
    settings = Settings(
        active_profile="openai-compatible",
        profiles={
            "openai-compatible": {
                "label": "OpenAI-Compatible API",
                "provider": "openai",
                "api_format": "openai",
                "auth_source": "openai_api_key",
                "default_model": "gemini-3.1-pro-low",
                "base_url": "http://127.0.0.1:8317/v1",
                "allowed_models": ["gemini-3.1-pro-low", "gemini-3.1-flash-image"],
            }
        },
    )

    updated = firefly_settings_transform(
        {"provider_profile": "openai-compatible", "model": "gemini-3.1-pro-low", "llm_api_key": "sk-test"},
        Path.cwd(),
    )(settings)

    assert updated.image_generation.provider == "openai"
    assert updated.image_generation.model == "gemini-3.1-flash-image"
    assert updated.image_generation.base_url == "http://127.0.0.1:8317/v1"
    assert updated.vision.model == "gemini-3.1-pro-low"
    assert updated.vision.api_key == "sk-test"
    assert updated.vision.base_url == "http://127.0.0.1:8317/v1"


def test_firefly_upload_context_reads_pending_file() -> None:
    with TemporaryDirectory() as tmp:
        path = Path(tmp) / "upload.md"
        path.write_text("这是本轮上传文件内容。", encoding="utf-8")

        context = build_upload_context([str(path)])

        assert "上传文件上下文" in context
        assert "upload.md" in context
        assert "本轮上传文件内容" in context


def test_firefly_image_upload_becomes_openharness_image_block() -> None:
    with TemporaryDirectory() as tmp:
        image = Path(tmp) / "upload.png"
        image.write_bytes(base64.b64decode("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+/p9sAAAAASUVORK5CYII="))

        message = _user_message_with_attachments("看图", [str(image)])
        context = build_upload_context([str(image)])

        assert len(message.content) == 2
        assert message.content[1].type == "image"
        assert "OpenHarness 图像附件" in context


def test_firefly_direct_image_generation_detector_avoids_help_questions() -> None:
    assert should_direct_image_generation("请生成一张图片")
    assert should_direct_image_generation("画一张流萤头像")
    assert not should_direct_image_generation("哈喽，流萤")
    assert not should_direct_image_generation("怎样能让她生成图片")
    assert not should_direct_image_generation("萤火巡望：你正在看用户当前窗口。如果画面没有新变化，就不要硬找话题。")


def test_firefly_direct_image_generation_reply_answers_question_text() -> None:
    assert image_generation_reply("流萤我想看看你现在在干嘛（生成一张图片）") == "给你看我现在在做什么。"
    assert image_generation_reply("流萤这么晚在干嘛（生成一张图片）") == "我在灯下整理今晚的想法，也把这一刻画给你看。"
    assert image_generation_reply("请生成一张图片") == ""


def test_firefly_self_image_prompt_anchors_identity() -> None:
    prompt = image_generation_prompt("我想看你（生成一张图片）")

    assert "画面主体是流萤本人" in prompt
    assert "不是猫" in prompt
    assert "脸型与眼睛瞳孔特征" in prompt


def test_firefly_implicit_self_image_prompt_anchors_identity() -> None:
    prompt = image_generation_prompt("睡觉穿这么多衣服干嘛（生成一张图片）")

    assert "画面主体是流萤本人" in prompt
    assert "不是猫" in prompt


def test_firefly_image_generation_uses_conversation_history_for_self_reference() -> None:
    history = [{"role": "user", "content": "流萤我想看看你现在在干嘛（生成一张图片）"}]
    prompt = image_generation_prompt("睡觉穿这么多衣服干嘛（生成一张图片）", history)

    assert "## Previous Conversation" in prompt
    assert "流萤我想看看你现在在干嘛" in prompt
    assert "画面主体是流萤本人" in prompt


def test_firefly_non_self_image_prompt_stays_plain() -> None:
    assert image_generation_prompt("请生成一张图片") == "请生成一张图片"
    assert image_generation_prompt("画一张睡觉的猫") == "画一张睡觉的猫"
    history = [{"role": "user", "content": "流萤我想看看你现在在干嘛（生成一张图片）"}]
    assert image_generation_prompt("画一张睡觉的猫", history) == "画一张睡觉的猫"


def test_firefly_image_followup_does_not_identify_as_animal() -> None:
    history = [{"role": "user", "content": "流萤我想看看你现在在干嘛（生成一张图片）"}]
    prompt = image_generation_followup_prompt("睡觉穿这么多衣服干嘛（生成一张图片）", history)

    assert "不要把附件里的动物当成“我”" in prompt
    assert "画面主体不像流萤本人" in prompt
    assert "当前对话上下文" in prompt


def test_firefly_direct_image_generation_uses_tool_without_chat_planning(monkeypatch) -> None:
    seen: dict[str, object] = {}

    async def fake_execute(self, arguments, context):
        del self, context
        output = Path(arguments.output_path)
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_bytes(b"png")
        seen["prompt"] = arguments.prompt
        seen["image_paths"] = arguments.image_paths
        seen["quality"] = arguments.quality
        seen["input_fidelity"] = arguments.input_fidelity
        return ToolResult("ok", metadata={"paths": [str(output)]})

    async def fake_followup(**kwargs):
        seen["followup_prompt"] = kwargs["prompt"]
        seen["followup_attachments"] = kwargs["attachments"]
        return firefly_runtime.FireflyResponse(text="这是一张测试图。")

    monkeypatch.setattr(firefly_runtime.ImageGenerationTool, "execute", fake_execute)
    monkeypatch.setattr(firefly_runtime, "run_firefly_prompt", fake_followup)
    with TemporaryDirectory() as tmp:
        runtime = FireflyRuntime(cwd=tmp, workspace=Path(tmp) / ".firefly")
        response = runtime.chat("请生成一张图片\n\n临场感知：这段不该进入生图提示")

        assert response.errors == []
        assert response.invoked_skills == ["image_generation"]
        assert seen["prompt"] == "请生成一张图片"
        assert seen["image_paths"] == []
        assert "请先看这张图片" in str(seen["followup_prompt"])
        assert seen["followup_attachments"]
        assert reply_image_paths(response.text, Path(tmp))
        assert strip_generated_image_notice(response.text) == "这是一张测试图。"


def test_firefly_direct_image_generation_uses_bundled_face_reference(monkeypatch) -> None:
    seen: dict[str, object] = {}

    async def fake_execute(self, arguments, context):
        del self, context
        output = Path(arguments.output_path)
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_bytes(b"png")
        seen["prompt"] = arguments.prompt
        seen["image_paths"] = arguments.image_paths
        return ToolResult("ok", metadata={"paths": [str(output)]})

    async def fake_followup(**_kwargs):
        return firefly_runtime.FireflyResponse(text="给你看。")

    monkeypatch.setattr(firefly_runtime.ImageGenerationTool, "execute", fake_execute)
    monkeypatch.setattr(firefly_runtime, "run_firefly_prompt", fake_followup)
    with TemporaryDirectory() as tmp:
        user_image = Path(tmp) / "pose.png"
        user_image.write_bytes(b"png")
        response = FireflyRuntime(cwd=tmp, workspace=Path(tmp) / ".firefly").chat(
            "画一张流萤在窗边看书",
            attachments=[str(user_image)],
        )

        assert "青蓝至蓝紫" in str(seen["prompt"])
        assert "只用于锁定流萤的脸型和眼睛瞳孔特征" in str(seen["prompt"])
        assert "不约束服装、发型、发饰、画风、姿势或场景" in str(seen["prompt"])
        assert "横向偏长、略呈水滴形而非大圆眼" in str(seen["prompt"])
        assert "玫红或洋红色竖椭圆" in str(seen["prompt"])
        assert seen["image_paths"] == [
            str(firefly_runtime.FIREFLY_FACE_REFERENCE_IMAGE),
            str(user_image),
        ]
        assert response.invoked_skills == ["image_generation", "firefly-face-reference"]


def test_firefly_direct_image_generation_uses_reference_for_pure_openai_generation(monkeypatch) -> None:
    seen: dict[str, object] = {}

    async def fake_execute(self, arguments, context):
        del self, context
        output = Path(arguments.output_path)
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_bytes(b"png")
        seen["prompt"] = arguments.prompt
        seen["image_paths"] = arguments.image_paths
        seen["quality"] = arguments.quality
        seen["input_fidelity"] = arguments.input_fidelity
        return ToolResult("ok", metadata={"paths": [str(output)]})

    async def fake_followup(**_kwargs):
        return firefly_runtime.FireflyResponse(text="给你看。")

    monkeypatch.setattr(firefly_runtime.ImageGenerationTool, "execute", fake_execute)
    monkeypatch.setattr(firefly_runtime, "run_firefly_prompt", fake_followup)
    monkeypatch.setattr(
        firefly_runtime,
        "_resolve_image_generation_config",
        lambda _settings: {"provider": "openai", "model": "gpt-image-2"},
    )
    with TemporaryDirectory() as tmp:
        response = FireflyRuntime(cwd=tmp, workspace=Path(tmp) / ".firefly").chat("画一张流萤在窗边看书")

        assert "青蓝至蓝紫" in str(seen["prompt"])
        assert seen["image_paths"] == [str(firefly_runtime.FIREFLY_FACE_REFERENCE_IMAGE)]
        assert seen["quality"] == "high"
        assert seen["input_fidelity"] == "high"
        assert response.invoked_skills == ["image_generation", "firefly-face-reference"]


def test_firefly_direct_image_generation_keeps_identity_when_reference_is_missing(monkeypatch) -> None:
    seen: dict[str, object] = {}

    async def fake_execute(self, arguments, context):
        del self, context
        output = Path(arguments.output_path)
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_bytes(b"png")
        seen["prompt"] = arguments.prompt
        seen["image_paths"] = arguments.image_paths
        return ToolResult("ok", metadata={"paths": [str(output)]})

    async def fake_followup(**_kwargs):
        return firefly_runtime.FireflyResponse(text="给你看。")

    monkeypatch.setattr(firefly_runtime.ImageGenerationTool, "execute", fake_execute)
    monkeypatch.setattr(firefly_runtime, "run_firefly_prompt", fake_followup)
    with TemporaryDirectory() as tmp:
        user_image = Path(tmp) / "pose.png"
        user_image.write_bytes(b"png")
        monkeypatch.setattr(firefly_runtime, "FIREFLY_FACE_REFERENCE_IMAGE", Path(tmp) / "missing.png")
        response = FireflyRuntime(cwd=tmp, workspace=Path(tmp) / ".firefly").chat(
            "画一张流萤在窗边看书",
            attachments=[str(user_image)],
        )

        assert "脸部为偏短的柔和鹅蛋脸" in str(seen["prompt"])
        assert seen["image_paths"] == [str(user_image)]
        assert response.invoked_skills == ["image_generation", "firefly-face-reference"]


def test_firefly_direct_image_generation_retries_safe_prompt_after_moderation(monkeypatch) -> None:
    prompts: list[str] = []
    image_paths: list[list[str]] = []

    async def fake_execute(self, arguments, context):
        del self, context
        prompts.append(arguments.prompt)
        image_paths.append(arguments.image_paths)
        if len(prompts) == 1:
            return ToolResult("image_generation failed: moderation_blocked sexual safety system", is_error=True)
        output = Path(arguments.output_path)
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_bytes(b"png")
        return ToolResult("ok", metadata={"paths": [str(output)]})

    async def fake_followup(**_kwargs):
        return firefly_runtime.FireflyResponse(text="我换成了更日常的版本。")

    monkeypatch.setattr(firefly_runtime.ImageGenerationTool, "execute", fake_execute)
    monkeypatch.setattr(firefly_runtime, "run_firefly_prompt", fake_followup)
    with TemporaryDirectory() as tmp:
        response = FireflyRuntime(cwd=tmp, workspace=Path(tmp) / ".firefly").chat(
            "我能再看看这样穿着的流萤吗（生成一张图片）"
        )

        assert response.errors == []
        assert response.invoked_skills == ["image_generation", "firefly-face-reference"]
        assert len(prompts) == 2
        assert "完整、保守" in prompts[1]
        assert "不要裸露" in prompts[1]
        assert image_paths == [[str(firefly_runtime.FIREFLY_FACE_REFERENCE_IMAGE)]] * 2
        assert strip_generated_image_notice(response.text) == "我换成了更日常的版本。"


def test_firefly_direct_image_generation_moderation_falls_back_to_text(monkeypatch) -> None:
    async def fake_execute(self, arguments, context):
        del self, arguments, context
        return ToolResult("image_generation failed: moderation_blocked sexual safety system", is_error=True)

    monkeypatch.setattr(firefly_runtime.ImageGenerationTool, "execute", fake_execute)
    with TemporaryDirectory() as tmp:
        response = FireflyRuntime(cwd=tmp, workspace=Path(tmp) / ".firefly").chat(
            "我能再看看这样穿着的流萤吗（生成一张图片）"
        )

        assert response.errors == []
        assert "安全审核" in response.text
        assert "可以把描述" in response.text
        assert "完整、保守" in response.text


def test_firefly_direct_image_generation_keeps_conversation_context(monkeypatch) -> None:
    seen: dict[str, object] = {}

    async def fake_execute(self, arguments, context):
        del self, context
        output = Path(arguments.output_path)
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_bytes(b"png")
        seen["prompt"] = arguments.prompt
        return ToolResult("ok", metadata={"paths": [str(output)]})

    async def fake_followup(**kwargs):
        seen["followup_history"] = kwargs["history"]
        return firefly_runtime.FireflyResponse(text="这张图跑偏了，我不是猫。")

    monkeypatch.setattr(firefly_runtime.ImageGenerationTool, "execute", fake_execute)
    monkeypatch.setattr(firefly_runtime, "run_firefly_prompt", fake_followup)
    history = [{"role": "user", "content": "流萤我想看看你现在在干嘛（生成一张图片）"}]
    with TemporaryDirectory() as tmp:
        response = FireflyRuntime(cwd=tmp, workspace=Path(tmp) / ".firefly").chat(
            "睡觉穿这么多衣服干嘛（生成一张图片）",
            history=history,
        )

        assert "## Previous Conversation" in str(seen["prompt"])
        assert "画面主体是流萤本人" in str(seen["prompt"])
        assert seen["followup_history"] == history
        assert strip_generated_image_notice(response.text) == "这张图跑偏了，我不是猫。"


def test_firefly_history_skips_stale_permission_workarounds() -> None:
    block = _history_block(
        [
            {"role": "user", "content": "整理图片"},
            {"role": "assistant", "content": "请你先输入：\n/permissions full_auto\n然后再发：继续"},
            {"role": "assistant", "content": "我会直接调用工具，等待弹窗确认。"},
        ]
    )

    assert "/permissions full_auto" not in block
    assert "然后再发" not in block
    assert "直接调用工具" in block


def test_firefly_direct_image_generation_keeps_parenthetical_prompt_for_tool(monkeypatch) -> None:
    seen: dict[str, object] = {}

    async def fake_execute(self, arguments, context):
        del self, context
        output = Path(arguments.output_path)
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_bytes(b"png")
        seen["prompt"] = arguments.prompt
        return ToolResult("ok", metadata={"paths": [str(output)]})

    async def fake_followup(**kwargs):
        seen["followup_attachments"] = kwargs["attachments"]
        return firefly_runtime.FireflyResponse(text="我正在灯下整理资料。")

    monkeypatch.setattr(firefly_runtime.ImageGenerationTool, "execute", fake_execute)
    monkeypatch.setattr(firefly_runtime, "run_firefly_prompt", fake_followup)
    with TemporaryDirectory() as tmp:
        runtime = FireflyRuntime(cwd=tmp, workspace=Path(tmp) / ".firefly")
        response = runtime.chat("流萤我想看看你现在在干嘛（生成一张图片）")

        assert str(seen["prompt"]).startswith("流萤我想看看你现在在干嘛（生成一张图片）")
        assert "画面主体是流萤本人" in str(seen["prompt"])
        assert seen["followup_attachments"]
        assert strip_generated_image_notice(response.text) == "我正在灯下整理资料。"


def test_firefly_plain_text_chat_has_no_general_timeout(monkeypatch) -> None:
    async def slow_prompt(**_kwargs):
        await asyncio.sleep(0.02)
        return firefly_runtime.FireflyResponse(text="late")

    monkeypatch.setattr(firefly_runtime, "run_firefly_prompt", slow_prompt)
    with TemporaryDirectory() as tmp:
        response = FireflyRuntime(cwd=tmp, workspace=Path(tmp) / ".firefly").chat("你好")

        assert response.text == "late"
        assert response.errors == []


def test_firefly_normalizes_empty_assistant_error() -> None:
    assert firefly_runtime.normalize_error_message(
        "Model returned an empty assistant message. The turn was ignored to keep the session healthy."
    ) == "模型这次没有返回可显示内容，本轮已跳过。请重试一次。"


def test_firefly_chat_keeps_awareness_context_without_timeout_retry(monkeypatch) -> None:
    calls: list[dict[str, object]] = []

    async def slow_with_screenshot(**kwargs):
        calls.append(kwargs)
        await asyncio.sleep(0.02)
        return firefly_runtime.FireflyResponse(text="普通回复")

    monkeypatch.setattr(firefly_runtime, "run_firefly_prompt", slow_with_screenshot)
    with TemporaryDirectory() as tmp:
        workspace = initialize_workspace(Path(tmp) / ".firefly")
        screenshot = workspace / "screenshots" / "chat_context_demo.png"
        screenshot.parent.mkdir(parents=True)
        screenshot.write_bytes(b"png")
        response = FireflyRuntime(cwd=tmp, workspace=workspace).chat(
            "你好\n\n临场感知：截图已作为图片附件发送。",
            attachments=[str(screenshot)],
        )

        assert response.text == "普通回复"
        assert len(calls) == 1
        assert calls[0]["prompt"].startswith("你好")
        assert calls[0]["attachments"] == [str(screenshot)]


def test_firefly_image_generation_has_ten_minute_timeout(monkeypatch) -> None:
    async def slow_image(**_kwargs):
        await asyncio.sleep(0.02)
        return firefly_runtime.FireflyResponse(text="late image")

    monkeypatch.setattr(firefly_runtime, "run_direct_image_generation", slow_image)
    monkeypatch.setattr(firefly_runtime, "IMAGE_GENERATION_TIMEOUT_SECONDS", 0.01)
    with TemporaryDirectory() as tmp:
        response = FireflyRuntime(cwd=tmp, workspace=Path(tmp) / ".firefly").chat("请生成一张图片")

        assert response.text == ""
        assert response.errors == ["图片生成超时（10 分钟）。本次任务已停止，请稍后重试。"]


def test_firefly_document_context_reads_docx_and_xlsx() -> None:
    with TemporaryDirectory() as tmp:
        root = Path(tmp)
        docx = root / "note.docx"
        xlsx = root / "sheet.xlsx"
        with zipfile.ZipFile(docx, "w") as archive:
            archive.writestr(
                "word/document.xml",
                "<w:document xmlns:w='http://schemas.openxmlformats.org/wordprocessingml/2006/main'>"
                "<w:body><w:p><w:r><w:t>流萤文档内容</w:t></w:r></w:p></w:body></w:document>",
            )
        with zipfile.ZipFile(xlsx, "w") as archive:
            archive.writestr(
                "xl/sharedStrings.xml",
                "<sst xmlns='http://schemas.openxmlformats.org/spreadsheetml/2006/main'>"
                "<si><t>项目</t></si><si><t>OpenHarness 表格内容</t></si></sst>",
            )
            archive.writestr(
                "xl/worksheets/sheet1.xml",
                "<worksheet xmlns='http://schemas.openxmlformats.org/spreadsheetml/2006/main'>"
                "<sheetData><row><c t='s'><v>0</v></c><c t='s'><v>1</v></c></row></sheetData></worksheet>",
            )

        assert "流萤文档内容" in read_file_sample(docx, 200)
        assert "OpenHarness 表格内容" in read_file_sample(xlsx, 200)
        upload_context = build_upload_context([str(docx), str(xlsx)])

        assert "note.docx" in upload_context
        assert "流萤文档内容" in upload_context
        assert "sheet.xlsx" in upload_context
        assert "OpenHarness 表格内容" in upload_context


def test_firefly_document_context_reads_pptx_and_pdf() -> None:
    with TemporaryDirectory() as tmp:
        root = Path(tmp)
        pptx = root / "slides.pptx"
        pdf = root / "note.pdf"
        with zipfile.ZipFile(pptx, "w") as archive:
            archive.writestr(
                "ppt/slides/slide1.xml",
                "<p:sld xmlns:p='http://schemas.openxmlformats.org/presentationml/2006/main' "
                "xmlns:a='http://schemas.openxmlformats.org/drawingml/2006/main'>"
                "<p:cSld><p:spTree><p:sp><p:txBody><a:p><a:r><a:t>流萤幻灯片内容</a:t></a:r></a:p>"
                "</p:txBody></p:sp></p:spTree></p:cSld></p:sld>",
            )
        write_minimal_pdf(pdf, "Firefly PDF text")

        assert "流萤幻灯片内容" in read_file_sample(pptx, 200)
        assert "Firefly PDF text" in read_file_sample(pdf, 200)


def write_minimal_pdf(path: Path, text: str) -> None:
    objects = [
        "<< /Type /Catalog /Pages 2 0 R >>",
        "<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        "<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
        "/Resources << /Font << /F1 4 0 R >> >> /Contents 5 0 R >>",
        "<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
        f"<< /Length {len(text) + 33} >>\nstream\nBT /F1 12 Tf 72 720 Td ({text}) Tj ET\nendstream",
    ]
    chunks = [b"%PDF-1.4\n"]
    offsets = [0]
    for index, body in enumerate(objects, start=1):
        offsets.append(sum(len(chunk) for chunk in chunks))
        chunks.append(f"{index} 0 obj\n{body}\nendobj\n".encode("ascii"))
    xref = sum(len(chunk) for chunk in chunks)
    table = ["xref\n0 6\n0000000000 65535 f \n"]
    table.extend(f"{offset:010d} 00000 n \n" for offset in offsets[1:])
    table.append(f"trailer\n<< /Root 1 0 R /Size 6 >>\nstartxref\n{xref}\n%%EOF\n")
    chunks.append("".join(table).encode("ascii"))
    path.write_bytes(b"".join(chunks))


def test_firefly_text_preview_handles_utf16() -> None:
    with TemporaryDirectory() as tmp:
        path = Path(tmp) / "desktop.ini"
        path.write_text("相机胶卷", encoding="utf-16")

        assert read_text_sample(path, 100).strip() == "相机胶卷"


def test_firefly_skill_registry_directory_context() -> None:
    with TemporaryDirectory() as tmp:
        root = Path(tmp)
        workspace = initialize_workspace(root / ".firefly")
        skill_dir = root / "skills" / "firefly-test"
        skill_dir.mkdir(parents=True)
        (skill_dir / "SKILL.md").write_text(
            "---\nname: firefly-test\ndescription: 处理萤火技能测试\n---\n\n# Firefly Test\n",
            encoding="utf-8",
        )
        config = {"skills_enabled": True, "skills_root": str(root / "skills")}

        summary = skill_registry_summary(config, workspace, root)
        context = build_skill_context("请使用萤火技能", config, workspace, root)

        assert "已加载" in summary
        assert "firefly-test" in summary
        assert "firefly-test" in context
        assert "萤火技能" in context


def test_firefly_skills_root_defaults_to_openharness_config_dir() -> None:
    with TemporaryDirectory() as tmp:
        root = Path(tmp)
        old_config_dir = os.environ.get("OPENHARNESS_CONFIG_DIR")
        os.environ["OPENHARNESS_CONFIG_DIR"] = str(root / "oh-config")
        try:
            workspace = root / ".firefly"
            expected = root / "oh-config" / "skills"

            assert skills_root({}, workspace) == expected
            assert skills_root({"skills_root": str(workspace / "skills")}, workspace) == expected
        finally:
            if old_config_dir is None:
                os.environ.pop("OPENHARNESS_CONFIG_DIR", None)
            else:
                os.environ["OPENHARNESS_CONFIG_DIR"] = old_config_dir


def test_firefly_web_context_disabled_does_not_search() -> None:
    with TemporaryDirectory() as tmp:
        context = asyncio.run(build_web_context("搜索 OpenHarness 最新版本", {"web_search_enabled": False}, Path(tmp)))

        assert context == ""


def test_firefly_auto_web_search_detects_freshness_question() -> None:
    assert should_search_web("你知道知更鸟新形态了吗", True)


def test_firefly_openharness_environment_does_not_mutate_process_env() -> None:
    old_enabled = os.environ.get("OPENHARNESS_SANDBOX_ENABLED")
    old_backend = os.environ.get("OPENHARNESS_SANDBOX_BACKEND")
    config = {"sandbox_enabled": True, "sandbox_backend": "docker", "sandbox_fail_if_unavailable": True}

    with openharness_environment(config):
        assert os.environ.get("OPENHARNESS_SANDBOX_ENABLED") == old_enabled
        assert os.environ.get("OPENHARNESS_SANDBOX_BACKEND") == old_backend

    assert os.environ.get("OPENHARNESS_SANDBOX_ENABLED") == old_enabled
    assert os.environ.get("OPENHARNESS_SANDBOX_BACKEND") == old_backend


def test_firefly_desktop_tools_schema_and_non_windows_unsupported() -> None:
    screenshot = DesktopScreenshotTool(Path.cwd())
    assert screenshot.is_read_only(DesktopScreenshotInput())
    assert DesktopWindowTool().is_read_only(DesktopWindowInput(action="list"))
    assert not DesktopWindowTool().is_read_only(DesktopWindowInput(action="focus"))

    original = desktop_tools_module.platform.system
    desktop_tools_module.platform.system = lambda: "Linux"
    try:
        result = asyncio.run(DesktopWindowTool().execute(DesktopWindowInput(action="list"), None))  # type: ignore[arg-type]
    finally:
        desktop_tools_module.platform.system = original

    assert result.is_error
    assert "Windows" in result.output


if __name__ == "__main__":
    test_firefly_persona_loads()
    test_firefly_live2d_manifest_is_complete()
    test_firefly_asset_attribution_exists()
    test_firefly_workspace_initializes()
    test_firefly_openharness_memory_roundtrip()
    test_firefly_library_context_reads_allowed_directory()
    test_firefly_library_index_refresh_search_and_delete()
    test_firefly_library_write_allowlist()
    test_firefly_settings_transform_injects_permissions_and_sandbox()
    test_firefly_upload_context_reads_pending_file()
    test_firefly_image_upload_becomes_openharness_image_block()
    test_firefly_document_context_reads_docx_and_xlsx()
    test_firefly_document_context_reads_pptx_and_pdf()
    test_firefly_text_preview_handles_utf16()
    test_firefly_skill_registry_directory_context()
    test_firefly_skills_root_defaults_to_openharness_config_dir()
    test_firefly_web_context_disabled_does_not_search()
    test_firefly_openharness_environment_does_not_mutate_process_env()
    test_firefly_desktop_tools_schema_and_non_windows_unsupported()
