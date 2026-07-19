"""Data-driven chapter framework for personalized relationship stories."""

from __future__ import annotations

import json
import os
import stat
import tempfile
import threading
from dataclasses import dataclass, replace
from datetime import date
from pathlib import Path

from .state import STAGES, StateError, StoryLine
from .visual_assets import visual_asset_ids


NARRATIVE_VERSION = 1
OUTCOMES = frozenset(("good", "neutral", "bad"))
MAX_AXIS_VALUE = 40
MAX_NARRATIVE_FILE_BYTES = 64 * 1024
MAX_SESSION_FILE_BYTES = 256 * 1024
MAX_ARCHIVE_FILE_BYTES = 8 * 1024 * 1024
MAX_ARCHIVED_SESSIONS = 40
SESSION_VERSION = 3
ARCHIVE_VERSION = 1
NEXT_NODE_TYPES = frozenset(("free_input", "choice", "complete"))
CHAPTER_ONE_FINALE_ID = "chapter-1-finale"


@dataclass(frozen=True)
class StoryEventDefinition:
    id: str
    title: str
    purpose: str
    personalized: bool = False


@dataclass(frozen=True)
class ChapterDefinition:
    id: str
    stage: str
    title: str
    focus: str
    expected_days: tuple[int, int]
    minimum_active_days: int
    core_event_target: int
    interaction_nodes_per_event: tuple[int, int]
    line_count_per_event: tuple[int, int]
    finale_title: str
    intimacy_boundary: str
    required_axes: tuple[int, int, int, int]
    events: tuple[StoryEventDefinition, ...] = ()
    future_directions: tuple[str, ...] = ()

    @property
    def required_event_ids(self) -> tuple[str, ...]:
        return tuple(event.id for event in self.events if not event.personalized)


CHAPTERS = (
    ChapterDefinition(
        id="chapter-1-acquainted",
        stage="acquainted",
        title="初识 · 把名字留在今天",
        focus="从陌生到愿意继续认识，建立交流节奏与基本边界。",
        expected_days=(7, 9),
        minimum_active_days=7,
        core_event_target=8,
        interaction_nodes_per_event=(14, 18),
        line_count_per_event=(120, 160),
        finale_title="下次还可以见面吗",
        intimacy_boundary="不开放专属昵称、主动拥抱、占有欲或明显依赖；越界请求会被温和拒绝。",
        required_axes=(10, 6, 8, 5),
        events=(
            StoryEventDefinition("first-greeting", "第一次认真打招呼", "建立用户偏好的交流节奏。"),
            StoryEventDefinition("conversation-rhythm", "你习惯怎样聊天", "理解主动交流、简短回应和安静陪伴的差异。"),
            StoryEventDefinition("small-task", "一起完成一件小事", "从近期日常对话生成共同经历。"),
            StoryEventDefinition("remembered-detail", "她记住了一点什么", "允许用户确认、纠正或回避被记住的细节。"),
            StoryEventDefinition("early-boundary", "还不能使用的称呼", "测试昵称、隐私问题和身体距离的阶段边界。"),
            StoryEventDefinition("small-misunderstanding", "一次轻微误解", "根据既有语气生成合理且不过度戏剧化的分歧。"),
            StoryEventDefinition("clarification", "把意思说清楚", "让解释、道歉、沉默或回避产生持续影响。"),
            StoryEventDefinition("meet-again", "下次还可以见面吗", "只确认愿意继续认识，不提前产生依赖。"),
            StoryEventDefinition("personalized-interlude-1", "用户专属插曲一", "从近期日常对话生成。", True),
            StoryEventDefinition("personalized-interlude-2", "用户专属插曲二", "从近期日常对话生成。", True),
        ),
    ),
    ChapterDefinition(
        id="chapter-2-trusted",
        stage="trusted",
        title="信赖 · 愿意被你看见",
        focus="从熟悉到愿意交付脆弱，学习稳定回应与修复失约。",
        expected_days=(8, 11),
        minimum_active_days=8,
        core_event_target=8,
        interaction_nodes_per_event=(14, 18),
        line_count_per_event=(120, 160),
        finale_title="有事情时，我可以来找你吗",
        intimacy_boundary="允许更真实的情绪与有限主动求助，但不开放明确占有和强依赖。",
        required_axes=(18, 14, 14, 12),
        future_directions=("交付脆弱", "失约与修复", "双向支持", "第一次主动求助"),
    ),
    ChapterDefinition(
        id="chapter-3-close",
        stage="close",
        title="亲近 · 成为重要的人",
        focus="从信赖到重要，逐步形成专属称呼、共同习惯与轻度依赖。",
        expected_days=(9, 12),
        minimum_active_days=9,
        core_event_target=8,
        interaction_nodes_per_event=(14, 18),
        line_count_per_event=(120, 160),
        finale_title="我已经开始期待你出现了",
        intimacy_boundary="满足前置条件后才开放专属昵称、主动靠近和表达想念。",
        required_axes=(27, 22, 20, 20),
        future_directions=("专属称呼", "共同习惯", "短暂错开", "承认想念"),
    ),
    ChapterDefinition(
        id="chapter-4-confirmed",
        stage="confirmed",
        title="羁绊 · 不可替代但仍然自由",
        focus="确认稳定、双向且有边界的依赖，不把陪伴写成控制或失去自我。",
        expected_days=(11, 13),
        minimum_active_days=11,
        core_event_target=8,
        interaction_nodes_per_event=(14, 18),
        line_count_per_event=(120, 160),
        finale_title="无论走到哪里，都知道可以回来",
        intimacy_boundary="允许明确依赖和承诺，同时保留拒绝、独处与各自生活的空间。",
        required_axes=(36, 31, 28, 28),
        future_directions=("依赖与独立", "重大分歧", "长时间分别", "双向承诺"),
    ),
)

