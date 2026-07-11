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
    background: #f4faf8;
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
    background: #f7fcfb;
    border-right: 1px solid #d2e5e1;
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
    background: #eef9f6;
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
    border-radius: 12px;
    padding: 9px 10px;
    margin: 3px 0;
    min-height: 24px;
}
QListWidget#conversationList::item:hover {
    background: #f3fbf9;
    color: #1f7069;
}
QListWidget#conversationList::item:selected {
    background: #eaf8f5;
    color: #0b6f68;
    border: 1px solid #66b8ae;
    font-weight: 700;
}
QWidget#conversationItem {
    background: transparent;
}
QLabel#conversationItemTitle {
    color: #496d68;
    font-size: 13px;
    font-weight: 600;
}
QLabel#conversationItemTime {
    color: #71847f;
    font-size: 11px;
}
QLabel#conversationHeading {
    color: #637c77;
    font-size: 12px;
    font-weight: 700;
    padding: 8px 4px 2px 4px;
}
QWidget#pageSurface,
QWidget#settingsCard {
    background: #ffffff;
    border: 1px solid #d9e7e4;
    border-radius: 8px;
}
QWidget#pageSurface {
    border: 0;
    border-radius: 0;
}
QWidget#settingsWorkspace {
    background: #ffffff;
    border: 0;
}
QWidget#settingsWorkspace QLineEdit,
QWidget#settingsWorkspace QComboBox {
    min-height: 38px;
    padding: 0 12px;
}
QComboBox::drop-down {
    border: 0;
    border-left: 1px solid #d7e5e2;
    width: 28px;
    border-top-right-radius: 7px;
    border-bottom-right-radius: 7px;
}
QLabel#settingsNavTitle {
    color: #172520;
    font-size: 20px;
    font-weight: 700;
}
QLabel#settingsPageTitle {
    color: #172520;
    font-size: 26px;
    font-weight: 700;
}
QLabel#settingsPageCaption {
    color: #667b76;
    font-size: 15px;
    padding-top: 3px;
}
QLabel#settingsStatusHeading,
QLabel#settingsSectionTitle,
QLabel#libraryColumnTitle {
    color: #1b302b;
    font-size: 16px;
    font-weight: 700;
}
QLabel#librarySubheading {
    color: #667b76;
    font-size: 12px;
    font-weight: 700;
    padding-top: 4px;
}
QLabel#settingsRowLabel {
    color: #263b36;
    font-size: 14px;
    font-weight: 600;
}
QWidget#connectionStatusPanel {
    background: #fbfefd;
    border: 1px solid #d5e5e2;
    border-radius: 8px;
}
QLabel#connectionState,
QLabel#permissionState {
    color: #14865d;
    font-size: 13px;
    font-weight: 700;
    min-width: 66px;
}
QLabel#connectionPrimary {
    color: #17312c;
    font-size: 16px;
    font-weight: 700;
}
QLabel#connectionDetailLabel {
    color: #71827e;
    font-size: 12px;
}
QLabel#connectionDetailValue {
    color: #334a45;
    font-size: 13px;
}
QLabel#connectionStatusText,
QLabel#settingsInlineStatus {
    background: transparent;
    border: 0;
    color: #506863;
    font-size: 13px;
    line-height: 1.7;
}
QFrame#settingsDivider {
    background: #dce9e6;
    border: 0;
    max-height: 1px;
}
QWidget#permissionModeControl {
    background: #fbfefd;
    border: 1px solid #cbdedb;
    border-radius: 8px;
}
QPushButton#permissionModeFirst,
QPushButton#permissionModeMiddle,
QPushButton#permissionModeLast {
    min-height: 38px;
    background: transparent;
    border: 0;
    border-radius: 0;
    color: #4f655f;
    font-size: 14px;
    font-weight: 600;
    padding: 0 26px;
}
QPushButton#permissionModeFirst,
QPushButton#permissionModeMiddle {
    border-right: 1px solid #d3e2df;
}
QPushButton#permissionModeFirst {
    border-top-left-radius: 7px;
    border-bottom-left-radius: 7px;
}
QPushButton#permissionModeLast {
    border-top-right-radius: 7px;
    border-bottom-right-radius: 7px;
}
QPushButton#permissionModeFirst:hover,
QPushButton#permissionModeMiddle:hover,
QPushButton#permissionModeLast:hover {
    background: #f2faf8;
    color: #147b72;
}
QPushButton#permissionModeFirst:checked,
QPushButton#permissionModeMiddle:checked,
QPushButton#permissionModeLast:checked {
    background: #eef9f6;
    border: 1px solid #27998f;
    color: #117d74;
    font-weight: 700;
}
QCheckBox#permissionToggle {
    min-width: 38px;
    max-width: 38px;
}
QCheckBox#permissionToggle::indicator {
    width: 34px;
    height: 18px;
    border-radius: 9px;
    border: 1px solid #b9cfca;
    background: #c7d1cf;
}
QCheckBox#permissionToggle::indicator:hover {
    border: 1px solid #79bdb4;
}
QCheckBox#permissionToggle::indicator:checked {
    background: #159a78;
    border: 1px solid #159a78;
}
QLabel#permissionWarning {
    background: #fff8f2;
    border: 1px solid #f3dbc7;
    border-radius: 8px;
    color: #c25b32;
    font-size: 13px;
    font-weight: 600;
    padding: 12px 14px;
}
QWidget#libraryColumn {
    border-right: 1px solid #d7e6e3;
    padding-right: 14px;
}
QWidget#libraryPreviewColumn {
    padding-left: 2px;
}
QTreeWidget#libraryDirectoryList,
QTreeWidget#libraryFileList {
    background: transparent;
    border: 0;
    border-top: 1px solid #dce9e6;
    border-radius: 0;
    padding: 4px 0;
}
QTreeWidget#libraryDirectoryList::item,
QTreeWidget#libraryFileList::item {
    border-bottom: 1px solid #e6efed;
    border-radius: 0;
    padding: 10px 8px;
    margin: 0;
}
QTreeWidget#libraryDirectoryList::item:selected,
QTreeWidget#libraryFileList::item:selected {
    background: #ecf8f5;
    color: #0d756e;
}
QTreeWidget#libraryDirectoryList QHeaderView::section,
QTreeWidget#libraryFileList QHeaderView::section {
    background: #fbfefd;
    border: 0;
    border-bottom: 1px solid #dce9e6;
    color: #657974;
    font-size: 12px;
    font-weight: 600;
    padding: 8px 6px;
}
QWidget#libraryFooter {
    border-top: 1px solid #d6e5e2;
}
QLabel#libraryIndexStatus {
    color: #5d716c;
    font-size: 13px;
}
QWidget#composerPanel {
    background: #fbfefd;
    border: 1px solid #d3e4e1;
    border-radius: 8px;
}
QWidget#inputBox {
    background: #fbfefd;
    border: 1px solid #bfded8;
    border-radius: 8px;
}
QWidget#chatPage {
    background: #fbfefd;
    border: 0;
}
QWidget#chatHeader {
    min-height: 52px;
    max-height: 52px;
    background: #fbfefd;
    border-bottom: 1px solid #d9e7e4;
}
QLabel#chatHeaderTitle {
    color: #17312c;
    font-size: 17px;
    font-weight: 700;
}
QLabel#chatHeaderStatus {
    color: #187c70;
    font-size: 13px;
    font-weight: 600;
}
QLabel#chatHeaderModel {
    color: #4e6963;
    font-size: 13px;
    padding-left: 14px;
    border-left: 1px solid #d4e4e0;
}
QComboBox#chatModelSelector {
    background: transparent;
    border: 0;
    border-left: 1px solid #d4e4e0;
    border-radius: 0;
    color: #294f49;
    font-size: 13px;
    font-weight: 600;
    padding: 4px 8px 4px 14px;
}
QComboBox#chatModelSelector:hover,
QComboBox#chatModelSelector:focus {
    color: #0f756d;
}
QWidget#settingsNav {
    background: #ffffff;
    border: 0;
    border-right: 1px solid #d9e7e4;
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
QTreeWidget,
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
QComboBox QAbstractItemView,
QComboBox QListView {
    background: #fbfefd;
    border: 1px solid #c8deda;
    color: #172520;
    selection-background-color: #e5f5f1;
    selection-color: #0f6f68;
    outline: 0;
}
QComboBox QAbstractItemView::item,
QComboBox QListView::item {
    background: #fbfefd;
    color: #172520;
    min-height: 28px;
    padding: 6px 8px;
}
QComboBox QAbstractItemView::item:hover,
QComboBox QAbstractItemView::item:selected,
QComboBox QListView::item:hover,
QComboBox QListView::item:selected {
    background: #e5f5f1;
    color: #0f6f68;
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
    background: #fbfefd;
    border: 0;
    padding: 8px;
}
QScrollArea#settingsScroll {
    background: #ffffff;
    border: 0;
}
QWidget#chatMessages {
    background: #fbfefd;
}
QFrame#chatBubbleAssistant,
QFrame#chatBubbleUser {
    background: transparent;
    border: 0;
}
QLabel#chatBubbleTextAssistant {
    background: transparent;
    border: 0;
    color: #17312c;
    font-size: 15px;
    font-weight: 400;
    padding: 0;
}
QLabel#chatBubbleTextUser {
    background: transparent;
    border: 0;
    color: #17312c;
    font-size: 15px;
    font-weight: 400;
    padding: 0;
}
QLabel#chatBubbleTime {
    background: transparent;
    border: 0;
    color: #6f8984;
    font-size: 10px;
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
QTextEdit#messageInput:focus {
    background: #f4fcfa;
    border-radius: 5px;
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
    border-radius: 8px;
    font-size: 13px;
    font-weight: 700;
    padding: 10px 12px;
    text-align: left;
}
QPushButton#settingsTab:hover {
    background: #f3fbf9;
    color: #1f7069;
}
QPushButton#settingsTab:checked {
    background: #eef9f6;
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
QLabel#conversationItemTitle {
    color: #c4e1da;
}
QLabel#conversationItemTime,
QLabel#chatBubbleTime {
    color: #9bbdb5;
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
QWidget#pageSurface {
    border: 0;
}
QWidget#settingsNav {
    background: #162b27;
    border-right: 1px solid #31574f;
}
QLabel#settingsNavTitle,
QLabel#connectionPrimary {
    color: #edf8f5;
}
QLabel#connectionDetailLabel {
    color: #8caaa3;
}
QLabel#connectionDetailValue {
    color: #d2e7e2;
}
QWidget#settingsWorkspace {
    background: #162b27;
}
QLabel#settingsPageTitle,
QLabel#settingsStatusHeading,
QLabel#settingsSectionTitle,
QLabel#libraryColumnTitle {
    color: #edf8f5;
}
QLabel#settingsPageCaption,
QLabel#librarySubheading {
    color: #a6c3bc;
}
QLabel#settingsRowLabel {
    color: #d6ece7;
}
QWidget#connectionStatusPanel {
    background: #10221f;
    border: 1px solid #31574f;
}
QLabel#connectionState,
QLabel#permissionState {
    color: #8fe5b7;
}
QLabel#connectionStatusText,
QLabel#settingsInlineStatus {
    color: #b6d0ca;
}
QFrame#settingsDivider {
    background: #31574f;
}
QWidget#permissionModeControl {
    background: #10221f;
    border: 1px solid #39695f;
}
QPushButton#permissionModeFirst,
QPushButton#permissionModeMiddle,
QPushButton#permissionModeLast {
    color: #bfd8d2;
    border-right: 1px solid #31574f;
}
QPushButton#permissionModeFirst:hover,
QPushButton#permissionModeMiddle:hover,
QPushButton#permissionModeLast:hover {
    background: #18342f;
    color: #a6f1e7;
}
QPushButton#permissionModeFirst:checked,
QPushButton#permissionModeMiddle:checked,
QPushButton#permissionModeLast:checked {
    background: #1d3a35;
    border: 1px solid #45b2a5;
    color: #a6f1e7;
}
QComboBox::drop-down {
    border-left-color: #335f57;
}
QCheckBox#permissionToggle::indicator {
    background: #49655f;
    border: 1px solid #66887f;
}
QCheckBox#permissionToggle::indicator:checked {
    background: #34a27d;
    border: 1px solid #34a27d;
}
QLabel#permissionWarning {
    background: #34261f;
    border: 1px solid #77533d;
    color: #ffbc91;
}
QWidget#libraryColumn {
    border-right: 1px solid #31574f;
}
QTreeWidget#libraryDirectoryList,
QTreeWidget#libraryFileList {
    border-top: 1px solid #31574f;
}
QTreeWidget#libraryDirectoryList::item,
QTreeWidget#libraryFileList::item {
    border-bottom: 1px solid #294a44;
}
QTreeWidget#libraryDirectoryList::item:selected,
QTreeWidget#libraryFileList::item:selected {
    background: #1d3a35;
    color: #bff8ef;
}
QTreeWidget#libraryDirectoryList QHeaderView::section,
QTreeWidget#libraryFileList QHeaderView::section {
    background: #10221f;
    border-bottom: 1px solid #31574f;
    color: #a9c5be;
}
QWidget#libraryFooter {
    border-top: 1px solid #31574f;
}
QLabel#libraryIndexStatus {
    color: #b2cec7;
}
QWidget#chatPage,
QWidget#chatHeader {
    background: #10201d;
    border-color: #31574f;
}
QLabel#chatHeaderTitle {
    color: #edf8f5;
}
QLabel#chatHeaderStatus {
    color: #8fe5da;
}
QLabel#chatHeaderModel {
    color: #b5d5ce;
    border-left-color: #31574f;
}
QComboBox#chatModelSelector {
    border-left-color: #31574f;
    color: #c6e5de;
}
QComboBox#chatModelSelector:hover,
QComboBox#chatModelSelector:focus {
    color: #9ce5dc;
}
QLabel#modelSummary {
    background: #10221f;
    border: 1px solid #2f554e;
    color: #c0ddd7;
}
QTextBrowser,
QTextEdit,
QListWidget,
QTreeWidget,
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
    background: #10201d;
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
QTextEdit#messageInput:focus {
    background: #18342f;
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


def combo_popup_style(dark_theme: bool) -> str:
    if dark_theme:
        return """
QAbstractItemView { background: #0f201d; border: 1px solid #335f57; color: #ecf8f5; outline: 0; }
QAbstractItemView::item { background: #0f201d; color: #ecf8f5; min-height: 28px; padding: 6px 8px; }
QAbstractItemView::item:hover, QAbstractItemView::item:selected { background: #1f6f68; color: #ffffff; }
"""
    return """
QAbstractItemView { background: #fbfefd; border: 1px solid #c8deda; color: #172520; outline: 0; }
QAbstractItemView::item { background: #fbfefd; color: #172520; min-height: 28px; padding: 6px 8px; }
QAbstractItemView::item:hover, QAbstractItemView::item:selected { background: #e5f5f1; color: #0f6f68; }
"""


def chat_viewport_style_for_mode(mode: object) -> str:
    return "background: #10201d;" if resolved_theme_mode(mode) == "dark" else "background: #fbfffe;"
