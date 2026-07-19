"""Validated, atomically persisted relationship state."""

from __future__ import annotations

import json
import os
import stat
import tempfile
import threading
from dataclasses import dataclass, replace
from datetime import datetime, timedelta, timezone
from pathlib import Path
from uuid import UUID, uuid4


LEGACY_SCHEMA_VERSION = 1
SCHEMA_VERSION = 2
STAGES = ("acquainted", "trusted", "close", "confirmed")
STAGE_THRESHOLDS = ((10, 7, 10), (30, 20, 30), (70, 40, 60))
EVENT_KINDS = frozenset(("memory", "gift", "anniversary"))
MAX_SUMMARY_LENGTH = 240
MAX_EVENTS = 100
MAX_CONTEXT_EVENTS = 8
MAX_CONTEXT_SUMMARY_LENGTH = 120
MAX_TIMESTAMP_LENGTH = 42
MAX_STATE_FILE_BYTES = 192 * 1024
MAX_STORY_FILE_BYTES = 48 * 1024
STORY_EXPRESSIONS = frozenset((
    "neutral", "happy", "shy", "worried", "relieved", "thoughtful", "serious",
    "awkward", "hurt", "surprised", "sleepy", "moved",
))

_LOCK_REGISTRY_GUARD = threading.Lock()
_LOCKS_BY_DATA_DIR: dict[str, threading.RLock] = {}


class StateError(ValueError):
    """Raised when relationship data breaks its local schema."""


@dataclass(frozen=True)
class RelationshipEvent:
    id: str
    kind: str
    summary: str
    timestamp: str

    def to_dict(self) -> dict[str, str]:
        return {
            "id": self.id,
            "kind": self.kind,
            "summary": self.summary,
            "timestamp": self.timestamp,
        }

    @classmethod
    def from_dict(cls, value: object) -> "RelationshipEvent":
        _require_exact_keys(value, {"id", "kind", "summary", "timestamp"}, "event")
        assert isinstance(value, dict)
        return cls(
            id=_validate_id(value["id"], "event id"),
            kind=_validate_event_kind(value["kind"]),
            summary=_validate_summary(value["summary"]),
            timestamp=_validate_timestamp(value["timestamp"], "event timestamp"),
        )


@dataclass(frozen=True)
class PendingProposal:
    id: str
    kind: str
    summary: str
    created_at: str

    def to_dict(self) -> dict[str, str]:
        return {
            "id": self.id,
            "kind": self.kind,
            "summary": self.summary,
            "created_at": self.created_at,
        }

    @classmethod
    def from_dict(cls, value: object) -> "PendingProposal":
        _require_exact_keys(value, {"id", "kind", "summary", "created_at"}, "pending proposal")
        assert isinstance(value, dict)
        return cls(
            id=_validate_id(value["id"], "proposal id"),
            kind=_validate_event_kind(value["kind"]),
            summary=_validate_summary(value["summary"]),
            created_at=_validate_timestamp(value["created_at"], "proposal timestamp"),
        )


@dataclass(frozen=True)
class StoryLine:
    speaker: str
    text: str
    expression: str
    scene: str | None = None
    sprite: str | None = None

    def to_dict(self) -> dict[str, str]:
        result = {"speaker": self.speaker, "text": self.text, "expression": self.expression}
        if self.scene is not None and self.sprite is not None:
            result["scene"] = self.scene
            result["sprite"] = self.sprite
        return result

    @classmethod
    def from_dict(cls, value: object) -> "StoryLine":
        legacy_keys = {"speaker", "text", "expression"}
        visual_keys = legacy_keys | {"scene", "sprite"}
        if not isinstance(value, dict) or set(value) not in (legacy_keys, visual_keys):
            raise StateError("story line has unknown or missing fields")
        assert isinstance(value, dict)
        speaker = value["speaker"]
        text = value["text"]
        expression = value["expression"]
        scene = value.get("scene")
        sprite = value.get("sprite")
        if not isinstance(speaker, str) or speaker not in {"旁白", "流萤"}:
            raise StateError("story speaker is unknown")
        if not isinstance(text, str) or not text.strip() or text != text.strip() or len(text) > 160:
            raise StateError("story text must contain 1 to 160 trimmed characters")
        if any(ord(character) < 32 or 127 <= ord(character) <= 159 for character in text):
            raise StateError("story text contains control characters")
        if not isinstance(expression, str) or expression not in STORY_EXPRESSIONS:
            raise StateError("story expression is unknown")
        if (scene is None) != (sprite is None):
            raise StateError("story visual state is incomplete")
        if scene is not None and (
            not isinstance(scene, str)
            or not isinstance(sprite, str)
            or not scene
            or not sprite
            or len(scene) > 80
            or len(sprite) > 80
            or any(ord(character) < 32 for character in scene + sprite)
        ):
            raise StateError("story visual state is invalid")
        return cls(speaker=speaker, text=text, expression=expression, scene=scene, sprite=sprite)