CHAPTER_BY_ID = {chapter.id: chapter for chapter in CHAPTERS}


@dataclass(frozen=True)
class NarrativeProgress:
    version: int
    chapter_id: str
    completed_event_ids: tuple[str, ...]
    active_dates: tuple[str, ...]
    familiarity: int
    consistency: int
    boundaries: int
    authenticity: int
    unresolved_flags: tuple[str, ...]
    finale_completed: bool

    @classmethod
    def default(cls) -> "NarrativeProgress":
        return cls(NARRATIVE_VERSION, CHAPTERS[0].id, (), (), 0, 0, 0, 0, (), False)

    def to_dict(self) -> dict[str, object]:
        return {
            "version": self.version,
            "chapter_id": self.chapter_id,
            "completed_event_ids": list(self.completed_event_ids),
            "active_dates": list(self.active_dates),
            "axes": {
                "familiarity": self.familiarity,
                "consistency": self.consistency,
                "boundaries": self.boundaries,
                "authenticity": self.authenticity,
            },
            "unresolved_flags": list(self.unresolved_flags),
            "finale_completed": self.finale_completed,
        }

    @classmethod
    def from_dict(cls, value: object) -> "NarrativeProgress":
        if not isinstance(value, dict) or set(value) != {
            "version", "chapter_id", "completed_event_ids", "active_dates", "axes",
            "unresolved_flags", "finale_completed",
        }:
            raise StateError("narrative progress has unknown or missing fields")
        if value["version"] != NARRATIVE_VERSION or value["chapter_id"] not in CHAPTER_BY_ID:
            raise StateError("narrative progress version or chapter is unsupported")
        completed = _string_tuple(value["completed_event_ids"], "completed narrative events")
        active_dates = _string_tuple(value["active_dates"], "narrative active dates")
        for value_date in active_dates:
            try:
                date.fromisoformat(value_date)
            except ValueError as error:
                raise StateError("narrative active date is invalid") from error
        axes = value["axes"]
        if not isinstance(axes, dict) or set(axes) != {
            "familiarity", "consistency", "boundaries", "authenticity"
        }:
            raise StateError("narrative axes are invalid")
        axis_values = tuple(axes[name] for name in ("familiarity", "consistency", "boundaries", "authenticity"))
        if any(type(axis) is not int or not -MAX_AXIS_VALUE <= axis <= MAX_AXIS_VALUE for axis in axis_values):
            raise StateError("narrative axis value is invalid")
        flags = _string_tuple(value["unresolved_flags"], "narrative flags")
        if type(value["finale_completed"]) is not bool:
            raise StateError("narrative finale state is invalid")
        return cls(
            NARRATIVE_VERSION, value["chapter_id"], completed, active_dates,
            *axis_values, flags, value["finale_completed"],
        )


@dataclass(frozen=True)
class NarrativeEventResult:
    outcome: str
    familiarity: int = 0
    consistency: int = 0
    boundaries: int = 0
    authenticity: int = 0
    add_flags: tuple[str, ...] = ()
    resolve_flags: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if self.outcome not in OUTCOMES:
            raise StateError("narrative outcome is invalid")
        if any(not -3 <= value <= 3 for value in (
            self.familiarity, self.consistency, self.boundaries, self.authenticity
        )):
            raise StateError("narrative event delta is out of bounds")


