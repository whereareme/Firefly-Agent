import tempfile
import threading
import unittest
from dataclasses import replace
from pathlib import Path
from queue import SimpleQueue
from unittest.mock import patch

import relationship_gateway.__main__ as command
from relationship_gateway.config import Config
from relationship_gateway.panel import (
    ASSET_PATH,
    GALGAME_MANIFEST_PATH,
    WINDOW_ICON_PATH,
    EVENT_BUTTON_COLUMN,
    EVENT_ENTRY_COLUMN,
    PANEL_COLUMN_COUNT,
    PENDING_KIND_LABELS,
    RELATIONSHIP_THEMES,
    PanelAction,
    TrayController,
    confirm_memory,
    compose_story_stage,
    completed_chapter_stories,
    dismiss_memory,
    gateway_diagnostic,
    galgame_asset_path,
    narrative_event_definition,
    next_narrative_event_id,
    preferred_user_title,
    relationship_theme,
    record_explicit_event,
    RelationshipPanel,
    stage_icon,
    story_dialogue_height,
)
from relationship_gateway.narrative import (
    CHAPTER_ONE_FINALE_ID,
    CHAPTERS,
    NarrativeEventResult,
    NarrativeEventSession,
    NarrativeProgress,
    apply_event_result,
)
from relationship_gateway.state import STAGES, StateStore, StoryLine


