"""Qt styles for Firefly desktop."""

from __future__ import annotations

import sys

THEME_LABELS = {
    "system": "跟随系统",
    "light": "明亮模式",
    "dark": "深色模式",
}

CHAT_STYLE = """
QMainWindow {
    background: #eef8f6;
    color: #172520;
    font-family: "Microsoft YaHei UI", "Microsoft YaHei", "Segoe UI", sans-serif;
}
QWidget {
    font-family: "Microsoft YaHei UI", "Microsoft YaHei", "Segoe UI", sans-serif;
}
QWidget#appRoot,
QWidget#appBody {
    background: #eef8f6;
}
QWidget#titleChrome {
    background: #fbfffe;
    border-bottom: 1px solid #cde3df;
}
QLabel#titleAvatar {
    background: #ecfaf7;
    border: 1px solid #b9ddd6;
    border-radius: 15px;
    color: #0f6f68;
    font-weight: 700;
}
QLabel#chromeTitle {
    color: #132a25;
    font-size: 14px;
    font-weight: 700;
}
QLabel#chromeCaption {
    color: #6f817d;
    font-size: 11px;
}
QLabel#chromePill {
    background: #eef8f6;
    border: 1px solid #c8e1dc;
    border-left: 3px solid #ef8f85;
    border-radius: 8px;
    color: #245f59;
    font-size: 11px;
    font-weight: 700;
    padding: 5px 10px;
}
QPushButton#windowControlButton,
QPushButton#windowCloseButton {
    min-width: 34px;
    max-width: 34px;
    min-height: 28px;
    max-height: 28px;
    border: 1px solid transparent;
    border-radius: 8px;
    background: transparent;
    color: #3d5d58;
    padding: 0;
    font-size: 13px;
    font-weight: 800;
}
QPushButton#windowControlButton:hover {
    background: #ecf7f5;
    border: 1px solid #c8e1dc;
    color: #0f6f68;
}
QPushButton#windowCloseButton:hover {
    background: #fff0ee;
    border: 1px solid #f1b8b0;
    color: #b83e35;
}
QSizeGrip#resizeGrip {
    background: transparent;
    width: 18px;
    height: 18px;
}
QWidget#featureBar {
    background: #e4f3f0;
    border-right: 1px solid #c7e1dc;
    border-radius: 0;
}
QSplitter#mainSplitter::handle {
    background: #c7e1dc;
}
QSplitter#mainSplitter::handle:horizontal {
    width: 2px;
}
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
QMenu::item:disabled {
    color: #8aa09b;
}
QMenu::separator {
    height: 1px;
    background: #c8e1dc;
    margin: 5px 8px;
}
QPushButton#railToggle {
    background: transparent;
    border: 1px solid transparent;
    border-radius: 16px;
    color: #2c756f;
    font-size: 17px;
    font-weight: 800;
}
QPushButton#railToggle:hover {
    background: #f8fffd;
    border: 1px solid #b7dad4;
    color: #0f6f68;
}
QPushButton#navButton {
    border: 1px solid transparent;
    border-radius: 14px;
    background: transparent;
    color: #496d68;
    font-size: 13px;
    font-weight: 700;
    outline: none;
    padding: 0;
}
QPushButton#navButton:hover {
    background: #f3fbf9;
    color: #1f7069;
}
QPushButton#navButton:checked {
    background: qlineargradient(x1:0, y1:0, x2:1, y2:1, stop:0 #ffffff, stop:1 #e4f5f2);
    color: #0b6f68;
    border: 1px solid #8ccbc3;
    font-weight: 800;
}
QListWidget#conversationList {
    background: transparent;
    border: 0;
    outline: none;
    padding: 0;
    color: #496d68;
}
QListWidget#conversationList::item {
    border: 1px solid transparent;
    border-radius: 14px;
    padding: 10px 8px;
    margin: 3px 0;
    min-height: 24px;
}
QListWidget#conversationList::item:hover {
    background: #f3fbf9;
    color: #1f7069;
}
QListWidget#conversationList::item:selected {
    background: qlineargradient(x1:0, y1:0, x2:1, y2:1, stop:0 #ffffff, stop:1 #e4f5f2);
    color: #0b6f68;
    border: 1px solid #8ccbc3;
    font-weight: 800;
}
QWidget#pageSurface,
QWidget#settingsCard {
    background: #ffffff;
    border: 1px solid #d9e7e4;
    border-radius: 8px;
}
QWidget#composerPanel {
    background: #f2f8f7;
    border: 1px solid #d9e7e4;
    border-radius: 8px;
}
QWidget#inputBox {
    background: #fbfefd;
    border: 1px solid #d7e5e2;
    border-radius: 8px;
}
QWidget#settingsNav {
    background: transparent;
    border: 0;
    border-radius: 0;
}
QLabel#appTitle {
    color: #172520;
    font-size: 22px;
    font-weight: 700;
}
QLabel#pageTitle {
    color: #172520;
    font-size: 22px;
    font-weight: 700;
    padding: 0;
}
QLabel#appCaption,
QLabel#sectionCaption,
QLabel#infoText {
    color: #667b76;
    line-height: 1.5;
}
QLabel#sectionTitle {
    color: #172520;
    font-size: 15px;
    font-weight: 600;
}
QLabel#skillPageTitle {
    color: #172520;
    font-size: 26px;
    font-weight: 700;
}
QLabel#statusBadge,
QLabel#infoBadge {
    background: #eaf7f5;
    border: 1px solid #c6ddd9;
    border-radius: 8px;
    color: #1d6d68;
    padding: 6px 10px;
    font-weight: 700;
}
QLabel#modelSummary {
    background: #f4faf9;
    border: 1px solid #dce9e6;
    border-radius: 8px;
    padding: 10px;
    color: #48615d;
}
QTextBrowser,
QTextEdit,
QListWidget,
QLineEdit,
QComboBox {
    border: 1px solid #d7e5e2;
    border-radius: 8px;
    background: #fbfefd;
    color: #172520;
    selection-background-color: #7fc8c1;
    selection-color: #10231f;
    padding: 8px;
}
QSplitter#librarySplitter::handle {
    background: #d4e8e4;
    border-radius: 2px;
    margin: 4px 5px;
}
QSplitter#librarySplitter::handle:horizontal {
    width: 8px;
}
QScrollArea#chatScroll {
    background: qlineargradient(x1:0, y1:0, x2:1, y2:1, stop:0 #fafdff, stop:0.46 #f1fbff, stop:1 #fffdf4);
    border: 0;
    padding: 8px;
}
QScrollArea#settingsScroll {
    background: #ffffff;
    border: 0;
}
QWidget#chatMessages {
    background: qlineargradient(x1:0, y1:0, x2:1, y2:1, stop:0 #fafdff, stop:0.42 #eefaff, stop:0.72 #f6fffd, stop:1 #fffdf4);
}
QFrame#chatBubbleAssistant,
QFrame#chatBubbleUser {
    background: transparent;
    border: 0;
}
QLabel#chatBubbleTextAssistant {
    background: transparent;
    border: 0;
    color: #10231f;
    font-size: 15px;
    font-weight: 400;
    padding: 0;
}
QLabel#chatBubbleTextUser {
    background: transparent;
    border: 0;
    color: #10322e;
    font-size: 15px;
    font-weight: 400;
    padding: 0;
}
QLabel#chatStatusMessage {
    background: #f0f8f7;
    border: 1px solid #d5e6e3;
    border-radius: 7px;
    color: #4d6d68;
    font-size: 12px;
    padding: 5px 9px;
}
QLabel#speakerAvatarAssistant {
    background: transparent;
    border: 0;
    padding: 0;
}
QTextEdit#messageInput {
    background: transparent;
    border: 0;
    padding: 4px 8px;
}
QTextBrowser#filePreview {
    background: #f7fbfa;
    font-size: 12px;
}
QCheckBox {
    color: #3f6761;
    font-size: 13px;
    font-weight: 700;
    spacing: 8px;
}
QCheckBox::indicator {
    width: 16px;
    height: 16px;
    border-radius: 8px;
    border: 1px solid #bfd8d4;
    background: #fbfefd;
}
QCheckBox::indicator:hover {
    border: 1px solid #8ccbc3;
    background: #f3fbf9;
}
QCheckBox::indicator:checked {
    background: #2b8f88;
    border: 1px solid #2b8f88;
}
QCheckBox::indicator:disabled {
    background: #e8f0ee;
    border: 1px solid #cbdcda;
}
QPushButton {
    border: 0;
    border-radius: 8px;
    padding: 9px 13px;
    background: #2b8f88;
    color: #ffffff;
    font-weight: 600;
}
QPushButton:hover {
    background: #237973;
}
QPushButton:disabled {
    background: #a8bbb7;
    color: #eef5f4;
}
QPushButton#secondaryButton {
    background: #eef8f6;
    color: #285d58;
    border: 1px solid #d3e4e1;
}
QPushButton#secondaryButton:hover {
    background: #e4f2ef;
}
QPushButton#settingsTab {
    background: transparent;
    color: #496d68;
    border: 1px solid transparent;
    border-radius: 14px;
    font-size: 13px;
    font-weight: 700;
    padding: 10px 8px;
    text-align: left;
}
QPushButton#settingsTab:hover {
    background: #f3fbf9;
    color: #1f7069;
}
QPushButton#settingsTab:checked {
    background: qlineargradient(x1:0, y1:0, x2:1, y2:1, stop:0 #ffffff, stop:1 #e4f5f2);
    color: #0b6f68;
    border: 1px solid #8ccbc3;
    font-weight: 800;
}
QPushButton#sendButton {
    min-width: 38px;
    max-width: 38px;
    min-height: 38px;
    max-height: 38px;
    border-radius: 19px;
    padding: 0;
    font-size: 12px;
    font-weight: 800;
}
QPushButton#contextButton {
    min-width: 32px;
    max-width: 32px;
    min-height: 28px;
    max-height: 28px;
    border-radius: 8px;
    padding: 0;
    background: #eef8f6;
    border: 1px solid #cde2de;
    color: #2b8f88;
    outline: none;
}
QPushButton#contextButton:hover,
QPushButton#contextButton:checked {
    background: #dff3f0;
    border: 1px solid #82c8bf;
    color: #0f756d;
}
QWidget#uploadPreviewStrip {
    background: transparent;
}
QFrame#uploadPreviewCard {
    background: #fbfffe;
    border: 1px solid #d7e8e5;
    border-radius: 8px;
    min-width: 84px;
    max-width: 84px;
    min-height: 72px;
    max-height: 72px;
}
QPushButton#uploadPreviewClose {
    background: #1d302b;
    color: #ffffff;
    border: 0;
    border-radius: 8px;
    min-width: 16px;
    max-width: 16px;
    min-height: 16px;
    max-height: 16px;
    padding: 0;
    font-size: 10px;
    font-weight: 700;
}
QPushButton#uploadButton {
    min-width: 32px;
    max-width: 32px;
    min-height: 28px;
    max-height: 28px;
    border-radius: 8px;
    padding: 0;
    outline: none;
    background: #eef8f6;
    border: 1px solid #cde2de;
}
QPushButton#uploadButton:hover {
    background: #e3f3f0;
}
QLabel {
    color: #26352f;
    font-weight: 500;
}
"""