@dataclass(frozen=True)
class NarrativeBeat:
    title: str
    purpose: str
    start_node: int
    end_node: int
    scene: str
    sprite: str
    allow_outfit_change: bool
    good_direction: str
    neutral_direction: str
    bad_direction: str

    def to_dict(self) -> dict[str, object]:
        return {
            "title": self.title,
            "purpose": self.purpose,
            "start_node": self.start_node,
            "end_node": self.end_node,
            "scene": self.scene,
            "sprite": self.sprite,
            "allow_outfit_change": self.allow_outfit_change,
            "directions": {
                "good": self.good_direction,
                "neutral": self.neutral_direction,
                "bad": self.bad_direction,
            },
        }

    @classmethod
    def from_dict(cls, value: object) -> "NarrativeBeat":
        if not isinstance(value, dict) or set(value) != {
            "title", "purpose", "start_node", "end_node", "scene", "sprite",
            "allow_outfit_change", "directions",
        }:
            raise StateError("narrative beat has unknown or missing fields")
        start, end = value["start_node"], value["end_node"]
        if type(start) is not int or type(end) is not int or start < 0 or end < start:
            raise StateError("narrative beat range is invalid")
        if value["scene"] not in visual_asset_ids("scenes") or value["sprite"] not in visual_asset_ids("sprites"):
            raise StateError("narrative beat visual is invalid")
        if type(value["allow_outfit_change"]) is not bool:
            raise StateError("narrative beat outfit rule is invalid")
        directions = value["directions"]
        if not isinstance(directions, dict) or set(directions) != {"good", "neutral", "bad"}:
            raise StateError("narrative beat directions are invalid")
        return cls(
            _bounded_text(value["title"], "narrative beat title", 80),
            _bounded_text(value["purpose"], "narrative beat purpose", 180),
            start,
            end,
            value["scene"],
            value["sprite"],
            value["allow_outfit_change"],
            *(_bounded_text(directions[name], "narrative beat direction", 160) for name in ("good", "neutral", "bad")),
        )


@dataclass(frozen=True)
class NarrativePlan:
    premise: str
    conflict: str
    resolution: str
    target_nodes: int
    target_lines: int
    choice_nodes: tuple[int, ...]
    beats: tuple[NarrativeBeat, ...]

    def to_dict(self) -> dict[str, object]:
        return {
            "premise": self.premise,
            "conflict": self.conflict,
            "resolution": self.resolution,
            "target_nodes": self.target_nodes,
            "target_lines": self.target_lines,
            "choice_nodes": list(self.choice_nodes),
            "beats": [beat.to_dict() for beat in self.beats],
        }

    @classmethod
    def from_dict(cls, value: object) -> "NarrativePlan":
        if not isinstance(value, dict) or set(value) != {
            "premise", "conflict", "resolution", "target_nodes", "target_lines", "choice_nodes", "beats",
        }:
            raise StateError("narrative plan has unknown or missing fields")
        target_nodes, target_lines = value["target_nodes"], value["target_lines"]
        if type(target_nodes) is not int or not 14 <= target_nodes <= 18:
            raise StateError("narrative plan interaction target is invalid")
        if type(target_lines) is not int or not 120 <= target_lines <= 160:
            raise StateError("narrative plan line target is invalid")
        raw_choices = value["choice_nodes"]
        if (
            not isinstance(raw_choices, list)
            or not 5 <= len(raw_choices) <= 6
            or any(type(node) is not int or not 1 <= node < target_nodes for node in raw_choices)
            or raw_choices != sorted(set(raw_choices))
        ):
            raise StateError("narrative plan choice nodes are invalid")
        raw_beats = value["beats"]
        if not isinstance(raw_beats, list) or not 6 <= len(raw_beats) <= 8:
            raise StateError("narrative plan beats are invalid")
        beats = tuple(NarrativeBeat.from_dict(beat) for beat in raw_beats)
        if beats[0].start_node != 0 or beats[-1].end_node != target_nodes:
            raise StateError("narrative plan does not cover the event")
        if any(left.end_node + 1 != right.start_node for left, right in zip(beats, beats[1:])):
            raise StateError("narrative plan beats are not contiguous")
        if len({beat.scene for beat in beats}) > 3:
            raise StateError("narrative plan uses too many locations")
        return cls(
            _bounded_text(value["premise"], "narrative premise", 240),
            _bounded_text(value["conflict"], "narrative conflict", 240),
            _bounded_text(value["resolution"], "narrative resolution", 240),
            target_nodes,
            target_lines,
            tuple(raw_choices),
            beats,
        )

    def beat_for_node(self, node: int) -> NarrativeBeat:
        return next(beat for beat in self.beats if beat.start_node <= node <= beat.end_node)


