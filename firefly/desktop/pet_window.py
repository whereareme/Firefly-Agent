"""Transparent Live2D pet window."""

from __future__ import annotations

import json
import re
from pathlib import Path

from PySide6.QtCore import QPoint, QRect, QSettings, Qt, QTimer, QUrl, Slot
from PySide6.QtGui import QAction, QColor, QDragEnterEvent, QDragMoveEvent, QDropEvent, QMouseEvent, QPainter, QPainterPath, QPen, QWheelEvent
from PySide6.QtWidgets import QApplication, QLabel, QMenu, QVBoxLayout, QWidget
from PySide6.QtWebEngineCore import QWebEngineSettings
from PySide6.QtWebEngineWidgets import QWebEngineView

from firefly.autostart import firefly_desktop_command_parts
from firefly.desktop.chat_window import local_file_paths_from_mime_data, strip_generated_image_notice
from firefly.desktop.music import DEFAULT_STARFIRE_SONG, DEFAULT_STARFIRE_SONG_URL, starfire_music_tracks
from firefly.stickers import extract_sticker_emotion
from firefly.workspace import load_config, save_config

MENU_STYLE = """
QMenu {
    background: #eef8f6;
    border: 1px solid #abd8d1;
    border-radius: 12px;
    padding: 7px;
    color: #285d58;
    font-size: 13px;
    font-weight: 600;
}
QMenu::item {
    background: transparent;
    border: 1px solid transparent;
    border-radius: 9px;
    padding: 8px 30px 8px 22px;
    margin: 2px 1px;
}
QMenu::item:selected {
    background: #ffffff;
    border: 1px solid #bdd9d5;
    color: #0d756e;
}
"""

DEFAULT_PET_WIDTH = 360
DEFAULT_PET_HEIGHT = 250
PET_RATIO = DEFAULT_PET_HEIGHT / DEFAULT_PET_WIDTH
PET_ACTIVE_LEFT = 0.06
PET_ACTIVE_TOP = 0.28
PET_ACTIVE_RIGHT = 0.94
PET_ACTIVE_BOTTOM = 0.98
BUBBLE_TAIL = 12
MAX_WIDGET_SIZE = 16777215
INTERNAL_REASONING_MARKERS = (
    "the user says",
    "the image is a screenshot",
    "instruction says",
    "prompt says",
    "formatting requirements",
    "let's double-check",
    "we need to",
)


def clean_live2d_reply(reply: str) -> str:
    """Remove non-user-facing model output before it reaches the desktop bubble."""
    text = strip_generated_image_notice(reply)
    text, _emotion = extract_sticker_emotion(text)
    text = re.sub(r"<think\b[^>]*>.*?</think>", "", text, flags=re.IGNORECASE | re.DOTALL).strip()
    final_match = re.search(r"(?:^|\n)\s*(?:final(?: answer)?|最终回答)\s*[:：]\s*(.+)\Z", text, re.IGNORECASE | re.DOTALL)
    if final_match:
        text = final_match.group(1).strip()
    lowered = text.lower().lstrip()
    marker_count = sum(marker in lowered for marker in INTERNAL_REASONING_MARKERS)
    if re.match(r"^(?:thought|analysis|reasoning)\b", lowered) or marker_count >= 2:
        return ""
    return text


class Live2DSpeechBubble(QWidget):
    def __init__(self) -> None:
        super().__init__(None)
        self.tail_x = 32
        self.tail_on_top = False
        self.setWindowFlags(Qt.Tool | Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.WindowDoesNotAcceptFocus)
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WA_ShowWithoutActivating, True)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 10 + BUBBLE_TAIL, 16, 12 + BUBBLE_TAIL)
        layout.setSpacing(0)
        self.label = QLabel(self)
        self.label.setWordWrap(True)
        self.label.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        self.label.setStyleSheet("background: transparent; border: 0; color: #10231f; font-size: 15px; font-weight: 400;")
        layout.addWidget(self.label)

    def setText(self, text: str) -> None:
        self.label.setText(text)

    def setBubbleWidth(self, width: int) -> None:
        self.setFixedWidth(width)
        margins = self.layout().contentsMargins()
        self.label.setFixedWidth(max(40, width - margins.left() - margins.right()))
        self.label.adjustSize()
        self.adjustSize()

    def resetHeightConstraint(self) -> None:
        self.setMinimumHeight(0)
        self.setMaximumHeight(MAX_WIDGET_SIZE)

    def setTailTarget(self, target_x: int, tail_on_top: bool) -> None:
        self.tail_x = max(24, min(target_x - self.x(), self.width() - 24))
        self.tail_on_top = tail_on_top
        margins = self.layout().contentsMargins()
        self.layout().setContentsMargins(
            margins.left(),
            10 + (BUBBLE_TAIL if tail_on_top else 0),
            margins.right(),
            12 + (0 if tail_on_top else BUBBLE_TAIL),
        )
        self.update()

    def paintEvent(self, event) -> None:
        del event
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing, True)
        rect = self.rect().adjusted(1, 1 + (BUBBLE_TAIL if self.tail_on_top else 0), -1, -1 - (0 if self.tail_on_top else BUBBLE_TAIL))
        path = QPainterPath()
        path.addRoundedRect(rect, 17, 17)
        tail = QPainterPath()
        if self.tail_on_top:
            tail.moveTo(self.tail_x - BUBBLE_TAIL, rect.top() + 1)
            tail.lineTo(self.tail_x, 1)
            tail.lineTo(self.tail_x + BUBBLE_TAIL, rect.top() + 1)
        else:
            tail.moveTo(self.tail_x - BUBBLE_TAIL, rect.bottom() - 1)
            tail.lineTo(self.tail_x, self.height() - 1)
            tail.lineTo(self.tail_x + BUBBLE_TAIL, rect.bottom() - 1)
        tail.closeSubpath()
        path = path.united(tail)
        painter.setBrush(QColor("#c9efea"))
        painter.setPen(QPen(QColor("#91d4cb"), 1))
        painter.drawPath(path)


