import os
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path

from relationship_gateway.narrative import (
    CHAPTERS,
    NarrativeArchiveStore,
    NarrativeEventSession,
    NarrativeEventResult,
    NarrativePlan,
    NarrativeProgress,
    NarrativeSessionStore,
    NarrativeStore,
    NarrativeTurn,
    apply_event_result,
    bridge_event_count,
    chapter_ready_for_finale,
    complete_chapter_finale,
)
from relationship_gateway.state import StoryLine


def valid_director_plan() -> NarrativePlan:
    ranges = ((0, 2), (3, 5), (6, 8), (9, 11), (12, 13), (14, 16))
    scenes = ("cafe_table_rollcake_afternoon",) * 3 + ("bookstore_afternoon",) * 3
    return NarrativePlan.from_dict({
        "premise": "一次从蛋糕店开始的普通相处。",
        "conflict": "双方对之后的安排有不同理解。",
        "resolution": "两人把想法说清并愿意下次再见。",
        "target_nodes": 16,
        "target_lines": 140,
        "choice_nodes": [3, 5, 8, 11, 13],
        "beats": [
            {
                "title": f"阶段{index + 1}",
                "purpose": "让对话自然推进并回收用户之前的回应。",
                "start_node": start,
                "end_node": end,
                "scene": scene,
                "sprite": "outdoor_neutral_attentive",
                "allow_outfit_change": False,
                "directions": {
                    "good": "更愿意继续交流。",
                    "neutral": "保持现在的距离。",
                    "bad": "出现需要之后修复的小误解。",
                },
            }
            for index, ((start, end), scene) in enumerate(zip(ranges, scenes))
        ],
    })


def valid_turn(**overrides: object) -> NarrativeTurn:
    value = {
        "lines": [
            {"speaker": "旁白", "text": "窗边的光慢慢移过桌面。", "expression": "neutral"},
            {"speaker": "流萤", "text": "我明白了，我们可以照你的节奏来。", "expression": "relieved"},
            {"speaker": "旁白", "text": "她把这句话认真记在心里。", "expression": "neutral"},
        ],
        "next_node_type": "free_input",
        "choices": [],
        "hidden_outcome": "good",
        "axis_changes": {"familiarity": 1, "consistency": 1, "boundaries": 0, "authenticity": 1},
        "add_flags": [],
        "resolve_flags": [],
        "user_summary": "用户说明自己更喜欢自然简短的交流。",
        "event_summary": "双方开始确认适合彼此的交流节奏。",
        "event_complete": False,
    }
    value.update(overrides)
    return NarrativeTurn.from_dict(value)