@dataclass(frozen=True)
class NarrativeTurn:
    """One strictly validated LLM continuation for a chapter event."""

    lines: tuple[StoryLine, ...]
    next_node_type: str
    choices: tuple[str, ...]
    hidden_outcome: str
    familiarity: int
    consistency: int
    boundaries: int
    authenticity: int
    add_flags: tuple[str, ...]
    resolve_flags: tuple[str, ...]
    user_summary: str
    event_summary: str
    continuity_facts: tuple[str, ...]
    event_complete: bool

    @classmethod
    def from_dict(cls, value: object) -> "NarrativeTurn":
        expected = {
            "lines", "next_node_type", "choices", "hidden_outcome", "axis_changes",
            "add_flags", "resolve_flags", "user_summary", "event_summary", "continuity_facts",
            "event_complete",
        }
        legacy_expected = expected - {"continuity_facts"}
        if not isinstance(value, dict) or set(value) not in (expected, legacy_expected):
            raise StateError("narrative turn has unknown or missing fields")
        lines_value = value["lines"]
        if not isinstance(lines_value, list) or not 3 <= len(lines_value) <= 10:
            raise StateError("narrative turn must contain 3 to 10 lines")
        lines = tuple(StoryLine.from_dict(line) for line in lines_value)
        next_node_type = value["next_node_type"]
        if next_node_type not in NEXT_NODE_TYPES:
            raise StateError("narrative next node type is invalid")
        choices = _bounded_strings(value["choices"], "narrative choices", 4, 80, allow_empty=True)
        if (next_node_type == "choice") != (2 <= len(choices) <= 4):
            raise StateError("narrative choices do not match the next node type")
        if next_node_type != "choice" and choices:
            raise StateError("narrative choices are only allowed for choice nodes")
        outcome = value["hidden_outcome"]
        if outcome not in OUTCOMES:
            raise StateError("narrative turn outcome is invalid")
        axes = value["axis_changes"]
        axis_names = ("familiarity", "consistency", "boundaries", "authenticity")
        if not isinstance(axes, dict) or set(axes) != set(axis_names):
            raise StateError("narrative turn axes are invalid")
        axis_values = tuple(axes[name] for name in axis_names)
        if any(type(axis) is not int or not -3 <= axis <= 3 for axis in axis_values):
            raise StateError("narrative turn axis change is out of bounds")
        add_flags = _bounded_strings(value["add_flags"], "narrative added flags", 8, 80, allow_empty=True)
        resolve_flags = _bounded_strings(
            value["resolve_flags"], "narrative resolved flags", 8, 80, allow_empty=True
        )
        user_summary = _bounded_text(value["user_summary"], "narrative user summary", 120)
        event_summary = _bounded_text(value["event_summary"], "narrative event summary", 1_000)
        continuity_facts = _bounded_strings(
            value.get("continuity_facts", []), "narrative continuity facts", 4, 160, allow_empty=True
        )
        if type(value["event_complete"]) is not bool:
            raise StateError("narrative event completion state is invalid")
        if value["event_complete"] != (next_node_type == "complete"):
            raise StateError("narrative completion state does not match the next node")
        return cls(
            lines, next_node_type, choices, outcome, *axis_values, add_flags, resolve_flags,
            user_summary, event_summary, continuity_facts, value["event_complete"],
        )


