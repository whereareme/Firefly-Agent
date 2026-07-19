"""Native confirmation panel for the local relationship Sidecar."""

from __future__ import annotations

import json
import re
import threading
import tkinter as tk
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from queue import Empty, SimpleQueue
from tkinter import filedialog, ttk
from typing import Callable

from .gateway import RelationshipGatewayServer
from .narrative import (
    CHAPTER_ONE_FINALE_ID,
    CHAPTERS,
    NarrativeEventSession,
    NarrativeProgress,
    StoryEventDefinition,
    bridge_event_count,
    chapter_ready_for_finale,
)
from .state import STAGES, StateError, StateStore, StoryLine
from .playback import StoryAudioPlayer, StoryPlaybackStore, is_cinematic_line
from .visual_assets import default_scene_id, default_sprite_id, visual_asset_path, visual_manifest


POLL_INTERVAL_MS = 1_000
TRAY_POLL_INTERVAL_MS = 100
PANEL_COLUMN_COUNT = 2
EVENT_ENTRY_COLUMN = 0
EVENT_BUTTON_COLUMN = 1
PENDING_KIND_LABELS = {"memory": "重要回忆", "gift": "礼物", "anniversary": "纪念日"}
STORY_DEFAULT_CHOICES = ("认真回应她", "按自己的节奏慢慢说")
ASSET_PATH = Path(__file__).with_name("assets") / "companion-imprint.png"
WINDOW_ICON_PATH = ASSET_PATH.with_suffix(".ico")
GALGAME_ASSET_ROOT = ASSET_PATH.parent / "galgame" / "chapter-01"
GALGAME_MANIFEST_PATH = GALGAME_ASSET_ROOT / "manifest.json"
STORY_STAGE_SIZE = (528, 330)
STORY_WINDOW_SIZE = (960, 600)
BGM_ROOT = ASSET_PATH.parent / "galgame" / "chapter-01" / "audio" / "bgm"
AMBIENT_ROOT = BGM_ROOT.parent / "ambient"
BGM_FILES = {
    "daily": BGM_ROOT / "firefly_theme_daily.wav",
    "hesitant": BGM_ROOT / "firefly_theme_hesitant.wav",
    "repair": BGM_ROOT / "firefly_theme_repair.wav",
    "ending": BGM_ROOT / "firefly_theme_ending.wav",
}
AMBIENT_FILES = {
    "rain": AMBIENT_ROOT / "rain.wav",
    "cafe": AMBIENT_ROOT / "cafe.wav",
    "street": AMBIENT_ROOT / "street.wav",
    "station": AMBIENT_ROOT / "station.wav",
}


def preferred_user_title(memory_context: str) -> str:
    """Use only an explicitly remembered user title; otherwise keep the canonical default."""
    matches = re.findall(
        r"(?:专属称号|称呼我为|叫我|把我叫(?:作|做))[：:\s「『]?([\w\u4e00-\u9fff·-]{1,24})",
        memory_context,
    )
    return matches[-1].strip("」』") if matches else "开拓者"


def next_narrative_event_id(
    progress: NarrativeProgress,
    session: NarrativeEventSession | None,
    has_memory_context: bool = False,
) -> str | None:
    """Return the resumable or next first-chapter event without exposing hidden scores."""
    chapter = CHAPTERS[0]
    if progress.chapter_id != chapter.id:
        return None
    if session is not None and not session.completed and session.event_id not in progress.completed_event_ids:
        return session.event_id
    core = [event for event in chapter.events if not event.personalized]
    interludes = {event.id: event for event in chapter.events if event.personalized}
    completed = set(progress.completed_event_ids)
    for index, event in enumerate(core):
        if event.id not in completed:
            return event.id
        interlude_id = {2: "personalized-interlude-1", 5: "personalized-interlude-2"}.get(index)
        if (
            interlude_id
            and interlude_id not in completed
            and has_memory_context
            and not any(later.id in completed for later in core[index + 1:])
        ):
            return interludes[interlude_id].id
    if chapter_ready_for_finale(progress):
        return None if progress.finale_completed else CHAPTER_ONE_FINALE_ID
    sequence = 1 + sum(event_id.startswith("llm-") for event_id in progress.completed_event_ids)
    kind = "repair" if bridge_event_count(progress) == 2 else "bridge"
    return f"llm-{kind}-{sequence}"


def narrative_event_definition(event_id: str) -> StoryEventDefinition:
    chapter = CHAPTERS[0]
    event = next((item for item in chapter.events if item.id == event_id), None)
    if event is not None:
        return event
    if event_id == CHAPTER_ONE_FINALE_ID:
        return StoryEventDefinition(event_id, chapter.finale_title, "完成第一章最后一次关系确认。")
    repairing = event_id.startswith("llm-repair-")
    return StoryEventDefinition(
        event_id,
        "把没有说清的话慢慢说完" if repairing else "再多了解彼此一点",
        "从此前没有解决的分歧中寻找一次低压力的修复机会。"
        if repairing else "根据近期相处生成一段自然的补充经历。",
        True,
    )


def completed_chapter_stories(
    sessions: tuple[NarrativeEventSession, ...], chapter_id: str
) -> tuple[NarrativeEventSession, ...]:
    return tuple(session for session in sessions if session.chapter_id == chapter_id and session.completed)
@dataclass(frozen=True)
class RelationshipTheme:
    label: str
    window: str
    surface: str
    text: str
    muted: str
    section: str
    tag_background: str
    tag_text: str
    pending: str
    status: str
    success: str
    entry: str
    border: str
    primary: str
    primary_active: str
    primary_disabled: str
    secondary: str
    secondary_text: str
    secondary_active: str
    separator: str
    icon: str
    primary_foreground: str
    disabled_foreground: str


RELATIONSHIP_THEMES = {
    "acquainted": RelationshipTheme(
        "初识", "#edf9f6", "#ffffff", "#172520", "#667b76", "#1b302b",
        "#dff4ef", "#0f6f68", "#263b36", "#506863", "#14865d", "#fbfefd",
        "#c9e1dc", "#237973", "#1c625d", "#a8bbb7", "#e6f5f2", "#285d58",
        "#d8eeea", "#d4e8e3", "#2b8f88", "#ffffff", "#334b46",
    ),
    "trusted": RelationshipTheme(
        "信赖", "#eaf5fb", "#fbfdff", "#122735", "#587180", "#17394c",
        "#d9edf7", "#176b91", "#213c4d", "#496878", "#14759a", "#f7fbfe",
        "#bfd9e6", "#1e6f91", "#185b77", "#9bb7c5", "#e0f0f7", "#275e78",
        "#d2e8f2", "#cce1eb", "#2584aa", "#ffffff", "#294653",
    ),
    "close": RelationshipTheme(
        "亲近", "#102e2c", "#173b37", "#fff7d6", "#b9ccc4", "#ffe9a6",
        "#295149", "#ffd66b", "#f7edd0", "#bdd1ca", "#ffd66b", "#214841",
        "#50736b", "#d7aa3e", "#bd8d27", "#596f69", "#244b45", "#f8df95",
        "#315951", "#496b64", "#e0b64e", "#172520", "#fff7d6",
    ),
    "confirmed": RelationshipTheme(
        "羁绊", "#fff1f5", "#fffafb", "#342127", "#80656d", "#4a2933",
        "#fde1e9", "#a53e62", "#4d3039", "#765761", "#b14468", "#fff7f9",
        "#ecc8d3", "#a94063", "#8d3652", "#c7a5af", "#fbe8ee", "#7f4055",
        "#f5dce4", "#edd1da", "#c45176", "#ffffff", "#51343d",
    ),
}


def relationship_theme(stage: str) -> RelationshipTheme:
    return RELATIONSHIP_THEMES.get(stage, RELATIONSHIP_THEMES[STAGES[0]])


def stage_icon(stage: str):
    """Return the cached icon for a canonical relationship stage."""
    return _stage_icon(stage if stage in RELATIONSHIP_THEMES else STAGES[0])


@lru_cache(maxsize=len(STAGES))
def _stage_icon(stage: str):
    from PIL import Image, ImageColor

    source = Image.open(ASSET_PATH).convert("RGBA")
    color = ImageColor.getrgb(relationship_theme(stage).icon)
    tinted = Image.new("RGBA", source.size, (*color, 0))
    tinted.putalpha(source.getchannel("A"))
    return tinted


@lru_cache(maxsize=1)
def _galgame_manifest() -> dict[str, object]:
    return visual_manifest()


def galgame_asset_path(*keys: str) -> Path:
    """Resolve one runtime image from the bundled chapter visual manifest."""
    if len(keys) == 2 and keys[0] in {"scenes", "sprites"}:
        return visual_asset_path(keys[0], keys[1])
    raise KeyError(".".join(keys))


@lru_cache(maxsize=12)
def _galgame_image(path: Path):
    from PIL import Image

    with Image.open(path) as source:
        return source.convert("RGBA")


