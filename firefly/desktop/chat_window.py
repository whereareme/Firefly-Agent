"""Chat window for Firefly desktop."""

from __future__ import annotations

import html
import re
import tempfile
import threading
from pathlib import Path
from typing import Any

from PySide6.QtCore import QPoint, QSize, Qt, QThread, QTimer, QUrl, Signal, Slot
from PySide6.QtGui import QCloseEvent, QDesktopServices, QDragEnterEvent, QDropEvent, QIcon, QKeyEvent, QMouseEvent, QPixmap
from PySide6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QMenu,
    QMessageBox,
    QInputDialog,
    QPushButton,
    QScrollArea,
    QSizeGrip,
    QSizePolicy,
    QSplitter,
    QStackedWidget,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from firefly.desktop.chat_rendering import ChatBubble, format_chat_text, normalize_chat_text, render_chat_html
from firefly.desktop.styles import chat_style_for_mode, chat_viewport_style_for_mode, resolved_theme_mode
from firefly.desktop.settings_panel import SettingsPanelMixin
from firefly.desktop.upload_widgets import upload_preview_widget
from firefly.desktop.workers import ChatWorker, live2d_mood_for_reply
from firefly.desktop_awareness import FIREFLY_WINDOW_TITLE_PARTS, capture_desktop_snapshot, snapshot_prompt
from firefly.runtime import FireflyRuntime
from firefly.session_storage import load_desktop_conversations, save_desktop_conversations
from firefly.workspace import load_config, save_config

UI_ASSET_ROOT = Path(__file__).resolve().parents[1] / "assets" / "ui"
IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp"}
IMAGE_PATH_RE = re.compile(
    r"(?i)([A-Za-z]:[\\/][^\s`'\"<>|，。！？；：、]+?\.(?:png|jpe?g|gif|webp|bmp)|"
    r"(?:\.{1,2}[\\/])?[^\s`'\"<>|，。！？；：、]+[\\/][^\s`'\"<>|，。！？；：、]+?\.(?:png|jpe?g|gif|webp|bmp))"
)
PERMISSION_MODES = {"default", "plan", "full_auto"}


def chat_bubble_max_width(window_width: int) -> int:
    return max(360, int(window_width * 0.65))


def remove_temporary_context_snapshot(path: str | Path | None) -> None:
    if not path:
        return
    candidate = Path(path)
    try:
        if candidate.name.startswith("chat_context_") and candidate.parent.resolve() == Path(tempfile.gettempdir()).resolve():
            candidate.unlink(missing_ok=True)
    except OSError:
        pass


def local_permission_mode_command(text: str) -> str | None:
    command = " ".join(text.strip().split()).lower()
    for prefix in ("/permissions ", "permissions "):
        if command.startswith(prefix):
            command = command.removeprefix(prefix).strip()
    if command.startswith("set "):
        command = command.removeprefix("set ").strip()
    return command if command in PERMISSION_MODES else None


def reply_image_paths(text: str, cwd: Path) -> list[Path]:
    paths: list[Path] = []
    seen: set[Path] = set()
    for match in IMAGE_PATH_RE.finditer(text):
        raw = match.group(1).strip("`'\"<>[]()")
        path = Path(raw).expanduser()
        if not path.is_absolute():
            path = cwd / path
        try:
            path = path.resolve(strict=True)
        except (OSError, RuntimeError):
            continue
        if path.suffix.lower() not in IMAGE_EXTENSIONS or not path.is_file() or path in seen:
            continue
        paths.append(path)
        seen.add(path)
    return paths


def strip_generated_image_notice(text: str) -> str:
    lines: list[str] = []
    skip_next_image_name = False
    removed_notice = False
    for line in text.splitlines():
        has_save_word = any(word in line for word in ("保存", "生成", "写入", "输出"))
        if skip_next_image_name and re.search(r"(?i)^\s*[\w .()（）-]+?\.(?:png|jpe?g|gif|webp|bmp)\b", line):
            skip_next_image_name = False
            removed_notice = True
            continue
        skip_next_image_name = False
        if IMAGE_PATH_RE.search(line) and has_save_word:
            removed_notice = True
            continue
        if "generated_images" in line and has_save_word:
            skip_next_image_name = line.rstrip().endswith(("/", "\\"))
            removed_notice = True
            continue
        lines.append(line)
    cleaned = normalize_chat_text("\n".join(lines))
    return cleaned if cleaned or removed_notice else normalize_chat_text(text)


def conversation_title(text: object, fallback: str = "对话", limit: int = 32) -> str:
    lines = format_chat_text(str(text or "")).splitlines()
    title = lines[0].strip() if lines else ""
    return (title or fallback)[:limit]


def local_file_paths_from_mime_data(source) -> list[str]:
    files: list[str] = []
    if source.hasUrls():
        files.extend(url.toLocalFile() for url in source.urls() if url.isLocalFile())
    elif source.hasText():
        for line in source.text().splitlines():
            value = line.strip().strip('"')
            url = QUrl(value)
            if url.isLocalFile():
                files.append(url.toLocalFile())
                continue
            try:
                if Path(value).expanduser().is_file():
                    files.append(value)
            except OSError:
                pass
    return files


class WindowChrome(QWidget):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._press_global: QPoint | None = None
        self._window_pos: QPoint | None = None
        self.setFixedHeight(46)
        self.setCursor(Qt.OpenHandCursor)

    def mousePressEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.LeftButton:
            self._press_global = event.globalPosition().toPoint()
            self._window_pos = self.window().pos()
            self.setCursor(Qt.ClosedHandCursor)
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event: QMouseEvent) -> None:
        if self._press_global is not None and self._window_pos is not None and event.buttons() & Qt.LeftButton:
            delta = event.globalPosition().toPoint() - self._press_global
            if delta.manhattanLength() > 3 and not self.window().isMaximized():
                self.window().move(self._window_pos + delta)
                event.accept()
                return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:
        self._press_global = None
        self._window_pos = None
        self.setCursor(Qt.OpenHandCursor)
        super().mouseReleaseEvent(event)

    def mouseDoubleClickEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.LeftButton:
            window = self.window()
            window.showNormal() if window.isMaximized() else window.showMaximized()
            event.accept()
            return
        super().mouseDoubleClickEvent(event)


