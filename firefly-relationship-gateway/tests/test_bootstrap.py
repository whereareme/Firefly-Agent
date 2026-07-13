import json
import os
import sys
import tempfile
import threading
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import Mock, patch

import relationship_gateway.config as config_module
import relationship_gateway.__main__ as main_module
from relationship_gateway.config import ConfigError, load_config
from relationship_gateway.state import (
    MAX_CONTEXT_EVENTS,
    MAX_CONTEXT_SUMMARY_LENGTH,
    MAX_EVENTS,
    MAX_STATE_FILE_BYTES,
    MAX_SUMMARY_LENGTH,
    MAX_TIMESTAMP_LENGTH,
    STAGES,
    RelationshipState,
    StateError,
    StateStore,
)


class BootstrapTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary_directory.name)
        self.store = StateStore(self.root / "data")

    def tearDown(self) -> None:
        self.temporary_directory.cleanup()

    def write_config(self, **overrides: object) -> Path:
        config_path = self.root / "config.json"
        config = {
            "host": "127.0.0.1",
            "port": 8787,
            "upstream_base_url": "https://example.test/v1/",
            "data_dir": "state",
        }
        config.update(overrides)
        config_path.write_text(json.dumps(config), encoding="utf-8")
        return config_path

    def load_config(self, **overrides: object):
        with patch.object(config_module, "PROJECT_ROOT", self.root):
            return load_config(self.write_config(**overrides))

    def test_config_is_loopback_only_secret_free_and_keeps_data_local(self) -> None:
        config = self.load_config()
        self.assertEqual(config.upstream_base_url, "https://example.test/v1")
        self.assertEqual(config.data_dir, (self.root / "state").resolve())

        with self.assertRaises(ConfigError):
            self.load_config(host="0.0.0.0", api_key="must-not-be-stored")
        with self.assertRaises(ConfigError):
            self.load_config(data_dir="../firefly_agent(re)/data")
        with self.assertRaises(ConfigError):
            self.load_config(data_dir=str((self.root / "outside").resolve()))

    def test_direct_config_construction_is_loopback_only(self) -> None:
        with self.assertRaises(ConfigError):
            config_module.Config(
                host="0.0.0.0",
                port=8787,
                upstream_base_url="https://example.test/v1",
                data_dir=self.root / "state",
            )

    def test_parent_watchdog_stops_server_after_managing_process_exits(self) -> None:
        class Stop:
            def wait(self, _timeout: float) -> bool:
                return False

        server = Mock()
        with patch.object(main_module, "process_is_alive", return_value=False):
            main_module.parent_watchdog(server, 12345, Stop())  # type: ignore[arg-type]

        server.shutdown.assert_called_once_with()

    def test_process_liveness_check_does_not_signal_on_windows(self) -> None:
        if os.name != "nt":
            self.skipTest("Windows-specific regression")
        with patch.object(main_module.os, "kill") as kill:
            self.assertTrue(main_module.process_is_alive(os.getpid()))
        kill.assert_not_called()

    def test_config_rejects_an_existing_data_file(self) -> None:
        (self.root / "state-file").write_text("not a directory", encoding="utf-8")

        with self.assertRaises(ConfigError):
            self.load_config(data_dir="state-file")

    def test_config_rejects_a_data_directory_below_a_file(self) -> None:
        (self.root / "state-file").write_text("not a directory", encoding="utf-8")

        with self.assertRaises(ConfigError):
            self.load_config(data_dir="state-file/child")

    def test_config_rejects_nul_data_paths_and_invalid_utf8(self) -> None:
        with self.assertRaises(ConfigError):
            self.load_config(data_dir="state\0")

        config_path = self.root / "invalid-utf8.json"
        config_path.write_bytes(b"\xff")
        with patch.object(config_module, "PROJECT_ROOT", self.root):
            with self.assertRaises(ConfigError):
                load_config(config_path)

    def test_config_rejects_invalid_upstream_hosts_and_ports(self) -> None:
        for upstream_base_url in (
            "https:///v1",
            "https://exa mple.test/v1",
            "https://example.test:/v1",
            "https://example.test:0/v1",
            "https://example.test:65536/v1",
            "https://[::1/v1",
        ):
            with self.subTest(upstream_base_url=upstream_base_url):
                with self.assertRaises(ConfigError):
                    self.load_config(upstream_base_url=upstream_base_url)

    def test_config_rejects_control_characters_and_raw_query_or_fragment_delimiters(self) -> None:
        invalid_urls = [
            "https://example.test/v1?",
            "https://example.test/v1#",
            "https://example.test/v1?model=firefly",
            "https://example.test/v1#fragment",
            *(f"https://example.test/v1{chr(code)}" for code in (*range(32), 127)),
        ]

        for upstream_base_url in invalid_urls:
            with self.subTest(upstream_base_url=repr(upstream_base_url)):
                with self.assertRaises(ConfigError):
                    self.load_config(upstream_base_url=upstream_base_url)

    def test_pending_confirmation_is_the_only_public_stage_transition(self) -> None:
        self.assertNotIn("save", vars(StateStore))
        self.assertNotIn("advance_stage", vars(StateStore))
        self.assertEqual(self.store.load().stage, STAGES[0])
        self.store.record_explicit_event("gift", "A handmade bookmark.")
        self.assertEqual(self.store.load().stage, STAGES[0])
        pending = self.store.queue_memory("We finished a difficult task together.")
        self.assertIsNotNone(pending.pending_proposal)
        with self.assertRaises(StateError):
            self.store.queue_memory("This cannot replace the first pending proposal.")

        confirmed = self.store.confirm_pending()
        self.assertEqual(confirmed.stage, STAGES[0])
        self.assertEqual(confirmed.events[-1].kind, "memory")
        self.assertIsNone(confirmed.pending_proposal)

        self.assertEqual(self.store.load().stage, STAGES[0])
        self.store.queue_memory("We made a meaningful promise.")
        dismissed = self.store.dismiss_pending()
        self.assertEqual(dismissed.stage, STAGES[0])
        self.assertIsNone(dismissed.pending_proposal)

        for summary in (
            "We made a meaningful promise.",
            "We chose to stay close.",
            "We remembered why this matters.",
        ):
            self.store.queue_memory(summary)
            self.assertEqual(self.store.confirm_pending().stage, STAGES[0])

    def test_relationship_stages_require_count_days_and_elapsed_time(self) -> None:
        base = datetime(2026, 1, 1, 12, tzinfo=timezone.utc)
        cases = (
            (10, 7, 10, STAGES[1]),
            (30, 20, 30, STAGES[2]),
            (70, 40, 60, STAGES[3]),
        )

        for count, distinct_days, elapsed_days, expected_stage in cases:
            with self.subTest(expected_stage=expected_stage):
                store = StateStore(self.root / expected_stage)
                offsets = [*range(distinct_days - 1), elapsed_days]
                offsets.extend([elapsed_days] * (count - len(offsets)))
                timestamps = [(base + timedelta(days=offset)).isoformat() for offset in offsets]
                with patch("relationship_gateway.state._now", side_effect=timestamps):
                    for index in range(count):
                        state = store.record_confirmed_proposal("memory", f"Memory {index}")
                self.assertEqual(state.stage, expected_stage)

    def test_elapsed_gate_uses_exact_duration(self) -> None:
        base = datetime(2026, 1, 1, 12, tzinfo=timezone.utc)
        for final_offset, expected_stage in (
            (timedelta(days=10) - timedelta(seconds=1), STAGES[0]),
            (timedelta(days=10), STAGES[1]),
        ):
            with self.subTest(final_offset=final_offset):
                store = StateStore(self.root / f"elapsed-{final_offset.total_seconds()}")
                timestamps = [base + timedelta(days=offset) for offset in range(6)]
                timestamps.extend([base + final_offset] * 4)
                with patch(
                    "relationship_gateway.state._now",
                    side_effect=[timestamp.isoformat() for timestamp in timestamps],
                ):
                    for index in range(10):
                        state = store.record_confirmed_proposal("memory", f"Memory {index}")
                self.assertEqual(state.stage, expected_stage)

    def test_each_relationship_threshold_requires_all_three_gates(self) -> None:
        base = datetime(2026, 1, 1, 12, tzinfo=timezone.utc)
        for count, distinct_days, elapsed_days, previous_stage in (
            (9, 7, 10, STAGES[0]),
            (10, 6, 10, STAGES[0]),
            (10, 7, 9, STAGES[0]),
            (29, 20, 30, STAGES[1]),
            (30, 19, 30, STAGES[1]),
            (30, 20, 29, STAGES[1]),
            (69, 40, 60, STAGES[2]),
            (70, 39, 60, STAGES[2]),
            (70, 40, 59, STAGES[2]),
        ):
            with self.subTest(count=count, distinct_days=distinct_days, elapsed_days=elapsed_days):
                store = StateStore(self.root / f"gates-{count}-{distinct_days}-{elapsed_days}")
                offsets = [*range(distinct_days - 1), elapsed_days]
                offsets.extend([elapsed_days] * (count - len(offsets)))
                timestamps = [(base + timedelta(days=offset)).isoformat() for offset in offsets]
                with patch("relationship_gateway.state._now", side_effect=timestamps):
                    for index in range(count):
                        state = store.record_confirmed_proposal("memory", f"Memory {index}")
                self.assertEqual(state.stage, previous_stage)

    def test_typed_proposals_confirm_as_typed_events_without_non_memory_stage_changes(self) -> None:
        for kind in ("gift", "anniversary"):
            with self.subTest(kind=kind):
                queued = self.store.queue_proposal(kind, f"Confirmed {kind}.")
                self.assertEqual(queued.pending_proposal.kind, kind)  # type: ignore[union-attr]

                confirmed = self.store.confirm_pending()

                self.assertEqual(confirmed.stage, STAGES[0])
                self.assertEqual((confirmed.events[-1].kind, confirmed.events[-1].summary), (kind, f"Confirmed {kind}."))

    def test_confirmed_gift_and_anniversary_exact_duplicates_are_not_queued_again(self) -> None:
        for kind in ("gift", "anniversary"):
            with self.subTest(kind=kind):
                self.store.record_explicit_event(kind, "A Shared Day")

                unchanged = self.store.queue_proposal(kind, "a   shared day")

                self.assertIsNone(unchanged.pending_proposal)
                self.assertEqual(sum(event.kind == kind for event in unchanged.events), 1)

        self.store.queue_memory("A Shared Day")
        self.assertIsNotNone(self.store.load().pending_proposal)

    def test_concurrent_confirm_and_dismiss_accepts_the_memory_once(self) -> None:
        self.store.queue_memory("We chose to remember this together.")
        confirm_is_saving = threading.Event()
        allow_confirm = threading.Event()
        dismiss_started = threading.Event()
        results: dict[str, object] = {}
        original_save = self.store._save

        def pause_confirm_save(state: RelationshipState) -> RelationshipState:
            if state.events and state.pending_proposal is None:
                confirm_is_saving.set()
                if not allow_confirm.wait(timeout=5):
                    raise RuntimeError("timed out waiting to resume confirmation")
            return original_save(state)

        def confirm() -> None:
            try:
                results["confirm"] = self.store.confirm_pending()
            except StateError as error:
                results["confirm"] = error

        def dismiss() -> None:
            dismiss_started.set()
            try:
                results["dismiss"] = self.store.dismiss_pending()
            except StateError as error:
                results["dismiss"] = error

        with patch.object(self.store, "_save", side_effect=pause_confirm_save):
            confirm_thread = threading.Thread(target=confirm)
            confirm_thread.start()
            self.assertTrue(confirm_is_saving.wait(timeout=5))

            dismiss_thread = threading.Thread(target=dismiss)
            dismiss_thread.start()
            self.assertTrue(dismiss_started.wait(timeout=5))
            allow_confirm.set()
            confirm_thread.join(timeout=5)
            dismiss_thread.join(timeout=5)

        self.assertFalse(confirm_thread.is_alive())
        self.assertFalse(dismiss_thread.is_alive())
        self.assertIsInstance(results["confirm"], RelationshipState)
        self.assertIsInstance(results["dismiss"], StateError)
        self.assertEqual(str(results["dismiss"]), "there is no pending proposal")
        state = self.store.load()
        self.assertIsNone(state.pending_proposal)
        self.assertEqual([event.summary for event in state.events], ["We chose to remember this together."])

    def test_state_store_instances_share_one_process_transaction_lock(self) -> None:
        first_store = StateStore(self.store.path.parent)
        second_store = StateStore(self.store.path.parent)
        first_loaded = threading.Event()
        allow_first_save = threading.Event()
        second_started = threading.Event()
        second_finished = threading.Event()
        results: dict[str, object] = {}
        original_load = first_store._load

        def pause_first_after_load() -> RelationshipState:
            state = original_load()
            first_loaded.set()
            if not allow_first_save.wait(timeout=5):
                raise RuntimeError("timed out waiting to resume first transaction")
            return state

        def record_first() -> None:
            results["first"] = first_store.record_explicit_event("gift", "The first shared token.")

        def record_second() -> None:
            second_started.set()
            results["second"] = second_store.record_explicit_event("anniversary", "The second shared token.")
            second_finished.set()

        with patch.object(first_store, "_load", side_effect=pause_first_after_load):
            first_thread = threading.Thread(target=record_first)
            first_thread.start()
            self.assertTrue(first_loaded.wait(timeout=5))

            second_thread = threading.Thread(target=record_second)
            second_thread.start()
            self.assertTrue(second_started.wait(timeout=5))
            self.assertFalse(second_finished.wait(timeout=0.1))
            allow_first_save.set()
            first_thread.join(timeout=5)
            second_thread.join(timeout=5)

        self.assertFalse(first_thread.is_alive())
        self.assertFalse(second_thread.is_alive())
        self.assertIsInstance(results["first"], RelationshipState)
        self.assertIsInstance(results["second"], RelationshipState)
        self.assertEqual(
            [event.summary for event in self.store.load().events],
            ["The first shared token.", "The second shared token."],
        )

    def test_data_directory_symlink_created_after_config_validation_is_rejected(self) -> None:
        config = self.load_config()
        store = StateStore(config.data_dir)
        external_data_dir = self.root / "external-data"
        external_data_dir.mkdir()
        external_state = external_data_dir / "relationship.json"
        external_payload = b"external relationship data"
        external_state.write_bytes(external_payload)
        try:
            os.symlink(external_data_dir, config.data_dir, target_is_directory=True)
        except OSError as error:
            self.skipTest(f"symbolic links are unavailable: {error}")

        with self.assertRaisesRegex(StateError, "symbolic links"):
            store.load()

        self.assertEqual(external_state.read_bytes(), external_payload)

    def test_symlink_state_file_is_rejected_before_reading_or_replacing(self) -> None:
        self.store.path.parent.mkdir(parents=True)
        external_state = self.root / "external-relationship.json"
        external_payload = b"external relationship data"
        external_state.write_bytes(external_payload)
        try:
            os.symlink(external_state, self.store.path)
        except OSError as error:
            self.skipTest(f"symbolic links are unavailable: {error}")

        with self.assertRaisesRegex(StateError, "symbolic link"):
            self.store.load()
        with self.assertRaisesRegex(StateError, "symbolic link"):
            self.store._save(RelationshipState.default())

        self.assertEqual(external_state.read_bytes(), external_payload)

    def test_explicit_event_rejects_non_string_kinds_as_state_errors(self) -> None:
        for kind in ([], {}, None, 1):
            with self.subTest(kind=repr(kind)):
                with self.assertRaises(StateError):
                    self.store.record_explicit_event(kind, "A deliberate gesture.")

    def test_valid_persisted_history_loads_without_replaying_a_transition(self) -> None:
        events = [self.event_dict(index) for index in range(3)]
        self.write_state({"version": 1, "stage": "confirmed", "events": events, "pending_proposal": None})

        loaded = self.store.load()

        self.assertEqual(loaded.stage, "confirmed")
        self.assertEqual([event.id for event in loaded.events], [event["id"] for event in events])

    def test_v1_relationship_stages_migrate_as_stage_floors(self) -> None:
        for stage, count in (("trusted", 1), ("close", 2), ("confirmed", 3)):
            with self.subTest(stage=stage):
                store = StateStore(self.root / f"migrate-{stage}")
                store.path.parent.mkdir(parents=True)
                store.path.write_text(
                    json.dumps(
                        {
                            "version": 1,
                            "stage": stage,
                            "events": [self.event_dict(index) for index in range(count)],
                            "pending_proposal": None,
                        }
                    ),
                    encoding="utf-8",
                )

                loaded = store.load()
                persisted = json.loads(store.path.read_text(encoding="utf-8"))

                self.assertEqual((loaded.version, loaded.stage, loaded.stage_floor), (2, stage, stage))
                self.assertEqual((persisted["version"], persisted["stage_floor"]), (2, stage))

    def test_v2_stage_floor_cannot_exceed_legacy_memory_history(self) -> None:
        self.write_state(
            {
                "version": 2,
                "stage": "confirmed",
                "stage_floor": "confirmed",
                "events": [],
                "pending_proposal": None,
            }
        )

        self.assertEqual(self.store.load(), RelationshipState.default())
        self.assertEqual(len(list(self.store.path.parent.glob("relationship.json.corrupt-*"))), 1)

    def test_stage_must_match_confirmed_memory_history(self) -> None:
        invalid_states = (
            ("trusted", []),
            ("close", [self.event_dict(0)]),
            ("confirmed", []),
            ("acquainted", [self.event_dict(0)]),
            ("trusted", [self.event_dict(0), self.event_dict(1)]),
        )

        for index, (stage, events) in enumerate(invalid_states):
            with self.subTest(stage=stage, events=events):
                store = StateStore(self.root / f"invalid-stage-{index}")
                store.path.parent.mkdir(parents=True)
                value = {"version": 1, "stage": stage, "events": events, "pending_proposal": None}
                store.path.write_text(json.dumps(value), encoding="utf-8")

                self.assertEqual(store.load(), RelationshipState.default())
                self.assertEqual(len(list(store.path.parent.glob("relationship.json.corrupt-*"))), 1)

    def test_bounded_history_retains_confirmed_memories(self) -> None:
        for summary in ("We learned to trust each other.", "We became close.", "We confirmed our relationship."):
            self.store.queue_memory(summary)
            self.store.confirm_pending()
        for index in range(MAX_EVENTS):
            self.store.record_explicit_event("gift", f"Gift {index}")

        state = self.store.load()

        self.assertEqual(state.stage, "acquainted")
        self.assertEqual(len(state.events), MAX_EVENTS)
        self.assertEqual(sum(event.kind == "memory" for event in state.events), 3)

    def test_full_memory_history_evicts_the_oldest_memory_for_a_new_gift(self) -> None:
        state = RelationshipState.from_dict(
            {
                "version": 2,
                "stage": "acquainted",
                "stage_floor": "acquainted",
                "events": [self.event_dict(index) for index in range(MAX_EVENTS)],
                "pending_proposal": None,
            }
        )
        self.store._save(state)

        updated = self.store.record_explicit_event("gift", "A gift that must be retained.")

        self.assertEqual(len(updated.events), MAX_EVENTS)
        self.assertEqual(updated.events[-1].kind, "gift")
        self.assertNotIn(state.events[0].id, {event.id for event in updated.events})

    def test_corrupt_state_is_preserved_then_replaced_with_default(self) -> None:
        self.store.load()
        self.store.path.write_text("{not json", encoding="utf-8")

        recovered = self.store.load()

        self.assertEqual(recovered.stage, STAGES[0])
        backups = list(self.store.path.parent.glob("relationship.json.corrupt-*"))
        self.assertEqual(len(backups), 1)
        self.assertEqual(backups[0].read_text(encoding="utf-8"), "{not json")
        self.assertEqual(json.loads(self.store.path.read_text(encoding="utf-8"))["stage"], STAGES[0])

    def test_oversized_state_is_preserved_before_decoding_and_replaced(self) -> None:
        self.store.path.parent.mkdir(parents=True)
        payload = b"{" + b"x" * MAX_STATE_FILE_BYTES
        self.store.path.write_bytes(payload)

        with patch("relationship_gateway.state.json.loads") as loads:
            recovered = self.store.load()

        self.assertEqual(recovered, RelationshipState.default())
        loads.assert_not_called()
        backups = list(self.store.path.parent.glob("relationship.json.corrupt-*"))
        self.assertEqual(len(backups), 1)
        self.assertEqual(backups[0].read_bytes(), payload)
        self.assertLessEqual(self.store.path.stat().st_size, MAX_STATE_FILE_BYTES)

    def test_maximum_astral_unicode_state_fits_the_read_cap_and_round_trips(self) -> None:
        summary = "\U0001F9E1" * MAX_SUMMARY_LENGTH
        expected = self.maximum_state(summary)

        self.store._save(expected)

        self.assertLess(self.store.path.stat().st_size, MAX_STATE_FILE_BYTES)
        self.assertEqual(self.store.load(), expected)

    def test_maximum_escaped_summary_state_fits_the_read_cap_and_round_trips(self) -> None:
        expected = self.maximum_state("\0" * MAX_SUMMARY_LENGTH)

        self.store._save(expected)

        self.assertLess(self.store.path.stat().st_size, MAX_STATE_FILE_BYTES)
        self.assertEqual(self.store.load(), expected)

    def test_deeply_nested_json_recursion_is_preserved_and_recovered(self) -> None:
        self.store.path.parent.mkdir(parents=True)
        payload = b"[" * 5_000 + b"]" * 5_000
        self.store.path.write_bytes(payload)

        with self.assertRaises(RecursionError):
            json.loads(payload)
        recovered = self.store.load()

        self.assertEqual(recovered, RelationshipState.default())
        backups = list(self.store.path.parent.glob("relationship.json.corrupt-*"))
        self.assertEqual(len(backups), 1)
        self.assertEqual(backups[0].read_bytes(), payload)

    @unittest.skipUnless(
        hasattr(sys, "set_int_max_str_digits"), "Python does not limit integer string conversions"
    )
    def test_5000_digit_json_number_is_preserved_and_recovered(self) -> None:
        self.store.path.parent.mkdir(parents=True)
        payload = b"9" * 5_000
        self.store.path.write_bytes(payload)
        original_limit = sys.get_int_max_str_digits()

        try:
            sys.set_int_max_str_digits(4_300)
            with self.assertRaises(ValueError):
                json.loads(payload)
            recovered = self.store.load()
        finally:
            sys.set_int_max_str_digits(original_limit)

        self.assertEqual(recovered, RelationshipState.default())
        backups = list(self.store.path.parent.glob("relationship.json.corrupt-*"))
        self.assertEqual(len(backups), 1)
        self.assertEqual(backups[0].read_bytes(), payload)

    def test_directory_at_state_path_is_preserved_then_replaced(self) -> None:
        self.store.path.parent.mkdir(parents=True)
        self.store.path.mkdir()
        (self.store.path / "preserve-me.txt").write_text("relationship data", encoding="utf-8")

        recovered = self.store.load()

        self.assertEqual(recovered, RelationshipState.default())
        backups = list(self.store.path.parent.glob("relationship.json.corrupt-*"))
        self.assertEqual(len(backups), 1)
        self.assertTrue(backups[0].is_dir())
        self.assertEqual((backups[0] / "preserve-me.txt").read_text(encoding="utf-8"), "relationship data")
        self.assertTrue(self.store.path.is_file())

    def test_permission_error_while_reading_preserves_valid_state(self) -> None:
        self.store.record_explicit_event("gift", "A carefully chosen gift.")
        payload = self.store.path.read_bytes()

        with patch("relationship_gateway.state.Path.open", side_effect=PermissionError("access denied")):
            with self.assertRaisesRegex(StateError, "could not read relationship state"):
                self.store.load()

        self.assertEqual(self.store.path.read_bytes(), payload)
        self.assertEqual(list(self.store.path.parent.glob("relationship.json.corrupt-*")), [])

    def test_failed_backup_preserves_corrupt_state_and_raises_state_error(self) -> None:
        self.store.path.parent.mkdir(parents=True)
        payload = b"{not json"
        self.store.path.write_bytes(payload)

        with patch("relationship_gateway.state.os.replace", side_effect=PermissionError("access denied")):
            with self.assertRaisesRegex(StateError, "could not preserve corrupt relationship state"):
                self.store.load()

        self.assertEqual(self.store.path.read_bytes(), payload)
        self.assertEqual(list(self.store.path.parent.glob("relationship.json.corrupt-*")), [])

    def test_failed_reset_keeps_backup_and_raises_state_error(self) -> None:
        self.store.path.parent.mkdir(parents=True)
        payload = b"{not json"
        self.store.path.write_bytes(payload)
        real_replace = os.replace

        def replace_only_backup(source: object, destination: object) -> None:
            if Path(source) == self.store.path:
                real_replace(source, destination)
                return
            raise PermissionError("access denied")

        with patch("relationship_gateway.state.os.replace", side_effect=replace_only_backup):
            with self.assertRaisesRegex(StateError, "could not reset relationship state after preserving it"):
                self.store.load()

        backups = list(self.store.path.parent.glob("relationship.json.corrupt-*"))
        self.assertEqual(len(backups), 1)
        self.assertEqual(backups[0].read_bytes(), payload)
        self.assertFalse(os.path.lexists(self.store.path))

    def test_json_valid_malformed_state_is_preserved_and_recovered(self) -> None:
        malformed_states = (
            {"version": True, "stage": "acquainted", "events": [], "pending_proposal": None},
            {"version": "1", "stage": "acquainted", "events": [], "pending_proposal": None},
            {"version": 1.0, "stage": "acquainted", "events": [], "pending_proposal": None},
            {
                "version": 1,
                "stage": "acquainted",
                "events": [{**self.event_dict(), "kind": []}],
                "pending_proposal": None,
            },
            {
                "version": 1,
                "stage": "acquainted",
                "events": [{**self.event_dict(), "kind": {}}],
                "pending_proposal": None,
            },
        )

        for index, value in enumerate(malformed_states):
            with self.subTest(value=value):
                store = StateStore(self.root / f"malformed-{index}")
                store.path.parent.mkdir(parents=True)
                store.path.write_text(json.dumps(value), encoding="utf-8")

                recovered = store.load()

                self.assertEqual(recovered, RelationshipState.default())
                backups = list(store.path.parent.glob("relationship.json.corrupt-*"))
                self.assertEqual(len(backups), 1)
                self.assertEqual(json.loads(backups[0].read_text(encoding="utf-8")), value)

    def test_uuid_ids_are_canonicalized_before_duplicate_checks(self) -> None:
        event = self.event_dict()
        uppercase_event = {**event, "id": event["id"].upper()}
        parsed = RelationshipState.from_dict(
            {"version": 1, "stage": "trusted", "events": [uppercase_event], "pending_proposal": None}
        )
        self.assertEqual(parsed.events[0].id, event["id"])

        self.write_state(
            {"version": 1, "stage": "trusted", "events": [event, uppercase_event], "pending_proposal": None}
        )
        self.assertEqual(self.store.load(), RelationshipState.default())
        self.assertEqual(len(list(self.store.path.parent.glob("relationship.json.corrupt-*"))), 1)

    def test_trailing_z_timestamps_load_on_python_310(self) -> None:
        event = {**self.event_dict(), "timestamp": "2026-07-11T00:00:00Z"}
        pending_id = "550e8400-e29b-41d4-a716-000000000999"
        self.write_state(
            {
                "version": 1,
                "stage": "trusted",
                "events": [event],
                "pending_proposal": {
                    "id": pending_id,
                    "kind": "memory",
                    "summary": "A moment we want to remember.",
                    "created_at": "2026-07-11T00:00:00Z",
                },
            }
        )

        loaded = self.store.load()

        self.assertEqual(loaded.events[0].timestamp, "2026-07-11T00:00:00Z")
        self.assertIsNotNone(loaded.pending_proposal)
        self.assertEqual(loaded.pending_proposal.created_at, "2026-07-11T00:00:00Z")

    def test_event_history_and_context_are_bounded(self) -> None:
        for index in range(MAX_EVENTS + 2):
            self.store.record_explicit_event("gift", f"{index:03d}-" + "x" * (240 - 4))

        state = self.store.load()

        self.assertEqual(len(state.events), MAX_EVENTS)
        self.assertTrue(state.events[0].summary.startswith("002-"))
        self.assertEqual(len(state.context_events), MAX_CONTEXT_EVENTS)
        self.assertTrue(state.context_events[0].summary.startswith("094-"))
        self.assertTrue(all(len(event.summary) <= MAX_CONTEXT_SUMMARY_LENGTH for event in state.context_events))

    @staticmethod
    def event_dict(index: int = 0) -> dict[str, str]:
        return {
            "id": f"550e8400-e29b-41d4-a716-{index:012d}",
            "kind": "memory",
            "summary": "A meaningful shared moment.",
            "timestamp": "2026-07-11T00:00:00+00:00",
        }

    @staticmethod
    def maximum_state(summary: str) -> RelationshipState:
        timestamp = "2026-07-11T00:00:00.123456+23:59:59.123456"
        assert len(timestamp) == MAX_TIMESTAMP_LENGTH
        return RelationshipState.from_dict(
            {
                "version": 1,
                "stage": "acquainted",
                "events": [
                    {
                        "id": f"550e8400-e29b-41d4-a716-{index:012d}",
                        "kind": "anniversary",
                        "summary": summary,
                        "timestamp": timestamp,
                    }
                    for index in range(MAX_EVENTS)
                ],
                "pending_proposal": {
                    "id": "550e8400-e29b-41d4-a716-000000000999",
                    "kind": "memory",
                    "summary": summary,
                    "created_at": timestamp,
                },
            }
        )

    def write_state(self, value: dict[str, object]) -> None:
        self.store.path.parent.mkdir(parents=True, exist_ok=True)
        self.store.path.write_text(json.dumps(value), encoding="utf-8")


if __name__ == "__main__":
    unittest.main()