@dataclass(frozen=True)
class NarrativeEventSession:
    """Bounded resumable state for a legacy or director-driven chapter event."""

    version: int
    chapter_id: str
    event_id: str
    target_nodes: int
    current_node: int
    lines: tuple[StoryLine, ...]
    user_summaries: tuple[str, ...]
    outcomes: tuple[str, ...]
    next_node_type: str
    choices: tuple[str, ...]
    event_summary: str
    hidden_outcome: str
    familiarity: int
    consistency: int
    boundaries: int
    authenticity: int
    add_flags: tuple[str, ...]
    resolve_flags: tuple[str, ...]
    director_plan: NarrativePlan | None
    continuity_facts: tuple[str, ...]
    completed: bool

    @classmethod
    def start(cls, event_id: str, target_nodes: int = 7) -> "NarrativeEventSession":
        chapter = CHAPTERS[0]
        if (
            event_id != CHAPTER_ONE_FINALE_ID
            and event_id not in {event.id for event in chapter.events}
            and not event_id.startswith("llm-")
        ):
            raise StateError("narrative session event is unsupported")
        if not (6 <= target_nodes <= 8 or 14 <= target_nodes <= 18):
            raise StateError("narrative session target is invalid")
        return cls(
            SESSION_VERSION, chapter.id, event_id, target_nodes, 0, (), (), (), "free_input", (), "",
            "neutral", 0, 0, 0, 0, (), (), None, (), False,
        )

    @property
    def director_mode(self) -> bool:
        return self.target_nodes >= 14

    def with_director_opening(
        self, plan: NarrativePlan, lines: tuple[StoryLine, ...], summary: str
    ) -> "NarrativeEventSession":
        if not self.director_mode or plan.target_nodes != self.target_nodes:
            raise StateError("narrative plan does not match the session")
        return NarrativeEventSession.from_dict({
            **self.to_dict(),
            "lines": [line.to_dict() for line in lines],
            "event_summary": summary,
            "director_plan": plan.to_dict(),
        })

    def with_opening(self, lines: tuple[StoryLine, ...], summary: str) -> "NarrativeEventSession":
        if self.current_node or self.lines or self.completed:
            raise StateError("narrative opening is already present")
        return NarrativeEventSession.from_dict({
            **self.to_dict(),
            "lines": [line.to_dict() for line in lines],
            "event_summary": summary,
        })

    def to_dict(self) -> dict[str, object]:
        return {
            "version": self.version,
            "chapter_id": self.chapter_id,
            "event_id": self.event_id,
            "target_nodes": self.target_nodes,
            "current_node": self.current_node,
            "lines": [line.to_dict() for line in self.lines],
            "user_summaries": list(self.user_summaries),
            "outcomes": list(self.outcomes),
            "next_node_type": self.next_node_type,
            "choices": list(self.choices),
            "event_summary": self.event_summary,
            "hidden_outcome": self.hidden_outcome,
            "axis_changes": {
                "familiarity": self.familiarity,
                "consistency": self.consistency,
                "boundaries": self.boundaries,
                "authenticity": self.authenticity,
            },
            "add_flags": list(self.add_flags),
            "resolve_flags": list(self.resolve_flags),
            "director_plan": self.director_plan.to_dict() if self.director_plan else None,
            "continuity_facts": list(self.continuity_facts),
            "completed": self.completed,
        }

    @classmethod
    def from_dict(cls, value: object) -> "NarrativeEventSession":
        expected = {
            "version", "chapter_id", "event_id", "target_nodes", "current_node", "lines",
            "user_summaries", "outcomes", "next_node_type", "choices", "event_summary", "hidden_outcome",
            "axis_changes", "add_flags", "resolve_flags", "director_plan", "continuity_facts", "completed",
        }
        version_two_expected = expected - {"director_plan", "continuity_facts"}
        version_one_expected = version_two_expected - {"outcomes"}
        if not isinstance(value, dict) or set(value) not in (expected, version_two_expected, version_one_expected):
            raise StateError("narrative session has unknown or missing fields")
        if value["version"] not in (1, 2, SESSION_VERSION) or value["chapter_id"] != CHAPTERS[0].id:
            raise StateError("narrative session version or chapter is unsupported")
        event_id = value["event_id"]
        if not isinstance(event_id, str) or not event_id or len(event_id) > 120:
            raise StateError("narrative session event is invalid")
        chapter = CHAPTER_BY_ID[value["chapter_id"]]
        if (
            event_id != CHAPTER_ONE_FINALE_ID
            and event_id not in {event.id for event in chapter.events}
            and not event_id.startswith("llm-")
        ):
            raise StateError("narrative session event is unsupported")
        target_nodes, current_node = value["target_nodes"], value["current_node"]
        if type(target_nodes) is not int or not (6 <= target_nodes <= 8 or 14 <= target_nodes <= 18):
            raise StateError("narrative session target is invalid")
        if type(current_node) is not int or not 0 <= current_node <= target_nodes:
            raise StateError("narrative session node is invalid")
        raw_lines = value["lines"]
        if not isinstance(raw_lines, list) or len(raw_lines) > 160:
            raise StateError("narrative session lines exceed their limit")
        lines = tuple(StoryLine.from_dict(line) for line in raw_lines)
        summaries = _bounded_strings(
            value["user_summaries"], "narrative user summaries", 18, 120,
            allow_empty=True, allow_duplicates=True,
        )
        if len(summaries) != current_node:
            raise StateError("narrative summaries do not match the current node")
        outcomes = tuple(value.get("outcomes", ()))
        if (
            not isinstance(outcomes, tuple)
            and not isinstance(outcomes, list)
        ) or len(outcomes) not in (0, current_node) or any(item not in OUTCOMES for item in outcomes):
            raise StateError("narrative outcomes are invalid")
        if not outcomes and current_node:
            outcomes = tuple(value["hidden_outcome"] for _ in range(current_node))
        next_node_type = value["next_node_type"]
        if next_node_type not in NEXT_NODE_TYPES:
            raise StateError("narrative session next node is invalid")
        choices = _bounded_strings(value["choices"], "narrative session choices", 4, 80, allow_empty=True)
        if (next_node_type == "choice") != (2 <= len(choices) <= 4):
            raise StateError("narrative session choices are invalid")
        if next_node_type != "choice" and choices:
            raise StateError("narrative session choices are misplaced")
        summary = value["event_summary"]
        if not isinstance(summary, str) or len(summary) > 1_000:
            raise StateError("narrative session summary is invalid")
        outcome = value["hidden_outcome"]
        if outcome not in OUTCOMES:
            raise StateError("narrative session outcome is invalid")
        axes = value["axis_changes"]
        axis_names = ("familiarity", "consistency", "boundaries", "authenticity")
        if not isinstance(axes, dict) or set(axes) != set(axis_names):
            raise StateError("narrative session axes are invalid")
        axis_values = tuple(axes[name] for name in axis_names)
        if any(type(axis) is not int or not -24 <= axis <= 24 for axis in axis_values):
            raise StateError("narrative session axis change is out of bounds")
        add_flags = _bounded_strings(value["add_flags"], "narrative session added flags", 16, 80, allow_empty=True)
        resolve_flags = _bounded_strings(
            value["resolve_flags"], "narrative session resolved flags", 16, 80, allow_empty=True
        )
        raw_plan = value.get("director_plan")
        plan = NarrativePlan.from_dict(raw_plan) if raw_plan is not None else None
        if target_nodes >= 14 and plan is not None and plan.target_nodes != target_nodes:
            raise StateError("narrative session plan target is invalid")
        facts = _bounded_strings(
            value.get("continuity_facts", []), "narrative session continuity facts", 24, 160,
            allow_empty=True,
        )
        if type(value["completed"]) is not bool or value["completed"] != (next_node_type == "complete"):
            raise StateError("narrative session completion state is invalid")
        return cls(
            SESSION_VERSION, value["chapter_id"], event_id, target_nodes, current_node, lines,
            summaries, tuple(outcomes), next_node_type, choices, summary, outcome, *axis_values, add_flags,
            resolve_flags, plan, facts, value["completed"],
        )

    def append(self, turn: NarrativeTurn) -> "NarrativeEventSession":
        if self.completed:
            raise StateError("narrative session is already complete")
        current_node = self.current_node + 1
        minimum_nodes = 14 if self.director_mode else 6
        if turn.event_complete and current_node < minimum_nodes:
            raise StateError("narrative event cannot complete before six interactions")
        if current_node >= self.target_nodes and not turn.event_complete:
            raise StateError("narrative event must complete at its target node")
        total_lines = len(self.lines) + len(turn.lines)
        if self.director_mode:
            if self.director_plan is None:
                raise StateError("narrative director plan is unavailable")
            if not 8 <= len(turn.lines) <= 10:
                raise StateError("directed narrative turn must contain 8 to 10 lines")
            if total_lines > 160:
                raise StateError("directed narrative event exceeds its line limit")
            if turn.event_complete and total_lines < 120:
                raise StateError("directed narrative event is shorter than its target")
        if (
            turn.event_complete
            and self.target_nodes == 7
            and total_lines < 45
        ):
            raise StateError("narrative event is shorter than the chapter target")
        return NarrativeEventSession.from_dict({
            **self.to_dict(),
            "current_node": current_node,
            "lines": [line.to_dict() for line in (*self.lines, *turn.lines)],
            "user_summaries": [*self.user_summaries, turn.user_summary],
            "outcomes": [*self.outcomes, turn.hidden_outcome],
            "next_node_type": turn.next_node_type,
            "choices": list(turn.choices),
            "event_summary": turn.event_summary,
            "hidden_outcome": turn.hidden_outcome,
            "axis_changes": {
                "familiarity": self.familiarity + turn.familiarity,
                "consistency": self.consistency + turn.consistency,
                "boundaries": self.boundaries + turn.boundaries,
                "authenticity": self.authenticity + turn.authenticity,
            },
            "add_flags": sorted((set(self.add_flags) | set(turn.add_flags)) - set(turn.resolve_flags)),
            "resolve_flags": sorted((set(self.resolve_flags) | set(turn.resolve_flags)) - set(turn.add_flags)),
            "continuity_facts": list(dict.fromkeys((*self.continuity_facts, *turn.continuity_facts)))[-24:],
            "completed": turn.event_complete,
        })

    def event_result(self) -> NarrativeEventResult:
        if not self.completed:
            raise StateError("narrative session is not complete")
        clamp = lambda value: max(-3, min(3, value))
        return NarrativeEventResult(
            self.hidden_outcome,
            clamp(self.familiarity), clamp(self.consistency), clamp(self.boundaries),
            clamp(self.authenticity), self.add_flags, self.resolve_flags,
        )