class ChatInput(QTextEdit):
    send_requested = Signal()
    files_pasted = Signal(object)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setAcceptDrops(True)

    def keyPressEvent(self, event: QKeyEvent) -> None:
        if event.key() in {Qt.Key_Return, Qt.Key_Enter} and not event.modifiers() & Qt.ShiftModifier:
            self.send_requested.emit()
            event.accept()
            return
        super().keyPressEvent(event)

    def insertFromMimeData(self, source) -> None:
        files = local_file_paths_from_mime_data(source)
        if files:
            self.files_pasted.emit(files)
            return
        super().insertFromMimeData(source)

    def dragEnterEvent(self, event: QDragEnterEvent) -> None:
        if local_file_paths_from_mime_data(event.mimeData()):
            event.acceptProposedAction()
            return
        super().dragEnterEvent(event)

    def dragMoveEvent(self, event: QDragEnterEvent) -> None:
        if local_file_paths_from_mime_data(event.mimeData()):
            event.acceptProposedAction()
            return
        super().dragMoveEvent(event)

    def dropEvent(self, event: QDropEvent) -> None:
        files = local_file_paths_from_mime_data(event.mimeData())
        if files:
            self.files_pasted.emit(files)
            event.acceptProposedAction()
            return
        super().dropEvent(event)