def compose_story_stage(scene, sprite, size: tuple[int, int] = STORY_STAGE_SIZE):
    """Place a complete character image over a complete scene image."""
    from PIL import Image, ImageChops, ImageDraw, ImageFilter, ImageOps

    stage = ImageOps.fit(scene, size, Image.Resampling.LANCZOS).convert("RGBA")
    character = sprite.convert("RGBA")
    alpha = character.getchannel("A")
    if alpha.getextrema() == (255, 255):
        working = sprite.convert("RGB")
        marker = (255, 0, 255)
        for point in (
            (0, 0), (working.width - 1, 0), (0, working.height - 1), (working.width - 1, working.height - 1)
        ):
            ImageDraw.floodfill(working, point, marker, thresh=34)
        red, green, blue = working.split()
        marker_mask = ImageChops.multiply(
            ImageChops.multiply(
                red.point(lambda value: 255 if value == marker[0] else 0),
                green.point(lambda value: 255 if value == marker[1] else 0),
            ),
            blue.point(lambda value: 255 if value == marker[2] else 0),
        )
        alpha = ImageOps.invert(marker_mask).filter(ImageFilter.GaussianBlur(0.7))
        character.putalpha(alpha)
    bounds = alpha.getbbox()
    if bounds is not None:
        character = character.crop(bounds)
    character = ImageOps.contain(
        character,
        (int(size[0] * 0.48), int(size[1] * 0.96)),
        Image.Resampling.LANCZOS,
    )
    position = (
        size[0] - character.width - max(12, size[0] // 40),
        size[1] - character.height,
    )
    stage.alpha_composite(character, position)
    return stage.convert("RGB")


@lru_cache(maxsize=24)
def _cached_story_stage(scene_id: str, sprite_id: str, width: int, height: int):
    scene = _galgame_image(visual_asset_path("scenes", scene_id))
    character = _galgame_image(visual_asset_path("sprites", sprite_id))
    return compose_story_stage(scene, character, (width, height))


def story_dialogue_height(text: str, width: int) -> int:
    characters_per_line = max(18, (width - 112) // 22)
    line_count = max(1, (len(text) + characters_per_line - 1) // characters_per_line)
    return min(180, max(112, 82 + line_count * 28))


@dataclass(frozen=True)
class PanelAction:
    ok: bool
    message: str


def confirm_memory(store: StateStore) -> PanelAction:
    """Confirm the one queued relationship proposal."""
    try:
        store.confirm_pending()
    except (OSError, StateError) as error:
        return PanelAction(False, f"无法记下：{error}")
    return PanelAction(True, "已记下。")


def dismiss_memory(store: StateStore) -> PanelAction:
    """Discard the one queued relationship proposal."""
    try:
        store.dismiss_pending()
    except (OSError, StateError) as error:
        return PanelAction(False, f"无法跳过：{error}")
    return PanelAction(True, "已跳过。")


def record_explicit_event(store: StateStore, kind: str, summary: str) -> PanelAction:
    """Persist a user-entered gift or anniversary summary."""
    summary = summary.strip()
    label = "礼物" if kind == "gift" else "纪念日"
    if not summary:
        return PanelAction(False, f"请填写{label}简介。")
    try:
        store.record_explicit_event(kind, summary)
    except (OSError, StateError) as error:
        return PanelAction(False, f"无法记录{label}：{error}")
    return PanelAction(True, f"已记录{label}。")


def gateway_diagnostic(gateway: RelationshipGatewayServer) -> str:
    """Return a local operational diagnostic, never relationship state."""
    if gateway.last_error:
        return f"网关：需注意 - {gateway.last_error}"
    return f"网关：运行中 - http://{gateway.config.host}:{gateway.server_port}/v1"


def _story_generation_error_text(error: Exception | None, fallback: str) -> str:
    if error is None:
        return fallback
    message = str(error).strip()
    if message.startswith(("剧情生成失败：", "剧情大纲生成失败：")):
        return message
    if "model access" in message:
        return "剧情生成失败：当前模型接口不可用，请先让 Firefly 用当前 API 正常发送一次消息。"
    if "changed while generating" in message:
        return "剧情生成失败：剧情状态已变化，请重新打开这一幕。"
    return fallback


def configure_style(root: tk.Tk, theme: RelationshipTheme | None = None, style: ttk.Style | None = None) -> ttk.Style:
    """Apply one relationship-stage palette to the existing ttk styles."""
    theme = theme or RELATIONSHIP_THEMES[STAGES[0]]
    root.configure(background=theme.window)
    style = style or ttk.Style(root)
    if "clam" in style.theme_names():
        style.theme_use("clam")
    font = ("Microsoft YaHei UI", 10)
    style.configure(".", background=theme.surface, foreground=theme.text, font=font)
    style.configure("Surface.TFrame", background=theme.surface)
    style.configure("Title.TLabel", background=theme.surface, foreground=theme.text, font=(font[0], 19, "bold"))
    style.configure("Caption.TLabel", background=theme.surface, foreground=theme.muted, font=(font[0], 10))
    style.configure("Section.TLabel", background=theme.surface, foreground=theme.section, font=(font[0], 11, "bold"))
    style.configure("Kind.TLabel", background=theme.tag_background, foreground=theme.tag_text, padding=(8, 4), font=(font[0], 9, "bold"))
    style.configure("Pending.TLabel", background=theme.surface, foreground=theme.pending, font=(font[0], 10))
    style.configure("Status.TLabel", background=theme.surface, foreground=theme.status, font=(font[0], 9))
    style.configure("Action.TLabel", background=theme.surface, foreground=theme.success, font=(font[0], 9, "bold"))
    style.configure(
        "ViewTab.TButton",
        background=theme.secondary,
        foreground=theme.secondary_text,
        borderwidth=0,
        padding=(16, 7),
        font=(font[0], 9, "bold"),
    )
    style.map(
        "ViewTab.TButton",
        background=[("active", theme.secondary_active)],
    )
    style.configure(
        "ViewTabSelected.TButton",
        background=theme.primary,
        foreground=theme.primary_foreground,
        borderwidth=0,
        padding=(16, 7),
        font=(font[0], 9, "bold"),
    )
    style.map("ViewTabSelected.TButton", background=[("active", theme.primary_active)])
    style.configure("Dialogue.TFrame", background=theme.tag_background)
    style.configure("DialogueName.TLabel", background=theme.tag_background, foreground=theme.tag_text, font=(font[0], 9, "bold"))
    style.configure("Dialogue.TLabel", background=theme.tag_background, foreground=theme.text, font=(font[0], 10))
    style.configure("TEntry", fieldbackground=theme.entry, foreground=theme.text, bordercolor=theme.border, padding=(10, 7))
    style.configure("TButton", background=theme.primary, foreground=theme.primary_foreground, borderwidth=0, padding=(13, 8), font=(font[0], 9, "bold"))
    style.map(
        "TButton",
        background=[("active", theme.primary_active), ("disabled", theme.primary_disabled)],
        foreground=[("disabled", theme.disabled_foreground)],
    )
    style.configure("Secondary.TButton", background=theme.secondary, foreground=theme.secondary_text, bordercolor=theme.border, borderwidth=1)
    style.map("Secondary.TButton", background=[("active", theme.secondary_active), ("disabled", theme.surface)])
    style.configure("TSeparator", background=theme.separator)
    return style


class TrayController:
    """Small pystray adapter that never touches Tk from its worker thread."""

    def __init__(self, enqueue: Callable[[Callable[[], None]], None], show: Callable[[], None], exit_: Callable[[], None], stage: str = STAGES[0]) -> None:
        self._enqueue = enqueue
        self._show = show
        self._exit = exit_
        self._stage = stage
        self._icon = None

    def start(self) -> None:
        import pystray
        menu = pystray.Menu(
            pystray.MenuItem("打开同行印记", lambda _icon, _item: self._enqueue(self._show), default=True),
            pystray.MenuItem("退出", lambda _icon, _item: self._enqueue(self._exit)),
        )
        self._icon = pystray.Icon("firefly-companion-imprint", stage_icon(self._stage), "同行印记", menu)
        self._icon.run_detached()

    def set_stage(self, stage: str) -> None:
        self._stage = stage if stage in RELATIONSHIP_THEMES else STAGES[0]
        if self._icon is not None:
            self._icon.icon = stage_icon(self._stage)

    def stop(self) -> None:
        if self._icon is not None:
            self._icon.stop()
            self._icon = None


class RelationshipPanel:
    """Poll local state and expose only user-confirmed relationship actions."""

    def __init__(self, root: tk.Tk, gateway: RelationshipGatewayServer) -> None:
        self.root = root
        self.gateway = gateway
        self.store = gateway.store
        self._poll_job: str | None = None
        self._tray_poll_job: str | None = None
        self._tray_actions: SimpleQueue[Callable[[], None]] = SimpleQueue()
        self._exiting = False
        self._tray: TrayController | None = None
        self._active_stage: str | None = None
        self._icon_stage: str | None = None
        self._pending_text = tk.StringVar()
        self._pending_kind_text = tk.StringVar(value="等待对话")
        self._stage_text = tk.StringVar(value="关系阶段：初识")
        self._gateway_text = tk.StringVar()
        self._action_text = tk.StringVar()
        self._gift_text = tk.StringVar()
        self._anniversary_text = tk.StringVar()
        self._story_title_text = tk.StringVar(value=CHAPTERS[0].title)
        self._story_status_text = tk.StringVar(value="正在读取第一章进度。")
        self._story_description_text = tk.StringVar(value=CHAPTERS[0].focus)
        self._narrative_progress: NarrativeProgress | None = None
        self._narrative_session: NarrativeEventSession | None = None
        self._narrative_event: StoryEventDefinition | None = None
        self._story_lines: tuple[StoryLine, ...] = ()
        self._story_index = 0
        self._story_waiting_choice = False
        self._story_judging = False
        self._story_choice_error: str | None = None
        self._story_opening_failed = False
        self._story_choice_bounds: dict[str, tuple[int, int, int, int]] = {}
        self._story_custom_confirm_bounds: tuple[int, int, int, int] | None = None
        self._story_custom_text = tk.StringVar()
        self._story_window: tk.Toplevel | None = None
        self._story_canvas: tk.Canvas | None = None
        self._story_photo = None
        self._story_resize_job: str | None = None
        self._story_generation_results: SimpleQueue[tuple[int, str, object, Exception | None]] = SimpleQueue()
        self._story_generation_token = 0
        self._story_generation_poll_job: str | None = None
        self._playback_store = StoryPlaybackStore(gateway.config.data_dir)
        self._story_playback = self._playback_store.load()
        self._story_audio = StoryAudioPlayer()
        self._story_ambient_audio = StoryAudioPlayer()
        self._story_reveal_chars = 0
        self._story_display_key: tuple[int, str, bool, str | None] | None = None
        self._story_text_job: str | None = None
        self._story_auto_job: str | None = None
        self._story_auto = False
        self._story_skip = False
        self._story_replay = False
        self._story_control_bounds: dict[str, tuple[int, int, int, int]] = {}
        self._title_window: tk.Toplevel | None = None
        self._title_canvas: tk.Canvas | None = None
        self._title_photo = None
        self._title_background_index = 0
        self._title_rotation_job: str | None = None
        self._title_menu_bounds: list[tuple[tuple[int, int, int, int], Callable[[], None]]] = []

        self._style = configure_style(root)
        root.title("同行印记")
        root.geometry("560x580")
        root.minsize(520, 520)
        root.resizable(True, True)
        root.protocol("WM_DELETE_WINDOW", self.exit)
        root.columnconfigure(0, weight=1)
        root.rowconfigure(0, weight=1)
        try:
            root.iconbitmap(default=str(WINDOW_ICON_PATH))
        except (OSError, tk.TclError):
            pass

        canvas = tk.Canvas(root, background=RELATIONSHIP_THEMES[STAGES[0]].surface, borderwidth=0, highlightthickness=0)
        self._canvas = canvas
        scrollbar = ttk.Scrollbar(root, orient="vertical", command=canvas.yview)
        canvas.configure(yscrollcommand=scrollbar.set)
        canvas.grid(row=0, column=0, sticky="nsew")
        scrollbar.grid(row=0, column=1, sticky="ns")

        content = ttk.Frame(canvas, padding=(28, 22, 28, 24), style="Surface.TFrame")
        content_window = canvas.create_window((0, 0), window=content, anchor="nw")
        content.bind("<Configure>", lambda _event: canvas.configure(scrollregion=canvas.bbox("all")))
        canvas.bind("<Configure>", lambda event: canvas.itemconfigure(content_window, width=event.width))
        canvas.bind_all("<MouseWheel>", lambda event: canvas.yview_scroll(int(-event.delta / 120), "units"))
        content.columnconfigure(EVENT_ENTRY_COLUMN, weight=1)
        content.columnconfigure(EVENT_BUTTON_COLUMN, weight=0)

        ttk.Label(content, text="同行印记", style="Title.TLabel").grid(row=0, column=0, sticky="w")
        ttk.Label(content, textvariable=self._stage_text, style="Caption.TLabel").grid(row=1, column=0, sticky="w", pady=(3, 0))
        ttk.Button(content, text="最小化到托盘", style="Secondary.TButton", command=self.hide).grid(row=0, column=1, rowspan=2, sticky="e")

        view_tabs = ttk.Frame(content, style="Surface.TFrame")
        view_tabs.grid(row=2, column=0, columnspan=2, sticky="w", pady=(22, 18))
        self._story_tab_button = ttk.Button(
            view_tabs,
            text="剧情",
            style="ViewTabSelected.TButton",
            command=lambda: self.show_panel_page("story"),
        )
        self._story_tab_button.grid(row=0, column=0, padx=(0, 6))
        self._imprint_tab_button = ttk.Button(
            view_tabs,
            text="印记",
            style="ViewTab.TButton",
            command=lambda: self.show_panel_page("imprint"),
        )
        self._imprint_tab_button.grid(row=0, column=1)

        pages = ttk.Frame(content, style="Surface.TFrame")
        pages.grid(row=3, column=0, columnspan=2, sticky="nsew")
        pages.columnconfigure(0, weight=1)
        story = ttk.Frame(pages, style="Surface.TFrame")
        imprint = ttk.Frame(pages, style="Surface.TFrame")
        story.grid(row=0, column=0, sticky="nsew")
        imprint.grid(row=0, column=0, sticky="nsew")
        self._story_page = story
        self._imprint_page = imprint
        story.columnconfigure(0, weight=1)
        imprint.columnconfigure(EVENT_ENTRY_COLUMN, weight=1)
        imprint.columnconfigure(EVENT_BUTTON_COLUMN, weight=0)

        ttk.Label(story, textvariable=self._story_title_text, style="Section.TLabel").grid(row=0, column=0, sticky="w")
        ttk.Label(story, textvariable=self._story_status_text, style="Caption.TLabel").grid(row=1, column=0, sticky="w", pady=(3, 16))
        ttk.Label(
            story,
            textvariable=self._story_description_text,
            style="Pending.TLabel",
            wraplength=450,
            justify="left",
        ).grid(row=2, column=0, sticky="ew")
        self._open_story_button = ttk.Button(
            story,
            text="进入这一幕",
            command=self.open_story_window,
        )
        self._open_story_button.grid(row=3, column=0, sticky="ew", pady=(18, 0))
        self._open_story_button.state(("disabled",))

        ttk.Label(imprint, text="待确认的重要回忆", style="Section.TLabel").grid(row=0, column=0, columnspan=2, sticky="w")
        ttk.Label(imprint, textvariable=self._pending_kind_text, style="Kind.TLabel").grid(row=1, column=0, sticky="w", pady=(12, 8))
        self._pending_label = ttk.Label(imprint, textvariable=self._pending_text, style="Pending.TLabel", wraplength=500, justify="left")
        self._pending_label.grid(row=2, column=0, columnspan=2, sticky="ew")
        ttk.Label(imprint, text="来自日常对话，确认后才会保存", style="Caption.TLabel").grid(row=3, column=0, columnspan=2, sticky="w", pady=(8, 12))
        memory_actions = ttk.Frame(imprint, style="Surface.TFrame")
        memory_actions.grid(row=4, column=0, columnspan=2, sticky="w")
        self._confirm_button = ttk.Button(memory_actions, text="记下", command=self.confirm)
        self._confirm_button.grid(row=0, column=0, padx=(0, 8))
        self._dismiss_button = ttk.Button(memory_actions, text="暂不", style="Secondary.TButton", command=self.dismiss)
        self._dismiss_button.grid(row=0, column=1)

        ttk.Separator(imprint).grid(row=5, column=0, columnspan=2, sticky="ew", pady=(24, 18))
        ttk.Label(imprint, text="已完成剧情", style="Section.TLabel").grid(row=6, column=0, columnspan=2, sticky="w")
        ttk.Label(imprint, text="可以重温已经走完的剧情", style="Caption.TLabel").grid(row=7, column=0, columnspan=2, sticky="w", pady=(3, 10))
        self._completed_story_frame = ttk.Frame(imprint, style="Surface.TFrame")
        self._completed_story_frame.grid(row=8, column=0, columnspan=2, sticky="ew")
        self._completed_story_frame.columnconfigure(EVENT_ENTRY_COLUMN, weight=1)

        ttk.Separator(imprint).grid(row=9, column=0, columnspan=2, sticky="ew", pady=(24, 18))
        ttk.Label(imprint, textvariable=self._gateway_text, style="Status.TLabel", wraplength=500).grid(row=10, column=0, columnspan=2, sticky="w")
        ttk.Label(imprint, textvariable=self._action_text, style="Action.TLabel", wraplength=500).grid(row=11, column=0, columnspan=2, sticky="w", pady=(5, 0))

        self.show_panel_page("story")
        self.refresh()
        self._start_tray()
        self._tray_poll_job = self.root.after(TRAY_POLL_INTERVAL_MS, self._drain_tray_actions)
        if self._tray is not None:
            self.root.withdraw()
        self._build_title_window()

    def _add_event_input(self, parent: ttk.Frame, row: int, label: str, value: tk.StringVar, command: object) -> None:
        ttk.Label(parent, text=label, style="Caption.TLabel").grid(row=row, column=0, columnspan=2, sticky="w")
        ttk.Entry(parent, textvariable=value).grid(row=row + 1, column=EVENT_ENTRY_COLUMN, sticky="ew", pady=(4, 8))
        ttk.Button(parent, text=f"记录{label}", style="Secondary.TButton", command=command).grid(row=row + 1, column=EVENT_BUTTON_COLUMN, sticky="e", padx=(8, 0), pady=(4, 8))

    def _build_title_window(self) -> None:
        window = tk.Toplevel(self.root)
        self._title_window = window
        window.title("同行印记")
        window.geometry("1100x680")
        window.minsize(900, 560)
        window.protocol("WM_DELETE_WINDOW", self.hide)
        canvas = tk.Canvas(window, borderwidth=0, highlightthickness=0)
        self._title_canvas = canvas
        canvas.pack(fill="both", expand=True)
        canvas.bind("<Configure>", lambda _event: self._render_title_window())
        canvas.bind("<Button-1>", self._handle_title_click)
        self._render_title_window()
        window.withdraw()

    def _render_title_window(self) -> None:
        from PIL import Image, ImageDraw, ImageTk

        canvas = self._title_canvas
        if canvas is None or not canvas.winfo_exists():
            return
        width, height = max(900, canvas.winfo_width()), max(560, canvas.winfo_height())
        backgrounds = [item for item in self.gateway.visual_library.backgrounds() if item["enabled"]]
        if not backgrounds:
            return
        self._title_background_index %= len(backgrounds)
        image = Image.open(backgrounds[self._title_background_index]["path"]).convert("RGB")
        scale = max(width / image.width, height / image.height)
        resized = image.resize((round(image.width * scale), round(image.height * scale)), Image.Resampling.LANCZOS)
        left = max(0, (resized.width - width) // 2)
        top = max(0, (resized.height - height) // 2)
        image = resized.crop((left, top, left + width, top + height)).convert("RGBA")
        overlay = Image.new("RGBA", image.size, (0, 0, 0, 0))
        draw = ImageDraw.Draw(overlay)
        menu_width = min(420, max(340, round(width * 0.38)))
        draw.rectangle((0, 0, menu_width, height), fill=(247, 251, 249, 138))
        draw.line((menu_width, 0, menu_width, height), fill=(48, 106, 93, 50), width=1)
        draw.rounded_rectangle((42, 18, 181, 46), radius=14, fill=(249, 252, 251, 220), outline=(67, 124, 112, 82), width=1)
        draw.rectangle((0, height - 35, width, height), fill=(245, 250, 248, 225))
        draw.line((0, height - 35, width, height - 35), fill=(62, 116, 104, 55), width=1)
        image.alpha_composite(overlay)
        self._title_photo = ImageTk.PhotoImage(image.convert("RGB"))
        canvas.delete("all")
        canvas.create_image(0, 0, anchor="nw", image=self._title_photo)
        canvas.create_oval(52, 29, 58, 35, fill="#48a28e", outline="")
        canvas.create_text(66, 32, anchor="w", text="同行印记已连接", fill="#32685d", font=("Microsoft YaHei UI", 9))
        canvas.create_text(42, 66, anchor="nw", text="FIREFLY COMPANION STORY", fill="#36786b", font=("Microsoft YaHei UI", 9, "bold"))
        canvas.create_text(42, 90, anchor="nw", text="同行印记", fill="#174e43", font=("Microsoft YaHei UI", 30, "bold"))
        canvas.create_text(42, 148, anchor="nw", text="有些相遇不会立刻改变什么，", fill="#52756d", font=("Microsoft YaHei UI", 10))
        canvas.create_text(42, 170, anchor="nw", text="却会在之后的日子里，慢慢留下形状。", fill="#52756d", font=("Microsoft YaHei UI", 10))
        canvas.create_line(42, 232, 288, 232, fill="#65998d")
        canvas.create_text(42, 247, anchor="nw", text="第一章 · 初识", fill="#205d50", font=("Microsoft YaHei UI", 12, "bold"))
        canvas.create_text(42, 274, anchor="nw", text="上次停留：清晨的公寓", fill="#69867f", font=("Microsoft YaHei UI", 9))
        canvas.create_line(42, 302, 288, 302, fill="#65998d")
        items = (
            ("继续故事", self.open_story_window),
            ("章节选择", self.open_chapter_selection),
            ("设置", self.open_settings),
        )
        self._title_menu_bounds = []
        menu_top = height - 60 - len(items) * 39
        for index, (text, command) in enumerate(items):
            y = menu_top + index * 39
            if index == 0:
                canvas.create_rectangle(29, y, 257, y + 39, fill="#c6e9de", outline="#75aa9e")
            canvas.create_oval(43, y + 17, 48, y + 22, fill="#328b79" if index == 0 else "#72b7a8", outline="")
            canvas.create_text(58, y + 20, anchor="w", text=text, fill="#205e52" if index == 0 else "#37675d", font=("Microsoft YaHei UI", 11, "bold"))
            canvas.create_line(42, y + 39, 257, y + 39, fill="#79a79c")
            self._title_menu_bounds.append(((29, y, 257, y + 39), command))
        dot_x = width - 115
        for index in range(4):
            canvas.create_rectangle(dot_x + index * 25, height - 51, dot_x + 18 + index * 25, height - 48, fill="#ffffff" if index == self._title_background_index else "#cbdad6", outline="")
        canvas.create_text(17, height - 18, anchor="w", text="RELATIONSHIP / 初识", fill="#a0614d", font=("Microsoft YaHei UI", 8, "bold"))
        canvas.create_text(width - 17, height - 18, anchor="e", text="本地保存 · 端口 8787", fill="#647f78", font=("Microsoft YaHei UI", 8))
        if self._title_rotation_job is not None:
            canvas.after_cancel(self._title_rotation_job)
        if len(backgrounds) > 1:
            self._title_rotation_job = canvas.after(8_000, self._rotate_title_background)

    def _rotate_title_background(self) -> None:
        self._title_rotation_job = None
        self._title_background_index += 1
        self._render_title_window()

    def _handle_title_click(self, event: tk.Event) -> str:
        for (left, top, right, bottom), command in self._title_menu_bounds:
            if left <= event.x <= right and top <= event.y <= bottom:
                command()
                break
        return "break"

    def open_management_panel(self) -> None:
        if self._title_window is not None:
            self._title_window.withdraw()
        self.root.deiconify()
        self.root.lift()

    def open_background_settings(self) -> None:
        self.open_settings("background")

    def open_cg_gallery(self) -> None:
        self.open_settings("cg")

    def open_settings(self, initial_page: str = "background") -> None:
        window = tk.Toplevel(self._title_window or self.root)
        window.title("同行印记设置")
        window.geometry("980x620")
        window.minsize(900, 570)
        window.configure(background="#f6faf8")
        header = tk.Frame(window, height=54, background="#ffffff", highlightbackground="#d6e4e0", highlightthickness=1)
        header.pack(fill="x")
        header.pack_propagate(False)
        tk.Label(header, text="同行印记设置", background="#ffffff", foreground="#294b43", font=("Microsoft YaHei UI", 12, "bold")).pack(side="left", padx=18)
        tk.Label(header, text="收藏与显示", background="#ffffff", foreground="#79908a", font=("Microsoft YaHei UI", 9)).pack(side="right", padx=18)
        body = tk.Frame(window, background="#f6faf8")
        body.pack(fill="both", expand=True)
        sidebar = tk.Frame(body, width=190, background="#edf5f2", highlightbackground="#d8e5e1", highlightthickness=1)
        sidebar.pack(side="left", fill="y")
        sidebar.pack_propagate(False)
        content = tk.Frame(body, background="#f6faf8")
        content.pack(side="left", fill="both", expand=True)
        current = {"page": initial_page}
        nav_buttons: dict[str, tk.Button] = {}

        def clear_content() -> None:
            for child in content.winfo_children():
                child.destroy()

        def nav_style() -> None:
            for name, button in nav_buttons.items():
                button.configure(
                    background="#c9e8df" if name == current["page"] else "#edf5f2",
                    foreground="#225f52" if name == current["page"] else "#607a73",
                    font=("Microsoft YaHei UI", 10, "bold" if name == current["page"] else "normal"),
                )

        def show_backgrounds() -> None:
            from PIL import Image, ImageTk

            clear_content()
            page = tk.Frame(content, background="#f6faf8")
            page.pack(fill="both", expand=True, padx=24, pady=22)
            top = tk.Frame(page, background="#f6faf8")
            top.pack(fill="x")
            tk.Label(top, text="开始界面背景", background="#f6faf8", foreground="#244f45", font=("Microsoft YaHei UI", 15, "bold")).pack(anchor="w")
            tk.Label(top, text="选择参与轮换的图片。用户图片会复制到同行印记的数据目录。", background="#f6faf8", foreground="#748a84", font=("Microsoft YaHei UI", 9)).pack(anchor="w", pady=(3, 0))
            gallery_shell = tk.Frame(page, background="#f6faf8")
            gallery_shell.pack(fill="both", expand=True, pady=(16, 10))
            gallery_canvas = tk.Canvas(gallery_shell, background="#f6faf8", borderwidth=0, highlightthickness=0)
            gallery_scrollbar = ttk.Scrollbar(gallery_shell, orient="vertical", command=gallery_canvas.yview)
            gallery_canvas.configure(yscrollcommand=gallery_scrollbar.set)
            gallery_canvas.pack(side="left", fill="both", expand=True)
            gallery_scrollbar.pack(side="right", fill="y")
            gallery = tk.Frame(gallery_canvas, background="#f6faf8")
            gallery_window = gallery_canvas.create_window((0, 0), window=gallery, anchor="nw")
            gallery.bind("<Configure>", lambda _event: gallery_canvas.configure(scrollregion=gallery_canvas.bbox("all")))
            gallery_canvas.bind("<Configure>", lambda event: gallery_canvas.itemconfigure(gallery_window, width=event.width))
            state = {"items": list(self.gateway.visual_library.backgrounds()), "selected": set(), "focus": ""}
            state["selected"] = {str(item["id"]) for item in state["items"] if item["enabled"]}
            photos: list[object] = []

            def scroll_gallery(event: tk.Event) -> str:
                gallery_canvas.yview_scroll(int(-event.delta / 120), "units")
                return "break"

            gallery_canvas.bind("<MouseWheel>", scroll_gallery)

            def render_cards() -> None:
                for child in gallery.winfo_children():
                    child.destroy()
                photos.clear()
                for index, item in enumerate(state["items"]):
                    item_id = str(item["id"])
                    selected = item_id in state["selected"]
                    card = tk.Canvas(gallery, width=292, height=166, background="#dce9e5", highlightthickness=2 if selected else 1, highlightbackground="#429c89" if selected else "#d1e0dc", cursor="hand2")
                    card.grid(row=index // 2, column=index % 2, padx=6, pady=6, sticky="nw")
                    image = Image.open(item["path"]).convert("RGB")
                    scale = max(292 / image.width, 166 / image.height)
                    image = image.resize((round(image.width * scale), round(image.height * scale)), Image.Resampling.LANCZOS)
                    image = image.crop(((image.width - 292) // 2, (image.height - 166) // 2, (image.width - 292) // 2 + 292, (image.height - 166) // 2 + 166))
                    photo = ImageTk.PhotoImage(image)
                    photos.append(photo)
                    card.create_image(0, 0, anchor="nw", image=photo)
                    card.create_rectangle(0, 124, 292, 166, fill="#f6fbf9", outline="")
                    card.create_text(11, 145, anchor="w", text=str(item["title"]), fill="#294f46", font=("Microsoft YaHei UI", 9, "bold"))
                    card.create_text(280, 145, anchor="e", text="内置" if item["builtin"] else "用户添加", fill="#738a84", font=("Microsoft YaHei UI", 8))
                    card.create_oval(9, 9, 31, 31, fill="#c8ebe1" if selected else "#f8fbfa", outline="#5ba995")
                    if selected:
                        card.create_text(20, 20, text="✓", fill="#1d6657", font=("Microsoft YaHei UI", 10, "bold"))

                    def toggle(_event: tk.Event, value: str = item_id) -> None:
                        state["focus"] = value
                        if value in state["selected"]:
                            if len(state["selected"]) > 1:
                                state["selected"].remove(value)
                        else:
                            state["selected"].add(value)
                        render_cards()

                    card.bind("<Button-1>", toggle)
                    card.bind("<MouseWheel>", scroll_gallery)
                gallery.update_idletasks()
                gallery_canvas.configure(scrollregion=gallery_canvas.bbox("all"))
                window._background_photos = photos

            def add_image() -> None:
                path = filedialog.askopenfilename(parent=window, filetypes=(("图片", "*.png *.jpg *.jpeg *.webp"),))
                if path:
                    item = self.gateway.visual_library.add_background(path)
                    state["items"] = list(self.gateway.visual_library.backgrounds())
                    state["selected"].add(str(item["id"]))
                    render_cards()

            def delete_image() -> None:
                item = next((item for item in state["items"] if item["id"] == state["focus"]), None)
                if item is None or item["builtin"]:
                    return
                self.gateway.visual_library.delete_background(str(item["id"]))
                state["selected"].discard(str(item["id"]))
                state["items"] = list(self.gateway.visual_library.backgrounds())
                render_cards()

            def save_selection() -> None:
                self.gateway.visual_library.set_enabled_backgrounds(list(state["selected"]))
                self._title_background_index = 0
                self._render_title_window()

            render_cards()
            actions = tk.Frame(page, background="#f6faf8")
            actions.pack(fill="x")
            for text, command in (("添加图片", add_image), ("删除用户图片", delete_image)):
                tk.Button(actions, text=text, command=command, relief="flat", background="#d8eee8", foreground="#245f52", activebackground="#c9e8df", font=("Microsoft YaHei UI", 9, "bold"), padx=14, pady=7).pack(side="left", padx=(0, 8))
            tk.Button(actions, text="保存选择", command=save_selection, relief="flat", background="#2f8e7d", foreground="#ffffff", activebackground="#287b6c", font=("Microsoft YaHei UI", 9, "bold"), padx=16, pady=7).pack(side="right")

        def show_cg() -> None:
            from PIL import Image, ImageTk

            clear_content()
            page = tk.Frame(content, background="#f6faf8")
            page.pack(fill="both", expand=True, padx=24, pady=22)
            tk.Label(page, text="剧情 CG 图鉴", background="#f6faf8", foreground="#244f45", font=("Microsoft YaHei UI", 15, "bold")).pack(anchor="w")
            tk.Label(page, text="选择章节，回看已经在剧情中出现或成功生成的画面。", background="#f6faf8", foreground="#748a84", font=("Microsoft YaHei UI", 9)).pack(anchor="w", pady=(3, 12))
            controls = tk.Frame(page, background="#f6faf8")
            controls.pack(fill="x")
            gallery = tk.Frame(page, background="#f6faf8")
            gallery.pack(fill="both", expand=True, pady=(14, 0))
            chapters = tk.Frame(gallery, width=165, background="#edf5f2", highlightbackground="#d8e5e1", highlightthickness=1)
            chapters.pack(side="left", fill="y")
            chapters.pack_propagate(False)
            album = tk.Frame(gallery, background="#f6faf8")
            album.pack(side="left", fill="both", expand=True, padx=(16, 0))
            mode = {"value": "story", "chapter_id": ""}
            photos: list[object] = []
            mode_buttons: dict[str, tk.Button] = {}

            def render() -> None:
                for child in chapters.winfo_children():
                    child.destroy()
                for child in album.winfo_children():
                    child.destroy()
                photos.clear()
                for name, button in mode_buttons.items():
                    button.configure(background="#c9e8df" if name == mode["value"] else "#d8eee8", foreground="#225f52" if name == mode["value"] else "#416b60")
                if mode["value"] == "story":
                    items = []
                    for session in self.gateway.narrative_archive_store.load():
                        if session.lines:
                            line = session.lines[-1]
                            items.append((session.chapter_id, narrative_event_definition(session.event_id).title, _cached_story_stage(line.scene or default_scene_id(), line.sprite or default_sprite_id(), 300, 185).convert("RGB"), "", True))
                    empty = "完成剧情后，实际出现过的画面会在这里收录。"
                else:
                    items = [
                        (str(item["chapter_id"]), str(item["title"]), Image.open(item["path"]).convert("RGB"), str(item["id"]), bool(item["selected"]))
                        for item in self.gateway.visual_library.chapter_cgs()
                    ]
                    empty = "章节完成后会保存待补绘档案；有生图模型时可以在这里生成。"
                chapter_ids = list(dict.fromkeys(item[0] for item in items))
                progress = self.gateway.narrative_store.load()
                if mode["value"] == "chapter" and progress.finale_completed and progress.chapter_id not in chapter_ids:
                    chapter_ids.append(progress.chapter_id)
                chapter_titles = {chapter.id: chapter.title for chapter in CHAPTERS}
                if chapter_ids and mode["chapter_id"] not in chapter_ids:
                    mode["chapter_id"] = chapter_ids[0]
                tk.Label(chapters, text="剧情章节", anchor="w", background="#edf5f2", foreground="#6d827c", font=("Microsoft YaHei UI", 8), padx=12, pady=10).pack(fill="x")
                for chapter_id in chapter_ids:
                    selected = chapter_id == mode["chapter_id"]
                    count = sum(1 for item in items if item[0] == chapter_id)

                    def choose(value: str = chapter_id) -> None:
                        mode["chapter_id"] = value
                        render()

                    button = tk.Button(
                        chapters,
                        text=f"{chapter_titles.get(chapter_id, chapter_id)}\n{count} 张已收录",
                        command=choose,
                        anchor="w",
                        justify="left",
                        relief="flat",
                        borderwidth=0,
                        background="#c9e8df" if selected else "#edf5f2",
                        foreground="#225f52" if selected else "#607a73",
                        activebackground="#c9e8df",
                        font=("Microsoft YaHei UI", 9, "bold" if selected else "normal"),
                        padx=12,
                        pady=9,
                    )
                    button.pack(fill="x", padx=7, pady=3)
                shown = [item for item in items if item[0] == mode["chapter_id"]]
                if mode["value"] == "chapter" and mode["chapter_id"]:
                    self.gateway.ensure_chapter_cg_brief(mode["chapter_id"])
                    status = self.gateway.visual_library.chapter_cg_status(mode["chapter_id"])
                    status_bar = tk.Frame(album, background="#edf5f2", highlightbackground="#cfdfda", highlightthickness=1)
                    status_bar.grid(row=0, column=0, columnspan=2, sticky="ew", pady=(0, 10))
                    message = (
                        f"已生成 {status['count']} 张，还可成功生成 {status['remaining']} 张"
                        if status["available"]
                        else "未检测到生图模型，章节CG档案已保留，可稍后补绘"
                    )
                    tk.Label(status_bar, text=message, background="#edf5f2", foreground="#476b62", font=("Microsoft YaHei UI", 9), padx=12, pady=10).pack(side="left")

                    def generate_chapter_cg() -> None:
                        self.gateway.visual_library.create_chapter_job(mode["chapter_id"])
                        render()

                    generate = tk.Button(status_bar, text="生成专属 CG", command=generate_chapter_cg, relief="flat", background="#2f8e7d", foreground="#ffffff", font=("Microsoft YaHei UI", 9, "bold"), padx=12, pady=6)
                    generate.pack(side="right", padx=8, pady=6)
                    if not status["available"] or not status["has_brief"] or status["pending"] or status["remaining"] <= 0:
                        generate.configure(state="disabled", background="#b9c9c4")
                if not shown:
                    tk.Label(album, text=empty, background="#ffffff", foreground="#71857f", font=("Microsoft YaHei UI", 10), padx=14, pady=14, anchor="w").grid(row=1, column=0, columnspan=2, sticky="ew")
                elif mode["chapter_id"]:
                    heading_row = 1 if mode["value"] == "chapter" else 0
                    tk.Label(album, text=chapter_titles.get(mode["chapter_id"], mode["chapter_id"]), background="#f6faf8", foreground="#315e53", font=("Microsoft YaHei UI", 10, "bold"), anchor="w").grid(row=heading_row, column=0, columnspan=2, sticky="ew", pady=(0, 8))
                for index, (_chapter_id, title, image, item_id, selected) in enumerate(shown):
                    full_image = image.copy()
                    image.thumbnail((300, 185), Image.Resampling.LANCZOS)
                    photo = ImageTk.PhotoImage(image)
                    photos.append(photo)
                    card = tk.Frame(album, background="#ffffff", highlightbackground="#d1e0dc", highlightthickness=1)
                    base_row = 2 if mode["value"] == "chapter" else 1
                    card.grid(row=base_row + index // 2, column=index % 2, padx=6, pady=6, sticky="nw")
                    image_label = tk.Label(card, image=photo, background="#ffffff", cursor="hand2")
                    image_label.pack()
                    title_label = tk.Label(card, text=title, background="#ffffff", foreground="#294f46", font=("Microsoft YaHei UI", 9, "bold"), anchor="w", padx=9, pady=7, cursor="hand2")
                    title_label.pack(fill="x")
                    if item_id:
                        def toggle_selected(value: str = item_id, next_value: bool = not selected) -> None:
                            self.gateway.visual_library.set_chapter_cg_selected(value, next_value)
                            render()

                        tk.Button(
                            card, text="已收藏" if selected else "收藏", command=toggle_selected,
                            relief="flat", background="#c9e8df" if selected else "#edf5f2",
                            foreground="#286c5e", font=("Microsoft YaHei UI", 8, "bold"), pady=5,
                        ).pack(fill="x")

                    def view(_event: tk.Event, value: object = full_image, item_title: str = title) -> None:
                        self._open_cg_viewer(item_title, value)

                    for widget in (card, image_label, title_label):
                        widget.bind("<Button-1>", view)
                window._cg_photos = photos

            def set_mode(value: str) -> None:
                mode["value"] = value
                render()

            for name, label in (("story", "剧情配图"), ("chapter", "章节专属 CG")):
                button = tk.Button(controls, text=label, command=lambda value=name: set_mode(value), relief="flat", font=("Microsoft YaHei UI", 9, "bold"), padx=13, pady=6)
                button.pack(side="left", padx=(0, 5))
                mode_buttons[name] = button
            render()

        def show_storage() -> None:
            clear_content()
            page = tk.Frame(content, background="#f6faf8")
            page.pack(fill="both", expand=True, padx=24, pady=22)
            tk.Label(page, text="数据与存储", background="#f6faf8", foreground="#244f45", font=("Microsoft YaHei UI", 15, "bold")).pack(anchor="w")
            tk.Label(page, text="背景、剧情回放和章节 CG 均保存在本机。", background="#f6faf8", foreground="#748a84", font=("Microsoft YaHei UI", 9)).pack(anchor="w", pady=(3, 16))
            tk.Label(page, text=str(self.gateway.config.data_dir), background="#ffffff", foreground="#315e53", font=("Microsoft YaHei UI", 10), padx=14, pady=14, anchor="w").pack(fill="x")

        def show_playback() -> None:
            clear_content()
            page = tk.Frame(content, background="#f6faf8")
            page.pack(fill="both", expand=True, padx=24, pady=22)
            tk.Label(page, text="剧情演出", background="#f6faf8", foreground="#244f45", font=("Microsoft YaHei UI", 15, "bold")).pack(anchor="w")
            tk.Label(page, text="调整逐字速度、自动播放和音量。", background="#f6faf8", foreground="#748a84", font=("Microsoft YaHei UI", 9)).pack(anchor="w", pady=(3, 18))
            values = {
                "text_speed_ms": tk.IntVar(value=int(self._story_playback["text_speed_ms"])),
                "auto_wait_ms": tk.IntVar(value=int(self._story_playback["auto_wait_ms"])),
                "bgm_volume": tk.IntVar(value=int(self._story_playback["bgm_volume"])),
                "ambient_volume": tk.IntVar(value=int(self._story_playback["ambient_volume"])),
            }
            rows = (
                ("text_speed_ms", "文字速度", 5, 100, "数值越小，文字出现越快"),
                ("auto_wait_ms", "自动播放等待", 300, 4_000, "每句显示完成后的等待时间"),
                ("bgm_volume", "背景音乐音量", 0, 100, "0 为静音"),
                ("ambient_volume", "环境音音量", 0, 100, "为后续场景环境音预留"),
            )
            for key, label, minimum, maximum, caption in rows:
                row = tk.Frame(page, background="#ffffff", highlightbackground="#d5e3df", highlightthickness=1)
                row.pack(fill="x", pady=(0, 10))
                tk.Label(row, text=label, background="#ffffff", foreground="#315e53", font=("Microsoft YaHei UI", 10, "bold"), width=16, anchor="w", padx=14).pack(side="left")
                tk.Scale(
                    row, from_=minimum, to=maximum, orient="horizontal", variable=values[key],
                    background="#ffffff", foreground="#4b6d65", highlightthickness=0, length=310,
                ).pack(side="left", fill="x", expand=True, padx=8, pady=8)
                tk.Label(row, text=caption, background="#ffffff", foreground="#7b8e89", font=("Microsoft YaHei UI", 8), width=25, anchor="w").pack(side="right", padx=12)

            def save_playback() -> None:
                self._story_playback = self._playback_store.update_settings(
                    **{key: value.get() for key, value in values.items()}
                )
                self._story_audio.set_volume(int(self._story_playback["bgm_volume"]))
                self._story_ambient_audio.set_volume(int(self._story_playback["ambient_volume"]))

            tk.Button(
                page, text="保存演出设置", command=save_playback, relief="flat",
                background="#2f8e7d", foreground="#ffffff", activebackground="#287b6c",
                font=("Microsoft YaHei UI", 9, "bold"), padx=18, pady=8,
            ).pack(anchor="e", pady=(8, 0))

        pages = {"background": show_backgrounds, "playback": show_playback, "cg": show_cg, "storage": show_storage}

        def switch(page: str) -> None:
            current["page"] = page
            nav_style()
            pages[page]()

        for name, label in (("background", "开始界面背景"), ("playback", "剧情演出"), ("cg", "剧情 CG 图鉴"), ("storage", "数据与存储")):
            button = tk.Button(sidebar, text=f"●  {label}", anchor="w", relief="flat", borderwidth=0, command=lambda value=name: switch(value), padx=13, pady=11)
            button.pack(fill="x", padx=10, pady=(14 if not nav_buttons else 0, 2))
            nav_buttons[name] = button
        switch(initial_page if initial_page in pages else "background")

    def _open_cg_viewer(self, title: str, source_image: object) -> None:
        from PIL import Image, ImageTk

        window = tk.Toplevel(self._title_window or self.root)
        window.title(title)
        window.geometry("1000x650")
        window.minsize(760, 500)
        window.configure(background="#10231f")
        canvas = tk.Canvas(window, background="#10231f", borderwidth=0, highlightthickness=0, cursor="arrow")
        canvas.pack(fill="both", expand=True)
        photo = {"value": None}

        def render(_event: tk.Event | None = None) -> None:
            if not isinstance(source_image, Image.Image):
                return
            width, height = max(760, canvas.winfo_width()), max(500, canvas.winfo_height())
            image = source_image.copy().convert("RGB")
            image.thumbnail((width - 56, height - 92), Image.Resampling.LANCZOS)
            photo["value"] = ImageTk.PhotoImage(image)
            canvas.delete("all")
            canvas.create_image(width // 2, (height - 44) // 2, image=photo["value"])
            canvas.create_rectangle(0, height - 44, width, height, fill="#18332c", outline="")
            canvas.create_text(20, height - 22, anchor="w", text=title, fill="#eaf7f3", font=("Microsoft YaHei UI", 10, "bold"))
            canvas.create_text(width - 22, 22, text="×", fill="#ffffff", font=("Microsoft YaHei UI", 19), tags="close")

        def click(event: tk.Event) -> None:
            if event.x >= canvas.winfo_width() - 55 and event.y <= 55:
                window.destroy()

        canvas.bind("<Configure>", render)
        canvas.bind("<Button-1>", click)
        window.bind("<Escape>", lambda _event: window.destroy())
        render()

    def open_chapter_selection(self) -> None:
        from PIL import Image, ImageDraw, ImageTk

        window = tk.Toplevel(self._title_window or self.root)
        window.title("章节选择")
        window.geometry("1000x620")
        window.minsize(860, 540)
        canvas = tk.Canvas(window, borderwidth=0, highlightthickness=0)
        canvas.pack(fill="both", expand=True)
        photo = {"value": None}
        archives = self.gateway.narrative_archive_store.load()
        progress = self.gateway.narrative_store.load()
        available = [
            chapter for chapter in CHAPTERS
            if chapter.id == progress.chapter_id or any(session.chapter_id == chapter.id for session in archives)
        ]
        selected = {"id": progress.chapter_id if any(chapter.id == progress.chapter_id for chapter in available) else available[0].id}
        chapter_bounds: list[tuple[tuple[int, int, int, int], str]] = []
        replay_bounds: list[tuple[tuple[int, int, int, int], str]] = []
        action_bounds = {"value": (0, 0, 0, 0)}

        def chapter_completed(chapter_id: str) -> bool:
            return (
                chapter_id == progress.chapter_id and progress.finale_completed
            ) or any(
                session.chapter_id == chapter_id and session.event_id == CHAPTER_ONE_FINALE_ID and session.completed
                for session in archives
            )

        def render(_event: tk.Event | None = None) -> None:
            backgrounds = [item for item in self.gateway.visual_library.backgrounds() if item["enabled"]]
            if not backgrounds:
                return
            width, height = max(860, canvas.winfo_width()), max(540, canvas.winfo_height())
            image = Image.open(backgrounds[self._title_background_index % len(backgrounds)]["path"]).convert("RGB")
            scale = max(width / image.width, height / image.height)
            image = image.resize((round(image.width * scale), round(image.height * scale)), Image.Resampling.LANCZOS)
            image = image.crop(((image.width - width) // 2, (image.height - height) // 2, (image.width - width) // 2 + width, (image.height - height) // 2 + height)).convert("RGBA")
            shade = Image.new("RGBA", image.size, (0, 0, 0, 0))
            draw = ImageDraw.Draw(shade)
            draw.rectangle((0, 0, width, 72), fill=(247, 251, 249, 205))
            draw.rectangle((0, height - 159, width, height), fill=(247, 251, 249, 225))
            draw.line((0, 72, width, 72), fill=(51, 108, 95, 55), width=1)
            draw.line((0, height - 159, width, height - 159), fill=(51, 108, 95, 60), width=1)
            image.alpha_composite(shade)
            photo["value"] = ImageTk.PhotoImage(image.convert("RGB"))
            canvas.delete("all")
            canvas.create_image(0, 0, anchor="nw", image=photo["value"])
            canvas.create_text(24, 18, anchor="nw", text="CHAPTER SELECT", fill="#36786b", font=("Microsoft YaHei UI", 8, "bold"))
            canvas.create_text(24, 35, anchor="nw", text="章节选择", fill="#174e43", font=("Microsoft YaHei UI", 20, "bold"))
            canvas.create_text(width - 22, 40, anchor="e", text="选择已经开启的故事章节", fill="#647f78", font=("Microsoft YaHei UI", 9))
            chapter_bounds.clear()
            replay_bounds.clear()
            completed_stories = completed_chapter_stories(archives, selected["id"])
            canvas.create_text(22, 92, anchor="nw", text="已走过的小剧情", fill="#245f52", font=("Microsoft YaHei UI", 11, "bold"))
            if not completed_stories:
                canvas.create_text(22, 122, anchor="nw", text="完成小剧情后，可在这里选择重温。", fill="#6f8780", font=("Microsoft YaHei UI", 9))
            for index, session in enumerate(completed_stories[-6:]):
                top = 122 + index * 55
                bounds = (18, top, min(390, width - 180), top + 46)
                canvas.create_rectangle(*bounds, fill="#f8fbfa", outline="#9fc3ba")
                canvas.create_text(bounds[0] + 12, top + 10, anchor="nw", text=narrative_event_definition(session.event_id).title, fill="#205e52", font=("Microsoft YaHei UI", 9, "bold"))
                canvas.create_text(bounds[2] - 12, top + 25, anchor="e", text="点击重温", fill="#347d6d", font=("Microsoft YaHei UI", 8))
                replay_bounds.append((bounds, session.event_id))
            card_top = height - 145
            card_width = min(210, max(170, (width - 150) // max(1, min(4, len(available))) - 10))
            for index, chapter in enumerate(available):
                left = 18 + index * (card_width + 9)
                right = left + card_width
                active = chapter.id == selected["id"]
                completed = chapter_completed(chapter.id)
                count = sum(1 for session in archives if session.chapter_id == chapter.id and session.completed)
                canvas.create_rectangle(left, card_top, right, card_top + 91, fill="#c9e8df" if active else "#f8fbfa", outline="#65a393" if active else "#9fc3ba")
                canvas.create_text(left + 11, card_top + 13, anchor="nw", text=chapter.title, width=card_width - 22, fill="#205e52", font=("Microsoft YaHei UI", 10, "bold"))
                canvas.create_text(left + 11, card_top + 41, anchor="nw", text=chapter.finale_title, width=card_width - 22, fill="#607d75", font=("Microsoft YaHei UI", 8))
                status = f"已完成 · {count} 段回忆" if completed else f"进行中 · {count} 段回忆"
                canvas.create_text(left + 11, card_top + 70, anchor="nw", text=status, fill="#347d6d", font=("Microsoft YaHei UI", 8, "bold"))
                chapter_bounds.append(((left, card_top, right, card_top + 91), chapter.id))
            selected_chapter = next(chapter for chapter in available if chapter.id == selected["id"])
            action_left = width - 124
            action_top = card_top + 28
            canvas.create_rectangle(action_left, action_top, width - 18, action_top + 38, fill="#2f8e7d", outline="")
            canvas.create_text((action_left + width - 18) // 2, action_top + 19, text="查看章节" if chapter_completed(selected_chapter.id) else "进入章节", fill="#ffffff", font=("Microsoft YaHei UI", 9, "bold"))
            action_bounds["value"] = (action_left, action_top, width - 18, action_top + 38)
            canvas.create_text(18, height - 12, anchor="w", text=f"RELATIONSHIP / {relationship_theme(selected_chapter.stage).label}", fill="#a0614d", font=("Microsoft YaHei UI", 8, "bold"))

        def click(event: tk.Event) -> None:
            for (left, top, right, bottom), event_id in replay_bounds:
                if left <= event.x <= right and top <= event.y <= bottom:
                    window.destroy()
                    self.open_completed_story(event_id)
                    return
            for (left, top, right, bottom), chapter_id in chapter_bounds:
                if left <= event.x <= right and top <= event.y <= bottom:
                    selected["id"] = chapter_id
                    render()
                    return
            left, top, right, bottom = action_bounds["value"]
            if left <= event.x <= right and top <= event.y <= bottom:
                chapter_id = selected["id"]
                window.destroy()
                if chapter_completed(chapter_id):
                    self.open_chapter_history(chapter_id)
                else:
                    self.open_story_window()

        canvas.bind("<Configure>", render)
        canvas.bind("<Button-1>", click)
        render()

    def open_chapter_history(self, chapter_id: str) -> None:
        from PIL import Image

        window = tk.Toplevel(self._title_window or self.root)
        window.title("章节回顾")
        window.geometry("960x620")
        window.minsize(860, 540)
        window.configure(background="#f6faf8")
        archives = completed_chapter_stories(self.gateway.narrative_archive_store.load(), chapter_id)
        chapter = next((item for item in CHAPTERS if item.id == chapter_id), CHAPTERS[0])
        header = tk.Frame(window, height=72, background="#ffffff", highlightbackground="#d5e3df", highlightthickness=1)
        header.pack(fill="x")
        header.pack_propagate(False)
        title_box = tk.Frame(header, background="#ffffff")
        title_box.pack(side="left", padx=20, pady=13)
        tk.Label(title_box, text="CHAPTER MEMORIES", background="#ffffff", foreground="#3b7b6d", font=("Microsoft YaHei UI", 8, "bold")).pack(anchor="w")
        tk.Label(title_box, text=chapter.title, background="#ffffff", foreground="#214f43", font=("Microsoft YaHei UI", 16, "bold")).pack(anchor="w", pady=(3, 0))
        body = tk.Frame(window, background="#f6faf8")
        body.pack(fill="both", expand=True)
        side = tk.Frame(body, width=180, background="#edf5f2", highlightbackground="#d7e4e0", highlightthickness=1)
        side.pack(side="left", fill="y")
        side.pack_propagate(False)
        available_ids = list(dict.fromkeys(session.chapter_id for session in self.gateway.narrative_archive_store.load() if session.completed))
        for available_id in available_ids:
            available_chapter = next((item for item in CHAPTERS if item.id == available_id), None)
            if available_chapter is None:
                continue
            tk.Button(
                side,
                text=available_chapter.title,
                command=lambda value=available_id: (window.destroy(), self.open_chapter_history(value)),
                anchor="w",
                relief="flat",
                borderwidth=0,
                background="#c9e8df" if available_id == chapter_id else "#edf5f2",
                foreground="#225f52" if available_id == chapter_id else "#607a73",
                font=("Microsoft YaHei UI", 9, "bold" if available_id == chapter_id else "normal"),
                padx=12,
                pady=11,
            ).pack(fill="x", padx=8, pady=(12 if available_id == available_ids[0] else 2, 2))
        content = tk.Frame(body, background="#f6faf8")
        content.pack(side="left", fill="both", expand=True, padx=22, pady=18)
        chapter_cgs = [item for item in self.gateway.visual_library.chapter_cgs() if item["chapter_id"] == chapter_id]
        self.gateway.ensure_chapter_cg_brief(chapter_id)
        cg_status = self.gateway.visual_library.chapter_cg_status(chapter_id)
        summary = tk.Frame(content, background="#f6faf8")
        summary.pack(fill="x", pady=(0, 12))
        tk.Label(summary, text="已经共同经历的故事", background="#f6faf8", foreground="#315e53", font=("Microsoft YaHei UI", 11, "bold")).pack(side="left")
        tk.Label(summary, text=f"{len(archives)} 段回忆 · {len(chapter_cgs)} 张专属 CG", background="#f6faf8", foreground="#738983", font=("Microsoft YaHei UI", 8)).pack(side="right")
        cg_actions = tk.Frame(content, background="#f6faf8")
        cg_actions.pack(fill="x", pady=(0, 12))

        def generate_chapter_cg() -> None:
            self.gateway.visual_library.create_chapter_job(chapter_id)
            window.destroy()
            self.open_chapter_history(chapter_id)

        generate = tk.Button(
            cg_actions,
            text=f"生成专属 CG（剩余 {cg_status['remaining']} 次）" if cg_status["available"] else "待生图模型可用后补绘",
            command=generate_chapter_cg,
            relief="flat",
            background="#2f8e7d",
            foreground="#ffffff",
            font=("Microsoft YaHei UI", 9, "bold"),
            padx=12,
            pady=7,
        )
        generate.pack(side="left")
        if not cg_status["available"] or not cg_status["has_brief"] or cg_status["pending"] or cg_status["remaining"] <= 0:
            generate.configure(state="disabled", background="#b9c9c4")
        for index, chapter_cg in enumerate(chapter_cgs, 1):
            tk.Button(
                cg_actions,
                text=f"查看 CG {index}",
                command=lambda item=chapter_cg: self._open_cg_viewer(str(item["title"]), Image.open(item["path"]).convert("RGB")),
                relief="flat",
                background="#d8eee8",
                foreground="#245f52",
                font=("Microsoft YaHei UI", 9, "bold"),
                padx=12,
                pady=7,
            ).pack(side="left", padx=(8, 0))
        if not archives:
            tk.Label(content, text="这一章暂时没有可重温的剧情归档。", background="#ffffff", foreground="#71857f", font=("Microsoft YaHei UI", 10), padx=14, pady=14, anchor="w").pack(fill="x")
        for index, session in enumerate(archives):
            event = narrative_event_definition(session.event_id)
            row = tk.Frame(content, background="#ffffff", highlightbackground="#d0e0dc", highlightthickness=1)
            row.pack(fill="x", pady=(0, 8))
            marker = tk.Label(row, text=f"{index + 1:02d}", background="#c9e8df", foreground="#286c5e", font=("Microsoft YaHei UI", 9, "bold"), width=4, pady=12)
            marker.pack(side="left", fill="y")
            copy = tk.Frame(row, background="#ffffff")
            copy.pack(side="left", fill="both", expand=True, padx=12, pady=8)
            tk.Label(copy, text=event.title, background="#ffffff", foreground="#294f46", font=("Microsoft YaHei UI", 10, "bold")).pack(anchor="w")
            tk.Label(copy, text=session.event_summary or event.purpose, background="#ffffff", foreground="#7a8d88", font=("Microsoft YaHei UI", 8), wraplength=470, justify="left").pack(anchor="w", pady=(3, 0))

            def replay(value: str = session.event_id) -> None:
                window.destroy()
                self.open_completed_story(value)

            tk.Button(row, text="重新播放", command=replay, relief="flat", background="#ffffff", foreground="#2f806e", activebackground="#eef8f5", font=("Microsoft YaHei UI", 9, "bold"), padx=12).pack(side="right", fill="y")

    def _current_story_line(self) -> StoryLine:
        if not self._story_lines:
            raise StateError("story is unavailable")
        return self._story_lines[self._story_index]

    def _story_line_key(self) -> tuple[int, str, bool, str | None]:
        line = self._current_story_line()
        return self._story_index, line.text, self._story_judging, self._story_choice_error

    def _prepare_story_text(self, text: str) -> str:
        key = self._story_line_key()
        if key != self._story_display_key:
            self._cancel_story_timers(text_only=True)
            self._story_display_key = key
            reveal_immediately = self._story_judging or bool(self._story_choice_error)
            already_read = self._story_replay or self._playback_store.is_read(self._current_story_line())
            if self._story_skip and not already_read:
                self._story_skip = False
            if not reveal_immediately and already_read:
                reveal_immediately = self._story_skip
            self._story_reveal_chars = len(text) if reveal_immediately else 0
        if self._story_reveal_chars < len(text) and self._story_text_job is None:
            self._story_text_job = self._story_window.after(
                int(self._story_playback["text_speed_ms"]), self._story_text_tick
            )
        elif self._story_reveal_chars >= len(text):
            self._schedule_story_auto()
        return text[:self._story_reveal_chars]

    def _story_text_tick(self) -> None:
        self._story_text_job = None
        if self._story_window is None or not self._story_window.winfo_exists() or not self._story_lines:
            return
        text = self._story_choice_error or self._current_story_line().text
        step = 3 if self._story_skip else 1
        self._story_reveal_chars = min(len(text), self._story_reveal_chars + step)
        self._render_story_window()

    def _story_text_complete(self) -> bool:
        if not self._story_lines:
            return True
        text = getattr(self, "_story_choice_error", None) or self._current_story_line().text
        return getattr(self, "_story_judging", False) or getattr(self, "_story_reveal_chars", len(text)) >= len(text)

    def _schedule_story_auto(self) -> None:
        if (
            self._story_auto_job is not None
            or self._story_window is None
            or self._story_judging
            or self._story_accepts_choice()
        ):
            return
        delay = 60 if self._story_skip else int(self._story_playback["auto_wait_ms"])
        if not self._story_auto and not self._story_skip:
            return
        if self._story_skip and not (self._story_replay or self._playback_store.is_read(self._current_story_line())):
            self._story_skip = False
            self._render_story_window()
            return
        self._story_auto_job = self._story_window.after(delay, self._story_auto_advance)

    def _story_auto_advance(self) -> None:
        self._story_auto_job = None
        self.advance_story()

    def _cancel_story_timers(self, *, text_only: bool = False) -> None:
        window = getattr(self, "_story_window", None)
        if window is None:
            return
        if getattr(self, "_story_text_job", None) is not None:
            try:
                window.after_cancel(self._story_text_job)
            except tk.TclError:
                pass
            self._story_text_job = None
        if not text_only and getattr(self, "_story_auto_job", None) is not None:
            try:
                window.after_cancel(self._story_auto_job)
            except tk.TclError:
                pass
            self._story_auto_job = None

    def _reset_story_display(self) -> None:
        self._cancel_story_timers()
        self._story_display_key = None
        self._story_reveal_chars = 0

    def _mark_current_story_read(self) -> None:
        store = getattr(self, "_playback_store", None)
        if store is not None and self._story_lines and not getattr(self, "_story_judging", False) and not getattr(self, "_story_choice_error", None):
            store.mark_read(self._current_story_line())

    def toggle_story_auto(self) -> str:
        self._story_auto = not self._story_auto
        if not self._story_auto and self._story_auto_job is not None:
            try:
                self._story_window.after_cancel(self._story_auto_job)
            except tk.TclError:
                pass
            self._story_auto_job = None
        self._render_story_window()
        return "break"

    def toggle_story_skip(self) -> str:
        enabling = not self._story_skip
        if enabling and self._story_lines and not (
            self._story_replay or self._playback_store.is_read(self._current_story_line())
        ):
            enabling = False
        self._story_skip = enabling
        self._reset_story_display()
        self._render_story_window()
        return "break"

    def open_story_log(self) -> str:
        session = self._narrative_session
        if session is None:
            return "break"
        window = tk.Toplevel(self._story_window or self.root)
        window.title("剧情历史")
        window.geometry("720x520")
        window.configure(background="#f6faf8")
        text = tk.Text(
            window, wrap="word", background="#f6faf8", foreground="#294f46",
            relief="flat", font=("Microsoft YaHei UI", 11), padx=22, pady=18,
        )
        scrollbar = ttk.Scrollbar(window, orient="vertical", command=text.yview)
        text.configure(yscrollcommand=scrollbar.set)
        text.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")
        for line in session.lines:
            text.insert("end", f"{line.speaker}\n{line.text}\n\n")
        text.configure(state="disabled")
        text.see("end")
        return "break"

    def _story_music_variant(self) -> str:
        session = self._narrative_session
        if session is None:
            return "daily"
        if session.event_id == CHAPTER_ONE_FINALE_ID:
            return "ending"
        if session.event_id in {"clarification"} or session.event_id.startswith("llm-repair-"):
            return "repair"
        if session.hidden_outcome == "bad" or session.add_flags:
            return "hesitant"
        return "daily"

    def _update_story_music(self) -> None:
        audio = getattr(self, "_story_audio", None)
        if audio is None:
            return
        audio.play(
            BGM_FILES[self._story_music_variant()], int(self._story_playback["bgm_volume"])
        )
        ambient = getattr(self, "_story_ambient_audio", None)
        if ambient is None or not self._story_lines:
            return
        scene = self._current_story_line().scene or ""
        kind = (
            "rain" if "rain" in scene else
            "station" if any(word in scene for word in ("station", "bus_stop")) else
            "cafe" if any(word in scene for word in ("cafe", "store", "bookstore", "laundromat")) else
            "street" if any(word in scene for word in ("street", "park", "riverside", "bridge", "rooftop", "crosswalk")) else
            ""
        )
        if kind:
            ambient.play(AMBIENT_FILES[kind], int(self._story_playback["ambient_volume"]))
        else:
            ambient.stop()

    def advance_story(self, _event: tk.Event | None = None) -> str:
        if getattr(self, "_story_opening_failed", False) and self._narrative_session is not None:
            self._story_opening_failed = False
            self._story_choice_error = None
            self._begin_story_opening(self._narrative_session, self._memory_narrative_context())
            self._render_story_window()
            return "break"
        if not self._story_text_complete() and not self._story_accepts_choice():
            self._story_reveal_chars = len(self._story_choice_error or self._current_story_line().text)
            if self._story_text_job is not None:
                try:
                    self._story_window.after_cancel(self._story_text_job)
                except tk.TclError:
                    pass
                self._story_text_job = None
            self._render_story_window()
            return "break"
        if (
            self._narrative_session is not None
            and self._narrative_session.completed
            and self._story_index + 1 >= len(self._story_lines)
        ):
            self._mark_current_story_read()
            self.close_story_window()
            return "break"
        if not self._story_lines or self._story_accepts_choice() or getattr(self, "_story_judging", False):
            return "break"
        if self._story_index + 1 < len(self._story_lines):
            self._mark_current_story_read()
            self._story_index += 1
            self._reset_story_display()
            self._update_story_music()
            self._render_story_window()
            return "break"
        if self._narrative_session is not None and self._narrative_session.completed:
            self._mark_current_story_read()
            self.close_story_window()
            return "break"
        self._mark_current_story_read()
        self._story_waiting_choice = True
        self._story_auto_job = None
        self._render_story_window()
        return "break"

    def _handle_story_click(self, event: tk.Event) -> str:
        for name, (left, top, right, bottom) in getattr(self, "_story_control_bounds", {}).items():
            if left <= event.x <= right and top <= event.y <= bottom:
                if name == "auto":
                    return self.toggle_story_auto()
                if name == "skip":
                    return self.toggle_story_skip()
                if name == "log":
                    return self.open_story_log()
                if name == "settings":
                    self.open_settings("playback")
                    return "break"
        if self._story_accepts_choice():
            bounds = getattr(self, "_story_custom_confirm_bounds", None)
            if bounds is not None:
                left, top, right, bottom = bounds
                if left <= event.x <= right and top <= event.y <= bottom:
                    return self.submit_custom_story_choice(event)
            for choice, (left, top, right, bottom) in self._story_choice_bounds.items():
                if left <= event.x <= right and top <= event.y <= bottom:
                    return self._begin_story_continuation(choice)
            return "break"
        return self.advance_story(event)

    def _story_accepts_choice(self) -> bool:
        return (
            self._story_waiting_choice
            and not self._story_judging
            and self._narrative_session is not None
            and not self._narrative_session.completed
        )

    def submit_custom_story_choice(self, _event: tk.Event | None = None) -> str:
        if not self._story_accepts_choice():
            return "break"
        text = self._story_custom_text.get().strip()
        if not text or len(text) > 300:
            self._story_choice_error = "请输入 1 至 300 个字符。"
            self._render_story_window()
            return "break"
        return self._begin_story_continuation(text)

    def _begin_story_continuation(self, text: str) -> str:
        session = self._narrative_session
        if session is None or not self._story_waiting_choice or self._story_judging:
            return "break"
        self._story_judging = True
        self._story_choice_error = None
        self._story_opening_failed = False
        self._render_story_window()
        memory_context = self._memory_narrative_context()
        token = self._story_generation_token

        def generate() -> None:
            try:
                updated, turn = self.gateway.continue_narrative_event(session, text, memory_context)
                result: object = (updated, turn.lines)
                error = None
            except (OSError, StateError) as caught:
                result = None
                error = caught
            self._story_generation_results.put((token, "continuation", result, error))

        threading.Thread(target=generate, name="story-continuation-generator", daemon=True).start()
        self._schedule_story_generation_poll()
        return "break"

    def _memory_narrative_context(self) -> str:
        return self.gateway.memory_context_snapshot()

    def _schedule_story_generation_poll(self) -> None:
        if self._story_generation_poll_job is None and not self._exiting:
            self._story_generation_poll_job = self.root.after(50, self._drain_story_generation_results)

    def _drain_story_generation_results(self) -> None:
        self._story_generation_poll_job = None
        handled = False
        while True:
            try:
                token, kind, result, error = self._story_generation_results.get_nowait()
            except Empty:
                break
            if token != self._story_generation_token:
                continue
            handled = True
            if kind == "opening":
                self._finish_story_opening(result, error)
            else:
                self._finish_story_continuation(result, error)
        if not handled and self._story_judging:
            self._schedule_story_generation_poll()

    def _finish_story_continuation(
        self,
        result: tuple[NarrativeEventSession, tuple[StoryLine, ...]] | None,
        error: Exception | None,
    ) -> None:
        if self._story_window is None or not self._story_window.winfo_exists():
            return
        self._story_judging = False
        if result is None:
            self._story_choice_error = _story_generation_error_text(error, "这一段暂时没有生成成功，请稍后再试。")
            if error is not None:
                self._action_text.set("剧情生成失败，详情已显示在剧情窗口。")
            self._render_story_window()
            return
        self._narrative_session, self._story_lines = result
        self._story_index = 0
        self._story_waiting_choice = False
        self._story_choice_error = None
        self._story_custom_text.set("")
        self._reset_story_display()
        self._update_story_music()
        self._render_story_window()

    def _begin_story_opening(
        self, session: NarrativeEventSession, memory_context: str
    ) -> None:
        self._story_judging = True
        token = self._story_generation_token

        def generate() -> None:
            try:
                updated, lines = self.gateway.start_narrative_event(session, memory_context)
                result: object = (updated, lines)
                error = None
            except (OSError, StateError) as caught:
                result = None
                error = caught
            self._story_generation_results.put((token, "opening", result, error))

        threading.Thread(target=generate, name="story-opening-generator", daemon=True).start()
        self._schedule_story_generation_poll()

    def _finish_story_opening(self, result: object, error: Exception | None) -> None:
        if self._story_window is None or not self._story_window.winfo_exists():
            return
        self._story_judging = False
        if result is None:
            self._story_choice_error = _story_generation_error_text(error, "开场暂时没有生成成功，点击画面重试。")
            self._story_opening_failed = True
            self._action_text.set("剧情开场生成失败，详情已显示在剧情窗口。")
            self._render_story_window()
            return
        session, lines = result
        self._narrative_session = session
        self._story_lines = lines
        self._story_index = 0
        self._story_choice_error = None
        self._story_opening_failed = False
        self._reset_story_display()
        self._update_story_music()
        self._render_story_window()

    def show_panel_page(self, page: str) -> None:
        story_selected = page == "story"
        (self._story_page if story_selected else self._imprint_page).tkraise()
        self._story_tab_button.configure(
            style="ViewTabSelected.TButton" if story_selected else "ViewTab.TButton"
        )
        self._imprint_tab_button.configure(
            style="ViewTab.TButton" if story_selected else "ViewTabSelected.TButton"
        )

    def _load_narrative_state(self) -> tuple[NarrativeProgress, NarrativeEventSession | None]:
        progress = self.gateway.narrative_store.load()
        session = self.gateway.narrative_session_store.load()
        self._sync_completed_story_session(session)
        if (
            session is not None
            and session.completed
            and session.event_id not in progress.completed_event_ids
            and not (session.event_id == CHAPTER_ONE_FINALE_ID and progress.finale_completed)
        ):
            self.gateway.continue_narrative_event(session, "恢复已完成的剧情进度")
            progress = self.gateway.narrative_store.load()
        if session is not None and session.completed and (
            session.event_id in progress.completed_event_ids
            or (session.event_id == CHAPTER_ONE_FINALE_ID and progress.finale_completed)
        ):
            session = None
        return progress, session

    def _sync_completed_story_session(self, saved: NarrativeEventSession | None) -> None:
        current = getattr(self, "_narrative_session", None)
        if (
            saved is None
            or not saved.completed
            or current is None
            or current.event_id != saved.event_id
            or getattr(self, "_story_window", None) is None
            or not self._story_window.winfo_exists()
        ):
            return
        changed = current != saved or self._story_waiting_choice or self._story_judging
        if not changed:
            return
        remaining_lines = saved.lines[len(current.lines):]
        self._narrative_session = saved
        if remaining_lines:
            self._story_lines = remaining_lines
            self._story_index = 0
        self._story_waiting_choice = False
        self._story_judging = False
        self._story_choice_error = None
        self._render_story_window()

    def _adopt_narrative_overview_state(
        self,
        progress: NarrativeProgress,
        session: NarrativeEventSession | None,
        event: StoryEventDefinition | None,
    ) -> None:
        """Refresh the management page without replacing a live story session."""
        self._narrative_progress = progress
        window = getattr(self, "_story_window", None)
        try:
            story_is_open = window is not None and window.winfo_exists()
        except tk.TclError:
            story_is_open = False
        if story_is_open:
            return
        self._narrative_session = session
        self._narrative_event = event

    def _refresh_completed_stories(self) -> None:
        frame = self._completed_story_frame
        for child in frame.winfo_children():
            child.destroy()
        try:
            archived = self.gateway.narrative_archive_store.load()
            progress = self.gateway.narrative_store.load()
        except (OSError, StateError) as error:
            ttk.Label(
                frame,
                text=f"已完成剧情读取失败：{error}",
                style="Caption.TLabel",
                wraplength=500,
            ).grid(row=0, column=0, columnspan=2, sticky="w")
            return
        sessions_by_id = {session.event_id: session for session in archived}
        event_ids = list(progress.completed_event_ids)
        if progress.finale_completed and CHAPTER_ONE_FINALE_ID not in event_ids:
            event_ids.append(CHAPTER_ONE_FINALE_ID)
        for session in archived:
            if session.event_id not in event_ids:
                event_ids.append(session.event_id)
        if not event_ids:
            ttk.Label(frame, text="暂无已完成剧情。", style="Caption.TLabel").grid(
                row=0, column=0, columnspan=2, sticky="w"
            )
            return
        for row, event_id in enumerate(reversed(event_ids)):
            session = sessions_by_id.get(event_id)
            event = narrative_event_definition(event_id)
            text = event.title
            if session is not None and session.event_summary:
                text = f"{text}\n{session.event_summary}"
            elif session is None:
                text = f"{text}\n旧版本完成的剧情没有回放归档，之后完成的剧情会保留。"
            ttk.Label(
                frame,
                text=text,
                style="Pending.TLabel",
                wraplength=390,
                justify="left",
            ).grid(row=row, column=EVENT_ENTRY_COLUMN, sticky="ew", pady=(0, 8))
            button = ttk.Button(
                frame,
                text="重温" if session is not None else "未归档",
                style="Secondary.TButton",
                command=lambda completed_event_id=event_id: self.open_completed_story(completed_event_id),
            )
            if session is None:
                button.state(("disabled",))
            button.grid(row=row, column=EVENT_BUTTON_COLUMN, sticky="ne", padx=(8, 0), pady=(0, 8))

    def open_story_window(self) -> None:
        if self._story_window is not None and self._story_window.winfo_exists():
            self._story_window.deiconify()
            self._story_window.lift()
            self._story_window.focus_force()
            return
        try:
            progress, saved_session = self._load_narrative_state()
        except (OSError, StateError) as error:
            self._action_text.set(f"剧情读取失败：{error}")
            return
        memory_context = self._memory_narrative_context()
        event_id = next_narrative_event_id(progress, saved_session, bool(memory_context))
        if event_id is None:
            self._action_text.set("第一章已经完成。")
            return
        session = (
            saved_session
            if saved_session is not None and not saved_session.completed and saved_session.event_id == event_id
            else NarrativeEventSession.start(event_id, target_nodes=16)
        )
        if session is not saved_session:
            session = self.gateway.narrative_session_store.save(session)
        event = narrative_event_definition(event_id)
        self._narrative_progress = progress
        needs_opening = not session.lines
        lines = session.lines[-7:] if session.lines else (
            StoryLine("流萤", "正在准备这一幕……", "neutral"),
        )
        self._open_story_window_with(event, session, lines, needs_opening, memory_context)

    def open_completed_story(self, event_id: str) -> None:
        if self._story_window is not None and self._story_window.winfo_exists():
            self._story_window.deiconify()
            self._story_window.lift()
            self._story_window.focus_force()
            return
        try:
            session = self.gateway.narrative_archive_store.get(event_id)
        except (OSError, StateError) as error:
            self._action_text.set(f"剧情归档读取失败：{error}")
            return
        if session is None:
            self._action_text.set("这段剧情暂时没有可重温的归档。")
            return
        self._open_story_window_with(
            narrative_event_definition(session.event_id),
            session,
            session.lines,
            False,
            "",
            replay=True,
        )

    def _open_story_window_with(
        self,
        event: StoryEventDefinition,
        session: NarrativeEventSession,
        lines: tuple[StoryLine, ...],
        needs_opening: bool,
        memory_context: str,
        replay: bool = False,
    ) -> None:
        self._narrative_session = session
        self._narrative_event = event
        self._story_lines = lines
        self._story_index = 0
        self._story_waiting_choice = False
        self._story_judging = needs_opening
        self._story_choice_error = None
        self._story_replay = replay
        self._story_auto = False
        self._story_skip = False
        self._reset_story_display()
        self._story_custom_text.set("")
        self._story_generation_token = getattr(self, "_story_generation_token", 0) + 1
        self.root.withdraw()
        if self._title_window is not None:
            self._title_window.withdraw()
        window = tk.Toplevel(self.root)
        self._story_window = window
        window.title(f"同行印记 · {event.title}")
        window.minsize(800, 500)
        width, height = STORY_WINDOW_SIZE
        x = max(0, (window.winfo_screenwidth() - width) // 2)
        y = max(0, (window.winfo_screenheight() - height) // 2)
        window.geometry(f"{width}x{height}+{x}+{y}")
        window.protocol("WM_DELETE_WINDOW", self.close_story_window)
        try:
            window.iconbitmap(default=str(WINDOW_ICON_PATH))
        except (OSError, tk.TclError):
            pass

        canvas = tk.Canvas(window, borderwidth=0, highlightthickness=0)
        canvas.pack(fill="both", expand=True)
        self._story_canvas = canvas
        self._story_custom_entry = tk.Entry(
            window,
            textvariable=self._story_custom_text,
            background="#15211f",
            foreground="#f8f5ee",
            insertbackground="#f8f5ee",
            relief="flat",
            font=("Microsoft YaHei UI", 11),
        )
        self._story_custom_entry.bind("<Return>", self.submit_custom_story_choice)
        window.bind("<Configure>", self._schedule_story_render)
        window.bind("<space>", self.advance_story)
        window.bind("<Return>", self.advance_story)
        window.bind("a", lambda _event: self.toggle_story_auto())
        window.bind("s", lambda _event: self.toggle_story_skip())
        window.bind("l", lambda _event: self.open_story_log())
        canvas.bind("<Button-1>", self._handle_story_click)
        window.update_idletasks()
        self._update_story_music()
        self._render_story_window()
        if needs_opening:
            self._begin_story_opening(session, memory_context)

    def _schedule_story_render(self, event: tk.Event) -> None:
        if event.widget is not self._story_window or self._story_window is None:
            return
        if self._story_resize_job is not None:
            self._story_window.after_cancel(self._story_resize_job)
        self._story_resize_job = self._story_window.after(70, self._render_story_window)

    def _render_story_window(self) -> None:
        from PIL import Image, ImageColor, ImageDraw, ImageFilter, ImageTk

        window = self._story_window
        canvas = self._story_canvas
        if window is None or canvas is None or not window.winfo_exists():
            return
        self._story_resize_job = None
        self._story_control_bounds = {}
        width = max(800, canvas.winfo_width())
        height = max(500, canvas.winfo_height())
        try:
            chapter_id = self._narrative_session.chapter_id if self._narrative_session is not None else ""
            chapter_cg = next((item for item in self.gateway.visual_library.chapter_cgs() if item["chapter_id"] == chapter_id), None)
            pending_cg = self.gateway.visual_library.pending_chapter_job()
            finale_screen = (
                self._narrative_session is not None
                and self._narrative_session.event_id == CHAPTER_ONE_FINALE_ID
                and self._narrative_session.completed
            )
            if finale_screen and (chapter_cg is not None or pending_cg is not None):
                source = Image.open(chapter_cg["path"]).convert("RGB") if chapter_cg is not None else _cached_story_stage(default_scene_id(), default_sprite_id(), width, height).convert("RGB").filter(ImageFilter.GaussianBlur(5))
                scale = max(width / source.width, height / source.height)
                source = source.resize((round(source.width * scale), round(source.height * scale)), Image.Resampling.LANCZOS)
                source = source.crop(((source.width - width) // 2, (source.height - height) // 2, (source.width - width) // 2 + width, (source.height - height) // 2 + height)).convert("RGBA")
                overlay = Image.new("RGBA", source.size, (235, 249, 244, 92 if chapter_cg is not None else 150))
                source.alpha_composite(overlay)
                self._story_photo = ImageTk.PhotoImage(source.convert("RGB"))
                canvas.delete("all")
                canvas.create_image(0, 0, anchor="nw", image=self._story_photo)
                title = "章节专属 CG" if chapter_cg is not None else "正在绘制我们的回忆"
                user_title = preferred_user_title(self._memory_narrative_context())
                subtitle = "点击画面返回开始界面" if chapter_cg is not None else f"专属 CG 生成中，请「{user_title}」耐心等待"
                canvas.create_text(58, height // 2 - 28, anchor="w", text=title, fill="#214f43", font=("Microsoft YaHei UI", 28, "bold"))
                canvas.create_text(60, height // 2 + 24, anchor="w", text=subtitle, fill="#416b60", font=("Microsoft YaHei UI", 12))
                self._story_choice_bounds = {}
                self._story_custom_confirm_bounds = None
                return
            line = self._current_story_line()
            full_text = (
                "流萤正在回应你……"
                if self._story_judging
                else self._story_choice_error or line.text
            )
            displayed_text = self._prepare_story_text(full_text)
            cinematic = (
                is_cinematic_line(line)
                and not self._story_judging
                and not self._story_choice_error
                and not self._story_accepts_choice()
            )
            visual = _cached_story_stage(
                line.scene or default_scene_id(),
                line.sprite or default_sprite_id(),
                width,
                height,
            ).convert("RGBA")
            theme = relationship_theme(STAGES[0])
            dialogue_height = story_dialogue_height(displayed_text, width)
            if not cinematic:
                tint = ImageColor.getrgb("#15211f")
                band = Image.new("RGBA", (width, dialogue_height), (*tint, 218))
                visual.alpha_composite(band, (0, height - dialogue_height))
                accent = Image.new("RGBA", (width, 3), (*ImageColor.getrgb(theme.primary), 255))
                visual.alpha_composite(accent, (0, height - dialogue_height))
            self._story_choice_bounds = {}
            self._story_custom_confirm_bounds = None
            choice_layout: list[tuple[str, str, tuple[int, int, int, int]]] = []
            custom_bounds: tuple[int, int, int, int] | None = None
            if self._story_accepts_choice():
                choices = (
                    self._narrative_session.choices
                    if self._narrative_session is not None and self._narrative_session.choices
                    else () if self._narrative_session is not None and self._narrative_session.director_mode
                    else STORY_DEFAULT_CHOICES
                )
                choice_width = min(620, width - 120)
                left = (width - choice_width) // 2
                row_height, gap = 52, 10
                total_height = len(choices) * (row_height + gap) + 62
                top = max(76, (height - dialogue_height - total_height) // 2)
                choice_layout = [
                    (
                        text,
                        text,
                        (left, top + index * (row_height + gap), left + choice_width,
                         top + index * (row_height + gap) + row_height),
                    )
                    for index, text in enumerate(choices)
                ]
                custom_top = top + len(choices) * (row_height + gap)
                custom_bounds = (left, custom_top, left + choice_width, custom_top + 58)
                overlay = Image.new("RGBA", visual.size, (0, 0, 0, 0))
                draw = ImageDraw.Draw(overlay)
                outline = (*ImageColor.getrgb(theme.primary), 255)
                for choice, _text, bounds in choice_layout:
                    draw.rounded_rectangle(bounds, radius=6, fill=(16, 29, 27, 198), outline=outline, width=2)
                    self._story_choice_bounds[choice] = bounds
                draw.rounded_rectangle(custom_bounds, radius=6, fill=(16, 29, 27, 198), outline=outline, width=2)
                draw.line(
                    (custom_bounds[2] - 86, custom_bounds[1] + 12, custom_bounds[2] - 86, custom_bounds[3] - 12),
                    fill=outline,
                    width=1,
                )
                self._story_custom_confirm_bounds = (
                    custom_bounds[2] - 86,
                    custom_bounds[1],
                    custom_bounds[2],
                    custom_bounds[3],
                )
                visual.alpha_composite(overlay)
            self._story_photo = ImageTk.PhotoImage(visual.convert("RGB"))
        except (OSError, KeyError, ValueError, json.JSONDecodeError) as error:
            self._action_text.set(f"剧情资源读取失败：{error}")
            self.close_story_window()
            return

        canvas.delete("all")
        canvas.create_image(0, 0, anchor="nw", image=self._story_photo)
        dialogue_top = height - dialogue_height
        if cinematic:
            canvas.create_text(
                width // 2 + 2, height - 69 + 2, text=displayed_text, width=width - 180,
                fill="#172522", font=("Microsoft YaHei UI", 15), justify="center",
            )
            canvas.create_text(
                width // 2, height - 69, text=displayed_text, width=width - 180,
                fill="#fffdf7", font=("Microsoft YaHei UI", 15), justify="center",
            )
        else:
            canvas.create_text(
                56, dialogue_top + 28, anchor="w", text="流萤" if self._story_judging else line.speaker,
                fill=theme.primary, font=("Microsoft YaHei UI", 11, "bold"),
            )
            canvas.create_text(
                56, dialogue_top + 58, anchor="nw", text=displayed_text,
                width=width - 112, fill="#f8f5ee", font=("Microsoft YaHei UI", 14),
            )
        if self._story_accepts_choice():
            for _tag, text, bounds in choice_layout:
                left, top, right, bottom = bounds
                canvas.create_text(
                    width // 2, (top + bottom) // 2, text=text, fill="#fffaf1",
                    font=("Microsoft YaHei UI", 12, "bold"),
                )
            assert custom_bounds is not None
            left, top, right, bottom = custom_bounds
            canvas.create_window(
                left + 18, (top + bottom) // 2, anchor="w",
                window=self._story_custom_entry, width=max(180, right - left - 126), height=32,
            )
            canvas.create_text(
                right - 43, (top + bottom) // 2, text="确认", fill="#fffaf1",
                font=("Microsoft YaHei UI", 12, "bold"),
            )
        else:
            canvas.create_text(
                width - 48, height - 24, anchor="e",
                text="点击画面结束本幕" if self._narrative_session is not None and self._narrative_session.completed else "点击画面继续",
                fill="#b9ccc4", font=("Microsoft YaHei UI", 9),
            )
        controls = (
            ("auto", "AUTO", self._story_auto),
            ("skip", "SKIP", self._story_skip),
            ("log", "LOG", False),
            ("settings", "设置", False),
        )
        self._story_control_bounds = {}
        control_width, gap, top = 64, 7, 15
        left = width - 18 - len(controls) * control_width - (len(controls) - 1) * gap
        for index, (name, label, active) in enumerate(controls):
            x1 = left + index * (control_width + gap)
            bounds = (x1, top, x1 + control_width, top + 28)
            self._story_control_bounds[name] = bounds
            canvas.create_rectangle(
                *bounds,
                fill="#2f8e7d" if active else "#172a28",
                outline="#7bcbb8" if active else "#6f8b84",
            )
            canvas.create_text(
                x1 + control_width // 2, top + 14, text=label,
                fill="#ffffff" if active else "#d3e2dd", font=("Microsoft YaHei UI", 8, "bold"),
            )

    def close_story_window(self) -> None:
        window = self._story_window
        if window is None:
            return
        self._cancel_story_timers()
        audio = getattr(self, "_story_audio", None)
        if audio is not None:
            audio.stop()
        ambient = getattr(self, "_story_ambient_audio", None)
        if ambient is not None:
            ambient.stop()
        if self._story_resize_job is not None:
            try:
                window.after_cancel(self._story_resize_job)
            except tk.TclError:
                pass
            self._story_resize_job = None
        self._story_window = None
        self._story_canvas = None
        self._story_control_bounds = {}
        self._story_generation_token = getattr(self, "_story_generation_token", 0) + 1
        self._story_judging = False
        if getattr(self, "_story_generation_poll_job", None) is not None:
            try:
                window.after_cancel(self._story_generation_poll_job)
            except tk.TclError:
                pass
            self._story_generation_poll_job = None
        window.destroy()
        if not self._exiting:
            self.show()

    def _start_tray(self) -> None:
        if getattr(self, "_tray", None) is not None:
            return
        try:
            self._tray = TrayController(
                self._tray_actions.put, self.show, self.exit, getattr(self, "_active_stage", None) or STAGES[0]
            )
            self._tray.start()
        except (ImportError, OSError, RuntimeError, NotImplementedError) as error:
            self._tray = None
            self._action_text.set(f"系统托盘暂不可用：{error}")

    def _drain_tray_actions(self) -> None:
        self._tray_poll_job = None
        while True:
            try:
                callback = self._tray_actions.get_nowait()
            except Empty:
                break
            callback()
            if self._exiting:
                return
        self._tray_poll_job = self.root.after(TRAY_POLL_INTERVAL_MS, self._drain_tray_actions)

    def refresh(self) -> None:
        self._poll_job = None
        try:
            state = self.store.load()
        except (OSError, StateError) as error:
            self._apply_stage_theme(STAGES[0])
            self._pending_kind_text.set("状态异常")
            self._pending_text.set("暂时无法读取待确认的重要回忆。")
            self._confirm_button.state(("disabled",))
            self._dismiss_button.state(("disabled",))
            self._action_text.set(f"状态读取失败：{error}")
        else:
            self._apply_stage_theme(state.stage)
            try:
                progress, session = self._load_narrative_state()
                event_id = next_narrative_event_id(
                    progress, session, bool(self._memory_narrative_context())
                )
            except (OSError, StateError) as error:
                self._narrative_progress = None
                self._narrative_session = None
                self._narrative_event = None
                self._story_title_text.set(CHAPTERS[0].title)
                self._story_status_text.set("第一章进度暂时无法读取。")
                self._story_description_text.set(CHAPTERS[0].focus)
                self._open_story_button.state(("disabled",))
                self._action_text.set(f"剧情读取失败：{error}")
            else:
                event = narrative_event_definition(event_id) if event_id is not None else None
                self._adopt_narrative_overview_state(progress, session, event)
                if event_id is None:
                    self._story_title_text.set(CHAPTERS[0].finale_title)
                    self._story_status_text.set("第一章已经完成。")
                    self._story_description_text.set("你们已经愿意继续认识彼此，但关系仍停留在克制的初识阶段。")
                    self._open_story_button.configure(text="第一章已完成")
                    self._open_story_button.state(("disabled",))
                else:
                    assert event is not None
                    self._story_title_text.set(event.title)
                    self._story_description_text.set(event.purpose)
                    if session is not None and not session.completed and session.event_id == event_id:
                        self._story_status_text.set(
                            f"已完成 {session.current_node} 次互动，可以继续这一幕。"
                        )
                        self._open_story_button.configure(text="继续这一幕")
                    else:
                        self._story_status_text.set("第一章的下一段专属剧情已准备好。")
                        self._open_story_button.configure(text="进入这一幕")
                    self._open_story_button.state(("!disabled",))
            self._refresh_completed_stories()
            pending = state.pending_proposal
            if pending is None:
                self._pending_kind_text.set("等待对话")
                self._pending_text.set("暂无待确认的重要回忆。")
                self._confirm_button.state(("disabled",))
                self._dismiss_button.state(("disabled",))
            else:
                self._pending_kind_text.set(PENDING_KIND_LABELS[pending.kind])
                self._pending_text.set(pending.summary)
                self._confirm_button.state(("!disabled",))
                self._dismiss_button.state(("!disabled",))
        self._gateway_text.set(gateway_diagnostic(self.gateway))
        if (
            self._story_window is not None
            and self._narrative_session is not None
            and self._narrative_session.event_id == CHAPTER_ONE_FINALE_ID
            and self._narrative_session.completed
        ):
            self._render_story_window()
        if not self._exiting:
            self._poll_job = self.root.after(POLL_INTERVAL_MS, self.refresh)

    def _apply_stage_theme(self, stage: str) -> None:
        stage = stage if stage in RELATIONSHIP_THEMES else STAGES[0]
        if stage != self._active_stage:
            fixed_theme = relationship_theme(STAGES[0])
            configure_style(self.root, fixed_theme, self._style)
            self._canvas.configure(background=fixed_theme.surface)
            self._stage_text.set(f"关系阶段：{relationship_theme(stage).label} · 确认值得留下的共同片段")
            self._active_stage = stage
            if getattr(self, "_story_window", None) is not None:
                self._render_story_window()
        if self._icon_stage == STAGES[0]:
            return
        try:
            if self._tray is not None:
                self._tray.set_stage(STAGES[0])
        except (ImportError, OSError, RuntimeError, tk.TclError) as error:
            self._action_text.set(f"阶段图标更新失败：{error}")
        else:
            self._icon_stage = STAGES[0]

    def confirm(self) -> None:
        result = confirm_memory(self.store)
        if result.ok:
            self.gateway.clear_resolved_pending_proposal_diagnostic()
        self._show_action(result)

    def dismiss(self) -> None:
        result = dismiss_memory(self.store)
        if result.ok:
            self.gateway.clear_resolved_pending_proposal_diagnostic()
        self._show_action(result)

    def record(self, kind: str) -> None:
        value = self._gift_text if kind == "gift" else self._anniversary_text
        result = record_explicit_event(self.store, kind, value.get())
        if result.ok:
            value.set("")
        self._show_action(result)

    def _show_action(self, result: PanelAction) -> None:
        self._action_text.set(result.message)
        if self._poll_job is not None:
            self.root.after_cancel(self._poll_job)
            self._poll_job = None
        self.refresh()

    def hide(self) -> None:
        if self._tray is None:
            self._start_tray()
        if self._tray is None:
            self._action_text.set("系统托盘暂不可用，已最小化到任务栏。")
            target = getattr(self, "_title_window", None) or self.root
            target.iconify()
            return
        self.root.withdraw()
        title_window = getattr(self, "_title_window", None)
        if title_window is not None:
            title_window.withdraw()

    def show(self) -> None:
        story_window = getattr(self, "_story_window", None)
        if story_window is not None and story_window.winfo_exists():
            story_window.deiconify()
            story_window.lift()
            story_window.focus_force()
            return
        title_window = getattr(self, "_title_window", None)
        if title_window is not None:
            self.root.withdraw()
        target = title_window or self.root
        target.deiconify()
        target.lift()
        target.focus_force()

    def request_show(self) -> None:
        self._tray_actions.put(self.show)

    def exit(self) -> None:
        if self._exiting:
            return
        self._exiting = True
        if self._poll_job is not None:
            self.root.after_cancel(self._poll_job)
            self._poll_job = None
        if self._tray_poll_job is not None:
            self.root.after_cancel(self._tray_poll_job)
            self._tray_poll_job = None
        if self._tray is not None:
            self._tray.stop()
        story_window = getattr(self, "_story_window", None)
        if story_window is not None:
            story_window.destroy()
            self._story_window = None
        if getattr(self, "_title_window", None) is not None:
            self._title_window.destroy()
            self._title_window = None
        self.gateway.shutdown()
        self.root.destroy()


def run_panel(gateway: RelationshipGatewayServer) -> None:
    """Run the native Sidecar panel until the user explicitly exits it."""
    root = tk.Tk()
    panel = RelationshipPanel(root, gateway)
    gateway.set_panel_show_callback(panel.request_show)
    try:
        root.mainloop()
    finally:
        gateway.set_panel_show_callback(None)