DARK_CHAT_STYLE = """
QMainWindow,
QWidget#appRoot,
QWidget#appBody {
    background: #10201d;
    color: #e8f5f2;
}
QWidget#titleChrome {
    background: #142723;
    border-bottom: 1px solid #24443e;
}
QLabel#titleAvatar {
    background: #1c3934;
    border: 1px solid #3d7d73;
    color: #9ee7de;
}
QLabel#chromeTitle,
QLabel#pageTitle,
QLabel#appTitle,
QLabel#skillPageTitle,
QLabel#sectionTitle {
    color: #edf8f5;
}
QLabel#chromeCaption,
QLabel#appCaption,
QLabel#sectionCaption,
QLabel#infoText {
    color: #a6c3bc;
}
QLabel#chromePill,
QLabel#statusBadge,
QLabel#infoBadge {
    background: #19332f;
    border: 1px solid #35645d;
    color: #a9eee5;
}
QPushButton#windowControlButton,
QPushButton#windowCloseButton {
    color: #b8d8d1;
}
QPushButton#windowControlButton:hover {
    background: #1d3833;
    border: 1px solid #376961;
    color: #b9f2ea;
}
QPushButton#windowCloseButton:hover {
    background: #3c2220;
    border: 1px solid #8a4a43;
    color: #ffc3bd;
}
QWidget#featureBar {
    background: #132824;
    border-right: 1px solid #264940;
}
QSplitter#mainSplitter::handle {
    background: #264940;
}
QMenu {
    background: #142723;
    border: 1px solid #386b62;
    color: #d8f3ee;
}
QMenu::item:selected,
QPushButton#navButton:checked,
QListWidget#conversationList::item:selected,
QPushButton#settingsTab:checked {
    background: #1d3a35;
    border: 1px solid #4f978b;
    color: #bff8ef;
}
QMenu::separator {
    background: #2f564f;
}
QPushButton#railToggle,
QPushButton#navButton,
QPushButton#settingsTab,
QListWidget#conversationList {
    color: #acd0c8;
}
QPushButton#railToggle:hover,
QPushButton#navButton:hover,
QListWidget#conversationList::item:hover,
QPushButton#settingsTab:hover {
    background: #1b342f;
    color: #bff8ef;
}
QWidget#pageSurface,
QWidget#settingsCard,
QWidget#composerPanel,
QWidget#inputBox {
    background: #162b27;
    border: 1px solid #31574f;
}
QLabel#modelSummary {
    background: #10221f;
    border: 1px solid #2f554e;
    color: #c0ddd7;
}
QTextBrowser,
QTextEdit,
QListWidget,
QLineEdit,
QComboBox {
    background: #0f201d;
    border: 1px solid #335f57;
    color: #ecf8f5;
    selection-background-color: #3fa89b;
    selection-color: #071310;
}
QComboBox QAbstractItemView,
QComboBox QListView {
    background: #0f201d;
    border: 1px solid #335f57;
    color: #ecf8f5;
    selection-background-color: #1f6f68;
    selection-color: #ffffff;
    outline: 0;
}
QComboBox QAbstractItemView::item,
QComboBox QListView::item {
    color: #ecf8f5;
    min-height: 28px;
    padding: 6px 8px;
}
QComboBox QAbstractItemView::item:selected,
QComboBox QListView::item:selected {
    background: #1f6f68;
    color: #ffffff;
}
QComboBox QAbstractItemView::item:disabled,
QComboBox QListView::item:disabled {
    color: #7fa39b;
}
QSplitter#librarySplitter::handle {
    background: #31574f;
}
QScrollArea#chatScroll,
QWidget#chatMessages {
    background: qlineargradient(x1:0, y1:0, x2:1, y2:1, stop:0 #0e1b1a, stop:0.52 #102924, stop:1 #152722);
}
QScrollArea#settingsScroll {
    background: #162b27;
}
QLabel#chatBubbleTextAssistant {
    color: #10231f;
}
QLabel#chatBubbleTextUser {
    color: #f1fbf8;
}
QLabel#chatStatusMessage {
    background: #122622;
    border: 1px solid #31564f;
    color: #bddbd5;
}
QTextBrowser#filePreview {
    background: #10221f;
}
QCheckBox {
    color: #cce8e2;
}
QCheckBox::indicator {
    background: #10221f;
    border: 1px solid #4d7e75;
}
QCheckBox::indicator:checked {
    background: #45b2a5;
    border: 1px solid #45b2a5;
}
QPushButton {
    background: #31968d;
    color: #ffffff;
}
QPushButton:hover {
    background: #3aaea4;
}
QPushButton:disabled {
    background: #49655f;
    color: #b8cbc6;
}
QPushButton#secondaryButton,
QPushButton#uploadButton {
    background: #10221f;
    color: #cdebe5;
    border: 1px solid #345c55;
}
QPushButton#secondaryButton:hover,
QPushButton#uploadButton:hover {
    background: #18342f;
}
QPushButton#contextButton {
    background: #10221f;
    border: 1px solid #4f978b;
    color: #8fe5da;
}
QPushButton#contextButton:hover,
QPushButton#contextButton:checked {
    background: #18342f;
    border: 1px solid #45b2a5;
    color: #a6f1e7;
}
QFrame#uploadPreviewCard {
    background: #10221f;
    border: 1px solid #345c55;
}
QLabel {
    color: #dfefeb;
}
QScrollBar:vertical {
    background: #10201d;
    width: 10px;
}
QScrollBar::handle:vertical {
    background: #3b6960;
    border-radius: 5px;
    min-height: 28px;
}
QScrollBar::add-line:vertical,
QScrollBar::sub-line:vertical {
    height: 0;
}
"""


def normalized_theme_mode(mode: object) -> str:
    value = str(mode or "system").strip().lower()
    return value if value in THEME_LABELS else "system"


def resolved_theme_mode(mode: object) -> str:
    value = normalized_theme_mode(mode)
    if value != "system":
        return value
    return "dark" if system_prefers_dark() else "light"


def system_prefers_dark() -> bool:
    if sys.platform == "win32":
        try:
            import winreg

            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\Microsoft\Windows\CurrentVersion\Themes\Personalize") as key:
                return winreg.QueryValueEx(key, "AppsUseLightTheme")[0] == 0
        except OSError:
            pass
    try:
        from PySide6.QtGui import QPalette
        from PySide6.QtWidgets import QApplication

        app = QApplication.instance()
        return bool(app and app.palette().color(QPalette.ColorRole.Window).lightness() < 128)
    except Exception:
        return False


def chat_style_for_mode(mode: object) -> str:
    return CHAT_STYLE + (DARK_CHAT_STYLE if resolved_theme_mode(mode) == "dark" else "")


def chat_viewport_style_for_mode(mode: object) -> str:
    return "background: #10201d;" if resolved_theme_mode(mode) == "dark" else "background: #fbfffe;"