@dataclass(frozen=True)
class StoryContinuation:
    choice: str
    lines: tuple[StoryLine, ...]

    @classmethod
    def from_dict(cls, value: object) -> "StoryContinuation":
        _require_exact_keys(value, {"choice", "lines"}, "story continuation")
        assert isinstance(value, dict)
        if value["choice"] not in {"near", "space"}:
            raise StateError("story continuation choice is unknown")
        return cls(
            choice=value["choice"],
            lines=_validate_story_lines(value["lines"], "story continuation", 3, 5),
        )


@dataclass(frozen=True)
class StoryScript:
    version: int
    chapter_id: str
    opening: tuple[StoryLine, ...]
    near: tuple[StoryLine, ...]
    space: tuple[StoryLine, ...]

    def to_dict(self) -> dict[str, object]:
        return {
            "version": self.version,
            "chapter_id": self.chapter_id,
            "opening": [line.to_dict() for line in self.opening],
            "branches": {
                "near": [line.to_dict() for line in self.near],
                "space": [line.to_dict() for line in self.space],
            },
        }

    @classmethod
    def from_dict(cls, value: object) -> "StoryScript":
        _require_exact_keys(value, {"version", "chapter_id", "opening", "branches"}, "story")
        assert isinstance(value, dict)
        if value["version"] != 1 or value["chapter_id"] != "acquainted-approach-1":
            raise StateError("story version or chapter is unsupported")
        branches = value["branches"]
        _require_exact_keys(branches, {"near", "space"}, "story branches")
        assert isinstance(branches, dict)
        opening = _validate_story_lines(value["opening"], "opening", 6, 10)
        near = _validate_story_lines(branches["near"], "near branch", 3, 5)
        space = _validate_story_lines(branches["space"], "space branch", 3, 5)
        return cls(version=1, chapter_id=value["chapter_id"], opening=opening, near=near, space=space)

    def branch(self, choice: str) -> tuple[StoryLine, ...]:
        if choice == "near":
            return self.near
        if choice == "space":
            return self.space
        raise StateError("story branch is unknown")


def default_story_script() -> StoryScript:
    """Return the fixed fallback used only when model generation fails."""
    return StoryScript.from_dict(
        {
            "version": 1,
            "chapter_id": "acquainted-approach-1",
            "opening": [
                {"speaker": "旁白", "text": "清晨的光越过窗帘，客厅里只剩下时钟轻微的走动声。", "expression": "neutral"},
                {"speaker": "流萤", "text": "你醒了吗？我没有吵到你吧。", "expression": "worried"},
                {"speaker": "旁白", "text": "她站在沙发旁，手指无意识地收紧，像是在确认自己是否越过了界线。", "expression": "worried"},
                {"speaker": "流萤", "text": "最近和你说话的时候，我总会忘记时间。", "expression": "shy"},
                {"speaker": "流萤", "text": "可我又担心，靠得太近会让你觉得有负担。", "expression": "worried"},
                {"speaker": "旁白", "text": "她抬起眼睛，认真等着你的回答。", "expression": "worried"},
                {"speaker": "流萤", "text": "如果我想在这里多待一会儿，你希望我怎么做？", "expression": "worried"},
            ],
            "branches": {
                "near": [
                    {"speaker": "旁白", "text": "你向旁边挪出位置，示意她坐近一些。", "expression": "neutral"},
                    {"speaker": "流萤", "text": "真的可以吗？那我就……稍微靠近一点。", "expression": "shy"},
                    {"speaker": "旁白", "text": "她的肩膀慢慢放松下来，晨光落在微微扬起的嘴角。", "expression": "happy"},
                    {"speaker": "流萤", "text": "谢谢你告诉我答案。以后我也会认真听你的感受。", "expression": "happy"},
                ],
                "space": [
                    {"speaker": "旁白", "text": "你没有立刻靠近，只告诉她不必为了陪伴勉强自己。", "expression": "neutral"},
                    {"speaker": "流萤", "text": "原来保持一点距离，也不代表你希望我离开。", "expression": "relieved"},
                    {"speaker": "旁白", "text": "她在另一侧坐下，安静却不再局促。", "expression": "relieved"},
                    {"speaker": "流萤", "text": "我明白了。能这样待在同一个地方，也已经很好。", "expression": "happy"},
                ],
            },
        }
    )


