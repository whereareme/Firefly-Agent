"""Settings panels for the Firefly desktop window."""

from __future__ import annotations

import html
import json
import shutil
import urllib.error
import urllib.request
from collections.abc import Callable
from pathlib import Path
from typing import Any

from PySide6.QtCore import QThread, Qt, QUrl
from PySide6.QtGui import QDesktopServices, QIntValidator
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFileDialog,
    QFormLayout,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QScrollArea,
    QSplitter,
    QStackedWidget,
    QTextBrowser,
    QVBoxLayout,
    QWidget,
)

from openharness.auth.manager import AuthManager
from openharness.auth.storage import load_credential
from openharness.config.settings import ProviderProfile, credential_storage_provider_name, resolve_auth_env_value
from openharness.tools import create_default_tool_registry

from firefly.autostart import autostart_supported, is_autostart_enabled, set_autostart
from firefly.context import (
    is_context_candidate,
    int_config,
    library_roots,
    permission_mode_value,
    read_file_sample,
    skill_registry_summary,
    skills_root,
)
from firefly.desktop.styles import THEME_LABELS, normalized_theme_mode
from firefly.desktop.workers import TaskWorker
from firefly.desktop_tools import firefly_desktop_tools
from firefly.library_index import library_index_summary, refresh_library_index
from firefly.memory import create_everos_client, memory_status_summary
from firefly.workspace import save_config

IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp"}


