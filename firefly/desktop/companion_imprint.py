"""Lifecycle management for the local companion imprint Sidecar."""

from __future__ import annotations

import json
import os
import sys
import tempfile
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from PySide6.QtCore import QObject, QProcess, QThread, QTimer, Qt, Signal

from openharness.auth.manager import AuthManager

from firefly.desktop.settings_panel import fetch_openai_compatible_models, profile_api_key
from firefly.desktop.workers import TaskWorker
from firefly.workspace import save_config


DEFAULT_PORT = 8787
MAX_HEALTH_CHECK_ATTEMPTS = 3
HEALTH_CHECK_INTERVAL_MS = 250
PROBE_THREAD_SHUTDOWN_TIMEOUT_MS = 1_500
_SIDECAR_CONFIG_KEYS = frozenset(("host", "port", "upstream_base_url", "data_dir"))


def is_http_url(value: object) -> bool:
    """Accept only credential-free HTTP(S) endpoints for the Sidecar upstream."""
    if not isinstance(value, str) or not value.strip() or value != value.strip():
        return False
    try:
        parsed = urlsplit(value)
        port = parsed.port
    except ValueError:
        return False
    return (
        parsed.scheme in {"http", "https"}
        and bool(parsed.hostname)
        and "@" not in parsed.netloc
        and not parsed.query
        and not parsed.fragment
        and (port is None or 1 <= port <= 65535)
    )


def atomic_write_sidecar_config(path: Path, payload: dict[str, object]) -> None:
    """Write the Sidecar's exact, secret-free configuration atomically."""
    if set(payload) != _SIDECAR_CONFIG_KEYS:
        raise ValueError("Sidecar config has unsupported fields")
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.", suffix=".tmp")
    temporary_path = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as file:
            json.dump(payload, file, ensure_ascii=False, indent=2)
            file.write("\n")
            file.flush()
            os.fsync(file.fileno())
        os.replace(temporary_path, path)
    finally:
        if temporary_path.exists():
            temporary_path.unlink()