class PetWindow(QWidget):
    def __init__(
        self,
        url: str,
        on_click,
        on_files_dropped=None,
        restart_cwd: str | Path | None = None,
        workspace: str | Path | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.on_click = on_click
        self.on_files_dropped = on_files_dropped
        self.restart_cwd = Path(restart_cwd or Path.cwd())
        self.workspace = Path(workspace).expanduser().resolve() if workspace else None
        self.settings = QSettings("Firefly", "FireflyAgent")
        self._press_global: QPoint | None = None
        self._window_pos: QPoint | None = None
        self._dragged = False
        self._focus_active = False
        self._restart_requested = False
        self._restart_callback = None
        self._ignore_release_after_double_click = False
        self._music_protected = False
        self._music_protect_timer = QTimer(self)
        self._music_protect_timer.setSingleShot(True)
        self._music_protect_timer.timeout.connect(self.clear_music_protection)
        self._single_click_timer = QTimer(self)
        self._single_click_timer.setSingleShot(True)
        self._single_click_timer.timeout.connect(self.open_chat_from_click)
        self.last_agent_reply = ""
        self._speech_token = 0
        self._live2d_ready = False

        self.setWindowTitle("Firefly")
        self.setWindowFlags(Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool)
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        self.setMouseTracking(True)
        self.setAcceptDrops(True)
        width = int(self.settings.value("pet/width", DEFAULT_PET_WIDTH))
        height = int(self.settings.value("pet/height", DEFAULT_PET_HEIGHT))
        if height > int(width * 1.08):
            height = int(width * PET_RATIO)
        self.resize(width, height)
        pos = self.settings.value("pet/pos")
        if isinstance(pos, QPoint):
            self.move(pos)

        self.view = QWebEngineView(self)
        self.view.setStyleSheet("background: transparent;")
        self.view.setAutoFillBackground(False)
        self.view.setContextMenuPolicy(Qt.NoContextMenu)
        self.view.setAcceptDrops(False)
        self.view.setAttribute(Qt.WA_TranslucentBackground, True)
        self.view.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        self.view.settings().setAttribute(QWebEngineSettings.WebAttribute.PlaybackRequiresUserGesture, False)
        page = self.view.page()
        if hasattr(page, "setBackgroundColor"):
            page.setBackgroundColor(QColor(0, 0, 0, 0))
        self.view.loadFinished.connect(lambda ok: setattr(self, "_live2d_ready", bool(ok)))
        page.renderProcessTerminated.connect(lambda *_args: setattr(self, "_live2d_ready", False))
        self.view.load(QUrl(url))

        self.speech_bubble = Live2DSpeechBubble()
        self.speech_bubble.hide()

    def dragEnterEvent(self, event: QDragEnterEvent) -> None:
        if local_file_paths_from_mime_data(event.mimeData()):
            event.acceptProposedAction()
            return
        super().dragEnterEvent(event)

    def dragMoveEvent(self, event: QDragMoveEvent) -> None:
        if local_file_paths_from_mime_data(event.mimeData()):
            event.acceptProposedAction()
            return
        super().dragMoveEvent(event)

    def dropEvent(self, event: QDropEvent) -> None:
        files = local_file_paths_from_mime_data(event.mimeData())
        if files:
            if self.on_files_dropped is not None:
                self.on_files_dropped(files)
            else:
                self.on_click()
            self.set_live2d_mood("happy")
            event.acceptProposedAction()
            return
        super().dropEvent(event)

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self.view.setGeometry(self.rect())
        self.position_speech_bubble()
        self.settings.setValue("pet/width", self.width())
        self.settings.setValue("pet/height", self.height())

    def show_speech(self, text: str, timeout_ms: int = 8000) -> None:
        message = " ".join(text.strip().split())
        if not message:
            return
        screen = self.screen() or QApplication.primaryScreen()
        available = screen.availableGeometry() if screen is not None else QApplication.primaryScreen().availableGeometry()
        width = min(max(260, self.width()), max(260, available.width() - 24), 420)
        self.speech_bubble.resetHeightConstraint()
        self.speech_bubble.setText(message)
        self.speech_bubble.setBubbleWidth(width)
        max_height = max(90, min(260, available.height() - 24))
        if self.speech_bubble.height() > max_height:
            self.speech_bubble.setFixedHeight(max_height)
        self.speech_bubble.adjustSize()
        self.position_speech_bubble()
        self._raise_speech_bubble()
        QTimer.singleShot(80, self._raise_speech_bubble)
        self._speech_token += 1
        token = self._speech_token
        QTimer.singleShot(timeout_ms, lambda: self.speech_bubble.hide() if token == self._speech_token else None)

    def _raise_speech_bubble(self) -> None:
        if not hasattr(self, "speech_bubble"):
            return
        if self.isVisible():
            self.raise_()
        if self.speech_bubble.isMinimized():
            self.speech_bubble.showNormal()
        else:
            self.speech_bubble.show()
        self.speech_bubble.raise_()
        self.speech_bubble.update()

    @Slot(str, str, object)
    def show_agent_reply(self, _message: str, reply: str, _skills: object = None) -> None:
        reply = clean_live2d_reply(reply)
        if not reply:
            self.speech_bubble.hide()
            return
        self.last_agent_reply = reply
        self.show_speech(reply)
        self.set_live2d_mood_from_watch("happy")

    @Slot(str)
    def show_agent_error(self, _error: str) -> None:
        self.show_speech("萤火巡望暂时没连上回应核心。", 5000)
        self.set_live2d_mood_from_watch("sweat")

    def position_speech_bubble(self) -> None:
        if not hasattr(self, "speech_bubble"):
            return
        screen = self.screen() or QApplication.primaryScreen()
        available = screen.availableGeometry() if screen is not None else QApplication.primaryScreen().availableGeometry()
        target = QPoint(self.x() + self.width() // 2, self.y() + int(self.height() * 0.22))
        x = self.x() + (self.width() - self.speech_bubble.width()) // 2
        x = max(available.left() + 6, min(x, available.right() - self.speech_bubble.width() - 6))
        y = self.y() - self.speech_bubble.height() - 2
        tail_on_top = False
        if y < available.top() + 6:
            y = self.y() + self.height() + 8
            tail_on_top = True
        if y + self.speech_bubble.height() > available.bottom() - 6:
            y = max(available.top() + 6, self.y() + 8)
            tail_on_top = False
        self.speech_bubble.move(x, y)
        self.speech_bubble.setTailTarget(target.x(), tail_on_top)

    def mousePressEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.LeftButton:
            self._press_global = event.globalPosition().toPoint()
            self._window_pos = self.pos()
            self._dragged = False
            event.accept()
            return
        if event.button() == Qt.RightButton:
            self.show_menu(event.globalPosition().toPoint())
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event: QMouseEvent) -> None:
        if self._press_global is not None and self._window_pos is not None and event.buttons() & Qt.LeftButton:
            delta = event.globalPosition().toPoint() - self._press_global
            if delta.manhattanLength() > 6:
                self._dragged = True
                self.move(self._window_pos + delta)
                self.position_speech_bubble()
                self.settings.setValue("pet/pos", self.pos())
                event.accept()
                return
        if self.active_rect().contains(event.position().toPoint()):
            self.focus_live2d(event.position().toPoint())
            event.accept()
            return
        self.reset_live2d_focus()
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:
        if self._ignore_release_after_double_click and event.button() == Qt.LeftButton:
            self._ignore_release_after_double_click = False
            self._press_global = None
            self._window_pos = None
            self._dragged = False
            event.accept()
            return
        was_click = event.button() == Qt.LeftButton and not self._dragged
        self._press_global = None
        self._window_pos = None
        self._dragged = False
        if was_click and self.active_rect().contains(event.position().toPoint()):
            self._single_click_timer.start(QApplication.doubleClickInterval() + 20)
            event.accept()
            return
        super().mouseReleaseEvent(event)

    def mouseDoubleClickEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.LeftButton and self.active_rect().contains(event.position().toPoint()):
            self._single_click_timer.stop()
            self._ignore_release_after_double_click = True
            self.set_live2d_mood("idle")
            event.accept()
            return
        super().mouseDoubleClickEvent(event)

    def open_chat_from_click(self) -> None:
        self.on_click()
        self.set_live2d_mood("happy")

    def leaveEvent(self, event) -> None:
        self.reset_live2d_focus()
        super().leaveEvent(event)

    def hideEvent(self, event) -> None:
        if hasattr(self, "speech_bubble"):
            self.speech_bubble.hide()
        super().hideEvent(event)

    def closeEvent(self, event) -> None:
        if hasattr(self, "speech_bubble"):
            self.speech_bubble.hide()
        super().closeEvent(event)

    def wheelEvent(self, event: QWheelEvent) -> None:
        delta = 24 if event.angleDelta().y() > 0 else -24
        width = max(220, min(760, self.width() + delta))
        self.resize(width, int(width * PET_RATIO))
        event.accept()

    def show_menu(self, global_pos: QPoint) -> None:
        menu = QMenu(self)
        menu.setStyleSheet(MENU_STYLE)
        music_menu = menu.addMenu("星火旋律")
        music_menu.setStyleSheet(MENU_STYLE)
        sequence_action = QAction("顺序播放", music_menu)
        sequence_action.triggered.connect(lambda: self.play_starfire_music("sequence"))
        random_action = QAction("随机播放", music_menu)
        random_action.triggered.connect(lambda: self.play_starfire_music("random"))
        previous_action = QAction("上一曲", music_menu)
        previous_action.triggered.connect(lambda: self.play_starfire_music("previous"))
        next_action = QAction("下一曲", music_menu)
        next_action.triggered.connect(lambda: self.play_starfire_music("next"))
        for action in (sequence_action, random_action, previous_action, next_action):
            music_menu.addAction(action)
        restart_action = QAction("重启", menu)
        restart_action.triggered.connect(self.restart_app)
        menu.addAction(restart_action)
        quit_action = QAction("退出", menu)
        quit_action.triggered.connect(QApplication.quit)
        menu.addAction(quit_action)
        menu.exec(global_pos)

    def restart_app(self) -> None:
        from PySide6.QtCore import QProcess

        if self._restart_requested:
            return
        self._restart_requested = True

        program, arguments = firefly_desktop_command_parts(self.restart_cwd)

        def start_replacement() -> None:
            QProcess.startDetached(program, arguments)

        self._restart_callback = start_replacement
        app = QApplication.instance()
        if app is not None:
            app.aboutToQuit.connect(start_replacement)
            app.exit(0)

    def active_rect(self) -> QRect:
        return QRect(
            int(self.width() * PET_ACTIVE_LEFT),
            int(self.height() * PET_ACTIVE_TOP),
            int(self.width() * (PET_ACTIVE_RIGHT - PET_ACTIVE_LEFT)),
            int(self.height() * (PET_ACTIVE_BOTTOM - PET_ACTIVE_TOP)),
        )

    def focus_live2d(self, point: QPoint) -> None:
        self._focus_active = True
        self.run_live2d_script(f"window.fireAgentLive2D?.focus({point.x()}, {point.y()})")

    def reset_live2d_focus(self) -> None:
        if not self._focus_active:
            return
        self._focus_active = False
        self.run_live2d_script("window.fireAgentLive2D?.resetFocus()")

    def run_live2d_script(self, script: str) -> None:
        if self._live2d_ready:
            self.view.page().runJavaScript(script)

    def set_live2d_mood(self, mood: str) -> None:
        safe = "".join(ch for ch in mood if ch.isalnum() or ch in {"_", "-"})
        if safe == "music":
            self._music_protected = True
            self._music_protect_timer.start(205_000)
        elif safe:
            self.clear_music_protection()
        self.run_live2d_script(f"window.fireAgentLive2D?.setMood('{safe}')")

    def play_starfire_music(self, command: str) -> None:
        config = load_config(self.workspace)
        if command in {"sequence", "random"}:
            config = {**config, "starfire_music_mode": command}
            save_config(config, self.workspace)
        tracks = []
        for path in starfire_music_tracks(config):
            builtin = path == DEFAULT_STARFIRE_SONG.resolve()
            url = DEFAULT_STARFIRE_SONG_URL if builtin else QUrl.fromLocalFile(str(path)).toString()
            tracks.append({"title": path.stem, "url": url, "builtin": builtin})
        if not tracks:
            self.show_speech("星火旋律还没有可播放的歌曲。", 4000)
            return
        self._music_protected = True
        self._music_protect_timer.start(205_000)
        payload = {
            "command": command,
            "mode": "random" if command == "random" else str(config.get("starfire_music_mode") or "sequence"),
            "tracks": tracks,
        }
        self.run_live2d_script(f"window.fireAgentLive2D?.music({json.dumps(payload, ensure_ascii=False)})")

    def set_live2d_mood_from_watch(self, mood: str) -> None:
        if self._music_protected:
            return
        self.set_live2d_mood(mood)

    def clear_music_protection(self) -> None:
        self._music_protected = False
        self._music_protect_timer.stop()