class ChatWindow(SettingsPanelMixin, QMainWindow):
    approval_requested = Signal(object)

    def __init__(self, runtime: FireflyRuntime, workspace: Path, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.runtime = runtime
        self.workspace = workspace
        self.config = load_config(workspace)
        self.history: list[dict[str, str]] = []
        self.messages: list[dict[str, str]] = []
        self.thread: QThread | None = None
        self.worker: ChatWorker | None = None
        self.active_threads: dict[int, QThread] = {}
        self.active_workers: dict[int, ChatWorker] = {}
        self.worker_conversations: dict[int, tuple[int, dict[str, Any]]] = {}
        self._mood_sender: Any = None
        self._approval_surface: QWidget | None = None
        self._context_snapshotter: Any = None
        self.pending_uploads: list[Path] = []
        self._status_token = 0
        self.nav_collapsed = False
        self.nav_expanded_width = 260
        self.resize_grip: QSizeGrip | None = None
        self.window_state_button: QPushButton | None = None
        self.conversations, self.current_conversation_index = load_desktop_conversations(workspace)

        self.setWindowTitle("Firefly Agent")
        self.setWindowFlags(self.windowFlags() | Qt.FramelessWindowHint)
        self.setMinimumSize(860, 560)
        self.resize(1080, 720)
        self.apply_theme()
        self.apply_runtime_config()
        self.setCentralWidget(self.build_ui())
        self.approval_requested.connect(self.handle_approval_request, Qt.QueuedConnection)
        self.load_conversation(self.current_conversation_index)

    def apply_theme(self) -> None:
        self.setProperty("darkTheme", resolved_theme_mode(self.config.get("theme_mode")) == "dark")
        self.setStyleSheet(chat_style_for_mode(self.config.get("theme_mode")))
        if hasattr(self, "chat_scroll"):
            self.chat_scroll.viewport().setStyleSheet(chat_viewport_style_for_mode(self.config.get("theme_mode")))
        if hasattr(self, "chat_messages_widget"):
            for bubble in self.chat_messages_widget.findChildren(ChatBubble):
                bubble.update()

    def set_live2d_mood_sender(self, sender) -> None:
        self._mood_sender = sender

    def set_approval_surface(self, surface: QWidget) -> None:
        self._approval_surface = surface

    def set_context_snapshotter(self, snapshotter) -> None:
        self._context_snapshotter = snapshotter

    def set_mood(self, mood: str) -> None:
        if self._mood_sender is not None:
            try:
                self._mood_sender(mood)
            except RuntimeError:
                pass

    def build_ui(self) -> QWidget:
        root = QWidget(self)
        root.setObjectName("appRoot")
        layout = QVBoxLayout(root)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.addWidget(self.build_window_chrome())

        body = QWidget(root)
        body.setObjectName("appBody")
        body_layout = QHBoxLayout(body)
        body_layout.setContentsMargins(0, 0, 0, 0)
        body_layout.setSpacing(0)

        self.main_splitter = QSplitter(Qt.Horizontal, body)
        self.main_splitter.setObjectName("mainSplitter")
        self.main_splitter.setChildrenCollapsible(False)
        self.main_stack = QStackedWidget(body)
        self.main_splitter.addWidget(self.build_nav_bar())
        self.main_stack.addWidget(self.build_chat_panel())
        self.main_stack.addWidget(self.build_settings_page())
        self.main_splitter.addWidget(self.main_stack)
        self.main_splitter.setSizes([self.nav_expanded_width, 920])
        body_layout.addWidget(self.main_splitter, 1)
        layout.addWidget(body, 1)

        self.resize_grip = QSizeGrip(root)
        self.resize_grip.setObjectName("resizeGrip")
        self.resize_grip.setFixedSize(18, 18)
        self.resize_grip.raise_()
        self.switch_page(0)
        return root

    def build_window_chrome(self) -> QWidget:
        chrome = WindowChrome(self)
        chrome.setObjectName("titleChrome")
        layout = QHBoxLayout(chrome)
        layout.setContentsMargins(14, 0, 8, 0)
        layout.setSpacing(10)

        avatar = QLabel("萤", chrome)
        avatar.setObjectName("titleAvatar")
        avatar.setFixedSize(30, 30)
        avatar.setAlignment(Qt.AlignCenter)
        pixmap = QPixmap(str(UI_ASSET_ROOT / "firefly_avatar.png"))
        if not pixmap.isNull():
            avatar.setPixmap(pixmap.scaled(30, 30, Qt.KeepAspectRatio, Qt.SmoothTransformation))
        layout.addWidget(avatar)
        title_box = QWidget(chrome)
        title_layout = QVBoxLayout(title_box)
        title_layout.setContentsMargins(0, 0, 0, 0)
        title_layout.setSpacing(0)
        title = QLabel("Firefly Agent", title_box)
        title.setObjectName("chromeTitle")
        title_layout.addWidget(title)
        layout.addWidget(title_box)
        layout.addStretch(1)

        minimize_button = self.window_control_button("-", "最小化", chrome)
        minimize_button.clicked.connect(self.showMinimized)
        self.window_state_button = self.window_control_button("□", "最大化", chrome)
        self.window_state_button.clicked.connect(self.toggle_window_state)
        close_button = self.window_control_button("×", "关闭", chrome, close=True)
        close_button.clicked.connect(self.close)
        layout.addWidget(minimize_button)
        layout.addWidget(self.window_state_button)
        layout.addWidget(close_button)
        self.update_window_state_button()
        return chrome

    def window_control_button(self, text: str, tooltip: str, parent: QWidget, close: bool = False) -> QPushButton:
        button = QPushButton(text, parent)
        button.setObjectName("windowCloseButton" if close else "windowControlButton")
        button.setToolTip(tooltip)
        button.setCursor(Qt.PointingHandCursor)
        button.setFocusPolicy(Qt.NoFocus)
        button.setFixedSize(34, 28)
        return button

    def build_nav_bar(self) -> QWidget:
        nav = QWidget(self)
        self.nav_bar = nav
        nav.setMinimumWidth(54)
        nav.setMaximumWidth(300)
        nav.setObjectName("featureBar")
        layout = QVBoxLayout(nav)
        self.nav_layout = layout
        layout.setContentsMargins(10, 14, 10, 14)
        layout.setSpacing(10)

        self.nav_toggle_button = QPushButton("‹", nav)
        self.nav_toggle_button.setObjectName("railToggle")
        self.nav_toggle_button.setToolTip("收起侧栏")
        self.nav_toggle_button.setCursor(Qt.PointingHandCursor)
        self.nav_toggle_button.setFixedSize(32, 32)
        self.nav_toggle_button.clicked.connect(self.toggle_nav_bar)
        layout.addWidget(self.nav_toggle_button, alignment=Qt.AlignHCenter)
        layout.addSpacing(14)

        self.new_chat_nav_button = self.nav_button("", "nav-new.svg", "新建")
        self.chat_nav_button = self.nav_button("对话", "nav-chat.svg", "对话")
        self.settings_nav_button = self.nav_button("设置", "nav-settings.svg", "设置")
        self.new_chat_nav_button.clicked.connect(self.new_conversation)
        self.chat_nav_button.clicked.connect(lambda _checked=False: self.switch_page(0))
        self.chat_nav_button.setContextMenuPolicy(Qt.CustomContextMenu)
        self.chat_nav_button.customContextMenuRequested.connect(self.show_chat_nav_conversation_menu)
        self.settings_nav_button.clicked.connect(lambda _checked=False: self.switch_page(1))

        layout.addWidget(self.new_chat_nav_button, alignment=Qt.AlignHCenter)
        layout.addWidget(self.chat_nav_button, alignment=Qt.AlignHCenter)
        self.conversation_heading = QLabel("对话历史", nav)
        self.conversation_heading.setObjectName("conversationHeading")
        layout.addWidget(self.conversation_heading)
        self.conversation_list = QListWidget(nav)
        self.conversation_list.setObjectName("conversationList")
        self.conversation_list.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.conversation_list.setTextElideMode(Qt.ElideRight)
        self.conversation_list.setContextMenuPolicy(Qt.CustomContextMenu)
        self.conversation_list.setDragDropMode(QAbstractItemView.InternalMove)
        self.conversation_list.setDefaultDropAction(Qt.MoveAction)
        self.conversation_list.setDragDropOverwriteMode(False)
        self.conversation_list.itemClicked.connect(lambda item: self.switch_conversation(self.conversation_list.row(item)))
        self.conversation_list.customContextMenuRequested.connect(self.show_conversation_menu)
        self.conversation_list.model().rowsMoved.connect(self.sync_conversations_after_drag)
        layout.addWidget(self.conversation_list, 1)
        layout.addStretch(1)
        layout.addWidget(self.settings_nav_button, alignment=Qt.AlignHCenter)
        self.apply_nav_collapsed_state()
        return nav

    def nav_button(self, text: str, icon_name: str, tooltip: str) -> QPushButton:
        button = QPushButton(text, self)
        button.setObjectName("navButton")
        button.setCheckable(True)
        button.setToolTip(tooltip)
        button.setCursor(Qt.PointingHandCursor)
        button.setIcon(QIcon(str(UI_ASSET_ROOT / icon_name)))
        button.setIconSize(QSize(18, 18))
        button.setFixedHeight(44)
        return button

    def toggle_nav_bar(self) -> None:
        if not self.nav_collapsed:
            self.nav_expanded_width = min(320, max(160, self.nav_bar.width()))
        self.nav_collapsed = not self.nav_collapsed
        self.apply_nav_collapsed_state()

    def apply_nav_collapsed_state(self) -> None:
        if self.nav_collapsed:
            self.nav_bar.setMinimumWidth(54)
            self.nav_bar.setMaximumWidth(54)
        else:
            self.nav_bar.setMinimumWidth(220)
            self.nav_bar.setMaximumWidth(300)
            if hasattr(self, "main_splitter"):
                self.main_splitter.setSizes([self.nav_expanded_width, max(1, self.width() - self.nav_expanded_width)])
        side_margin = 8 if self.nav_collapsed else 10
        self.nav_layout.setContentsMargins(side_margin, 14, side_margin, 14)
        self.nav_toggle_button.setText("›" if self.nav_collapsed else "‹")
        self.nav_toggle_button.setToolTip("展开侧栏" if self.nav_collapsed else "收起侧栏")
        self.new_chat_nav_button.setText("" if self.nav_collapsed else "新对话")
        self.chat_nav_button.setText("" if self.nav_collapsed else "对话")
        self.settings_nav_button.setText("" if self.nav_collapsed else "设置")
        self.chat_nav_button.setVisible(self.nav_collapsed)
        self.conversation_heading.setVisible(not self.nav_collapsed)
        self.conversation_list.setVisible(not self.nav_collapsed)
        width = 40 if self.nav_collapsed else max(180, self.nav_expanded_width - 20)
        height = 42 if self.nav_collapsed else 44
        for button in (self.new_chat_nav_button, self.chat_nav_button, self.settings_nav_button):
            button.setIconSize(QSize(20, 20) if self.nav_collapsed else QSize(18, 18))
            button.setFixedSize(width, height)

    def switch_page(self, index: int) -> None:
        self.main_stack.setCurrentIndex(index)
        self.chat_nav_button.setChecked(index == 0)
        self.settings_nav_button.setChecked(index == 1)
        self.new_chat_nav_button.setChecked(False)
        self.refresh_conversation_list()

    def build_chat_panel(self) -> QWidget:
        panel = QWidget(self)
        panel.setObjectName("chatPage")
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        header = QWidget(panel)
        header.setObjectName("chatHeader")
        header_layout = QHBoxLayout(header)
        header_layout.setContentsMargins(28, 0, 28, 0)
        header_layout.setSpacing(16)
        self.chat_title_label = QLabel("", header)
        self.chat_title_label.setObjectName("chatHeaderTitle")
        self.chat_ready_label = QLabel("● 就绪", header)
        self.chat_ready_label.setObjectName("chatHeaderStatus")
        self.chat_model_label = QLabel("", header)
        self.chat_model_label.setObjectName("chatHeaderModel")
        header_layout.addWidget(self.chat_title_label)
        header_layout.addWidget(self.chat_ready_label)
        header_layout.addWidget(self.chat_model_label)
        header_layout.addStretch(1)
        layout.addWidget(header)

        body = QHBoxLayout()
        body.setContentsMargins(18, 18, 18, 18)
        body.setSpacing(12)

        chat_column = QWidget(panel)
        chat_layout = QVBoxLayout(chat_column)
        chat_layout.setContentsMargins(0, 0, 0, 0)
        chat_layout.setSpacing(12)

        self.chat_scroll = QScrollArea(chat_column)
        self.chat_scroll.setObjectName("chatScroll")
        self.chat_scroll.setWidgetResizable(True)
        self.chat_scroll.setFrameShape(QFrame.NoFrame)
        self.chat_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.chat_scroll.viewport().setStyleSheet(chat_viewport_style_for_mode(self.config.get("theme_mode")))
        self.chat_messages_widget = QWidget(self.chat_scroll)
        self.chat_messages_widget.setObjectName("chatMessages")
        self.chat_messages_layout = QVBoxLayout(self.chat_messages_widget)
        self.chat_messages_layout.setContentsMargins(20, 18, 20, 18)
        self.chat_messages_layout.setSpacing(10)
        self.chat_messages_layout.addStretch(1)
        self.chat_scroll.setWidget(self.chat_messages_widget)
        self.status_label = QLabel("", self.chat_scroll.viewport())
        self.status_label.setObjectName("statusBadge")
        self.status_label.setTextFormat(Qt.RichText)
        self.status_label.hide()
        self.position_status_label()
        chat_layout.addWidget(self.chat_scroll, 1)

        composer = QWidget(chat_column)
        composer.setObjectName("composerPanel")
        composer_layout = QVBoxLayout(composer)
        composer_layout.setContentsMargins(10, 8, 10, 10)
        composer_layout.setSpacing(5)

        self.upload_preview_strip = QWidget(composer)
        self.upload_preview_strip.setObjectName("uploadPreviewStrip")
        self.upload_preview_layout = QHBoxLayout(self.upload_preview_strip)
        self.upload_preview_layout.setContentsMargins(4, 0, 4, 0)
        self.upload_preview_layout.setSpacing(6)
        self.upload_preview_strip.hide()
        composer_layout.addWidget(self.upload_preview_strip)

        input_box = QWidget(composer)
        input_box.setObjectName("inputBox")
        input_box.setFixedHeight(58)
        input_layout = QHBoxLayout(input_box)
        input_layout.setContentsMargins(8, 4, 12, 4)
        input_layout.setSpacing(8)
        self.upload_button = QPushButton("", input_box)
        self.upload_button.setObjectName("uploadButton")
        self.upload_button.setToolTip("上传文件")
        self.upload_button.setIcon(QIcon(str(UI_ASSET_ROOT / "folder.svg")))
        self.upload_button.setIconSize(QSize(18, 18))
        self.upload_button.clicked.connect(self.choose_upload_files)
        input_layout.addWidget(self.upload_button, 0, Qt.AlignVCenter)
        self.context_button = QPushButton("", input_box)
        self.context_button.setObjectName("contextButton")
        self.context_button.setCheckable(True)
        self.context_button.setIcon(QIcon(str(UI_ASSET_ROOT / "screen.svg")))
        self.context_button.setIconSize(QSize(18, 18))
        self.context_button.clicked.connect(self.toggle_chat_context)
        input_layout.addWidget(self.context_button, 0, Qt.AlignVCenter)
        self.input = ChatInput(input_box)
        self.input.setObjectName("messageInput")
        self.input.setPlaceholderText("输入你想问的内容")
        self.input.setFixedHeight(48)
        self.input.send_requested.connect(self.send_message)
        self.input.files_pasted.connect(self.add_upload_files)
        input_layout.addWidget(self.input, 1)
        self.send_button = QPushButton("", input_box)
        self.send_button.setObjectName("sendButton")
        self.send_button.setToolTip("发送")
        self.send_button.setIcon(QIcon(str(UI_ASSET_ROOT / "send.svg")))
        self.send_button.setIconSize(QSize(18, 18))
        self.send_button.clicked.connect(self.send_message)
        input_layout.addWidget(self.send_button, alignment=Qt.AlignVCenter)
        composer_layout.addWidget(input_box)
        chat_layout.addWidget(composer)
        body.addWidget(chat_column, 1)
        layout.addLayout(body, 1)
        self.sync_context_button()
        return panel

    def apply_runtime_config(self) -> None:
        model = str(self.config.get("model") or "") or None
        profile = str(self.config.get("provider_profile") or "") or None
        self.runtime.configure(model=model, provider_profile=profile)
        self.update_chat_header()

    def update_chat_header(self) -> None:
        if not hasattr(self, "chat_title_label") or not self.conversations:
            return
        conversation = self.conversations[self.current_conversation_index]
        self.chat_title_label.setText(conversation_title(conversation.get("title"), "对话"))
        model = str(self.config.get("model") or "").strip() or "未选择模型"
        self.chat_model_label.setText(model)

    def sync_context_button(self) -> None:
        if not hasattr(self, "context_button"):
            return
        enabled = bool(self.config.get("chat_window_context_enabled", False))
        self.context_button.setChecked(enabled)
        self.context_button.setToolTip("临场感知：已开启" if enabled else "临场感知：已关闭")

    def toggle_chat_context(self) -> None:
        self.config = {**self.config, "chat_window_context_enabled": self.context_button.isChecked()}
        save_config(self.config, self.workspace)
        self.sync_context_button()
        self.set_status_text("临场感知已开启" if self.context_button.isChecked() else "临场感知已关闭")

    def new_conversation(self) -> None:
        self.save_current_conversation()
        self.conversations.append({"title": f"对话 {len(self.conversations) + 1}", "history": [], "messages": []})
        self.load_conversation(len(self.conversations) - 1)
        self.persist_conversations()

    def switch_conversation(self, index: int) -> None:
        if index == self.current_conversation_index:
            return
        self.save_current_conversation()
        self.load_conversation(index)
        self.persist_conversations()

    def save_current_conversation(self) -> None:
        self.conversations[self.current_conversation_index]["history"] = list(self.history)
        self.conversations[self.current_conversation_index]["messages"] = list(self.messages)

    def persist_conversations(self) -> None:
        self.save_current_conversation()
        save_desktop_conversations(self.workspace, self.conversations, self.current_conversation_index)

    def load_conversation(self, index: int) -> None:
        self.current_conversation_index = index
        self.pending_uploads.clear()
        conversation = self.conversations[index]
        self.history = list(conversation.get("history", []))
        self.messages = list(conversation.get("messages", []))
        self.update_chat_header()
        self.render_chat_log()
        self.refresh_conversation_list()
        self.sync_composer_state()
        self.switch_page(0)

    def refresh_conversation_list(self) -> None:
        self.conversation_list.blockSignals(True)
        self.conversation_list.clear()
        for index, conversation in enumerate(self.conversations):
            item = QListWidgetItem(conversation_title(conversation.get("title"), f"对话 {index + 1}"))
            item.setData(Qt.UserRole, index)
            self.conversation_list.addItem(item)
        self.conversation_list.setCurrentRow(self.current_conversation_index)
        self.conversation_list.blockSignals(False)

    def show_conversation_menu(self, pos: QPoint) -> None:
        item = self.conversation_list.itemAt(pos)
        if item is None:
            return
        index = self.conversation_list.row(item)
        menu = QMenu(self)
        rename_action = menu.addAction("改名")
        menu.addSeparator()
        move_up_action = menu.addAction("上移")
        move_down_action = menu.addAction("下移")
        menu.addSeparator()
        delete_action = menu.addAction("删除")
        any_busy = self.any_busy()
        rename_action.setEnabled(not any_busy)
        move_up_action.setEnabled(index > 0 and not any_busy)
        move_down_action.setEnabled(index < len(self.conversations) - 1 and not any_busy)
        delete_action.setEnabled(not any_busy)
        action = menu.exec(self.conversation_list.mapToGlobal(pos))
        if action == rename_action:
            self.rename_conversation(index)
        elif action == move_up_action:
            self.move_conversation(index, -1)
        elif action == move_down_action:
            self.move_conversation(index, 1)
        elif action == delete_action:
            self.delete_conversation(index)

    def show_chat_nav_conversation_menu(self, pos: QPoint) -> None:
        menu = QMenu(self)
        for index, conversation in enumerate(self.conversations):
            action = menu.addAction(conversation_title(conversation.get("title"), f"对话 {index + 1}"))
            action.setData(index)
            action.setCheckable(True)
            action.setChecked(index == self.current_conversation_index)
        action = menu.exec(self.chat_nav_button.mapToGlobal(pos))
        if action is not None:
            self.switch_conversation(int(action.data()))

    def rename_conversation(self, index: int, title: str | None = None) -> None:
        if self.any_busy():
            return
        if title is None:
            title, ok = QInputDialog.getText(
                self,
                "改对话名称",
                "名称：",
                text=conversation_title(self.conversations[index].get("title"), ""),
            )
            if not ok:
                return
        title = conversation_title(title, "")
        if not title:
            return
        self.conversations[index]["title"] = title
        self.refresh_conversation_list()
        self.persist_conversations()

    def move_conversation(self, index: int, delta: int) -> None:
        target = index + delta
        if self.any_busy() or target < 0 or target >= len(self.conversations):
            return
        self.save_current_conversation()
        current = self.conversations[self.current_conversation_index]
        conversation = self.conversations.pop(index)
        self.conversations.insert(target, conversation)
        self.current_conversation_index = next(i for i, item in enumerate(self.conversations) if item is current)
        self.refresh_conversation_list()
        self.persist_conversations()

    def sync_conversations_after_drag(self, *_args: object) -> None:
        if self.any_busy():
            self.refresh_conversation_list()
            return
        self.save_current_conversation()
        current = self.conversations[self.current_conversation_index]
        ordered: list[dict[str, Any]] = []
        for row in range(self.conversation_list.count()):
            original_index = self.conversation_list.item(row).data(Qt.UserRole)
            if isinstance(original_index, int) and 0 <= original_index < len(self.conversations):
                ordered.append(self.conversations[original_index])
        if len(ordered) != len(self.conversations):
            self.refresh_conversation_list()
            return
        self.conversations = ordered
        self.current_conversation_index = next(i for i, item in enumerate(self.conversations) if item is current)
        self.refresh_conversation_list()
        self.persist_conversations()

    def delete_conversation(self, index: int) -> None:
        if self.any_busy():
            return
        self.save_current_conversation()
        if len(self.conversations) == 1:
            self.conversations[0] = {"title": "对话 1", "history": [], "messages": []}
            self.load_conversation(0)
            self.persist_conversations()
            return
        del self.conversations[index]
        if index == self.current_conversation_index:
            self.load_conversation(min(index, len(self.conversations) - 1))
        else:
            if index < self.current_conversation_index:
                self.current_conversation_index -= 1
            self.refresh_conversation_list()
        self.persist_conversations()

    def busy(self) -> bool:
        if not self.active_threads and self.thread is not None and not self.thread.isRunning():
            self.cleanup_worker()
        return self.conversation_busy(self.current_conversation_index)

    def any_busy(self) -> bool:
        for key, thread in list(self.active_threads.items()):
            if thread.isRunning():
                return True
            self.cleanup_worker(key)
        if self.thread is not None and not self.thread.isRunning():
            self.cleanup_worker()
        return False

    def conversation_busy(self, index: int) -> bool:
        if index < 0 or index >= len(self.conversations):
            return False
        key = id(self.conversations[index])
        thread = self.active_threads.get(key)
        if thread is None:
            return False
        if thread.isRunning():
            return True
        self.cleanup_worker(key)
        return False

    def sync_composer_state(self) -> None:
        enabled = not self.busy()
        self.send_button.setEnabled(enabled)
        self.upload_button.setEnabled(enabled)

    def conversation_index_for_object(self, conversation: dict[str, Any]) -> int | None:
        for index, item in enumerate(self.conversations):
            if item is conversation:
                return index
        return None

    def worker_conversation_context(self) -> tuple[int, dict[str, Any]]:
        sender = self.sender()
        if sender is not None:
            context = self.worker_conversations.get(id(sender))
            if context is not None:
                return context
        conversation = self.conversations[self.current_conversation_index]
        return id(conversation), conversation

    def append_message_to_conversation(self, conversation: dict[str, Any], role: str, text: str) -> None:
        if self.conversation_index_for_object(conversation) == self.current_conversation_index:
            self.append_message(role, text)
            return
        content = normalize_chat_text(text)
        if role == "status" and format_chat_text(content).startswith("本轮使用 Skill:"):
            return
        messages = list(conversation.get("messages", []))
        messages.append({"role": role, "content": content})
        conversation["messages"] = messages

    def render_chat_log(self) -> None:
        while self.chat_messages_layout.count() > 1:
            item = self.chat_messages_layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()
        rendered_assistant_files = {
            Path(message["content"]).expanduser().resolve()
            for message in self.messages
            if message.get("role") == "assistant_file"
        }
        for message in self.messages:
            role = message["role"]
            content = message["content"]
            if role == "status" and str(content).startswith("本轮使用 Skill:"):
                continue
            if role in {"file", "assistant_file"}:
                widget = self.file_card_widget(content, is_user=role == "file")
            else:
                widget = self.message_widget(role, content, hidden_image_paths=rendered_assistant_files)
            self.chat_messages_layout.insertWidget(self.chat_messages_layout.count() - 1, widget)
        self.scroll_chat_to_bottom()

    def message_widget(
        self,
        role: str,
        text: str,
        *,
        hidden_image_paths: set[Path] | None = None,
    ) -> QWidget:
        row = QWidget(self.chat_messages_widget)
        row_layout = QHBoxLayout(row)
        row_layout.setContentsMargins(0, 2, 0, 2)
        row_layout.setSpacing(8)
        if role == "status":
            label = QLabel(format_chat_text(text), row)
            label.setObjectName("chatStatusMessage")
            label.setWordWrap(True)
            label.setTextInteractionFlags(Qt.TextSelectableByMouse)
            label.setMaximumWidth(self.current_chat_bubble_width())
            row_layout.addStretch(1)
            row_layout.addWidget(label, 0, Qt.AlignCenter)
            row_layout.addStretch(1)
            return row

        is_user = role == "user"
        image_paths: list[Path] = []
        display_text = text
        if role == "assistant":
            cwd = Path(self.runtime.cwd or self.workspace)
            hidden = hidden_image_paths or set()
            image_paths = [path for path in reply_image_paths(text, cwd) if path not in hidden]
            if image_paths:
                display_text = strip_generated_image_notice(text)

        avatar = self.assistant_avatar(row) if not is_user else None

        bubble = ChatBubble(is_user, row)
        bubble.setObjectName("chatBubbleUser" if is_user else "chatBubbleAssistant")
        max_width = self.current_chat_bubble_width()
        bubble.setMaximumWidth(max_width)
        bubble_layout = QVBoxLayout(bubble)
        bubble_layout.setContentsMargins(16 if not is_user else 15, 9, 18 if is_user else 15, 11)
        bubble_layout.setSpacing(8 if image_paths else 0)

        if display_text.strip() or not image_paths:
            body = QLabel(
                render_chat_html(
                    display_text,
                    dark_theme=resolved_theme_mode(self.config.get("theme_mode")) == "dark",
                    is_user=is_user,
                ),
                bubble,
            )
            body.setObjectName("chatBubbleTextUser" if is_user else "chatBubbleTextAssistant")
            body.setAttribute(Qt.WA_TranslucentBackground, True)
            body.setAutoFillBackground(False)
            body.setStyleSheet("background: transparent; border: 0;")
            body.setTextFormat(Qt.RichText)
            body.setWordWrap(True)
            body.setOpenExternalLinks(True)
            body.setTextInteractionFlags(Qt.TextSelectableByMouse | Qt.LinksAccessibleByMouse)
            body.setMaximumWidth(max(280, max_width - 38))
            bubble_layout.addWidget(body)

        for path in image_paths:
            image = self.image_preview_label(path, bubble)
            if image is not None:
                bubble_layout.addWidget(image, 0, Qt.AlignLeft)

        if is_user:
            row_layout.addStretch(1)
            row_layout.addWidget(bubble, 0, Qt.AlignRight | Qt.AlignTop)
        else:
            if avatar is not None:
                row_layout.addWidget(avatar, 0, Qt.AlignLeft | Qt.AlignBottom)
            row_layout.addWidget(bubble, 0, Qt.AlignLeft | Qt.AlignTop)
            row_layout.addStretch(1)
        return row

    def image_preview_label(self, path: Path, parent: QWidget) -> QLabel | None:
        image = QLabel(parent)
        pixmap = QPixmap(str(path))
        if pixmap.isNull():
            return None
        image.setPixmap(pixmap.scaled(260, 180, Qt.KeepAspectRatio, Qt.SmoothTransformation))
        image.setCursor(Qt.PointingHandCursor)
        image.setToolTip(str(path))
        image.mousePressEvent = lambda _event, value=str(path): self.open_chat_file(value)
        return image

    def assistant_avatar(self, parent: QWidget) -> QLabel:
        avatar = QLabel(parent)
        avatar.setObjectName("speakerAvatarAssistant")
        avatar.setAttribute(Qt.WA_TranslucentBackground, True)
        avatar.setAutoFillBackground(False)
        avatar.setAlignment(Qt.AlignCenter)
        avatar.setFixedSize(48, 48)
        avatar.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
        avatar.setToolTip("流萤")
        pixmap = QPixmap(str(UI_ASSET_ROOT / "firefly_avatar.png"))
        if not pixmap.isNull():
            avatar.setPixmap(pixmap.scaled(48, 48, Qt.KeepAspectRatio, Qt.SmoothTransformation))
        return avatar

    def append_message(self, role: str, text: str) -> None:
        content = normalize_chat_text(text)
        if role == "status" and format_chat_text(content).startswith("本轮使用 Skill:"):
            return
        self.messages.append({"role": role, "content": content})
        widget = self.message_widget(role, content)
        self.chat_messages_layout.insertWidget(self.chat_messages_layout.count() - 1, widget)
        self.scroll_chat_to_bottom()

    def append_file_message(self, raw_path: str, *, is_user: bool = True) -> None:
        role = "file" if is_user else "assistant_file"
        self.messages.append({"role": role, "content": raw_path})
        self.chat_messages_layout.insertWidget(self.chat_messages_layout.count() - 1, self.file_card_widget(raw_path, is_user=is_user))
        self.scroll_chat_to_bottom()

    def scroll_chat_to_bottom(self) -> None:
        self._scroll_chat_to_bottom_now()
        QTimer.singleShot(0, self._scroll_chat_to_bottom_now)
        QTimer.singleShot(50, self._scroll_chat_to_bottom_now)

    def current_chat_bubble_width(self) -> int:
        return chat_bubble_max_width(self.width())

    def update_chat_bubble_widths(self) -> None:
        if not hasattr(self, "chat_messages_widget"):
            return
        max_width = self.current_chat_bubble_width()
        for bubble in self.chat_messages_widget.findChildren(ChatBubble):
            bubble.setMaximumWidth(max_width)
            for label in bubble.findChildren(QLabel):
                if label.objectName() in {"chatBubbleTextAssistant", "chatBubbleTextUser"}:
                    label.setMaximumWidth(max(280, max_width - 38))
            bubble.updateGeometry()

    def _scroll_chat_to_bottom_now(self) -> None:
        self.chat_messages_widget.adjustSize()
        bar = self.chat_scroll.verticalScrollBar()
        bar.setValue(bar.maximum())

    def set_status_text(self, text: str) -> None:
        if not hasattr(self, "status_label"):
            return
        self._status_token += 1
        if not text:
            self.status_label.hide()
            return
        token = self._status_token
        self.status_label.setText(html.escape(text))
        self.status_label.adjustSize()
        self.position_status_label()
        self.status_label.raise_()
        self.status_label.show()
        QTimer.singleShot(2000, lambda: self.status_label.hide() if token == self._status_token else None)

    def position_status_label(self) -> None:
        if not hasattr(self, "status_label") or not hasattr(self, "chat_scroll"):
            return
        viewport = self.chat_scroll.viewport()
        margin = 12
        self.status_label.adjustSize()
        self.status_label.move(max(margin, viewport.width() - self.status_label.width() - margin), margin)

    def choose_upload_files(self) -> None:
        dialog = QFileDialog(self, "上传文件给流萤", str(Path(self.runtime.cwd or self.workspace)))
        dialog.setFileMode(QFileDialog.ExistingFiles)
        dialog.setNameFilters(
            [
                "所有文件 (*)",
                "文本和代码 (*.txt *.md *.py *.js *.ts *.json *.yaml *.yml *.html *.css *.csv *.log)",
                "图片 (*.png *.jpg *.jpeg *.gif *.webp *.bmp)",
                "文档 (*.pdf *.docx *.xlsx *.pptx)",
            ]
        )
        if dialog.exec():
            self.add_upload_files(dialog.selectedFiles())

    def add_upload_files(self, file_names: list[str]) -> None:
        added = 0
        skipped = 0
        existing = {path.resolve() for path in self.pending_uploads}
        for file_name in file_names:
            try:
                path = Path(file_name).expanduser().resolve(strict=True)
            except (OSError, RuntimeError):
                skipped += 1
                continue
            if not path.is_file() or path in existing:
                skipped += 1
                continue
            self.pending_uploads.append(path)
            existing.add(path)
            added += 1
        if added:
            self.render_upload_previews()
        self.set_status_text(f"已添加 {added} 个文件，忽略 {skipped} 个无效路径" if skipped else f"已添加 {added} 个文件，待发送 {len(self.pending_uploads)} 个")

    def render_upload_previews(self) -> None:
        while self.upload_preview_layout.count():
            item = self.upload_preview_layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()
        for path in self.pending_uploads:
            self.upload_preview_layout.addWidget(upload_preview_widget(self.upload_preview_strip, path, IMAGE_EXTENSIONS, self.revoke_upload))
        self.upload_preview_strip.setVisible(bool(self.pending_uploads))

    def file_card_widget(self, raw_path: str, *, is_user: bool = True) -> QWidget:
        path = Path(raw_path)
        row = QWidget(self.chat_messages_widget)
        layout = QHBoxLayout(row)
        layout.setContentsMargins(0, 2, 0, 2)
        layout.setSpacing(8)
        if is_user:
            layout.addStretch(1)
        else:
            layout.addWidget(self.assistant_avatar(row), 0, Qt.AlignLeft | Qt.AlignBottom)
        is_pending = is_user and path.resolve() in {item.resolve() for item in self.pending_uploads}
        alignment = Qt.AlignRight if is_user else Qt.AlignLeft
        if path.suffix.lower() in IMAGE_EXTENSIONS:
            image = self.image_preview_label(path, row)
            if image is not None:
                layout.addWidget(image, 0, alignment)
                if is_pending:
                    layout.addWidget(self.revoke_upload_button(path), 0, Qt.AlignRight)
                if not is_user:
                    layout.addStretch(1)
                return row
            image = QLabel(row)
            image.setText("图片预览失败")
            image.setStyleSheet("color:#667b76; padding:8px; border:1px solid #d7e5e2; border-radius:8px;")
            layout.addWidget(image, 0, alignment)
            if is_pending:
                layout.addWidget(self.revoke_upload_button(path), 0, Qt.AlignRight)
            if not is_user:
                layout.addStretch(1)
            return row
        button = QPushButton(f"文件：{path.name}", row)
        button.setObjectName("secondaryButton")
        button.setToolTip(str(path))
        button.clicked.connect(lambda _checked=False, value=str(path): self.open_chat_file(value))
        layout.addWidget(button, 0, alignment)
        if is_pending:
            layout.addWidget(self.revoke_upload_button(path), 0, Qt.AlignRight)
        if not is_user:
            layout.addStretch(1)
        return row

    def revoke_upload_button(self, path: Path) -> QPushButton:
        button = QPushButton("撤回", self.chat_messages_widget)
        button.setObjectName("secondaryButton")
        button.setToolTip("从待发送文件中移除")
        button.clicked.connect(lambda _checked=False, value=path: self.revoke_upload(value))
        return button

    def revoke_upload(self, path: Path) -> None:
        target = path.resolve()
        self.pending_uploads = [item for item in self.pending_uploads if item.resolve() != target]
        for index in range(len(self.messages) - 1, -1, -1):
            message = self.messages[index]
            if message.get("role") == "file" and Path(message.get("content", "")).resolve() == target:
                del self.messages[index]
                break
        self.render_upload_previews()
        self.render_chat_log()
        self.set_status_text(f"已撤回文件，待发送 {len(self.pending_uploads)} 个")
        self.persist_conversations()

    def open_chat_file(self, raw_path: str) -> None:
        QDesktopServices.openUrl(QUrl.fromLocalFile(raw_path))

    def approve_permission_from_worker(self, tool_name: str, reason: str) -> bool:
        return bool(
            self.request_approval_from_worker(
                {
                    "kind": "permission",
                    "title": "确认本地操作",
                    "text": "允许执行这个本地修改操作吗？",
                    "details": f"工具：{tool_name}\n{reason}",
                }
            )
        )

    def approve_edit_from_worker(self, path: str, diff: str, added: int, removed: int) -> str:
        allowed = bool(
            self.request_approval_from_worker(
                {
                    "kind": "edit",
                    "title": "确认文件修改",
                    "text": "允许修改这个本地文件吗？",
                    "details": f"路径：{path}\n变更：+{added} -{removed}",
                    "diff": diff[:5000],
                }
            )
        )
        return "approve" if allowed else "reject"

    def request_approval_from_worker(self, request: dict[str, object]) -> bool:
        event = threading.Event()
        request["event"] = event
        request["result"] = False
        app = QApplication.instance()
        if app is not None and QThread.currentThread() == app.thread():
            self.handle_approval_request(request)
        else:
            self.approval_requested.emit(request)
            event.wait(120)
        return bool(request.get("result"))

    @Slot(object)
    def handle_approval_request(self, request: dict[str, object]) -> None:
        parent = self if self.isVisible() else self._approval_surface
        if parent is self._approval_surface and hasattr(parent, "show_speech"):
            parent.show_speech("需要确认一个本地修改。", 8000)
        dialog = QMessageBox(parent)
        dialog.setWindowTitle(str(request.get("title") or "确认操作"))
        dialog.setIcon(QMessageBox.Question)
        dialog.setText(str(request.get("text") or "允许执行这个操作吗？"))
        dialog.setInformativeText(str(request.get("details") or ""))
        if request.get("diff"):
            dialog.setDetailedText(str(request.get("diff")))
        dialog.setStyleSheet(chat_style_for_mode(self.config.get("theme_mode")))
        allow_button = dialog.addButton("允许", QMessageBox.AcceptRole)
        deny_button = dialog.addButton("拒绝", QMessageBox.RejectRole)
        dialog.setDefaultButton(deny_button)
        dialog.setEscapeButton(deny_button)
        dialog.exec()
        request["result"] = dialog.clickedButton() == allow_button
        event = request.get("event")
        if isinstance(event, threading.Event):
            event.set()

    @Slot()
    def send_message(self) -> None:
        message = self.input.toPlainText().strip()
        if (not message and not self.pending_uploads) or self.busy():
            return
        if message and not self.pending_uploads and self.handle_local_permission_command(message):
            return
        conversation = self.conversations[self.current_conversation_index]
        conversation_key = id(conversation)
        attachments = [str(path) for path in self.pending_uploads]
        visible_attachments = list(attachments)
        context_snapshot_path: Path | None = None
        prompt_message = message or "用户上传了文件，请根据附件内容回应。"
        if bool(self.config.get("chat_window_context_enabled", False)):
            if self._context_snapshotter is not None:
                snapshot = self._context_snapshotter("chat_context")
            else:
                snapshot = capture_desktop_snapshot(
                    self.workspace,
                    "chat_context",
                    excluded_title_parts=FIREFLY_WINDOW_TITLE_PARTS,
                    exclude_own_process=True,
                    persist=False,
                )
            if snapshot.image_path is not None:
                context_snapshot_path = snapshot.image_path
                prompt_message = f"{prompt_message}\n\n{snapshot_prompt(snapshot, '临场感知：请结合用户当前窗口内容判断是否需要补充说明。')}"
                attachments.append(str(snapshot.image_path))
            else:
                prompt_message = f"{prompt_message}\n\n临场感知：没有捕获到可用屏幕截图；不要声称看到了窗口、图片或界面。"
        self.pending_uploads.clear()
        self.render_upload_previews()
        self.input.clear()
        if message:
            self.append_message("user", message)
        for attachment in visible_attachments:
            self.append_file_message(attachment)
        self.persist_conversations()
        self.set_mood("thinking")
        thread = QThread(self)
        worker = ChatWorker(
            self.runtime,
            prompt_message,
            self.history,
            attachments,
            permission_prompt=self.approve_permission_from_worker,
            edit_approval_prompt=self.approve_edit_from_worker,
        )
        self.thread = thread
        self.worker = worker
        self.active_threads[conversation_key] = thread
        self.active_workers[conversation_key] = worker
        self.worker_conversations[id(worker)] = (conversation_key, conversation)
        worker.moveToThread(thread)
        thread.started.connect(worker.run)
        worker.finished.connect(self.handle_reply, Qt.QueuedConnection)
        worker.failed.connect(self.handle_error, Qt.QueuedConnection)
        worker.finished.connect(worker.deleteLater)
        worker.failed.connect(worker.deleteLater)
        worker.finished.connect(thread.quit)
        worker.failed.connect(thread.quit)
        if context_snapshot_path is not None:
            worker.finished.connect(
                lambda _message, _reply, _skills, path=context_snapshot_path: remove_temporary_context_snapshot(path)
            )
            worker.failed.connect(lambda _error, path=context_snapshot_path: remove_temporary_context_snapshot(path))
            thread.finished.connect(lambda path=context_snapshot_path: remove_temporary_context_snapshot(path))
        thread.finished.connect(thread.deleteLater)
        thread.finished.connect(lambda key=conversation_key: self.cleanup_worker(key))
        thread.start()
        self.sync_composer_state()

    def handle_local_permission_command(self, message: str) -> bool:
        mode = local_permission_mode_command(message)
        if mode is None:
            return False
        self.input.clear()
        self.append_message("user", message)
        self.config = {**self.config, "permission_mode": mode}
        save_config(self.config, self.workspace)
        if hasattr(self, "permission_mode_input"):
            self.permission_mode_input.setCurrentText(mode)
        notes = {
            "default": "之后需要本地修改时，会弹窗让你确认。",
            "full_auto": "大多数本地修改会直接执行；文件写改仍受目录边界保护。",
            "plan": "会阻止本地修改，只做计划和说明。",
        }
        self.append_message("assistant", f"权限模式已切换为 {mode}。{notes[mode]}")
        self.persist_conversations()
        return True

    @Slot(str, str, object)
    def handle_reply(self, message: str, reply: str, invoked_skills: object = None) -> None:
        del invoked_skills
        _conversation_key, conversation = self.worker_conversation_context()
        conversation_index = self.conversation_index_for_object(conversation)
        if conversation_index is None:
            return
        image_paths = reply_image_paths(reply, Path(self.runtime.cwd or self.workspace))
        clean_reply = strip_generated_image_notice(reply)
        assistant_content = clean_reply
        if image_paths:
            notices = "\n".join(f"生成的图片已保存到 `{path}`。" for path in image_paths)
            assistant_content = f"{clean_reply}\n{notices}" if clean_reply.strip() else notices
        if assistant_content.strip():
            self.append_message_to_conversation(conversation, "assistant", assistant_content)
        history = list(conversation.get("history", []))
        history.extend([{"role": "user", "content": message}, {"role": "assistant", "content": clean_reply}])
        conversation["history"] = history[-12:]
        if conversation_index == self.current_conversation_index:
            self.history = list(conversation["history"])
            conversation["messages"] = list(self.messages)
        if str(conversation.get("title", "")).startswith("对话 "):
            conversation["title"] = conversation_title(message, "对话", 18)
            self.refresh_conversation_list()
        self.set_mood(live2d_mood_for_reply(clean_reply))
        self.sync_composer_state()
        self.persist_conversations()

    @Slot(str)
    def handle_error(self, error: str) -> None:
        _conversation_key, conversation = self.worker_conversation_context()
        if self.conversation_index_for_object(conversation) is None:
            return
        self.append_message_to_conversation(conversation, "assistant", f"请求失败：{error}")
        self.set_mood("sweat")
        self.sync_composer_state()
        self.persist_conversations()

    def cleanup_worker(self, conversation_key: int | None = None) -> None:
        if conversation_key is None:
            if self.worker is not None:
                self.worker_conversations.pop(id(self.worker), None)
            self.thread = None
            self.worker = None
            self.sync_composer_state()
            return
        thread = self.active_threads.pop(conversation_key, None)
        worker = self.active_workers.pop(conversation_key, None)
        if worker is not None:
            self.worker_conversations.pop(id(worker), None)
        if self.thread is thread:
            self.thread = None
        if self.worker is worker:
            self.worker = None
        self.sync_composer_state()

    def show_and_raise(self) -> None:
        self.show()
        self.scroll_chat_to_bottom()
        self.raise_()
        self.activateWindow()
        self.input.setFocus()

    def toggle_window_state(self) -> None:
        if self.isMaximized():
            self.showNormal()
        else:
            self.showMaximized()
        self.update_window_state_button()

    def update_window_state_button(self) -> None:
        if self.window_state_button is None:
            return
        self.window_state_button.setText("❐" if self.isMaximized() else "□")
        self.window_state_button.setToolTip("还原" if self.isMaximized() else "最大化")

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        if self.resize_grip is not None:
            self.resize_grip.move(self.width() - self.resize_grip.width() - 4, self.height() - self.resize_grip.height() - 4)
        self.position_status_label()

    def closeEvent(self, event: QCloseEvent) -> None:
        self.persist_conversations()
        self.hide()
        event.ignore()