@dataclass(frozen=True)
class RelationshipState:
    version: int
    stage: str
    stage_floor: str
    events: tuple[RelationshipEvent, ...]
    pending_proposal: PendingProposal | None

    @classmethod
    def default(cls) -> "RelationshipState":
        return cls(
            version=SCHEMA_VERSION,
            stage=STAGES[0],
            stage_floor=STAGES[0],
            events=(),
            pending_proposal=None,
        )

    def to_dict(self) -> dict[str, object]:
        return {
            "version": self.version,
            "stage": self.stage,
            "stage_floor": self.stage_floor,
            "events": [event.to_dict() for event in self.events],
            "pending_proposal": None if self.pending_proposal is None else self.pending_proposal.to_dict(),
        }

    @property
    def context_events(self) -> tuple[RelationshipEvent, ...]:
        """The bounded recent event subset intended for model context."""
        return tuple(
            replace(event, summary=event.summary[:MAX_CONTEXT_SUMMARY_LENGTH])
            for event in self.events[-MAX_CONTEXT_EVENTS:]
        )

    @classmethod
    def from_dict(cls, value: object) -> "RelationshipState":
        if not isinstance(value, dict) or type(value.get("version")) is not int:
            raise StateError("state has unknown or missing fields")
        version = value["version"]
        if version == LEGACY_SCHEMA_VERSION:
            _require_exact_keys(value, {"version", "stage", "events", "pending_proposal"}, "state")
        elif version == SCHEMA_VERSION:
            _require_exact_keys(
                value, {"version", "stage", "stage_floor", "events", "pending_proposal"}, "state"
            )
        else:
            raise StateError(f"unsupported state version: {value['version']!r}")
        if not isinstance(value["stage"], str) or value["stage"] not in STAGES:
            raise StateError("unknown relationship stage")
        if not isinstance(value["events"], list):
            raise StateError("events must be a list")
        if len(value["events"]) > MAX_EVENTS:
            raise StateError(f"events must contain at most {MAX_EVENTS} entries")
        events = tuple(RelationshipEvent.from_dict(event) for event in value["events"])
        if len({event.id for event in events}) != len(events):
            raise StateError("event ids must be unique")
        if version == LEGACY_SCHEMA_VERSION:
            if value["stage"] != _legacy_stage_from_confirmed_memories(events):
                raise StateError("relationship stage does not match confirmed memory history")
            stage_floor = value["stage"]
        else:
            stage_floor = value["stage_floor"]
            if not isinstance(stage_floor, str) or stage_floor not in STAGES:
                raise StateError("unknown relationship stage floor")
            if STAGES.index(stage_floor) > STAGES.index(_legacy_stage_from_confirmed_memories(events)):
                raise StateError("relationship stage floor does not match confirmed memory history")
            if value["stage"] != _later_stage(stage_floor, _stage_from_confirmed_memories(events)):
                raise StateError("relationship stage does not match confirmed memory history")

        pending_value = value["pending_proposal"]
        if pending_value is None:
            pending = None
        else:
            pending = PendingProposal.from_dict(pending_value)
            if pending.id in {event.id for event in events}:
                raise StateError("proposal id is already used by an event")
        return cls(
            version=SCHEMA_VERSION,
            stage=value["stage"],
            stage_floor=stage_floor,
            events=events,
            pending_proposal=pending,
        )