class CompanionImprintController(QObject):
    """Own one Sidecar process while keeping model traffic on its direct URL."""

    status_changed = Signal(str)
    error_changed = Signal(str)

    def __init__(self, window: Any, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self.window = window
        self.process = QProcess(self)
        self.process.started.connect(self._on_process_started)
        self.process.finished.connect(self._on_process_finished)
        self.process.errorOccurred.connect(self._on_process_error)
        self.status = "stopped"
        self.error = ""
        self._probe_attempts = 0
        self._probe_generation = 0
        self._probe_tasks: list[tuple[QThread, TaskWorker]] = []
        self._stopping = False
        self._restart_after_stop = False

    @property
    def endpoint(self) -> str:
        return f"http://127.0.0.1:{self.port}/v1"

    @property
    def port(self) -> int:
        value = self.window.config.get("companion_imprint_port", DEFAULT_PORT)
        try:
            port = int(value)
        except (TypeError, ValueError):
            return DEFAULT_PORT
        return port if 1 <= port <= 65535 else DEFAULT_PORT

    @property
    def project_path(self) -> Path:
        configured = str(self.window.config.get("companion_imprint_project_path") or "").strip()
        if configured:
            return Path(configured).expanduser().resolve()
        return Path(__file__).resolve().parents[2] / "firefly-relationship-gateway"

    @property
    def config_path(self) -> Path:
        configured = str(self.window.config.get("companion_imprint_config_path") or "").strip()
        if configured:
            return Path(configured).expanduser().resolve()
        return self.project_path / "config.json"

    @property
    def enabled(self) -> bool:
        return bool(self.window.config.get("companion_imprint_enabled", False))

    def configure(self, *, enabled: bool, port: int, project_path: str, config_path: str) -> bool:
        """Persist local launch settings while the owned Sidecar is stopped."""
        if self._process_running() or self.status == "starting":
            self._set_error("请先停止同行印记，再修改本机设置")
            return False
        if not 1 <= port <= 65535:
            self._set_error("端口必须在 1 到 65535 之间")
            return False
        self._save_settings(
            companion_imprint_enabled=enabled,
            companion_imprint_port=port,
            companion_imprint_project_path=project_path.strip(),
            companion_imprint_config_path=config_path.strip(),
        )
        return True

    def enable(self) -> bool:
        """Persist the direct upstream and launch the non-proxy Sidecar."""
        if self._process_running() or self.status in {"starting", "connected"}:
            return False
        profile = self._selected_profile()
        upstream = self._original_upstream()
        if not is_http_url(upstream):
            self._save_settings(companion_imprint_enabled=False, companion_imprint_takeover=False)
            self._set_error("当前供应源不支持 OpenAI 兼容地址")
            return False
        self._save_settings(
            companion_imprint_enabled=True,
            companion_imprint_port=self.port,
            companion_imprint_project_path=str(self.project_path),
            companion_imprint_config_path=str(self.config_path),
            companion_imprint_original_base_url=upstream.rstrip("/"),
            companion_imprint_profile=profile,
            companion_imprint_takeover=False,
            companion_imprint_takeover_endpoint="",
        )
        return self.start()

    def disable(self) -> None:
        """Turn off context synchronization and stop the managed Sidecar."""
        self._save_settings(companion_imprint_enabled=False)
        self.stop()

    def start(self) -> bool:
        """Launch one managed Sidecar process without changing the model profile."""
        if not self.enabled:
            self._set_error("请先启用同行印记")
            return False
        if self._process_running() or self.status == "starting":
            return False
        upstream = self._original_upstream()
        if not is_http_url(upstream):
            self._fail("当前供应源不支持 OpenAI 兼容地址", stop_process=False)
            return False
        profile = str(self.window.config.get("companion_imprint_profile") or self._selected_profile())
        current = str(self.window.current_profile_base_url() or "")
        if self._is_local_endpoint(current):
            try:
                self._set_profile_base_url(profile, upstream)
            except Exception as error:
                self._fail(f"无法恢复直连模型地址：{type(error).__name__}: {error}", stop_process=False)
                return False
        self._save_settings(
            companion_imprint_original_base_url=upstream.rstrip("/"),
            companion_imprint_profile=profile,
            companion_imprint_takeover=False,
            companion_imprint_takeover_endpoint="",
        )
        if not self.project_path.is_dir():
            self._fail("未找到同行印记 Sidecar 工程", stop_process=False)
            return False
        try:
            atomic_write_sidecar_config(
                self.config_path,
                {
                    "host": "127.0.0.1",
                    "port": self.port,
                    "upstream_base_url": upstream.rstrip("/"),
                    "data_dir": "data",
                },
            )
        except OSError as error:
            self._fail(f"无法写入 Sidecar 配置：{error}", stop_process=False)
            return False
        self._stopping = False
        self._probe_attempts = 0
        self._set_status("starting")
        self.process.setWorkingDirectory(str(self.project_path))
        self.process.start(
            sys.executable,
            [
                "-m",
                "relationship_gateway",
                "--config",
                str(self.config_path),
                "--parent-pid",
                str(os.getpid()),
            ],
        )
        return True

    def stop(self) -> None:
        """Restore direct traffic, then request a graceful stop of our own process."""
        self._cancel_probes()
        self._restart_after_stop = False
        restored = self._restore_upstream()
        self._stopping = True
        if self._process_running():
            self.process.terminate()
        elif restored:
            self._set_status("stopped")

    def restart(self) -> bool:
        """Restart through the same restoration path used by a manual stop."""
        if not self.enabled:
            self._set_error("请先启用同行印记")
            return False
        self._cancel_probes()
        self._restart_after_stop = True
        self._restore_upstream()
        if self._process_running():
            self._stopping = True
            self.process.terminate()
            return True
        self._restart_after_stop = False
        return self.start()

    def shutdown(self) -> None:
        """Bound app-exit cleanup for the process this controller owns."""
        self._cancel_probes()
        self._restart_after_stop = False
        self._restore_upstream()
        self._stopping = True
        if self._process_running():
            self.process.terminate()
            if not self.process.waitForFinished(1_500):
                self.process.kill()
                self.process.waitForFinished(500)
        self._wait_for_probe_tasks()
        self._set_status("stopped")

    def provider_changed(self, profile: str, base_url: str) -> None:
        """Keep Sidecar diagnostics aligned with a changed direct provider."""
        if not self.enabled:
            return
        if not is_http_url(base_url) or self._is_local_endpoint(base_url):
            self._cancel_probes()
            self._restart_after_stop = False
            self._save_settings(
                companion_imprint_enabled=False,
                companion_imprint_original_base_url="",
                companion_imprint_profile="",
                companion_imprint_takeover=False,
                companion_imprint_takeover_endpoint="",
            )
            self._stop_process_without_restore()
            self._set_error("当前供应源不支持 OpenAI 兼容地址")
            return
        self._save_settings(
            companion_imprint_original_base_url=base_url.rstrip("/"),
            companion_imprint_profile=profile,
            companion_imprint_takeover=False,
        )
        self.restart()

    def _on_process_started(self) -> None:
        self._probe_attempts = 0
        self._probe_generation += 1
        self._start_probe(self._probe_generation)

    def _on_process_finished(self, *_arguments: object) -> None:
        if self._restart_after_stop:
            self._restart_after_stop = False
            self._stopping = False
            self.start()
            return
        if self._stopping:
            self._stopping = False
            if self.status != "error":
                self._set_status("stopped")
            return
        if self.status in {"starting", "connected"}:
            self._fail("同行印记 Sidecar 已停止", stop_process=False)

    def _on_process_error(self, _error: object) -> None:
        if not self._stopping:
            self._fail("同行印记 Sidecar 无法启动", stop_process=False)

    def _start_probe(self, generation: int) -> None:
        if generation != self._probe_generation or not self._process_running() or self.status != "starting":
            return
        profile = str(self.window.config.get("companion_imprint_profile") or self._selected_profile())
        api_key = self._profile_api_key(profile)
        thread = QThread(self)
        worker = TaskWorker(lambda: fetch_openai_compatible_models(self.endpoint, api_key=api_key, timeout=1))
        self._probe_tasks.append((thread, worker))
        worker.moveToThread(thread)
        thread.started.connect(worker.run)
        worker.finished.connect(lambda _result, value=generation: self._probe_succeeded(value), Qt.QueuedConnection)
        worker.failed.connect(lambda _error, value=generation: self._probe_failed(value), Qt.QueuedConnection)
        worker.finished.connect(worker.deleteLater)
        worker.failed.connect(worker.deleteLater)
        worker.finished.connect(thread.quit)
        worker.failed.connect(thread.quit)
        thread.finished.connect(thread.deleteLater)
        thread.finished.connect(lambda value=thread: self._clear_probe_task(value))
        thread.start()

    def _probe_succeeded(self, generation: int) -> None:
        if generation == self._probe_generation and self._process_running() and self.status == "starting":
            self._save_settings(companion_imprint_takeover=False, companion_imprint_takeover_endpoint="")
            self._set_status("connected")

    def _probe_failed(self, generation: int) -> None:
        if generation != self._probe_generation or not self._process_running() or self.status != "starting":
            return
        self._probe_attempts += 1
        if self._probe_attempts >= MAX_HEALTH_CHECK_ATTEMPTS:
            self._fail("同行印记 Sidecar 未在预期端口响应", stop_process=True)
            return
        QTimer.singleShot(HEALTH_CHECK_INTERVAL_MS, lambda value=generation: self._start_probe(value))

    def _clear_probe_task(self, thread: QThread) -> None:
        self._probe_tasks = [task for task in self._probe_tasks if task[0] is not thread]

    def _wait_for_probe_tasks(self) -> None:
        for thread, _worker in tuple(self._probe_tasks):
            if thread.isRunning():
                thread.wait(PROBE_THREAD_SHUTDOWN_TIMEOUT_MS)

    def _cancel_probes(self) -> None:
        self._probe_generation += 1

    def _fail(self, message: str, *, stop_process: bool) -> None:
        self._cancel_probes()
        self._restore_upstream()
        self._set_error(message)
        if stop_process:
            self._stopping = True
            if self._process_running():
                self.process.terminate()

    def _restore_upstream(self) -> bool:
        current = str(self.window.current_profile_base_url() or "")
        if not bool(self.window.config.get("companion_imprint_takeover", False)) and not self._is_local_endpoint(current):
            return True
        profile = str(self.window.config.get("companion_imprint_profile") or self._selected_profile())
        upstream = str(self.window.config.get("companion_imprint_original_base_url") or "")
        if not is_http_url(upstream):
            self._set_error("无法恢复同行印记之前的模型地址")
            return False
        try:
            self._set_profile_base_url(profile, upstream)
        except Exception as error:
            self._set_error(f"无法恢复模型地址：{type(error).__name__}: {error}")
            return False
        self._save_settings(companion_imprint_takeover=False, companion_imprint_takeover_endpoint="")
        return True

    def _stop_process_without_restore(self) -> None:
        self._stopping = True
        if self._process_running():
            self.process.terminate()

    def _original_upstream(self) -> str:
        stored = str(self.window.config.get("companion_imprint_original_base_url") or "")
        current = str(self.window.current_profile_base_url() or "")
        try:
            current_parts = urlsplit(current)
            stale_loopback = (
                current_parts.hostname == "127.0.0.1"
                and current_parts.path.rstrip("/") == "/v1"
                and current.rstrip("/") != stored.rstrip("/")
            )
        except ValueError:
            stale_loopback = False
        if bool(self.window.config.get("companion_imprint_takeover", False)) or self._is_local_endpoint(current):
            if is_http_url(stored) and not self._is_local_endpoint(stored):
                return stored
            fallback = str(self.window.config.get("llm_base_url") or "")
            if is_http_url(fallback) and not self._is_local_endpoint(fallback):
                return fallback
            return ""
        if stale_loopback and is_http_url(stored):
            return stored
        return current

    def _selected_profile(self) -> str:
        return str(self.window.selected_profile_name() or "")

    def _profile_api_key(self, profile: str) -> str:
        try:
            profile_config = AuthManager().list_profiles().get(profile)
            return profile_api_key(profile, profile_config) if profile_config is not None else ""
        except Exception:
            return ""

    def _is_local_endpoint(self, value: str) -> bool:
        try:
            parsed = urlsplit(value)
            current_endpoint = urlsplit(self.endpoint)
            previous_endpoint = urlsplit(str(self.window.config.get("companion_imprint_takeover_endpoint") or ""))
            return (
                parsed.hostname == "127.0.0.1"
                and parsed.path.rstrip("/") == "/v1"
                and (parsed.port == current_endpoint.port or parsed.port == previous_endpoint.port)
            )
        except ValueError:
            return False

    def _set_profile_base_url(self, profile: str, base_url: str) -> None:
        manager = AuthManager()
        manager.use_profile(profile)
        manager.update_profile(profile, base_url=base_url)
        self.window.apply_runtime_config()

    def _save_settings(self, **updates: object) -> None:
        self.window.config = {**self.window.config, **updates}
        save_config(self.window.config, self.window.workspace)

    def _process_running(self) -> bool:
        return self.process.state() != QProcess.ProcessState.NotRunning

    def _set_status(self, status: str) -> None:
        self.status = status
        if status != "error":
            self.error = ""
            self.error_changed.emit("")
        self.status_changed.emit(status)

    def _set_error(self, message: str) -> None:
        self.status = "error"
        self.error = message
        self.error_changed.emit(message)
        self.status_changed.emit("error")
