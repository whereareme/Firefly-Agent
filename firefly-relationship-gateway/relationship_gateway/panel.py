"""Native confirmation panel for the local relationship Sidecar."""

from __future__ import annotations

import tkinter as tk
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from queue import Empty, SimpleQueue
from tkinter import ttk
from typing import Callable

from .gateway import RelationshipGatewayServer
from .state import STAGES, StateError, StateStore


POLL_INTERVAL_MS = 1_000
TRAY_POLL_INTERVAL_MS = 100
PANEL_COLUMN_COUNT = 2
EVENT_ENTRY_COLUMN = 0
EVENT_BUTTON_COLUMN = 1
PENDING_KIND_LABELS = {"memory": "重要回忆", "gift": "礼物", "anniversary": "纪念日"}
ASSET_PATH = Path(__file__).with_name("assets") / "companion-imprint.png"
WINDOW_ICON_PATH = ASSET_PATH.with_suffix(".ico")


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

        self._style = configure_style(root)
        root.title("同行印记")
        root.geometry("520x520")
        root.minsize(480, 430)
        root.resizable(True, True)
        root.protocol("WM_DELETE_WINDOW", self.hide)
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

        content = ttk.Frame(canvas, padding=(36, 28, 36, 26), style="Surface.TFrame")
        content_window = canvas.create_window((0, 0), window=content, anchor="nw")
        content.bind("<Configure>", lambda _event: canvas.configure(scrollregion=canvas.bbox("all")))
        canvas.bind("<Configure>", lambda event: canvas.itemconfigure(content_window, width=event.width))
        canvas.bind_all("<MouseWheel>", lambda event: canvas.yview_scroll(int(-event.delta / 120), "units"))
        content.columnconfigure(EVENT_ENTRY_COLUMN, weight=1)
        content.columnconfigure(EVENT_BUTTON_COLUMN, weight=0)

        ttk.Label(content, text="同行印记", style="Title.TLabel").grid(row=0, column=0, sticky="w")
        ttk.Label(content, textvariable=self._stage_text, style="Caption.TLabel").grid(row=1, column=0, sticky="w", pady=(3, 0))
        ttk.Button(content, text="最小化到托盘", style="Secondary.TButton", command=self.hide).grid(row=0, column=1, rowspan=2, sticky="e")

        ttk.Separator(content).grid(row=2, column=0, columnspan=2, sticky="ew", pady=(24, 22))
        ttk.Label(content, text="待确认的重要回忆", style="Section.TLabel").grid(row=3, column=0, columnspan=2, sticky="w")
        ttk.Label(content, textvariable=self._pending_kind_text, style="Kind.TLabel").grid(row=4, column=0, sticky="w", pady=(12, 8))
        self._pending_label = ttk.Label(content, textvariable=self._pending_text, style="Pending.TLabel", wraplength=430, justify="left")
        self._pending_label.grid(row=5, column=0, columnspan=2, sticky="ew")
        ttk.Label(content, text="来自日常对话，确认后才会保存", style="Caption.TLabel").grid(row=6, column=0, columnspan=2, sticky="w", pady=(8, 12))
        memory_actions = ttk.Frame(content, style="Surface.TFrame")
        memory_actions.grid(row=7, column=0, columnspan=2, sticky="w")
        self._confirm_button = ttk.Button(memory_actions, text="记下", command=self.confirm)
        self._confirm_button.grid(row=0, column=0, padx=(0, 8))
        self._dismiss_button = ttk.Button(memory_actions, text="暂不", style="Secondary.TButton", command=self.dismiss)
        self._dismiss_button.grid(row=0, column=1)

        ttk.Separator(content).grid(row=8, column=0, columnspan=2, sticky="ew", pady=(24, 18))
        ttk.Label(content, text="手动补记", style="Section.TLabel").grid(row=9, column=0, columnspan=2, sticky="w")
        ttk.Label(content, text="仅在日常对话没有识别时使用", style="Caption.TLabel").grid(row=10, column=0, columnspan=2, sticky="w", pady=(3, 10))
        self._add_event_input(content, 11, "礼物", self._gift_text, lambda: self.record("gift"))
        self._add_event_input(content, 13, "纪念日", self._anniversary_text, lambda: self.record("anniversary"))

        ttk.Separator(content).grid(row=15, column=0, columnspan=2, sticky="ew", pady=(18, 12))
        ttk.Label(content, textvariable=self._gateway_text, style="Status.TLabel", wraplength=440).grid(row=16, column=0, columnspan=2, sticky="w")
        ttk.Label(content, textvariable=self._action_text, style="Action.TLabel", wraplength=440).grid(row=17, column=0, columnspan=2, sticky="w", pady=(5, 0))

        self.refresh()
        self._start_tray()
        self._tray_poll_job = self.root.after(TRAY_POLL_INTERVAL_MS, self._drain_tray_actions)
        if self._tray is not None:
            self.root.withdraw()

    def _add_event_input(self, parent: ttk.Frame, row: int, label: str, value: tk.StringVar, command: object) -> None:
        ttk.Label(parent, text=label, style="Caption.TLabel").grid(row=row, column=0, columnspan=2, sticky="w")
        ttk.Entry(parent, textvariable=value).grid(row=row + 1, column=EVENT_ENTRY_COLUMN, sticky="ew", pady=(4, 8))
        ttk.Button(parent, text=f"记录{label}", style="Secondary.TButton", command=command).grid(row=row + 1, column=EVENT_BUTTON_COLUMN, sticky="e", padx=(8, 0), pady=(4, 8))

    def _start_tray(self) -> None:
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
        if not self._exiting:
            self._poll_job = self.root.after(POLL_INTERVAL_MS, self.refresh)

    def _apply_stage_theme(self, stage: str) -> None:
        stage = stage if stage in RELATIONSHIP_THEMES else STAGES[0]
        if stage != self._active_stage:
            theme = relationship_theme(stage)
            configure_style(self.root, theme, self._style)
            self._canvas.configure(background=theme.surface)
            self._stage_text.set(f"关系阶段：{theme.label} · 确认值得留下的共同片段")
            self._active_stage = stage
        if stage == self._icon_stage:
            return
        try:
            if self._tray is not None:
                self._tray.set_stage(stage)
        except (ImportError, OSError, RuntimeError, tk.TclError) as error:
            self._action_text.set(f"阶段图标更新失败：{error}")
        else:
            self._icon_stage = stage

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
            self._action_text.set("系统托盘不可用，窗口将保持打开。")
            return
        self.root.withdraw()

    def show(self) -> None:
        self.root.deiconify()
        self.root.lift()
        self.root.focus_force()

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
        self.gateway.shutdown()
        self.root.destroy()


def run_panel(gateway: RelationshipGatewayServer) -> None:
    """Run the native Sidecar panel until the user explicitly exits it."""
    root = tk.Tk()
    RelationshipPanel(root, gateway)
    root.mainloop()