class StateStore:
    """Owns `relationship.json` and the allowed relationship changes."""

    def __init__(self, data_dir: str | Path) -> None:
        self._data_dir = Path(os.path.abspath(data_dir))
        self.path = self._data_dir / "relationship.json"
        self.story_path = self._data_dir / "story.json"
        canonical_data_dir = str(self._data_dir.resolve(strict=False))
        with _LOCK_REGISTRY_GUARD:
            self._lock = _LOCKS_BY_DATA_DIR.setdefault(canonical_data_dir, threading.RLock())
        # ponytail: process-wide only; use a file lock or SQLite for multi-process writers.
        self._assert_safe_paths()
        self._remove_legacy_story()

    def load(self) -> RelationshipState:
        with self._lock:
            return self._load()

    def _load(self) -> RelationshipState:
        self._assert_safe_paths()
        try:
            metadata = self.path.stat()
        except FileNotFoundError:
            try:
                path_metadata = os.lstat(self.path)
            except FileNotFoundError:
                return self._save(RelationshipState.default())
            except OSError as error:
                raise StateError(f"could not inspect relationship state at {self.path}: {error}") from error
            if stat.S_ISLNK(path_metadata.st_mode):
                return self._recover_corrupt_state()
            raise StateError(f"could not inspect relationship state at {self.path}: state changed while reading")
        except OSError as error:
            raise StateError(f"could not inspect relationship state at {self.path}: {error}") from error

        if not stat.S_ISREG(metadata.st_mode):
            return self._recover_corrupt_state()

        try:
            if metadata.st_size > MAX_STATE_FILE_BYTES:
                raise StateError(f"state file exceeds {MAX_STATE_FILE_BYTES} bytes")
            with self.path.open("rb") as state_file:
                payload = state_file.read(MAX_STATE_FILE_BYTES + 1)
            if len(payload) > MAX_STATE_FILE_BYTES:
                raise StateError(f"state file exceeds {MAX_STATE_FILE_BYTES} bytes")
            value = json.loads(payload.decode("utf-8"))
            state = RelationshipState.from_dict(value)
            return self._save(state) if value.get("version") == LEGACY_SCHEMA_VERSION else state
        except (UnicodeDecodeError, json.JSONDecodeError, RecursionError, StateError, TypeError, ValueError):
            return self._recover_corrupt_state()
        except OSError as error:
            raise StateError(f"could not read relationship state at {self.path}: {error}") from error

    def _save(self, state: RelationshipState) -> RelationshipState:
        if not isinstance(state, RelationshipState):
            raise StateError("state must be a RelationshipState")
        validated = RelationshipState.from_dict(state.to_dict())
        self._ensure_safe_data_dir()
        payload = json.dumps(
            validated.to_dict(), ensure_ascii=False, separators=(",", ":"), sort_keys=True
        ).encode("utf-8", "backslashreplace")
        if len(payload) > MAX_STATE_FILE_BYTES:
            raise StateError(f"state file exceeds {MAX_STATE_FILE_BYTES} bytes")
        file_descriptor, temporary_path = tempfile.mkstemp(
            dir=self.path.parent,
            prefix=f".{self.path.name}.",
            suffix=".tmp",
        )
        try:
            with os.fdopen(file_descriptor, "wb") as temporary_file:
                temporary_file.write(payload)
                temporary_file.flush()
                os.fsync(temporary_file.fileno())
            self._assert_safe_paths()
            os.replace(temporary_path, self.path)
        finally:
            if os.path.exists(temporary_path):
                os.unlink(temporary_path)
        return validated

    def queue_memory(self, summary: str) -> RelationshipState:
        return self.queue_proposal("memory", summary)

    def load_story(self) -> StoryScript | None:
        return None

    def save_story(self, value: object) -> StoryScript:
        del value
        raise StateError("legacy story scripts are disabled")

    def _remove_legacy_story(self) -> None:
        """Delete only the obsolete story.json entry without following links."""
        try:
            metadata = os.lstat(self.story_path)
        except FileNotFoundError:
            return
        except OSError as error:
            raise StateError(f"could not inspect legacy story state at {self.story_path}: {error}") from error
        if stat.S_ISREG(metadata.st_mode) or stat.S_ISLNK(metadata.st_mode):
            try:
                self.story_path.unlink()
            except OSError as error:
                raise StateError(f"could not remove legacy story state at {self.story_path}: {error}") from error

    def queue_proposal(self, kind: str, summary: str) -> RelationshipState:
        kind = _validate_event_kind(kind)
        summary = _validate_summary(summary)
        with self._lock:
            state = self.load()
            if state.pending_proposal is not None:
                raise StateError("a relationship proposal is already pending")
            if kind != "memory" and any(
                event.kind == kind and _normalized_summary(event.summary) == _normalized_summary(summary)
                for event in state.events
            ):
                return state
            pending = PendingProposal(
                id=str(uuid4()), kind=kind, summary=summary, created_at=_now()
            )
            return self._save(replace(state, pending_proposal=pending))

    def confirm_pending(self) -> RelationshipState:
        with self._lock:
            state = self.load()
            if state.pending_proposal is None:
                raise StateError("there is no pending proposal")
            pending = state.pending_proposal
            event = RelationshipEvent(
                id=pending.id, kind=pending.kind, summary=pending.summary, timestamp=_now()
            )
            events = _append_event(state.events, event)
            stage_floor, stage = _stage_after_confirmed_memory(state, events)
            return self._save(
                replace(
                    state,
                    stage=stage if pending.kind == "memory" else state.stage,
                    stage_floor=stage_floor,
                    events=events,
                    pending_proposal=None,
                )
            )

    def dismiss_pending(self) -> RelationshipState:
        with self._lock:
            state = self.load()
            if state.pending_proposal is None:
                raise StateError("there is no pending proposal")
            return self._save(replace(state, pending_proposal=None))

    def record_explicit_event(self, kind: str, summary: str) -> RelationshipState:
        if not isinstance(kind, str) or kind not in {"gift", "anniversary"}:
            raise StateError("only explicit gifts and anniversaries can be recorded directly")
        with self._lock:
            state = self.load()
            event = RelationshipEvent(id=str(uuid4()), kind=kind, summary=_validate_summary(summary), timestamp=_now())
            events = _append_event(state.events, event)
            stage_floor, _stage = _stage_after_confirmed_memory(state, events)
            return self._save(replace(state, stage_floor=stage_floor, events=events))

    def record_confirmed_proposal(self, kind: str, summary: str) -> RelationshipState:
        """Atomically persist one user-confirmed model proposal."""
        kind = _validate_event_kind(kind)
        summary = _validate_summary(summary)
        with self._lock:
            state = self.load()
            if any(
                event.kind == kind and _normalized_summary(event.summary) == _normalized_summary(summary)
                for event in state.events
            ):
                return state
            pending = state.pending_proposal
            matching_pending = (
                pending is not None
                and pending.kind == kind
                and _normalized_summary(pending.summary) == _normalized_summary(summary)
            )
            event = RelationshipEvent(
                id=pending.id if matching_pending else str(uuid4()),
                kind=kind,
                summary=summary,
                timestamp=_now(),
            )
            events = _append_event(state.events, event)
            stage_floor, stage = _stage_after_confirmed_memory(state, events)
            return self._save(
                replace(
                    state,
                    stage=stage if kind == "memory" else state.stage,
                    stage_floor=stage_floor,
                    events=events,
                    pending_proposal=None if matching_pending else pending,
                )
            )

    def _recover_corrupt_state(self) -> RelationshipState:
        self._assert_safe_paths()
        backup_path = self.path.with_name(
            f"{self.path.name}.corrupt-{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')}-{uuid4().hex}"
        )
        try:
            os.replace(self.path, backup_path)
        except OSError as error:
            raise StateError(f"could not preserve corrupt relationship state at {self.path}: {error}") from error
        try:
            return self._save(RelationshipState.default())
        except (OSError, StateError) as error:
            raise StateError(f"could not reset relationship state after preserving it at {backup_path}: {error}") from error

    def _recover_corrupt_story(self) -> None:
        self._assert_safe_file(self.story_path, "story")
        backup_path = self.story_path.with_name(
            f"{self.story_path.name}.corrupt-{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')}-{uuid4().hex}"
        )
        try:
            os.replace(self.story_path, backup_path)
        except FileNotFoundError:
            return None
        except OSError as error:
            raise StateError(f"could not preserve corrupt story state at {self.story_path}: {error}") from error
        return None

    def _ensure_safe_data_dir(self) -> None:
        self._assert_safe_paths()
        try:
            self._data_dir.mkdir(parents=True, exist_ok=True)
        except OSError as error:
            raise StateError(f"could not create relationship data directory at {self._data_dir}: {error}") from error
        self._assert_safe_paths()

    def _assert_safe_paths(self) -> None:
        current = Path(self._data_dir.anchor)
        for part in self._data_dir.parts[1:]:
            current /= part
            try:
                metadata = os.lstat(current)
            except FileNotFoundError:
                break
            except OSError as error:
                raise StateError(f"could not inspect relationship data directory at {self._data_dir}: {error}") from error
            if stat.S_ISLNK(metadata.st_mode):
                raise StateError("relationship data directory must not contain symbolic links")
            if current != self._data_dir and not stat.S_ISDIR(metadata.st_mode):
                raise StateError("relationship data directory must not have a non-directory ancestor")
            if current == self._data_dir and not stat.S_ISDIR(metadata.st_mode):
                raise StateError("relationship data directory must be a directory")

        try:
            metadata = os.lstat(self.path)
        except FileNotFoundError:
            return
        except OSError as error:
            raise StateError(f"could not inspect relationship state at {self.path}: {error}") from error
        if stat.S_ISLNK(metadata.st_mode):
            raise StateError("relationship state file must not be a symbolic link")

    def _assert_safe_file(self, path: Path, label: str) -> None:
        try:
            metadata = os.lstat(path)
        except FileNotFoundError:
            return
        except OSError as error:
            raise StateError(f"could not inspect {label} state at {path}: {error}") from error
        if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISREG(metadata.st_mode):
            raise StateError(f"{label} state file must be a regular file")