class NarrativeFrameworkTests(unittest.TestCase):
    def test_four_chapters_cover_about_forty_days_without_time_auto_upgrade(self) -> None:
        self.assertEqual([chapter.stage for chapter in CHAPTERS], ["acquainted", "trusted", "close", "confirmed"])
        self.assertEqual(sum(chapter.expected_days[0] for chapter in CHAPTERS), 35)
        self.assertEqual(sum(chapter.expected_days[1] for chapter in CHAPTERS), 45)
        progress = NarrativeProgress.default()
        progress = progress.__class__(
            **{**progress.__dict__, "active_dates": tuple(f"2026-07-{day:02d}" for day in range(1, 10))}
        )
        self.assertFalse(chapter_ready_for_finale(progress))

    def test_director_session_reaches_full_length_and_round_trips(self) -> None:
        plan = valid_director_plan()
        opening = tuple(
            StoryLine("流萤", f"开场第{index + 1}句。", "neutral", plan.beats[0].scene, plan.beats[0].sprite)
            for index in range(8)
        )
        session = NarrativeEventSession.start("first-greeting", target_nodes=16).with_director_opening(
            plan, opening, "两人在蛋糕店开始了一次普通交谈。"
        )
        for index in range(16):
            complete = index == 15
            session = session.append(valid_turn(
                lines=[
                    {
                        "speaker": "流萤",
                        "text": f"剧情继续推进，第{index + 1}轮的第{line + 1}句。",
                        "expression": "neutral",
                        "scene": plan.beat_for_node(index + 1).scene,
                        "sprite": plan.beat_for_node(index + 1).sprite,
                    }
                    for line in range(8)
                ],
                next_node_type="complete" if complete else "free_input",
                event_complete=complete,
                continuity_facts=[f"第{index + 1}轮已经发生。"],
            ))

        restored = NarrativeEventSession.from_dict(session.to_dict())
        self.assertTrue(restored.completed)
        self.assertEqual(restored.current_node, 16)
        self.assertEqual(len(restored.lines), 136)
        self.assertEqual(restored.director_plan, plan)
        self.assertEqual(len(restored.continuity_facts), 16)

    def test_first_chapter_has_eight_core_events_and_two_personalized_slots(self) -> None:
        chapter = CHAPTERS[0]
        self.assertEqual(len(chapter.required_event_ids), 8)
        self.assertEqual(sum(event.personalized for event in chapter.events), 2)
        self.assertEqual(chapter.interaction_nodes_per_event, (14, 18))
        self.assertEqual(chapter.line_count_per_event, (120, 160))

    def test_required_events_days_axes_and_repairs_all_gate_the_finale(self) -> None:
        progress = NarrativeProgress.default()
        chapter = CHAPTERS[0]
        for index, event_id in enumerate(chapter.required_event_ids):
            progress = apply_event_result(
                progress,
                event_id,
                f"2026-07-{index + 1:02d}",
                NarrativeEventResult("good", familiarity=2, consistency=1, boundaries=1, authenticity=1),
            )
        self.assertTrue(chapter_ready_for_finale(progress))
        blocked = apply_event_result(
            progress,
            "llm-boundary-setback",
            "2026-07-09",
            NarrativeEventResult("bad", boundaries=-2, add_flags=("boundary-unresolved",)),
        )
        self.assertFalse(chapter_ready_for_finale(blocked))
        self.assertEqual(bridge_event_count(blocked), 2)
        repaired = apply_event_result(
            blocked,
            "llm-boundary-repair",
            "2026-07-10",
            NarrativeEventResult("good", boundaries=2, resolve_flags=("boundary-unresolved",)),
        )
        self.assertTrue(chapter_ready_for_finale(repaired))

    def test_narrative_progress_round_trips_without_raw_dialogue(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store = NarrativeStore(Path(directory))
            progress = apply_event_result(
                NarrativeProgress.default(),
                "first-greeting",
                "2026-07-14",
                NarrativeEventResult("neutral", familiarity=1),
            )
            store.save(progress)
            self.assertEqual(store.load(), progress)
            self.assertNotIn("dialogue", store.path.read_text(encoding="utf-8"))

    def test_event_session_round_trips_only_bounded_generated_text_and_safe_summaries(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store = NarrativeSessionStore(directory)
            session = NarrativeEventSession.start("first-greeting").append(valid_turn())

            saved = store.save(session)

            self.assertEqual(store.load(), saved)
            payload = store.path.read_text(encoding="utf-8")
            self.assertNotIn("API", payload)
            self.assertEqual(saved.current_node, 1)
            self.assertEqual(saved.user_summaries, ("用户说明自己更喜欢自然简短的交流。",))

    def test_completed_event_archive_round_trips_for_replay(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store = NarrativeArchiveStore(directory)
            session = NarrativeEventSession.start("first-greeting", target_nodes=6)
            for _ in range(5):
                session = session.append(valid_turn())
            session = session.append(valid_turn(next_node_type="complete", event_complete=True))

            archived = store.archive(session)

            self.assertEqual(store.load(), (archived,))
            self.assertEqual(store.get("first-greeting"), archived)

    def test_save_if_current_rejects_deleted_request_baseline(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store = NarrativeSessionStore(directory)
            expected = store.save(NarrativeEventSession.start("first-greeting"))
            store.path.unlink()

            with self.assertRaisesRegex(Exception, "changed while generating"):
                store.save_if_current(expected, expected.append(valid_turn()))

    def test_narrative_stores_reject_replaced_data_directory_and_linked_files(self) -> None:
        for store_type in (NarrativeStore, NarrativeSessionStore, NarrativeArchiveStore):
            with self.subTest(store=store_type.__name__), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                data_dir = root / "data"
                store = store_type(data_dir)
                external = root / "external"
                external.mkdir()
                try:
                    os.symlink(external, data_dir, target_is_directory=True)
                except OSError as error:
                    self.skipTest(f"symbolic links are unavailable: {error}")
                with self.assertRaisesRegex(Exception, "symbolic links"):
                    store.load()

                data_dir.unlink()
                data_dir.mkdir()
                external_file = root / "external.json"
                external_file.write_text("external", encoding="utf-8")
                os.symlink(external_file, store.path)
                with self.assertRaisesRegex(Exception, "symbolic link"):
                    store.load()

    def test_turn_schema_rejects_unbounded_axes_and_inconsistent_completion(self) -> None:
        with self.assertRaisesRegex(Exception, "axis change"):
            valid_turn(axis_changes={"familiarity": 4, "consistency": 0, "boundaries": 0, "authenticity": 0})
        with self.assertRaisesRegex(Exception, "completion"):
            valid_turn(next_node_type="complete")

    def test_event_requires_six_interactions_and_finishes_by_target(self) -> None:
        session = NarrativeEventSession.start("first-greeting", target_nodes=6)
        with self.assertRaisesRegex(Exception, "before six"):
            session.append(valid_turn(
                next_node_type="complete", event_complete=True,
            ))
        for _ in range(5):
            session = session.append(valid_turn())
        session = session.append(valid_turn(next_node_type="complete", event_complete=True))
        self.assertTrue(session.completed)
        self.assertEqual(session.current_node, 6)
        self.assertEqual(session.event_result().familiarity, 3)

    def test_normal_seven_node_event_reaches_the_45_line_target(self) -> None:
        turn = valid_turn()
        six_line_turn = replace(turn, lines=turn.lines * 2)
        session = NarrativeEventSession.start("first-greeting").with_opening(
            six_line_turn.lines, "双方开始认真打招呼。"
        )
        for _ in range(6):
            session = session.append(six_line_turn)
        session = session.append(replace(
            six_line_turn, next_node_type="complete", event_complete=True
        ))
        self.assertGreaterEqual(len(session.lines), 45)

    def test_finale_marks_the_chapter_complete_only_after_all_gates(self) -> None:
        progress = NarrativeProgress.default()
        with self.assertRaisesRegex(Exception, "not ready"):
            complete_chapter_finale(progress)
        for index, event_id in enumerate(CHAPTERS[0].required_event_ids):
            progress = apply_event_result(
                progress, event_id, f"2026-07-{index + 1:02d}",
                NarrativeEventResult("good", familiarity=2, consistency=1, boundaries=1, authenticity=1),
            )
        self.assertTrue(complete_chapter_finale(progress).finale_completed)


if __name__ == "__main__":
    unittest.main()