def apply_event_result(
    progress: NarrativeProgress,
    event_id: str,
    interaction_date: str,
    result: NarrativeEventResult,
) -> NarrativeProgress:
    chapter = CHAPTER_BY_ID[progress.chapter_id]
    if event_id in progress.completed_event_ids:
        return progress
    if chapter.events and event_id not in {event.id for event in chapter.events} and not event_id.startswith("llm-"):
        raise StateError("narrative event does not belong to the current chapter")
    try:
        date.fromisoformat(interaction_date)
    except ValueError as error:
        raise StateError("narrative interaction date is invalid") from error
    flags = (set(progress.unresolved_flags) | set(result.add_flags)) - set(result.resolve_flags)
    return replace(
        progress,
        completed_event_ids=(*progress.completed_event_ids, event_id),
        active_dates=tuple(sorted(set((*progress.active_dates, interaction_date)))),
        familiarity=_bounded(progress.familiarity + result.familiarity),
        consistency=_bounded(progress.consistency + result.consistency),
        boundaries=_bounded(progress.boundaries + result.boundaries),
        authenticity=_bounded(progress.authenticity + result.authenticity),
        unresolved_flags=tuple(sorted(flags)),
    )


def chapter_ready_for_finale(progress: NarrativeProgress) -> bool:
    chapter = CHAPTER_BY_ID[progress.chapter_id]
    required_events = set(chapter.required_event_ids)
    axes = (progress.familiarity, progress.consistency, progress.boundaries, progress.authenticity)
    return (
        required_events.issubset(progress.completed_event_ids)
        and len(progress.active_dates) >= chapter.minimum_active_days
        and all(current >= required for current, required in zip(axes, chapter.required_axes))
        and not progress.unresolved_flags
    )


def complete_chapter_finale(progress: NarrativeProgress) -> NarrativeProgress:
    if progress.finale_completed:
        return progress
    if not chapter_ready_for_finale(progress):
        raise StateError("narrative chapter is not ready for its finale")
    return replace(progress, finale_completed=True)