def _later_stage(first: str, second: str) -> str:
    try:
        return STAGES[max(STAGES.index(first), STAGES.index(second))]
    except ValueError as error:
        raise StateError("unknown relationship stage") from error


def _validate_story_lines(
    value: object, name: str, minimum: int, maximum: int
) -> tuple[StoryLine, ...]:
    if not isinstance(value, list) or not minimum <= len(value) <= maximum:
        raise StateError(f"{name} must contain {minimum} to {maximum} lines")
    return tuple(StoryLine.from_dict(line) for line in value)


def _append_event(
    events: tuple[RelationshipEvent, ...], event: RelationshipEvent
) -> tuple[RelationshipEvent, ...]:
    events = (*events, event)
    if len(events) <= MAX_EVENTS:
        return events
    for index, existing_event in enumerate(events[:-1]):
        if existing_event.kind != "memory":
            return events[:index] + events[index + 1 :]
    return events[1:]


def _stage_after_confirmed_memory(
    state: RelationshipState, events: tuple[RelationshipEvent, ...]
) -> tuple[str, str]:
    stage_floor = _later_stage(state.stage_floor, state.stage)
    return stage_floor, _later_stage(stage_floor, _stage_from_confirmed_memories(events))


def _stage_from_confirmed_memories(events: tuple[RelationshipEvent, ...]) -> str:
    memory_times = [
        _parse_timestamp(event.timestamp).astimezone(timezone.utc)
        for event in events
        if event.kind == "memory"
    ]
    if not memory_times:
        return STAGES[0]
    count = len(memory_times)
    distinct_days = len({timestamp.date() for timestamp in memory_times})
    elapsed = max(memory_times) - min(memory_times)
    stage = STAGES[0]
    for index, (required_count, required_days, required_elapsed) in enumerate(STAGE_THRESHOLDS, 1):
        if (
            count >= required_count
            and distinct_days >= required_days
            and elapsed >= timedelta(days=required_elapsed)
        ):
            stage = STAGES[index]
    return stage