class PanelActionTests(unittest.TestCase):
    def test_preferred_user_title_uses_explicit_memory_then_default(self) -> None:
        self.assertEqual(preferred_user_title(""), "开拓者")
        self.assertEqual(preferred_user_title("长期记忆：流萤称呼我为「星光」"), "星光")

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

    def test_tray_fallback_minimizes_to_taskbar(self) -> None:
        root = type("Root", (), {"withdrawn": False, "iconified": False})()
        root.withdraw = lambda: setattr(root, "withdrawn", True)
        root.iconify = lambda: setattr(root, "iconified", True)
        action = type("Text", (), {"value": ""})()
        action.set = lambda value: setattr(action, "value", value)
        panel = RelationshipPanel.__new__(RelationshipPanel)
        panel.root = root
        panel._tray = None
        panel._action_text = action
        panel._start_tray = lambda: None

        panel.hide()

        self.assertFalse(root.withdrawn)
        self.assertTrue(root.iconified)
        self.assertIn("任务栏", action.value)

    def test_hide_retries_tray_start_before_falling_back(self) -> None:
        root = type("Root", (), {"withdrawn": False})()
        root.withdraw = lambda: setattr(root, "withdrawn", True)
        panel = RelationshipPanel.__new__(RelationshipPanel)
        panel.root = root
        panel._tray = None
        panel._action_text = type("Text", (), {"set": lambda self, value: None})()
        panel._start_tray = lambda: setattr(panel, "_tray", object())

        panel.hide()

        self.assertTrue(root.withdrawn)

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

    def test_galgame_runtime_assets_use_the_chapter_one_pack(self) -> None:
        self.assertTrue(GALGAME_MANIFEST_PATH.is_file())
        assets = [
            galgame_asset_path("scenes", "apartment_morning"),
            galgame_asset_path("scenes", "riverside_cloudy"),
            galgame_asset_path("scenes", "cafe_afternoon"),
            galgame_asset_path("scenes", "outdoor_long_bench_evening"),
            galgame_asset_path("sprites", "home_neutral_stand"),
            galgame_asset_path("sprites", "outdoor_surprised_turn"),
            galgame_asset_path("sprites", "night_seated_smile"),
        ]

        from PIL import Image

        for asset in assets:
            self.assertIn("chapter-01", asset.parts)
            with Image.open(asset) as image:
                image.verify()

        scene = Image.open(galgame_asset_path("scenes", "outdoor_long_bench_evening")).convert("RGB")
        sprite = Image.open(galgame_asset_path("sprites", "night_seated_smile")).convert("RGBA")
        self.assertEqual(compose_story_stage(scene, sprite).size, (528, 330))
        self.assertEqual(compose_story_stage(scene, sprite, (960, 600)).size, (960, 600))

    def test_closing_story_window_restores_the_management_panel(self) -> None:
        window = type("Window", (), {"destroyed": False})()
        window.destroy = lambda: setattr(window, "destroyed", True)
        panel = RelationshipPanel.__new__(RelationshipPanel)
        panel._story_window = window
        panel._story_canvas = object()
        panel._story_resize_job = None
        panel._exiting = False
        panel.show = lambda: setattr(panel, "shown", True)
        panel.shown = False

        panel.close_story_window()

        self.assertTrue(window.destroyed)
        self.assertTrue(panel.shown)
        self.assertIsNone(panel._story_window)
        self.assertIsNone(panel._story_canvas)

    def test_story_waits_for_another_reply_after_each_generated_turn(self) -> None:
        panel = RelationshipPanel.__new__(RelationshipPanel)
        panel._story_lines = (StoryLine("流萤", "我在听。", "neutral"),)
        panel._story_index = 0
        panel._story_waiting_choice = False
        panel._story_judging = False
        panel._narrative_session = NarrativeEventSession.start("first-greeting")
        panel._render_story_window = lambda: None
        panel.close_story_window = lambda: None

        panel.advance_story()

        self.assertTrue(panel._story_waiting_choice)

    def test_first_click_finishes_typewriter_without_advancing(self) -> None:
        panel = RelationshipPanel.__new__(RelationshipPanel)
        panel._story_lines = (StoryLine("流萤", "慢慢出现的文字。", "neutral"),)
        panel._story_index = 0
        panel._story_reveal_chars = 2
        panel._story_choice_error = None
        panel._story_judging = False
        panel._story_waiting_choice = False
        panel._story_text_job = None
        panel._narrative_session = NarrativeEventSession.start("first-greeting")
        panel._render_story_window = lambda: None

        panel.advance_story()

        self.assertEqual(panel._story_index, 0)
        self.assertEqual(panel._story_reveal_chars, len(panel._story_lines[0].text))

    def test_skip_stays_off_for_unread_text_and_enables_during_replay(self) -> None:
        panel = RelationshipPanel.__new__(RelationshipPanel)
        panel._story_lines = (StoryLine("流萤", "还没有读过。", "neutral"),)
        panel._story_index = 0
        panel._story_skip = False
        panel._story_replay = False
        panel._playback_store = type("ReadStore", (), {"is_read": lambda self, line: False})()
        panel._reset_story_display = lambda: None
        panel._render_story_window = lambda: None

        panel.toggle_story_skip()
        self.assertFalse(panel._story_skip)
        panel._story_replay = True
        panel.toggle_story_skip()
        self.assertTrue(panel._story_skip)

    def test_generated_narrative_turn_becomes_the_next_playable_lines(self) -> None:
        lines = (
            StoryLine("旁白", "她停下来听你说完。", "neutral"),
            StoryLine("流萤", "原来是这样。", "relieved"),
            StoryLine("流萤", "那我们慢慢来。", "happy"),
        )
        session = NarrativeEventSession.start("first-greeting")
        window = type("Window", (), {"winfo_exists": lambda self: True})()
        panel = RelationshipPanel.__new__(RelationshipPanel)
        panel._story_window = window
        panel._story_waiting_choice = True
        panel._story_judging = True
        panel._story_custom_text = type("Text", (), {"set": lambda self, value: None})()
        panel._render_story_window = lambda: None

        panel._finish_story_continuation((session, lines), None)

        self.assertIs(panel._narrative_session, session)
        self.assertEqual(panel._story_lines, lines)
        self.assertEqual(panel._story_index, 0)
        self.assertFalse(panel._story_waiting_choice)

    def test_story_dialogue_height_tracks_text_without_taking_over_the_scene(self) -> None:
        short = story_dialogue_height("一句短对白。", 960)
        long = story_dialogue_height("这是一段更长的对白。" * 24, 960)

        self.assertEqual(short, 112)
        self.assertGreater(long, short)
        self.assertLessEqual(long, 180)

    def test_center_choice_hit_area_selects_only_the_clicked_branch(self) -> None:
        panel = RelationshipPanel.__new__(RelationshipPanel)
        panel._story_waiting_choice = True
        panel._story_judging = False
        panel._narrative_session = NarrativeEventSession.start("first-greeting")
        panel._story_choice_bounds = {
            "near": (100, 100, 500, 150),
            "space": (100, 170, 500, 220),
        }
        selected: list[str] = []
        panel._begin_story_continuation = (
            lambda text: selected.append(text) or "break"
        )
        event = type("Event", (), {"x": 300, "y": 190})()

        panel._handle_story_click(event)

        self.assertEqual(selected, ["space"])

    def test_completed_story_ignores_stale_choice_overlay_and_closes(self) -> None:
        panel = RelationshipPanel.__new__(RelationshipPanel)
        panel._story_lines = (StoryLine("流萤", "这一幕结束了。", "neutral"),)
        panel._story_index = 0
        panel._story_waiting_choice = True
        panel._story_judging = False
        panel._narrative_session = type("Session", (), {"completed": True})()
        closed: list[bool] = []
        panel.close_story_window = lambda: closed.append(True)

        result = panel.advance_story()

        self.assertEqual(result, "break")
        self.assertEqual(closed, [True])
        self.assertFalse(panel._story_accepts_choice())

    def test_panel_recovers_completed_story_result_missed_by_the_window(self) -> None:
        old_line = StoryLine("流萤", "下次再见。", "neutral")
        final_line = StoryLine("流萤", "今天能认识你，我很开心。", "happy")
        current = type("Session", (), {"event_id": "first-greeting", "completed": False, "lines": (old_line,)})()
        saved = type(
            "Session",
            (),
            {"event_id": "first-greeting", "completed": True, "lines": (old_line, final_line)},
        )()
        window = type("Window", (), {"winfo_exists": lambda self: True})()
        panel = RelationshipPanel.__new__(RelationshipPanel)
        panel._narrative_session = current
        panel._story_window = window
        panel._story_lines = (old_line,)
        panel._story_index = 0
        panel._story_waiting_choice = True
        panel._story_judging = True
        panel._story_choice_error = "旧状态"
        rendered: list[bool] = []
        panel._render_story_window = lambda: rendered.append(True)

        panel._sync_completed_story_session(saved)

        self.assertIs(panel._narrative_session, saved)
        self.assertEqual(panel._story_lines, (final_line,))
        self.assertFalse(panel._story_waiting_choice)
        self.assertFalse(panel._story_judging)
        self.assertIsNone(panel._story_choice_error)
        self.assertEqual(rendered, [True])

    def test_management_refresh_keeps_the_live_story_session(self) -> None:
        active = NarrativeEventSession.start("first-greeting")
        overview = NarrativeEventSession.start("conversation-rhythm")
        progress = NarrativeProgress.default()
        event = narrative_event_definition("conversation-rhythm")
        window = type("Window", (), {"winfo_exists": lambda self: True})()
        panel = RelationshipPanel.__new__(RelationshipPanel)
        panel._story_window = window
        panel._narrative_session = active
        panel._narrative_event = narrative_event_definition("first-greeting")

        panel._adopt_narrative_overview_state(progress, overview, event)

        self.assertIs(panel._narrative_progress, progress)
        self.assertIs(panel._narrative_session, active)
        self.assertEqual(panel._narrative_event.id, "first-greeting")

    def test_management_refresh_adopts_session_after_story_window_closes(self) -> None:
        active = NarrativeEventSession.start("first-greeting")
        overview = NarrativeEventSession.start("conversation-rhythm")
        progress = NarrativeProgress.default()
        event = narrative_event_definition("conversation-rhythm")
        panel = RelationshipPanel.__new__(RelationshipPanel)
        panel._story_window = None
        panel._narrative_session = active
        panel._narrative_event = narrative_event_definition("first-greeting")

        panel._adopt_narrative_overview_state(progress, overview, event)

        self.assertIs(panel._narrative_progress, progress)
        self.assertIs(panel._narrative_session, overview)
        self.assertIs(panel._narrative_event, event)

    def test_completed_chapter_stories_exposes_only_replayable_events(self) -> None:
        completed = replace(NarrativeEventSession.start("first-greeting"), completed=True)
        active = NarrativeEventSession.start("conversation-rhythm")

        self.assertEqual(completed_chapter_stories((completed, active), completed.chapter_id), (completed,))

    def test_first_chapter_scheduler_resumes_then_advances_core_events_in_order(self) -> None:
        progress = NarrativeProgress.default()
        session = NarrativeEventSession.start("first-greeting")
        self.assertEqual(next_narrative_event_id(progress, session), "first-greeting")

        progress = apply_event_result(
            progress, "first-greeting", "2026-07-14", NarrativeEventResult("neutral")
        )
        self.assertEqual(next_narrative_event_id(progress, session), "conversation-rhythm")
        self.assertEqual(narrative_event_definition("conversation-rhythm").title, "你习惯怎样聊天")

    def test_first_chapter_scheduler_uses_hidden_bridge_or_repair_events(self) -> None:
        progress = NarrativeProgress.default()
        for index, event_id in enumerate(CHAPTERS[0].required_event_ids):
            progress = apply_event_result(
                progress, event_id, f"2026-07-{index + 1:02d}", NarrativeEventResult("neutral")
            )

        event_id = next_narrative_event_id(progress, None)

        self.assertIsNotNone(event_id)
        self.assertTrue(event_id.startswith("llm-repair-"))  # type: ignore[union-attr]
        self.assertNotIn("bad", narrative_event_definition(event_id).title)  # type: ignore[arg-type]

    def test_first_chapter_scheduler_reports_finale_only_after_all_gates_pass(self) -> None:
        progress = NarrativeProgress.default()
        for index, event_id in enumerate(CHAPTERS[0].required_event_ids):
            progress = apply_event_result(
                progress,
                event_id,
                f"2026-07-{index + 1:02d}",
                NarrativeEventResult(
                    "good", familiarity=2, consistency=1, boundaries=1, authenticity=1
                ),
            )

        self.assertEqual(next_narrative_event_id(progress, None), CHAPTER_ONE_FINALE_ID)

    def test_personalized_interludes_run_only_at_their_slots_with_memory_context(self) -> None:
        progress = NarrativeProgress.default()
        for index, event_id in enumerate(CHAPTERS[0].required_event_ids[:3]):
            progress = apply_event_result(
                progress, event_id, f"2026-07-{index + 1:02d}", NarrativeEventResult("neutral")
            )
        self.assertEqual(
            next_narrative_event_id(progress, None, True), "personalized-interlude-1"
        )
        self.assertEqual(next_narrative_event_id(progress, None, False), "remembered-detail")

    def test_panel_uses_only_everos_memory_context_for_personalized_interludes(self) -> None:
        panel = RelationshipPanel.__new__(RelationshipPanel)
        panel.gateway = type(
            "Gateway", (), {"memory_context_snapshot": lambda self: "## EverOS 记忆\n- 用户正在准备考试"}
        )()
        panel.store = type(
            "Store", (), {"load": lambda self: type("State", (), {"context_events": (type("Event", (), {"kind": "memory", "summary": "confirmed-only"})(),)})()}
        )()

        self.assertEqual(
            panel._memory_narrative_context(),
            "## EverOS 记忆\n- 用户正在准备考试",
        )

    def test_custom_story_reply_uses_the_same_narrative_continuation_path(self) -> None:
        panel = RelationshipPanel.__new__(RelationshipPanel)
        panel._story_waiting_choice = True
        panel._story_judging = False
        panel._narrative_session = NarrativeEventSession.start("first-greeting")
        panel._story_custom_text = type("Text", (), {"get": lambda self: "我想先听你说"})()
        submitted: list[str] = []
        panel._begin_story_continuation = lambda text: submitted.append(text) or "break"

        panel.submit_custom_story_choice()

        self.assertEqual(submitted, ["我想先听你说"])

    def test_panel_recovers_completed_session_before_scheduling_the_next_event(self) -> None:
        pending = NarrativeProgress.default()
        recovered = apply_event_result(
            pending, "first-greeting", "2026-07-14", NarrativeEventResult("neutral")
        )
        progress_values = iter((pending, recovered))
        completed_session = type(
            "CompletedSession", (), {"completed": True, "event_id": "first-greeting"}
        )()
        gateway = type("Gateway", (), {})()
        gateway.narrative_store = type("Store", (), {"load": lambda self: next(progress_values)})()
        gateway.narrative_session_store = type(
            "SessionStore", (), {"load": lambda self: completed_session}
        )()
        calls: list[str] = []
        gateway.continue_narrative_event = (
            lambda session, reply: calls.append(reply) or (session, None)
        )
        panel = RelationshipPanel.__new__(RelationshipPanel)
        panel.gateway = gateway

        progress, session = panel._load_narrative_state()

        self.assertEqual(calls, ["恢复已完成的剧情进度"])
        self.assertIsNone(session)
        self.assertIn("first-greeting", progress.completed_event_ids)

    def test_panel_hides_completed_session_that_is_already_recorded(self) -> None:
        progress = apply_event_result(
            NarrativeProgress.default(), "first-greeting", "2026-07-14", NarrativeEventResult("neutral")
        )
        completed_session = type(
            "CompletedSession", (), {"completed": True, "event_id": "first-greeting"}
        )()
        gateway = type("Gateway", (), {})()
        gateway.narrative_store = type("Store", (), {"load": lambda self: progress})()
        gateway.narrative_session_store = type(
            "SessionStore", (), {"load": lambda self: completed_session}
        )()
        gateway.continue_narrative_event = lambda *_args: (_ for _ in ()).throw(AssertionError("must not recover"))
        panel = RelationshipPanel.__new__(RelationshipPanel)
        panel.gateway = gateway

        loaded_progress, session = panel._load_narrative_state()

        self.assertIs(loaded_progress, progress)
        self.assertIsNone(session)

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

    def test_stage_label_changes_without_recoloring_the_fixed_theme(self) -> None:
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
        self.assertEqual(tray.stages, ["acquainted"])
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
        self.assertEqual(panel._icon_stage, "acquainted")

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