def bridge_event_count(progress: NarrativeProgress) -> int:
    if chapter_ready_for_finale(progress):
        return 0
    chapter = CHAPTER_BY_ID[progress.chapter_id]
    axes = (progress.familiarity, progress.consistency, progress.boundaries, progress.authenticity)
    serious = bool(progress.unresolved_flags) or any(required - current >= 5 for current, required in zip(axes, chapter.required_axes))
    return 2 if serious else 1


class NarrativeStore:
    """Persist only bounded narrative progress, never raw conversation text."""

    def __init__(self, data_dir: str | Path) -> None:
        self.path = Path(os.path.abspath(data_dir)) / "narrative.json"
        self._lock = threading.RLock()

    def load(self) -> NarrativeProgress:
        with self._lock:
            _assert_safe_path(self.path)
            try:
                payload = self.path.read_bytes()
            except FileNotFoundError:
                return self.save(NarrativeProgress.default())
            except OSError as error:
                raise StateError(f"could not read narrative progress: {error}") from error
            if len(payload) > MAX_NARRATIVE_FILE_BYTES:
                raise StateError("narrative progress exceeds its size limit")
            try:
                return NarrativeProgress.from_dict(json.loads(payload.decode("utf-8")))
            except (UnicodeDecodeError, json.JSONDecodeError) as error:
                raise StateError("narrative progress is invalid") from error

    def save(self, progress: NarrativeProgress) -> NarrativeProgress:
        validated = NarrativeProgress.from_dict(progress.to_dict())
        payload = json.dumps(validated.to_dict(), ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        if len(payload) > MAX_NARRATIVE_FILE_BYTES:
            raise StateError("narrative progress exceeds its size limit")
        with self._lock:
            _atomic_write(self.path, payload)
        return validated

    def record_activity(self, activity_date: str) -> NarrativeProgress:
        """Count a daily Firefly interaction without storing its prompt."""
        try:
            date.fromisoformat(activity_date)
        except (TypeError, ValueError) as error:
            raise StateError("narrative activity date is invalid") from error
        with self._lock:
            progress = self.load()
            return self.save(replace(
                progress,
                active_dates=tuple(sorted(set((*progress.active_dates, activity_date)))),
            ))


class NarrativeSessionStore:
    """Atomically persist the current bounded event session."""

    def __init__(self, data_dir: str | Path) -> None:
        self.path = Path(os.path.abspath(data_dir)) / "narrative-session.json"
        self._lock = threading.RLock()

    def load(self) -> NarrativeEventSession | None:
        with self._lock:
            _assert_safe_path(self.path)
            try:
                payload = self.path.read_bytes()
            except FileNotFoundError:
                return None
            except OSError as error:
                raise StateError(f"could not read narrative session: {error}") from error
            if len(payload) > MAX_SESSION_FILE_BYTES:
                raise StateError("narrative session exceeds its size limit")
            try:
                return NarrativeEventSession.from_dict(json.loads(payload.decode("utf-8")))
            except (UnicodeDecodeError, json.JSONDecodeError) as error:
                raise StateError("narrative session is invalid") from error

    def save(self, session: NarrativeEventSession) -> NarrativeEventSession:
        validated = NarrativeEventSession.from_dict(session.to_dict())
        payload = json.dumps(validated.to_dict(), ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        if len(payload) > MAX_SESSION_FILE_BYTES:
            raise StateError("narrative session exceeds its size limit")
        with self._lock:
            _atomic_write(self.path, payload)
        return validated

    def ensure_current(self, session: NarrativeEventSession) -> NarrativeEventSession:
        """Create a missing request baseline without replacing another session."""
        with self._lock:
            current = self.load()
            if current is None:
                return self.save(session)
            if current != session:
                raise StateError("narrative session changed while generating")
            return current

    def save_if_current(
        self,
        expected: NarrativeEventSession,
        session: NarrativeEventSession,
    ) -> NarrativeEventSession:
        """Save only when no newer continuation has replaced the request baseline."""
        with self._lock:
            current = self.load()
            if current != expected:
                raise StateError("narrative session changed while generating")
            return self.save(session)


class NarrativeArchiveStore:
    """Keep completed generated story sessions available for replay."""

    def __init__(self, data_dir: str | Path) -> None:
        self.path = Path(os.path.abspath(data_dir)) / "narrative-archive.json"
        self._lock = threading.RLock()

    def load(self) -> tuple[NarrativeEventSession, ...]:
        with self._lock:
            _assert_safe_path(self.path)
            try:
                payload = self.path.read_bytes()
            except FileNotFoundError:
                return ()
            except OSError as error:
                raise StateError(f"could not read narrative archive: {error}") from error
            if len(payload) > MAX_ARCHIVE_FILE_BYTES:
                raise StateError("narrative archive exceeds its size limit")
            try:
                return self._sessions_from_dict(json.loads(payload.decode("utf-8")))
            except (UnicodeDecodeError, json.JSONDecodeError) as error:
                raise StateError("narrative archive is invalid") from error

    def archive(self, session: NarrativeEventSession) -> NarrativeEventSession:
        validated = NarrativeEventSession.from_dict(session.to_dict())
        if not validated.completed:
            raise StateError("only completed narrative sessions can be archived")
        with self._lock:
            sessions = [item for item in self.load() if item.event_id != validated.event_id]
            sessions.append(validated)
            self._save(tuple(sessions[-MAX_ARCHIVED_SESSIONS:]))
        return validated

    def get(self, event_id: str) -> NarrativeEventSession | None:
        for session in reversed(self.load()):
            if session.event_id == event_id:
                return session
        return None

    def _save(self, sessions: tuple[NarrativeEventSession, ...]) -> None:
        payload = json.dumps(
            {
                "version": ARCHIVE_VERSION,
                "sessions": [session.to_dict() for session in sessions],
            },
            ensure_ascii=False,
            separators=(",", ":"),
        ).encode("utf-8")
        if len(payload) > MAX_ARCHIVE_FILE_BYTES:
            raise StateError("narrative archive exceeds its size limit")
        _atomic_write(self.path, payload)

    @staticmethod
    def _sessions_from_dict(value: object) -> tuple[NarrativeEventSession, ...]:
        if not isinstance(value, dict) or set(value) != {"version", "sessions"}:
            raise StateError("narrative archive has unknown or missing fields")
        if value["version"] != ARCHIVE_VERSION:
            raise StateError("narrative archive version is unsupported")
        raw_sessions = value["sessions"]
        if not isinstance(raw_sessions, list) or len(raw_sessions) > MAX_ARCHIVED_SESSIONS:
            raise StateError("narrative archive sessions are invalid")
        sessions = tuple(NarrativeEventSession.from_dict(item) for item in raw_sessions)
        if any(not session.completed for session in sessions):
            raise StateError("narrative archive contains unfinished sessions")
        if len({session.event_id for session in sessions}) != len(sessions):
            raise StateError("narrative archive contains duplicate sessions")
        return sessions


def _bounded(value: int) -> int:
    return max(-MAX_AXIS_VALUE, min(MAX_AXIS_VALUE, value))


def _string_tuple(value: object, label: str) -> tuple[str, ...]:
    if not isinstance(value, list) or len(value) > 200:
        raise StateError(f"{label} must be a bounded list")
    if any(not isinstance(item, str) or not item or len(item) > 120 for item in value):
        raise StateError(f"{label} contains an invalid value")
    if len(set(value)) != len(value):
        raise StateError(f"{label} contains duplicates")
    return tuple(value)


def _bounded_text(value: object, label: str, maximum: int) -> str:
    if not isinstance(value, str) or not value.strip() or value != value.strip() or len(value) > maximum:
        raise StateError(f"{label} is invalid")
    if any(ord(character) < 32 or 127 <= ord(character) <= 159 for character in value):
        raise StateError(f"{label} contains control characters")
    return value


def _bounded_strings(
    value: object,
    label: str,
    maximum_items: int,
    maximum_length: int,
    *,
    allow_empty: bool,
    allow_duplicates: bool = False,
) -> tuple[str, ...]:
    if not isinstance(value, list) or len(value) > maximum_items or (not allow_empty and not value):
        raise StateError(f"{label} must be a bounded list")
    items = tuple(_bounded_text(item, label, maximum_length) for item in value)
    if not allow_duplicates and len(set(items)) != len(items):
        raise StateError(f"{label} contains duplicates")
    return items


def _atomic_write(path: Path, payload: bytes) -> None:
    _ensure_safe_parent(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    _assert_safe_path(path)
    descriptor, temporary_name = tempfile.mkstemp(
        dir=path.parent, prefix=f".{path.name}.", suffix=".tmp"
    )
    temporary_path = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "wb") as file:
            file.write(payload)
            file.flush()
            os.fsync(file.fileno())
        _assert_safe_path(path)
        os.replace(temporary_path, path)
    finally:
        if temporary_path.exists():
            temporary_path.unlink()


def _ensure_safe_parent(path: Path) -> None:
    _assert_safe_path(path)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
    except OSError as error:
        raise StateError(f"could not create narrative data directory: {error}") from error
    _assert_safe_path(path)


def _assert_safe_path(path: Path) -> None:
    current = Path(path.parent.anchor)
    for part in path.parent.parts[1:]:
        current /= part
        try:
            metadata = os.lstat(current)
        except FileNotFoundError:
            break
        except OSError as error:
            raise StateError(f"could not inspect narrative data directory: {error}") from error
        if stat.S_ISLNK(metadata.st_mode):
            raise StateError("narrative data directory must not contain symbolic links")
        if not stat.S_ISDIR(metadata.st_mode):
            raise StateError("narrative data directory must be a directory")
    try:
        metadata = os.lstat(path)
    except FileNotFoundError:
        return
    except OSError as error:
        raise StateError(f"could not inspect narrative state: {error}") from error
    if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISREG(metadata.st_mode):
        raise StateError("narrative state file must be a regular file, not a symbolic link")