def _legacy_stage_from_confirmed_memories(events: tuple[RelationshipEvent, ...]) -> str:
    confirmed_memories = sum(event.kind == "memory" for event in events)
    return STAGES[min(confirmed_memories, len(STAGES) - 1)]


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _require_exact_keys(value: object, expected: set[str], name: str) -> None:
    if not isinstance(value, dict) or set(value) != expected:
        raise StateError(f"{name} has unknown or missing fields")


def _validate_id(value: object, name: str) -> str:
    if not isinstance(value, str):
        raise StateError(f"{name} must be a UUID")
    try:
        parsed = UUID(value)
    except (ValueError, AttributeError) as error:
        raise StateError(f"{name} must be a UUID") from error
    if parsed.version != 4:
        raise StateError(f"{name} must be a version 4 UUID")
    return str(parsed)


def _validate_event_kind(value: object) -> str:
    if not isinstance(value, str) or value not in EVENT_KINDS:
        raise StateError("event kind is unknown")
    return value


def _validate_summary(value: object) -> str:
    if not isinstance(value, str) or not value.strip() or len(value) > MAX_SUMMARY_LENGTH:
        raise StateError(f"summary must contain 1 to {MAX_SUMMARY_LENGTH} non-blank characters")
    if value != value.strip():
        raise StateError("summary must not have leading or trailing whitespace")
    return value


def _normalized_summary(value: str) -> str:
    return " ".join(value.split()).casefold()


def _validate_timestamp(value: object, name: str) -> str:
    if not isinstance(value, str):
        raise StateError(f"{name} must be an ISO 8601 timestamp")
    try:
        parsed = _parse_timestamp(value)
    except ValueError as error:
        raise StateError(f"{name} must be an ISO 8601 timestamp") from error
    if parsed.tzinfo is None:
        raise StateError(f"{name} must include a timezone")
    return value if len(value) <= MAX_TIMESTAMP_LENGTH else parsed.isoformat()


def _parse_timestamp(value: str) -> datetime:
    return datetime.fromisoformat(value[:-1] + "+00:00" if value.endswith("Z") else value)