def fetch_openai_compatible_models(base_url: str, api_key: str = "", timeout: float = 8) -> list[str]:
    if not base_url:
        raise ValueError("接口地址为空")
    headers = {"Accept": "application/json"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    request = urllib.request.Request(f"{base_url.rstrip('/')}/models", headers=headers)
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as error:
        raise RuntimeError(f"HTTP {error.code}") from error
    data = payload.get("data", []) if isinstance(payload, dict) else []
    models: list[str] = []
    for item in data:
        value = item.get("id") if isinstance(item, dict) else item
        if value:
            models.append(str(value))
    return models


def profile_api_key(profile_name: str, profile: ProviderProfile, typed_key: str = "") -> str:
    if typed_key:
        return typed_key
    env_value = resolve_auth_env_value(profile.auth_source)
    if env_value:
        return env_value[1]
    return load_credential(credential_storage_provider_name(profile_name, profile), "api_key") or ""


def is_image_generation_model(model: str) -> bool:
    lowered = model.lower()
    return "image" in lowered or lowered.startswith("gpt-image")


class SettingsPanelMixin:
    def start_settings_task(
        self,
        key: str,
        task: Callable[[], Any],
        on_finished: Callable[[object], None],
        on_failed: Callable[[str], None],
    ) -> bool:
        tasks = getattr(self, "_settings_tasks", None)
        if tasks is None:
            tasks = {}
            self._settings_tasks = tasks
        if key in tasks:
            return False
        thread = QThread(self)
        worker = TaskWorker(task)
        tasks[key] = (thread, worker)
        worker.moveToThread(thread)
        thread.started.connect(worker.run)
        worker.finished.connect(on_finished, Qt.QueuedConnection)
        worker.failed.connect(on_failed, Qt.QueuedConnection)
        worker.finished.connect(worker.deleteLater)
        worker.failed.connect(worker.deleteLater)
        worker.finished.connect(thread.quit)
        worker.failed.connect(thread.quit)
        thread.finished.connect(thread.deleteLater)
        thread.finished.connect(lambda task_key=key: tasks.pop(task_key, None))
        thread.start()
        return True

    def build_settings_page(self) -> QWidget:
        page = QWidget(self)
        page.setObjectName("pageSurface")
        layout = QVBoxLayout(page)
        layout.setContentsMargins(18, 16, 18, 18)
        layout.setSpacing(14)
        title = QLabel("设置", page)
        title.setObjectName("pageTitle")
        caption = QLabel("模型、资料、联网、记忆、技能和系统权限都在这里管理。", page)
        caption.setObjectName("sectionCaption")
        layout.addWidget(title)
        layout.addWidget(caption)
        body = QHBoxLayout()
        body.setSpacing(14)
        body.addWidget(self.build_settings_nav(), 0)
        self.settings_stack = QStackedWidget(page)
        self.settings_stack.addWidget(self.build_model_panel())
        self.settings_stack.addWidget(self.build_files_panel())
        self.settings_stack.addWidget(self.build_web_search_panel())
        self.settings_stack.addWidget(self.build_memory_panel())
        self.settings_stack.addWidget(self.build_skills_panel())
        self.settings_stack.addWidget(self.build_appearance_panel())
        self.settings_stack.addWidget(self.build_computer_control_panel())
        body.addWidget(self.settings_stack, 1)
        layout.addLayout(body, 1)
        self.switch_settings_page(0)
        return page

    def build_settings_nav(self) -> QWidget:
        nav = QWidget(self)
        nav.setObjectName("settingsNav")
        nav.setFixedWidth(162)
        layout = QVBoxLayout(nav)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(8)
        self.model_settings_button = QPushButton("回应核心", nav)
        self.files_settings_button = QPushButton("资料舱", nav)
        self.web_search_settings_button = QPushButton("星网检索", nav)
        self.memory_settings_button = QPushButton("记忆回廊", nav)
        self.skills_settings_button = QPushButton("技能库", nav)
        self.appearance_settings_button = QPushButton("外观", nav)
        self.computer_control_settings_button = QPushButton("行动权限", nav)
        self.settings_buttons = [
            self.model_settings_button,
            self.files_settings_button,
            self.web_search_settings_button,
            self.memory_settings_button,
            self.skills_settings_button,
            self.appearance_settings_button,
            self.computer_control_settings_button,
        ]
        for index, button in enumerate(self.settings_buttons):
            button.setObjectName("settingsTab")
            button.setCheckable(True)
            button.setCursor(Qt.PointingHandCursor)
            button.setMinimumHeight(42)
            button.clicked.connect(lambda _checked=False, value=index: self.switch_settings_page(value))
            layout.addWidget(button)
        layout.addStretch(1)
        return nav

    def switch_settings_page(self, index: int) -> None:
        self.settings_stack.setCurrentIndex(index)
        for row, button in enumerate(self.settings_buttons):
            button.setChecked(row == index)

    def build_model_panel(self) -> QWidget:
        panel = QWidget(self)
        panel.setObjectName("settingsCard")
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(18, 16, 18, 18)
        layout.setSpacing(12)
        title = QLabel("回应核心", panel)
        title.setObjectName("sectionTitle")
        caption = QLabel("配置流萤调用的模型接口，保存后会立即应用到当前会话。", panel)
        caption.setObjectName("sectionCaption")
        layout.addWidget(title)
        layout.addWidget(caption)

        statuses = self.openharness_profile_statuses()
        self.provider_input = QComboBox(panel)
        for name, info in statuses.items():
            self.provider_input.addItem(f"{name} · {info.get('label')}", name)
        active_profile = str(self.config.get("provider_profile") or self.openharness_active_profile() or "claude-api")
        profile_index = self.provider_input.findData(active_profile)
        if profile_index >= 0:
            self.provider_input.setCurrentIndex(profile_index)
        self.base_url_input = QLineEdit(self.current_profile_base_url(), panel)
        self.model_input = QComboBox(panel)
        self.model_input.setEditable(True)
        model = str(self.config.get("model") or self.current_profile_model() or "")
        self.model_input.addItem(model)
        self.model_input.setCurrentText(model)
        self.image_model_input = QComboBox(panel)
        self.image_model_input.setEditable(True)
        image_model = str(self.config.get("image_generation_model") or "")
        self.populate_image_model_input(self.current_profile_models(), image_model)
        self.api_key_input = QLineEdit("", panel)
        self.api_key_input.setPlaceholderText("留空则不修改 OpenHarness 已保存密钥")
        self.api_key_input.setEchoMode(QLineEdit.Password)
        form = QFormLayout()
        form.addRow("OpenHarness Profile", self.provider_input)
        form.addRow("接口地址", self.base_url_input)
        form.addRow("模型", self.model_input)
        form.addRow("生图模型", self.image_model_input)
        form.addRow("密钥", self.api_key_input)
        layout.addLayout(form)

        row = QHBoxLayout()
        self.load_models_button = QPushButton("同步模型列表", panel)
        self.load_models_button.setObjectName("secondaryButton")
        self.load_models_button.clicked.connect(self.load_models_from_api)
        self.llm_test_button = QPushButton("测试连接", panel)
        self.llm_test_button.setObjectName("secondaryButton")
        self.llm_test_button.clicked.connect(self.test_llm_connection)
        save_button = QPushButton("保存并应用", panel)
        save_button.clicked.connect(self.save_model_settings)
        row.addWidget(self.load_models_button)
        row.addWidget(self.llm_test_button)
        row.addStretch(1)
        row.addWidget(save_button)
        layout.addLayout(row)
        self.model_status_label = QLabel(self.model_summary(), panel)
        self.model_status_label.setObjectName("modelSummary")
        self.model_status_label.setWordWrap(True)
        layout.addWidget(self.model_status_label)
        layout.addStretch(1)
        return panel

    def build_web_search_panel(self) -> QWidget:
        panel = QWidget(self)
        panel.setObjectName("settingsCard")
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(18, 16, 18, 18)
        layout.setSpacing(12)
        title = QLabel("星网检索", panel)
        title.setObjectName("sectionTitle")
        caption = QLabel("需要最新消息、官网、价格、版本或攻略时，流萤会接入网络检索补全外部事实。", panel)
        caption.setObjectName("sectionCaption")
        layout.addWidget(title)
        layout.addWidget(caption)
        self.web_search_enabled_check = QCheckBox("启用星网检索", panel)
        self.web_search_enabled_check.setChecked(bool(self.config.get("web_search_enabled", False)))
        self.web_search_auto_check = QCheckBox("按问题自动判断是否检索", panel)
        self.web_search_auto_check.setChecked(bool(self.config.get("web_search_auto", True)))
        self.web_fetch_enabled_check = QCheckBox("自动抓取消息里的网页链接", panel)
        self.web_fetch_enabled_check.setChecked(bool(self.config.get("web_fetch_enabled", True)))
        self.web_search_max_results_input = QLineEdit(str(self.config.get("web_search_max_results") or 5), panel)
        self.web_search_max_results_input.setValidator(QIntValidator(1, 10, self.web_search_max_results_input))
        self.web_fetch_max_chars_input = QLineEdit(str(self.config.get("web_fetch_max_chars") or 6000), panel)
        self.web_fetch_max_chars_input.setValidator(QIntValidator(500, 50000, self.web_fetch_max_chars_input))
        self.web_search_url_input = QLineEdit(str(self.config.get("web_search_url") or ""), panel)
        self.web_search_url_input.setPlaceholderText("可选：自定义 OpenHarness web_search HTML endpoint")
        form = QFormLayout()
        form.addRow("", self.web_search_enabled_check)
        form.addRow("", self.web_search_auto_check)
        form.addRow("", self.web_fetch_enabled_check)
        form.addRow("结果数量", self.web_search_max_results_input)
        form.addRow("网页字符上限", self.web_fetch_max_chars_input)
        form.addRow("搜索端点", self.web_search_url_input)
        layout.addLayout(form)
        save_button = QPushButton("保存并应用", panel)
        save_button.clicked.connect(self.save_web_search_settings)
        layout.addWidget(save_button, alignment=Qt.AlignLeft)
        self.web_search_status_label = QLabel(self.web_search_summary(), panel)
        self.web_search_status_label.setObjectName("modelSummary")
        self.web_search_status_label.setWordWrap(True)
        layout.addWidget(self.web_search_status_label)
        layout.addStretch(1)
        return panel

    def web_search_summary(self) -> str:
        state = "已开启" if bool(self.config.get("web_search_enabled", False)) else "已关闭"
        auto = "自动判断" if bool(self.config.get("web_search_auto", True)) else "每次联网请求都检索"
        fetch = "抓取链接" if bool(self.config.get("web_fetch_enabled", True)) else "不抓取链接"
        return f"状态: {state}\n模式: {auto}；{fetch}\n结果数量: {self.config.get('web_search_max_results') or 5}"

    def save_web_search_settings(self) -> None:
        self.config = {
            **self.config,
            "web_search_enabled": self.web_search_enabled_check.isChecked(),
            "web_search_auto": self.web_search_auto_check.isChecked(),
            "web_fetch_enabled": self.web_fetch_enabled_check.isChecked(),
            "web_search_max_results": self.int_input_value(self.web_search_max_results_input, 5, 1, 10),
            "web_fetch_max_chars": self.int_input_value(self.web_fetch_max_chars_input, 6000, 500, 50000),
            "web_search_url": self.web_search_url_input.text().strip(),
        }
        save_config(self.config, self.workspace)
        self.web_search_status_label.setText(f"{self.web_search_summary()}\n已保存并应用。")

    def int_input_value(self, input_widget: QLineEdit, default: int, minimum: int, maximum: int) -> int:
        try:
            value = int(input_widget.text().strip())
        except ValueError:
            value = default
        return max(minimum, min(maximum, value))

    def build_memory_panel(self) -> QWidget:
        scroll = QScrollArea(self)
        scroll.setObjectName("settingsScroll")
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        panel = QWidget(scroll)
        panel.setObjectName("settingsCard")
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(18, 16, 18, 28)
        layout.setSpacing(16)
        title = QLabel("记忆回廊", panel)
        title.setObjectName("sectionTitle")
        caption = QLabel("管理长期记忆和跨对话承接；连接本机 EverOS，失败后按配置降级。", panel)
        caption.setObjectName("sectionCaption")
        layout.addWidget(title)
        layout.addWidget(caption)

        self.memory_enabled_check = QCheckBox("启用长期记忆", panel)
        self.memory_enabled_check.setChecked(bool(self.config.get("memory_enabled", False)))
        self.everos_memory_enabled_check = QCheckBox("接入 EverOS", panel)
        self.everos_memory_enabled_check.setChecked(bool(self.config.get("everos_memory_enabled", self.config.get("memory_enabled", False))))
        self.openharness_memdir_enabled_check = QCheckBox("接入 OpenHarness memdir", panel)
        self.openharness_memdir_enabled_check.setChecked(bool(self.config.get("openharness_memdir_enabled", self.config.get("memory_enabled", False))))
        self.openharness_session_memory_enabled_check = QCheckBox("接入 OpenHarness session memory", panel)
        self.openharness_session_memory_enabled_check.setChecked(bool(self.config.get("openharness_session_memory_enabled", self.config.get("memory_enabled", False))))
        self.memory_context_link_check = QCheckBox("自动承接上下文", panel)
        self.memory_context_link_check.setToolTip("用上一段对话摘要作为新对话背景，不复制完整聊天记录")
        self.memory_context_link_check.setChecked(bool(self.config.get("memory_context_link_enabled", True)))
        self.memory_base_url_input = QLineEdit(str(self.config.get("memory_base_url") or "http://127.0.0.1:8000"), panel)
        self.memory_user_id_input = QLineEdit(str(self.config.get("memory_user_id") or "firefly_user"), panel)
        self.memory_project_id_input = QLineEdit(str(self.config.get("memory_project_id") or "default"), panel)
        self.openharness_memory_cwd_input = QLineEdit(str(self.config.get("openharness_memory_cwd") or self.workspace), panel)
        self.openharness_session_id_input = QLineEdit(str(self.config.get("openharness_session_id") or "firefly"), panel)
        self.memory_method_input = QComboBox(panel)
        self.memory_method_input.addItems(["agentic", "hybrid", "vector"])
        self.memory_method_input.setCurrentText(str(self.config.get("memory_method") or "agentic"))
        self.memory_fallback_input = QComboBox(panel)
        self.memory_fallback_input.addItems(["keyword", ""])
        self.memory_fallback_input.setCurrentText(str(self.config.get("memory_fallback_method") or "keyword"))

        form = QFormLayout()
        form.addRow("", self.memory_enabled_check)
        form.addRow("", self.everos_memory_enabled_check)
        form.addRow("", self.openharness_memdir_enabled_check)
        form.addRow("", self.openharness_session_memory_enabled_check)
        form.addRow("", self.memory_context_link_check)
        form.addRow("EverOS 服务", self.memory_base_url_input)
        form.addRow("EverOS 用户", self.memory_user_id_input)
        form.addRow("EverOS 项目", self.memory_project_id_input)
        form.addRow("EverOS 主回忆", self.memory_method_input)
        form.addRow("EverOS 备用", self.memory_fallback_input)
        form.addRow("OH 项目路径", self.openharness_memory_cwd_input)
        form.addRow("OH 会话 ID", self.openharness_session_id_input)
        layout.addLayout(form)

        action_row = QHBoxLayout()
        action_row.setContentsMargins(0, 0, 0, 0)
        self.everos_health_button = QPushButton("测试 EverOS", panel)
        self.everos_health_button.setObjectName("secondaryButton")
        self.everos_health_button.clicked.connect(self.test_everos_memory)
        save_button = QPushButton("保存并应用", panel)
        save_button.clicked.connect(self.save_memory_settings)
        action_row.addWidget(self.everos_health_button)
        action_row.addStretch(1)
        action_row.addWidget(save_button)
        layout.addLayout(action_row)
        self.memory_status_label = QLabel(self.memory_summary(), panel)
        self.memory_status_label.setObjectName("modelSummary")
        self.memory_status_label.setWordWrap(True)
        layout.addWidget(self.memory_status_label)
        scroll.setWidget(panel)
        return scroll

    def memory_summary(self) -> str:
        return memory_status_summary(self.config, self.workspace, self.openharness_memory_cwd_input.text().strip() if hasattr(self, "openharness_memory_cwd_input") else None)

    def save_memory_settings(self) -> None:
        self.config = {
            **self.config,
            "memory_enabled": self.memory_enabled_check.isChecked(),
            "memory_context_link_enabled": self.memory_context_link_check.isChecked(),
            "everos_memory_enabled": self.everos_memory_enabled_check.isChecked(),
            "openharness_memdir_enabled": self.openharness_memdir_enabled_check.isChecked(),
            "openharness_session_memory_enabled": self.openharness_session_memory_enabled_check.isChecked(),
            "memory_base_url": self.memory_base_url_input.text().strip() or "http://127.0.0.1:8000",
            "memory_user_id": self.memory_user_id_input.text().strip() or "firefly_user",
            "memory_project_id": self.memory_project_id_input.text().strip() or "default",
            "memory_method": self.memory_method_input.currentText().strip() or "agentic",
            "memory_fallback_method": self.memory_fallback_input.currentText().strip(),
            "openharness_memory_cwd": self.openharness_memory_cwd_input.text().strip() or str(self.workspace),
            "openharness_session_id": self.openharness_session_id_input.text().strip() or "firefly",
        }
        save_config(self.config, self.workspace)
        self.memory_status_label.setText(f"{self.memory_summary()}\n已保存并应用。")

    def test_everos_memory(self) -> None:
        self.save_memory_settings()
        config = dict(self.config)
        workspace = self.workspace
        self.everos_health_button.setEnabled(False)
        self.memory_status_label.setText(f"{self.memory_summary()}\n正在测试 EverOS...")
        started = self.start_settings_task(
            "everos_health",
            lambda: create_everos_client(config, workspace).health(timeout_sec=1),
            self.finish_everos_memory_test,
            self.fail_everos_memory_test,
        )
        if not started:
            self.everos_health_button.setEnabled(True)

    def finish_everos_memory_test(self, result: object) -> None:
        ok, status = result if isinstance(result, tuple) and len(result) == 2 else (False, "invalid response")
        state = "EverOS 可访问" if ok else "EverOS 未连通"
        self.memory_status_label.setText(f"{self.memory_summary()}\n{state}: {status}")
        self.everos_health_button.setEnabled(True)

    def fail_everos_memory_test(self, error: str) -> None:
        self.memory_status_label.setText(f"{self.memory_summary()}\nEverOS 测试失败: {error}")
        self.everos_health_button.setEnabled(True)

    def build_skills_panel(self) -> QWidget:
        panel = QWidget(self)
        panel.setObjectName("settingsCard")
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(20, 18, 20, 18)
        layout.setSpacing(10)

        title = QLabel("技能库", panel)
        title.setObjectName("skillPageTitle")
        self.skills_enabled_check = QCheckBox("启用 OpenHarness Skills", panel)
        self.skills_enabled_check.setChecked(bool(self.config.get("skills_enabled", False)))
        header_row = QHBoxLayout()
        header_row.setContentsMargins(0, 0, 0, 0)
        header_row.setSpacing(12)
        header_row.addWidget(title)
        header_row.addStretch(1)
        header_row.addWidget(self.skills_enabled_check)
        layout.addLayout(header_row)

        self.skills_root_input = QLineEdit(str(skills_root(self.config, self.workspace)), panel)
        save_button = QPushButton("保存并应用", panel)
        save_button.clicked.connect(self.save_skills_settings)
        root_row = QHBoxLayout()
        root_row.setContentsMargins(0, 0, 0, 0)
        root_row.setSpacing(12)
        root_row.addWidget(self.skills_root_input, 1)
        root_row.addWidget(save_button)
        layout.addLayout(root_row)

        action_row = QHBoxLayout()
        action_row.setContentsMargins(0, 0, 0, 0)
        action_row.setSpacing(12)
        import_file_button = QPushButton("导入 SKILL.md", panel)
        import_file_button.setObjectName("secondaryButton")
        import_file_button.clicked.connect(self.import_skill_file)
        import_folder_button = QPushButton("导入文件夹", panel)
        import_folder_button.clicked.connect(self.import_skill_folder)
        refresh_button = QPushButton("刷新", panel)
        refresh_button.setObjectName("secondaryButton")
        refresh_button.clicked.connect(self.refresh_skills_status)
        open_button = QPushButton("打开目录", panel)
        open_button.setObjectName("secondaryButton")
        open_button.clicked.connect(self.open_skills_directory)
        for button in (import_file_button, import_folder_button, refresh_button, open_button):
            action_row.addWidget(button, 1)
        layout.addLayout(action_row)

        self.skill_status_label = QLabel(self.skills_summary(), panel)
        self.skill_status_label.setObjectName("modelSummary")
        self.skill_status_label.setWordWrap(True)
        layout.addWidget(self.skill_status_label)
        layout.addStretch(1)
        return panel

    def skills_summary(self) -> str:
        return skill_registry_summary(self.config, self.workspace, self.runtime.cwd)

    def save_skills_settings(self) -> None:
        next_config = {
            **self.config,
            "skills_enabled": self.skills_enabled_check.isChecked(),
            "skills_root": self.skills_root_input.text().strip(),
        }
        root = skills_root(next_config, self.workspace)
        self.config = {**next_config, "skills_root": str(root)}
        self.skills_root_input.setText(str(root))
        root.mkdir(parents=True, exist_ok=True)
        save_config(self.config, self.workspace)
        self.skill_status_label.setText(f"{self.skills_summary()}\n已保存并应用。")

    def refresh_skills_status(self) -> None:
        self.save_skills_settings()
        self.skill_status_label.setText(f"{self.skills_summary()}\n已刷新。")

    def open_skills_directory(self) -> None:
        self.save_skills_settings()
        root = skills_root(self.config, self.workspace)
        root.mkdir(parents=True, exist_ok=True)
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(root)))
        self.skill_status_label.setText(f"{self.skills_summary()}\n目录已打开。")

    def import_skill_file(self) -> None:
        self.save_skills_settings()
        file_path, _selected = QFileDialog.getOpenFileName(self, "选择 SKILL.md", str(Path.home()), "Skill Markdown (SKILL.md *.md)")
        if not file_path:
            return
        source = Path(file_path)
        target_dir = skills_root(self.config, self.workspace) / source.stem
        target_dir.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, target_dir / "SKILL.md")
        self.refresh_skills_status()

    def import_skill_folder(self) -> None:
        self.save_skills_settings()
        folder = QFileDialog.getExistingDirectory(self, "选择技能文件夹", str(Path.home()))
        if not folder:
            return
        source = Path(folder)
        if not (source / "SKILL.md").exists():
            self.skill_status_label.setText(f"{self.skills_summary()}\n选择的文件夹里没有 SKILL.md。")
            return
        target = skills_root(self.config, self.workspace) / source.name
        if target.exists():
            self.skill_status_label.setText(f"{self.skills_summary()}\n目标目录已存在：{target}")
            return
        shutil.copytree(source, target)
        self.refresh_skills_status()

    def build_appearance_panel(self) -> QWidget:
        panel = QWidget(self)
        panel.setObjectName("settingsCard")
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(18, 16, 18, 18)
        layout.setSpacing(12)

        title = QLabel("外观", panel)
        title.setObjectName("sectionTitle")
        caption = QLabel("选择聊天窗口主题和星火旋律曲库。", panel)
        caption.setObjectName("sectionCaption")
        layout.addWidget(title)
        layout.addWidget(caption)

        self.theme_mode_input = QComboBox(panel)
        for value, label in THEME_LABELS.items():
            self.theme_mode_input.addItem(label, value)
        index = self.theme_mode_input.findData(normalized_theme_mode(self.config.get("theme_mode")))
        self.theme_mode_input.setCurrentIndex(max(index, 0))
        self.starfire_music_dir_input = QLineEdit(str(self.config.get("starfire_music_dir") or ""), panel)
        self.starfire_music_dir_input.setPlaceholderText("留空只使用内置曲目")
        music_dir_button = QPushButton("选择目录", panel)
        music_dir_button.setObjectName("secondaryButton")
        music_dir_button.clicked.connect(self.choose_starfire_music_dir)
        music_dir_row = QHBoxLayout()
        music_dir_row.addWidget(self.starfire_music_dir_input, 1)
        music_dir_row.addWidget(music_dir_button)

        form = QFormLayout()
        form.addRow("主题", self.theme_mode_input)
        form.addRow("星火旋律曲库", music_dir_row)
        layout.addLayout(form)

        save_button = QPushButton("保存并应用", panel)
        save_button.clicked.connect(self.save_appearance_settings)
        layout.addWidget(save_button, alignment=Qt.AlignLeft)

        self.appearance_status_label = QLabel(self.appearance_summary(), panel)
        self.appearance_status_label.setObjectName("modelSummary")
        layout.addWidget(self.appearance_status_label)
        layout.addStretch(1)
        return panel

    def appearance_summary(self) -> str:
        mode = normalized_theme_mode(self.config.get("theme_mode"))
        music_dir = str(self.config.get("starfire_music_dir") or "").strip() or "未选择"
        return f"当前主题: {THEME_LABELS[mode]}\n星火旋律曲库: {music_dir}（始终包含内置曲目）"

    def save_appearance_settings(self) -> None:
        self.config = {
            **self.config,
            "theme_mode": self.theme_mode_input.currentData() or "system",
            "starfire_music_dir": self.starfire_music_dir_input.text().strip(),
        }
        save_config(self.config, self.workspace)
        self.apply_theme()
        self.appearance_status_label.setText(f"{self.appearance_summary()}\n已保存并应用。")

    def choose_starfire_music_dir(self) -> None:
        folder = QFileDialog.getExistingDirectory(self, "选择星火旋律曲库", self.starfire_music_dir_input.text().strip() or str(Path.home()))
        if folder:
            self.starfire_music_dir_input.setText(folder)

    def build_computer_control_panel(self) -> QWidget:
        scroll = QScrollArea(self)
        scroll.setObjectName("settingsScroll")
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        panel = QWidget(scroll)
        panel.setObjectName("settingsCard")
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(18, 16, 18, 28)
        layout.setSpacing(18)

        title = QLabel("行动权限", panel)
        title.setObjectName("sectionTitle")
        caption = QLabel("配置 OpenHarness 的工具权限和 sandbox。", panel)
        caption.setObjectName("sectionCaption")
        layout.addWidget(title)
        layout.addWidget(caption)

        self.permission_mode_input = QComboBox(panel)
        self.permission_mode_input.addItems(["default", "plan", "full_auto"])
        self.permission_mode_input.setCurrentText(permission_mode_value(self.config))
        self.sandbox_enabled_check = QCheckBox("启用 OpenHarness sandbox", panel)
        self.sandbox_enabled_check.setChecked(bool(self.config.get("sandbox_enabled", False)))
        self.sandbox_enabled_check.stateChanged.connect(self.update_computer_control_options)
        self.sandbox_backend_input = QComboBox(panel)
        self.sandbox_backend_input.addItems(["srt", "docker"])
        backend = str(self.config.get("sandbox_backend") or "srt")
        self.sandbox_backend_input.setCurrentText(backend if backend in {"srt", "docker"} else "srt")
        self.sandbox_fail_check = QCheckBox("sandbox 不可用时中止工具执行", panel)
        self.sandbox_fail_check.setChecked(bool(self.config.get("sandbox_fail_if_unavailable", False)))
        self.desktop_control_enabled_check = QCheckBox("启用 Firefly 电脑操控工具", panel)
        self.desktop_control_enabled_check.setChecked(bool(self.config.get("desktop_control_enabled", False)))
        self.firefly_watch_enabled_check = QCheckBox("启用萤火巡望", panel)
        self.firefly_watch_enabled_check.setToolTip("按间隔读取当前窗口截图，让流萤通过 Live2D 气泡轻量互动")
        self.firefly_watch_enabled_check.setChecked(bool(self.config.get("firefly_watch_enabled", False)))
        self.firefly_watch_interval_input = QLineEdit(str(self.config.get("firefly_watch_interval_sec") or 300), panel)
        self.firefly_watch_interval_input.setValidator(QIntValidator(30, 86400, self.firefly_watch_interval_input))
        self.chat_window_context_enabled_check = QCheckBox("启用临场感知", panel)
        self.chat_window_context_enabled_check.setToolTip("聊天发送时自动附带当前窗口截图和窗口标题")
        self.chat_window_context_enabled_check.setChecked(bool(self.config.get("chat_window_context_enabled", False)))
        self.autostart_enabled_check = QCheckBox("开机自启 Firefly", panel)
        self.autostart_enabled_check.setChecked(is_autostart_enabled() if autostart_supported() else False)
        self.autostart_enabled_check.setEnabled(autostart_supported())

        permission_title = QLabel("OpenHarness 权限", panel)
        permission_title.setObjectName("sectionTitle")
        layout.addWidget(permission_title)
        permission_form = QFormLayout()
        permission_form.setVerticalSpacing(10)
        permission_form.addRow("权限模式", self.permission_mode_input)
        permission_form.addRow("", self.sandbox_enabled_check)
        permission_form.addRow("sandbox 后端", self.sandbox_backend_input)
        permission_form.addRow("", self.sandbox_fail_check)
        layout.addLayout(permission_form)

        desktop_title = QLabel("桌面能力", panel)
        desktop_title.setObjectName("sectionTitle")
        layout.addWidget(desktop_title)
        layout.addWidget(self.desktop_control_enabled_check)

        interaction_title = QLabel("流萤互动", panel)
        interaction_title.setObjectName("sectionTitle")
        layout.addWidget(interaction_title)
        interaction_form = QFormLayout()
        interaction_form.setVerticalSpacing(10)
        interaction_form.addRow("", self.firefly_watch_enabled_check)
        interaction_form.addRow("巡望间隔（秒）", self.firefly_watch_interval_input)
        interaction_form.addRow("", self.chat_window_context_enabled_check)
        layout.addLayout(interaction_form)

        system_title = QLabel("系统", panel)
        system_title.setObjectName("sectionTitle")
        layout.addWidget(system_title)
        layout.addWidget(self.autostart_enabled_check)

        save_button = QPushButton("保存并应用", panel)
        save_button.clicked.connect(self.save_computer_control_settings)
        layout.addWidget(save_button, alignment=Qt.AlignLeft)

        self.computer_control_status_label = QLabel(self.computer_control_summary(), panel)
        self.computer_control_status_label.setObjectName("modelSummary")
        self.computer_control_status_label.setWordWrap(True)
        layout.addWidget(self.computer_control_status_label)
        layout.addStretch(1)
        self.update_computer_control_options()
        scroll.setWidget(panel)
        return scroll

    def computer_control_summary(self) -> str:
        sandbox_state = "已开启" if bool(self.config.get("sandbox_enabled", False)) else "已关闭"
        tools = self.openharness_tool_names()
        if bool(self.config.get("desktop_control_enabled", False)):
            tools = sorted({*tools, *(tool.name for tool in firefly_desktop_tools(self.config, self.workspace))})
        desktop_tools = [name for name in tools if name.startswith("desktop_")]
        file_tools = [name for name in ("read_file", "write_file", "edit_file") if name in tools]
        tool_preview = ", ".join(tools[:12]) if tools else "未加载"
        desktop_state = ", ".join(desktop_tools) if desktop_tools else "未发现"
        desktop_enabled = "已开启" if bool(self.config.get("desktop_control_enabled", False)) else "已关闭"
        watch_state = "已开启" if bool(self.config.get("firefly_watch_enabled", False)) else "已关闭"
        context_state = "已开启" if bool(self.config.get("chat_window_context_enabled", False)) else "已关闭"
        autostart_state = "不支持" if not autostart_supported() else ("已开启" if is_autostart_enabled() else "已关闭")
        file_state = ", ".join(file_tools) if file_tools else "未发现"
        return (
            f"OpenHarness 权限模式: {permission_mode_value(self.config)}\n"
            f"sandbox: {sandbox_state} ({self.config.get('sandbox_backend') or 'srt'})\n"
            f"Firefly 电脑操控: {desktop_enabled}\n"
            f"萤火巡望: {watch_state}，间隔 {self.config.get('firefly_watch_interval_sec') or 300} 秒\n"
            f"临场感知: {context_state}\n"
            f"开机自启: {autostart_state}\n"
            f"OpenHarness 工具: {tool_preview}\n"
            f"文件工具: {file_state}\n"
            f"桌面操控工具: {desktop_state}"
        )

    def openharness_tool_names(self) -> list[str]:
        try:
            registry = create_default_tool_registry()
            return sorted(tool.name for tool in registry.list_tools())
        except Exception:
            return []

    def update_computer_control_options(self) -> None:
        enabled = self.sandbox_enabled_check.isChecked()
        self.sandbox_backend_input.setEnabled(enabled)
        self.sandbox_fail_check.setEnabled(enabled)
        if not enabled:
            self.sandbox_fail_check.setChecked(False)

    def save_computer_control_settings(self) -> None:
        try:
            if autostart_supported():
                set_autostart(self.autostart_enabled_check.isChecked(), self.runtime.cwd or Path.cwd())
        except (OSError, RuntimeError) as error:
            self.computer_control_status_label.setText(f"{self.computer_control_summary()}\n{error}")
            return
        self.config = {
            **self.config,
            "permission_mode": self.permission_mode_input.currentText().strip() or "default",
            "sandbox_enabled": self.sandbox_enabled_check.isChecked(),
            "sandbox_backend": self.sandbox_backend_input.currentText().strip() or "srt",
            "sandbox_fail_if_unavailable": self.sandbox_enabled_check.isChecked() and self.sandbox_fail_check.isChecked(),
            "desktop_control_enabled": self.desktop_control_enabled_check.isChecked(),
            "firefly_watch_enabled": self.firefly_watch_enabled_check.isChecked(),
            "firefly_watch_interval_sec": self.int_input_value(self.firefly_watch_interval_input, 300, 30, 86400),
            "chat_window_context_enabled": self.chat_window_context_enabled_check.isChecked(),
            "autostart_enabled": self.autostart_enabled_check.isChecked(),
        }
        save_config(self.config, self.workspace)
        if hasattr(self, "sync_context_button"):
            self.sync_context_button()
        self.computer_control_status_label.setText(f"{self.computer_control_summary()}\n已保存并应用。")

    def build_files_panel(self) -> QWidget:
        panel = QWidget(self)
        panel.setObjectName("settingsCard")
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(18, 16, 18, 18)
        layout.setSpacing(12)
        title = QLabel("资料舱", panel)
        title.setObjectName("sectionTitle")
        caption = QLabel("管理流萤可读取和写入的本地资料目录；只有允许读取的目录会参与检索。", panel)
        caption.setObjectName("sectionCaption")
        layout.addWidget(title)
        layout.addWidget(caption)

        body = QSplitter(Qt.Horizontal, panel)
        body.setObjectName("librarySplitter")
        body.setChildrenCollapsible(False)

        directory_column = QWidget(panel)
        directory_layout = QVBoxLayout(directory_column)
        directory_layout.setContentsMargins(0, 0, 0, 0)
        directory_layout.setSpacing(8)
        directory_title = QLabel("资料目录", directory_column)
        directory_title.setObjectName("sectionTitle")
        directory_layout.addWidget(directory_title)
        path_row = QHBoxLayout()
        path_row.setContentsMargins(0, 0, 0, 0)
        self.location_path_input = QLineEdit(directory_column)
        self.location_path_input.setPlaceholderText("粘贴目录路径，例如 D:/notes")
        add_path_button = QPushButton("添加路径", directory_column)
        add_path_button.clicked.connect(self.add_library_location_from_input)
        path_row.addWidget(self.location_path_input, 1)
        path_row.addWidget(add_path_button)
        directory_layout.addLayout(path_row)
        self.location_list = QListWidget(directory_column)
        self.location_list.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.location_list.setTextElideMode(Qt.ElideMiddle)
        directory_layout.addWidget(self.location_list, 1)
        library_locations = self.config.get("library_locations")
        for path in library_locations if isinstance(library_locations, list) else []:
            value = path.get("path") if isinstance(path, dict) else path
            if value:
                self.location_list.addItem(str(value))

        self.allow_read_check = QCheckBox("允许读取", directory_column)
        self.allow_read_check.setChecked(bool(self.config.get("library_allow_read", True)))
        self.allow_write_check = QCheckBox("允许写入", directory_column)
        self.allow_write_check.setChecked(bool(self.config.get("library_allow_write", False)))
        self.library_index_check = QCheckBox("启用本地全文索引", directory_column)
        self.library_index_check.setChecked(bool(self.config.get("library_index_enabled", True)))
        directory_layout.addWidget(self.allow_read_check)
        directory_layout.addWidget(self.allow_write_check)
        directory_layout.addWidget(self.library_index_check)

        directory_actions = QHBoxLayout()
        directory_actions.setContentsMargins(0, 0, 0, 0)
        for text, secondary in (("添加目录", False), ("移除", True), ("保存权限", False), ("刷新文件", True), ("刷新索引", True)):
            button = QPushButton(text, directory_column)
            if secondary:
                button.setObjectName("secondaryButton")
            if text == "添加目录":
                button.clicked.connect(self.choose_library_directory)
            elif text == "移除":
                button.clicked.connect(self.remove_library_location)
            elif text == "保存权限":
                button.clicked.connect(self.save_library_locations)
            elif text == "刷新文件":
                button.clicked.connect(self.refresh_library_files)
            else:
                self.refresh_library_index_button = button
                button.clicked.connect(self.refresh_library_index_now)
            directory_actions.addWidget(button)
        directory_layout.addLayout(directory_actions)
        self.library_index_status_label = QLabel(library_index_summary(self.config, self.workspace), directory_column)
        self.library_index_status_label.setObjectName("modelSummary")
        self.library_index_status_label.setWordWrap(True)
        directory_layout.addWidget(self.library_index_status_label)
        body.addWidget(directory_column)

        preview_column = QWidget(panel)
        preview_layout = QVBoxLayout(preview_column)
        preview_layout.setContentsMargins(0, 0, 0, 0)
        preview_layout.setSpacing(8)
        file_title = QLabel("舱内文件", preview_column)
        file_title.setObjectName("sectionTitle")
        preview_layout.addWidget(file_title)
        self.file_list = QListWidget(preview_column)
        self.file_list.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.file_list.setTextElideMode(Qt.ElideMiddle)
        self.file_list.itemClicked.connect(self.preview_library_file)
        preview_layout.addWidget(self.file_list, 1)
        self.location_list.currentItemChanged.connect(lambda _current, _previous: self.refresh_library_files())
        preview_title = QLabel("文件预览", preview_column)
        preview_title.setObjectName("sectionTitle")
        preview_layout.addWidget(preview_title)
        self.file_preview = QTextBrowser(preview_column)
        self.file_preview.setObjectName("filePreview")
        self.file_preview.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.file_preview.setLineWrapMode(QTextBrowser.WidgetWidth)
        preview_layout.addWidget(self.file_preview, 1)
        body.addWidget(preview_column)
        body.setSizes([360, 520])
        layout.addWidget(body, 1)
        self.refresh_library_files()
        return panel

    def set_file_preview(self, text: str) -> None:
        if hasattr(self, "file_preview"):
            self.file_preview.setPlainText(text)

    def add_library_location_from_input(self) -> None:
        path = self.location_path_input.text().strip()
        if not path:
            return
        if path in [self.location_list.item(index).text() for index in range(self.location_list.count())]:
            self.location_path_input.clear()
            return
        self.location_list.addItem(path)
        self.location_path_input.clear()

    def choose_library_directory(self) -> None:
        folder = QFileDialog.getExistingDirectory(self, "选择资料目录", str(Path.home()))
        if folder:
            self.location_path_input.setText(folder)
            self.add_library_location_from_input()

    def remove_library_location(self) -> None:
        row = self.location_list.currentRow()
        if row >= 0:
            self.location_list.takeItem(row)

    def save_library_locations(self) -> None:
        locations = [self.location_list.item(index).text() for index in range(self.location_list.count())]
        self.config = {
            **self.config,
            "library_locations": locations,
            "library_allow_read": self.allow_read_check.isChecked(),
            "library_allow_write": self.allow_write_check.isChecked(),
            "library_index_enabled": self.library_index_check.isChecked(),
        }
        save_config(self.config, self.workspace)
        self.location_list.clearSelection()
        self.location_list.setCurrentRow(-1)
        self.refresh_library_files()
        self.set_file_preview("目录和权限已保存。")

    def current_library_config(self) -> dict[str, object]:
        return {
            **self.config,
            "library_locations": [self.location_list.item(index).text() for index in range(self.location_list.count())],
            "library_allow_read": self.allow_read_check.isChecked(),
            "library_allow_write": self.allow_write_check.isChecked(),
            "library_index_enabled": self.library_index_check.isChecked(),
        }

    def refresh_library_files(self) -> None:
        if not hasattr(self, "file_list"):
            return
        self.file_list.clear()
        config = self.current_library_config()
        if not bool(config.get("library_allow_read", True)):
            self.set_file_preview("资料舱读取已关闭。")
            return
        self.library_index_status_label.setText(library_index_summary(config, self.workspace))
        current = self.location_list.currentItem()
        if current is None:
            self.set_file_preview("请选择左侧资料目录。")
            return
        count = 0
        for path in self.previewable_library_files(config, Path(current.text()).expanduser()):
            item = QListWidgetItem(path.name)
            item.setData(Qt.UserRole, str(path))
            item.setToolTip(str(path))
            self.file_list.addItem(item)
            count += 1
        self.set_file_preview(f"已扫描 {count} 个可读取文件。聊天时只会按问题匹配少量片段作为上下文。")

    def refresh_library_index_now(self) -> None:
        self.save_library_locations()
        config = self.current_library_config()
        workspace = self.workspace
        self.refresh_library_index_button.setEnabled(False)
        self.library_index_status_label.setText(f"{library_index_summary(config, self.workspace)}\n正在刷新索引...")
        started = self.start_settings_task(
            "library_index",
            lambda: refresh_library_index(config, workspace),
            lambda result: self.finish_library_index_refresh(config, result),
            lambda error: self.fail_library_index_refresh(config, error),
        )
        if not started:
            self.refresh_library_index_button.setEnabled(True)

    def finish_library_index_refresh(self, config: dict[str, object], result: object) -> None:
        self.library_index_status_label.setText(f"{library_index_summary(config, self.workspace)}\n已刷新: {result}")
        self.refresh_library_index_button.setEnabled(True)

    def fail_library_index_refresh(self, config: dict[str, object], error: str) -> None:
        self.library_index_status_label.setText(f"{library_index_summary(config, self.workspace)}\n刷新失败: {error}")
        self.refresh_library_index_button.setEnabled(True)

    def preview_library_file(self, item: QListWidgetItem) -> None:
        raw_path = item.data(Qt.UserRole)
        if not raw_path:
            return
        path = Path(str(raw_path))
        if path.suffix.lower() in IMAGE_EXTENSIONS:
            self.file_preview.clear()
            image_url = html.escape(QUrl.fromLocalFile(str(path)).toString(), quote=True)
            self.file_preview.setHtml(f"<p>{html.escape(str(path))}</p><img src='{image_url}' style='max-width:100%; max-height:320px;' />")
            return
        text = read_file_sample(path, 4000)
        self.set_file_preview(f"{path}\n\n{text}" if text else f"{path}\n\n无法预览该文件。")

    def previewable_library_files(self, config: dict[str, object], selected_root: Path | None = None) -> list[Path]:
        files: list[Path] = []
        max_files = int_config(config, "library_max_scan_files", 250, minimum=1, maximum=5000)
        for root in library_roots(config, self.workspace):
            if selected_root is not None and root != selected_root.expanduser().resolve():
                continue
            try:
                for path in root.rglob("*"):
                    if path.is_file() and (is_context_candidate(path) or path.suffix.lower() in IMAGE_EXTENSIONS):
                        files.append(path)
                        if len(files) >= max_files:
                            return files
            except OSError:
                continue
        return files

    def model_summary(self) -> str:
        profile = self.selected_profile_name()
        status = self.openharness_profile_statuses().get(profile, {})
        key_state = "已配置" if status.get("configured") else "未配置"
        return "\n".join(
            [
                "供应源: OpenHarness",
                f"Profile: {profile}",
                f"模型: {self.current_model_text() or status.get('model') or 'provider 默认'}",
                f"生图模型: {self.current_image_model_text() or '自动选择'}",
                f"接口地址: {self.base_url_input.text().strip() or status.get('base_url') or 'provider 默认'}",
                f"密钥: {key_state}",
            ]
        )

    def save_model_settings(self) -> None:
        profile = self.selected_profile_name()
        model = self.model_input.currentText().strip()
        base_url = self.base_url_input.text().strip()
        manager = AuthManager()
        try:
            manager.use_profile(profile)
            manager.update_profile(
                profile,
                base_url=base_url or None,
                last_model=model or None,
            )
            key = self.api_key_input.text().strip()
            if key:
                manager.store_profile_credential(profile, "api_key", key)
                self.api_key_input.clear()
        except Exception as error:
            self.model_status_label.setText(f"{self.model_summary()}\n保存 OpenHarness profile 失败: {type(error).__name__}: {error}")
            return
        self.config = {
            **self.config,
            "provider_profile": profile,
            "model": model,
            "image_generation_model": self.current_image_model_text(),
            "max_turns": None,
        }
        save_config(self.config, self.workspace)
        self.apply_runtime_config()
        self.model_status_label.setText(f"{self.model_summary()}\n已保存并应用。")

    def current_model_text(self) -> str:
        return self.model_input.currentText().strip()

    def current_image_model_text(self) -> str:
        return self.image_model_input.currentText().strip() if hasattr(self, "image_model_input") else str(self.config.get("image_generation_model") or "")

    def current_profile_models(self) -> list[str]:
        profile_obj = AuthManager().list_profiles().get(self.selected_profile_name())
        if profile_obj is None:
            return []
        return [model for model in [profile_obj.last_model, profile_obj.default_model, *profile_obj.allowed_models] if model]

    def populate_image_model_input(self, models: list[str], current: str) -> None:
        self.image_model_input.clear()
        image_models = [model for model in models if is_image_generation_model(model)]
        for model in dict.fromkeys([*image_models, current]):
            if model:
                self.image_model_input.addItem(model)
        if current:
            self.image_model_input.setCurrentText(current)

    def load_models_from_api(self) -> None:
        profile = self.selected_profile_name()
        profile_obj = AuthManager().list_profiles().get(profile)
        if profile_obj is None:
            self.apply_model_sync(profile, ([], [], False, "没有可同步的模型候选。"))
            return
        base_url = self.base_url_input.text().strip() or profile_obj.base_url or ""
        api_key = profile_api_key(profile, profile_obj, self.api_key_input.text().strip())
        fallback = [model for model in [profile_obj.last_model, profile_obj.default_model, *profile_obj.allowed_models] if model]
        self.load_models_button.setEnabled(False)
        self.model_status_label.setText(f"{self.model_summary()}\n正在同步模型列表...")
        started = self.start_settings_task(
            "model_sync",
            lambda: self.fetch_profile_models(base_url, api_key, fallback),
            lambda result: self.apply_model_sync(profile, result),
            lambda error: self.fail_model_sync(profile, fallback, error),
        )
        if not started:
            self.load_models_button.setEnabled(True)

    @staticmethod
    def fetch_profile_models(base_url: str, api_key: str, fallback: list[str]) -> tuple[list[str], list[str], bool, str]:
        try:
            models = fetch_openai_compatible_models(base_url, api_key)
        except Exception as error:
            return fallback, fallback, False, f"接口模型同步失败: {type(error).__name__}: {error}\n已显示 OpenHarness profile 候选。"
        if not models:
            return fallback, fallback, False, "接口没有返回模型，已显示 OpenHarness profile 候选。"
        return models, fallback, True, "已从接口同步模型列表。"

    def apply_model_sync(self, profile: str, result: object) -> None:
        if not isinstance(result, tuple) or len(result) != 4:
            self.fail_model_sync(profile, [], "invalid response")
            return
        models, fallback, remote_models, message = result
        if profile != self.selected_profile_name():
            self.load_models_button.setEnabled(True)
            self.model_status_label.setText(f"{self.model_summary()}\nProfile 已切换，本次同步结果已忽略。")
            return
        if remote_models:
            try:
                AuthManager().update_profile(profile, allowed_models=models)
            except Exception as error:
                models = fallback
                message = f"保存模型列表失败: {type(error).__name__}: {error}\n已显示 OpenHarness profile 候选。"
        current = self.current_model_text()
        current_image = self.current_image_model_text()
        self.model_input.clear()
        for model in dict.fromkeys([*models, current]):
            if model:
                self.model_input.addItem(model)
        if current:
            self.model_input.setCurrentText(current)
        self.populate_image_model_input(models, current_image)
        self.model_status_label.setText(f"{self.model_summary()}\n{message}")
        self.load_models_button.setEnabled(True)

    def fail_model_sync(self, profile: str, fallback: list[str], error: str) -> None:
        self.apply_model_sync(
            profile,
            (fallback, fallback, False, f"接口模型同步失败: {error}\n已显示 OpenHarness profile 候选。"),
        )

    def test_llm_connection(self) -> None:
        self.save_model_settings()
        status = self.openharness_profile_statuses().get(self.selected_profile_name(), {})
        state = "可用" if status.get("configured") else "未配置"
        self.model_status_label.setText(f"{self.model_summary()}\nOpenHarness profile {state}。")

    def openharness_profile_statuses(self) -> dict[str, object]:
        try:
            return AuthManager().get_profile_statuses()
        except Exception:
            return {}

    def openharness_active_profile(self) -> str:
        try:
            return AuthManager().get_active_profile()
        except Exception:
            return ""

    def selected_profile_name(self) -> str:
        value = self.provider_input.currentData() if hasattr(self, "provider_input") else None
        return str(value or self.config.get("provider_profile") or self.openharness_active_profile() or "claude-api")

    def current_profile_model(self) -> str:
        status = self.openharness_profile_statuses().get(self.selected_profile_name(), {})
        return str(status.get("model") or "")

    def current_profile_base_url(self) -> str:
        status = self.openharness_profile_statuses().get(str(self.config.get("provider_profile") or self.openharness_active_profile() or "claude-api"), {})
        return str(status.get("base_url") or self.config.get("llm_base_url") or "")
