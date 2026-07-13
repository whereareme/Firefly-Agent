import tempfile
import threading
import unittest
from pathlib import Path
from queue import SimpleQueue
from unittest.mock import patch

import relationship_gateway.__main__ as command
from relationship_gateway.config import Config
from relationship_gateway.panel import (
    ASSET_PATH,
    WINDOW_ICON_PATH,
    EVENT_BUTTON_COLUMN,
    EVENT_ENTRY_COLUMN,
    PANEL_COLUMN_COUNT,
    PENDING_KIND_LABELS,
    RELATIONSHIP_THEMES,
    PanelAction,
    TrayController,
    confirm_memory,
    dismiss_memory,
    gateway_diagnostic,
    relationship_theme,
    record_explicit_event,
    RelationshipPanel,
    stage_icon,
)
from relationship_gateway.state import STAGES, StateStore


class PanelActionTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.store = StateStore(Path(self.temporary_directory.name) / "data")

    def tearDown(self) -> None:
        self.temporary_directory.cleanup()

    def test_memory_actions_confirm_or_dismiss_the_pending_proposal(self) -> None:
        self.store.queue_memory("We chose this as a shared memory.")

        confirmed = confirm_memory(self.store)

        self.assertEqual(confirmed, PanelAction(True, "已记下。"))
        self.assertEqual([(event.kind, event.summary) for event in self.store.load().events], [
            ("memory", "We chose this as a shared memory.")
        ])

        self.store.queue_memory("This one should be skipped.")
        dismissed = dismiss_memory(self.store)

        self.assertEqual(dismissed, PanelAction(True, "已跳过。"))
        self.assertIsNone(self.store.load().pending_proposal)

    def test_explicit_panel_actions_are_the_gift_and_anniversary_write_path(self) -> None:
        gift = record_explicit_event(self.store, "gift", "  A paper crane.  ")
        anniversary = record_explicit_event(self.store, "anniversary", "First shared project day.")

        self.assertEqual(gift, PanelAction(True, "已记录礼物。"))
        self.assertEqual(anniversary, PanelAction(True, "已记录纪念日。"))
        self.assertEqual(
            [(event.kind, event.summary) for event in self.store.load().events],
            [("gift", "A paper crane."), ("anniversary", "First shared project day.")],
        )

    def test_empty_or_invalid_panel_actions_report_safely_without_writing(self) -> None:
        self.assertEqual(record_explicit_event(self.store, "gift", " \t "), PanelAction(False, "请填写礼物简介。"))
        self.assertFalse(confirm_memory(self.store).ok)
        self.assertFalse(dismiss_memory(self.store).ok)
        self.assertEqual(self.store.load().events, ())

    def test_gateway_diagnostic_never_contains_relationship_progress(self) -> None:
        gateway = type(
            "Gateway",
            (),
            {"last_error": None, "config": type("Config", (), {"host": "127.0.0.1"})(), "server_port": 8787},
        )()

        self.assertEqual(gateway_diagnostic(gateway), "网关：运行中 - http://127.0.0.1:8787/v1")
        gateway.last_error = "upstream unavailable"
        self.assertEqual(gateway_diagnostic(gateway), "网关：需注意 - upstream unavailable")

    def test_event_entry_and_button_use_separate_grid_columns(self) -> None:
        self.assertEqual(PANEL_COLUMN_COUNT, 2)
        self.assertEqual((EVENT_ENTRY_COLUMN, EVENT_BUTTON_COLUMN), (0, 1))
        self.assertNotEqual(EVENT_ENTRY_COLUMN, EVENT_BUTTON_COLUMN)

    def test_confirm_and_dismiss_clear_the_resolved_proposal_diagnostic(self) -> None:
        gateway = type("Gateway", (), {"cleared": 0})()
        gateway.clear_resolved_pending_proposal_diagnostic = lambda: setattr(gateway, "cleared", gateway.cleared + 1)
        panel = RelationshipPanel.__new__(RelationshipPanel)
        panel.store = self.store
        panel.gateway = gateway
        actions: list[PanelAction] = []
        panel._show_action = actions.append

        self.store.queue_memory("We chose to keep this moment.")
        panel.confirm()
        self.store.queue_memory("We chose to skip this moment.")
        panel.dismiss()

        self.assertEqual(gateway.cleared, 2)
        self.assertEqual(actions, [PanelAction(True, "已记下。"), PanelAction(True, "已跳过。")])

    def test_window_close_hides_without_stopping_the_gateway(self) -> None:
        root = type("Root", (), {"withdrawn": False})()
        root.withdraw = lambda: setattr(root, "withdrawn", True)
        gateway = type("Gateway", (), {"shutdown_called": False})()
        gateway.shutdown = lambda: setattr(gateway, "shutdown_called", True)
        panel = RelationshipPanel.__new__(RelationshipPanel)
        panel.root = root
        panel.gateway = gateway
        panel._tray = object()

        panel.hide()

        self.assertTrue(root.withdrawn)
        self.assertFalse(gateway.shutdown_called)

    def test_tray_restore_and_explicit_exit_are_safe_and_idempotent(self) -> None:
        root = type(
            "Root",
            (),
            {"cancelled": [], "destroyed": 0, "shown": [], "focused": False},
        )()
        root.after_cancel = root.cancelled.append
        root.destroy = lambda: setattr(root, "destroyed", root.destroyed + 1)
        root.deiconify = lambda: root.shown.append("deiconify")
        root.lift = lambda: root.shown.append("lift")
        root.focus_force = lambda: setattr(root, "focused", True)
        gateway = type("Gateway", (), {"shutdown_called": 0})()
        gateway.shutdown = lambda: setattr(gateway, "shutdown_called", gateway.shutdown_called + 1)
        tray = type("Tray", (), {"stopped": 0})()
        tray.stop = lambda: setattr(tray, "stopped", tray.stopped + 1)
        panel = RelationshipPanel.__new__(RelationshipPanel)
        panel.root = root
        panel.gateway = gateway
        panel._tray = tray
        panel._poll_job = "poll-job"
        panel._tray_poll_job = "tray-poll-job"
        panel._exiting = False

        panel.show()
        panel.exit()
        panel.exit()

        self.assertEqual(root.shown, ["deiconify", "lift"])
        self.assertTrue(root.focused)
        self.assertEqual(root.cancelled, ["poll-job", "tray-poll-job"])
        self.assertEqual(root.destroyed, 1)
        self.assertEqual(gateway.shutdown_called, 1)
        self.assertEqual(tray.stopped, 1)

    def test_tray_fallback_keeps_window_open(self) -> None:
        root = type("Root", (), {"withdrawn": False})()
        root.withdraw = lambda: setattr(root, "withdrawn", True)
        action = type("Text", (), {"value": ""})()
        action.set = lambda value: setattr(action, "value", value)
        panel = RelationshipPanel.__new__(RelationshipPanel)
        panel.root = root
        panel._tray = None
        panel._action_text = action

        panel.hide()

        self.assertFalse(root.withdrawn)
        self.assertIn("托盘不可用", action.value)

    def test_tray_worker_only_enqueues_until_tk_main_thread_drains(self) -> None:
        root = type("Root", (), {"shown": [], "scheduled": []})()
        root.deiconify = lambda: root.shown.append("deiconify")
        root.lift = lambda: root.shown.append("lift")
        root.focus_force = lambda: root.shown.append("focus")
        root.after = lambda delay, callback: root.scheduled.append((delay, callback)) or "tray-job"
        panel = RelationshipPanel.__new__(RelationshipPanel)
        panel.root = root
        panel._tray_actions = SimpleQueue()
        panel._tray_poll_job = None
        panel._exiting = False

        worker = threading.Thread(target=lambda: panel._tray_actions.put(panel.show))
        worker.start()
        worker.join()

        self.assertEqual(root.shown, [])
        panel._drain_tray_actions()
        self.assertEqual(root.shown, ["deiconify", "lift", "focus"])
        self.assertEqual(root.scheduled[0][0], 100)

    def test_not_implemented_tray_backend_falls_back_without_hiding(self) -> None:
        action = type("Text", (), {"value": ""})()
        action.set = lambda value: setattr(action, "value", value)
        panel = RelationshipPanel.__new__(RelationshipPanel)
        panel.root = object()
        panel._tray_actions = SimpleQueue()
        panel._action_text = action

        with patch("relationship_gateway.panel.TrayController.start", side_effect=NotImplementedError("unsupported")):
            panel._start_tray()

        self.assertIsNone(panel._tray)
        self.assertIn("unsupported", action.value)

    def test_panel_owns_companion_icon_and_typed_pending_labels(self) -> None:
        self.assertTrue(ASSET_PATH.is_file())
        self.assertTrue(WINDOW_ICON_PATH.is_file())
        self.assertEqual(
            PENDING_KIND_LABELS,
            {"memory": "重要回忆", "gift": "礼物", "anniversary": "纪念日"},
        )

    def test_all_relationship_stages_have_distinct_complete_themes(self) -> None:
        self.assertEqual(tuple(RELATIONSHIP_THEMES), STAGES)
        self.assertEqual(
            [RELATIONSHIP_THEMES[stage].label for stage in STAGES],
            ["初识", "信赖", "亲近", "羁绊"],
        )
        self.assertEqual(len({RELATIONSHIP_THEMES[stage].surface for stage in STAGES}), len(STAGES))
        self.assertIs(relationship_theme("unknown"), RELATIONSHIP_THEMES[STAGES[0]])

        def luminance(color: str) -> float:
            channels = [int(color[index:index + 2], 16) / 255 for index in (1, 3, 5)]
            red, green, blue = [value / 12.92 if value <= 0.04045 else ((value + 0.055) / 1.055) ** 2.4 for value in channels]
            return 0.2126 * red + 0.7152 * green + 0.0722 * blue

        def contrast(first: str, second: str) -> float:
            light, dark = sorted((luminance(first), luminance(second)), reverse=True)
            return (light + 0.05) / (dark + 0.05)

        for theme in RELATIONSHIP_THEMES.values():
            self.assertGreaterEqual(contrast(theme.primary, theme.primary_foreground), 4.5)
            self.assertGreaterEqual(contrast(theme.primary_active, theme.primary_foreground), 4.5)
            self.assertGreaterEqual(contrast(theme.primary_disabled, theme.disabled_foreground), 4.5)

    def test_close_and_confirmed_use_the_swapped_palettes_and_icons(self) -> None:
        close = RELATIONSHIP_THEMES["close"]
        confirmed = RELATIONSHIP_THEMES["confirmed"]

        self.assertEqual((close.window, close.primary, close.icon), ("#102e2c", "#d7aa3e", "#e0b64e"))
        self.assertEqual((confirmed.window, confirmed.primary, confirmed.icon), ("#fff1f5", "#a94063", "#c45176"))
        self.assertEqual(stage_icon("close").getpixel((32, 32))[:3], (224, 182, 78))
        self.assertEqual(stage_icon("confirmed").getpixel((32, 32))[:3], (196, 81, 118))

    def test_stage_icons_are_distinct_and_cached(self) -> None:
        icons = [stage_icon(stage) for stage in STAGES]
        self.assertEqual(len({icon.getpixel((32, 32)) for icon in icons}), len(STAGES))
        self.assertIs(stage_icon(STAGES[0]), icons[0])
        for index in range(20):
            self.assertIs(stage_icon(f"unknown-{index}"), icons[0])
        self.assertTrue(all(stage_icon(stage) is icon for stage, icon in zip(STAGES, icons)))

    def test_stage_theme_switches_once_per_stage_and_falls_back(self) -> None:
        root = object()
        canvas = type("Canvas", (), {"colors": []})()
        canvas.configure = lambda **kwargs: canvas.colors.append(kwargs["background"])
        stage_text = type("Text", (), {"values": []})()
        stage_text.set = stage_text.values.append
        tray = type("Tray", (), {"stages": []})()
        tray.set_stage = tray.stages.append
        panel = RelationshipPanel.__new__(RelationshipPanel)
        panel.root = root
        panel._canvas = canvas
        panel._stage_text = stage_text
        panel._action_text = type("Text", (), {"set": lambda self, value: None})()
        panel._tray = tray
        panel._style = object()
        panel._active_stage = None
        panel._icon_stage = None

        with patch("relationship_gateway.panel.configure_style") as configure:
            panel._apply_stage_theme("trusted")
            panel._apply_stage_theme("trusted")
            panel._apply_stage_theme("unknown")

        self.assertEqual(configure.call_count, 2)
        self.assertEqual(tray.stages, ["trusted", "acquainted"])
        self.assertEqual(stage_text.values, [
            "关系阶段：信赖 · 确认值得留下的共同片段",
            "关系阶段：初识 · 确认值得留下的共同片段",
        ])

    def test_transient_icon_failure_retries_without_reapplying_styles(self) -> None:
        root = object()
        canvas = type("Canvas", (), {"configure": lambda self, **kwargs: None})()
        text = type("Text", (), {"set": lambda self, value: None})()
        tray = type("Tray", (), {"calls": 0})()

        def set_stage(_stage: str) -> None:
            tray.calls += 1
            if tray.calls == 1:
                raise RuntimeError("temporary")

        tray.set_stage = set_stage
        panel = RelationshipPanel.__new__(RelationshipPanel)
        panel.root = root
        panel._canvas = canvas
        panel._stage_text = text
        panel._action_text = text
        panel._tray = tray
        panel._style = object()
        panel._active_stage = None
        panel._icon_stage = None

        with patch("relationship_gateway.panel.configure_style") as configure:
            panel._apply_stage_theme("close")
            panel._apply_stage_theme("close")

        self.assertEqual(configure.call_count, 1)
        self.assertEqual(tray.calls, 2)
        self.assertEqual(panel._icon_stage, "close")

    def test_tray_stage_update_recolors_existing_icon_without_restarting(self) -> None:
        tray = TrayController(lambda callback: None, lambda: None, lambda: None)
        icon = type("Icon", (), {})()
        tray._icon = icon

        tray.set_stage("close")
        close_icon = icon.icon
        tray.set_stage("unknown")

        self.assertIs(close_icon, stage_icon("close"))
        self.assertIs(icon.icon, stage_icon("acquainted"))


class _ServerDouble:
    def __init__(self, config: Config) -> None:
        self.config = config
        self.server_port = config.port
        self.started = threading.Event()
        self.stopped = threading.Event()
        self.closed = False

    def serve_forever(self) -> None:
        self.started.set()
        self.stopped.wait(timeout=5)

    def shutdown(self) -> None:
        self.stopped.set()

    def server_close(self) -> None:
        self.closed = True


class CommandTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.config = Config(
            host="127.0.0.1",
            port=18787,
            upstream_base_url="https://example.test/v1",
            data_dir=Path(self.temporary_directory.name) / "data",
        )

    def tearDown(self) -> None:
        self.temporary_directory.cleanup()

    def test_headless_cli_runs_the_server_without_importing_the_panel(self) -> None:
        server = _ServerDouble(self.config)
        server.stopped.set()

        with (
            patch.object(command, "load_config", return_value=self.config),
            patch.object(command, "RelationshipGatewayServer", return_value=server),
        ):
            result = command.main(["--config", "test.json", "--headless"])

        self.assertEqual(result, 0)
        self.assertTrue(server.started.is_set())
        self.assertTrue(server.closed)
        self.assertFalse(server.proposals_enabled)

    def test_default_cli_runs_panel_and_stops_the_background_gateway(self) -> None:
        server = _ServerDouble(self.config)

        def close_panel(received_server: _ServerDouble) -> None:
            self.assertIs(received_server, server)
            self.assertTrue(server.started.wait(timeout=5))
            server.shutdown()

        with (
            patch.object(command, "load_config", return_value=self.config),
            patch.object(command, "RelationshipGatewayServer", return_value=server),
            patch("relationship_gateway.panel.run_panel", side_effect=close_panel),
        ):
            result = command.main(["--config", "test.json"])

        self.assertEqual(result, 0)
        self.assertTrue(server.stopped.is_set())
        self.assertTrue(server.closed)
        self.assertTrue(server.proposals_enabled)


if __name__ == "__main__":
    unittest.main()
