import json
import os
import sys
import time
import threading
from pathlib import Path
from types import SimpleNamespace

import pytest
from PySide6.QtWidgets import QApplication

import firefly.desktop.companion_imprint as imprint


os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


class _Signal:
    def __init__(self) -> None:
        self.callbacks = []

    def connect(self, callback) -> None:
        self.callbacks.append(callback)

    def emit(self, *args) -> None:
        for callback in self.callbacks:
            callback(*args)


class _FakeProcess:
    ProcessState = SimpleNamespace(NotRunning=0)

    def __init__(self, _parent) -> None:
        self.started = _Signal()
        self.finished = _Signal()
        self.errorOccurred = _Signal()
        self._state = self.ProcessState.NotRunning
        self.program = ""
        self.arguments = []
        self.working_directory = ""
        self.terminated = False
        self.killed = False

    def state(self):
        return self._state

    def setWorkingDirectory(self, path: str) -> None:
        self.working_directory = path

    def start(self, program: str, arguments: list[str]) -> None:
        self.program = program
        self.arguments = list(arguments)
        self._state = 1

    def terminate(self) -> None:
        self.terminated = True
        self._state = self.ProcessState.NotRunning

    def kill(self) -> None:
        self.killed = True
        self._state = self.ProcessState.NotRunning

    def waitForFinished(self, _milliseconds: int) -> bool:
        return True


class _FakeAuthManager:
    updates: list[tuple[str, str]] = []

    def use_profile(self, _profile: str) -> None:
        pass

    def update_profile(self, profile: str, *, base_url: str) -> None:
        self.updates.append((profile, base_url))

    def list_profiles(self):
        return {"demo": object()}


class _Host:
    def __init__(self, root: Path) -> None:
        project = root / "sidecar"
        project.mkdir()
        self.workspace = root / "workspace"
        self.profile = "demo"
        self.base_url = "https://upstream.example/v1"
        self.runtime_updates = 0
        self.config: dict[str, object] = {
            "companion_imprint_enabled": False,
            "companion_imprint_port": 18787,
            "companion_imprint_project_path": str(project),
            "companion_imprint_config_path": str(project / "config.json"),
            "companion_imprint_original_base_url": "",
            "companion_imprint_profile": "",
            "companion_imprint_takeover": False,
            "llm_base_url": "https://fallback.example/v1",
        }

    def current_profile_base_url(self) -> str:
        return self.base_url

    def selected_profile_name(self) -> str:
        return self.profile

    def apply_runtime_config(self) -> None:
        self.runtime_updates += 1


@pytest.fixture
def controller(tmp_path, monkeypatch):
    QApplication.instance() or QApplication([])
    _FakeAuthManager.updates = []
    monkeypatch.setattr(imprint, "QProcess", _FakeProcess)
    monkeypatch.setattr(imprint, "AuthManager", _FakeAuthManager)
    monkeypatch.setattr(imprint, "save_config", lambda _config, _workspace: None)
    monkeypatch.setattr(imprint, "profile_api_key", lambda _name, _profile: "transient-key")
    monkeypatch.setattr(
        imprint,
        "fetch_openai_compatible_models",
        lambda _url, api_key="", timeout=1: ["firefly-test"],
    )
    host = _Host(tmp_path)
    return imprint.CompanionImprintController(host), host


def wait_until(predicate) -> None:
    application = QApplication.instance()
    assert application is not None
    deadline = time.monotonic() + 2
    while time.monotonic() < deadline:
        application.processEvents()
        if predicate():
            return
        time.sleep(0.01)
    assert predicate()


def connect(gateway) -> None:
    gateway.process.started.emit()
    wait_until(lambda: gateway.status == "connected")


def test_enable_writes_exact_config_without_switching_profile_after_probe(controller):
    gateway, host = controller

    assert gateway.enable() is True

    payload = json.loads(gateway.config_path.read_text(encoding="utf-8"))
    assert payload == {
        "host": "127.0.0.1",
        "port": 18787,
        "upstream_base_url": "https://upstream.example/v1",
        "data_dir": "data",
    }
    assert gateway.process.program == sys.executable
    assert gateway.process.arguments == [
        "-m",
        "relationship_gateway",
        "--config",
        str(gateway.config_path),
        "--parent-pid",
        str(os.getpid()),
    ]
    assert gateway.process.working_directory == str(gateway.project_path)
    assert gateway.start() is False

    connect(gateway)

    assert gateway.status == "connected"
    assert host.config["companion_imprint_takeover"] is False
    assert _FakeAuthManager.updates == []
    assert host.runtime_updates == 0


def test_stop_restores_the_original_profile_address(controller):
    gateway, host = controller
    gateway.enable()
    connect(gateway)

    gateway.stop()
    assert gateway.status == "connected"
    gateway.process.finished.emit(0, 0)

    assert gateway.status == "stopped"
    assert gateway.process.terminated is True
    assert host.config["companion_imprint_takeover"] is False
    assert _FakeAuthManager.updates == []
    assert host.runtime_updates == 0


def test_failed_probe_restores_direct_traffic_and_reports_an_error(controller, monkeypatch):
    gateway, host = controller
    monkeypatch.setattr(imprint, "MAX_HEALTH_CHECK_ATTEMPTS", 1)
    monkeypatch.setattr(
        imprint,
        "fetch_openai_compatible_models",
        lambda _url, api_key="", timeout=1: (_ for _ in ()).throw(RuntimeError("offline")),
    )

    gateway.enable()
    gateway.process.started.emit()
    wait_until(lambda: gateway.status == "error")

    assert gateway.status == "error"
    assert "预期端口" in gateway.error
    assert gateway.process.terminated is True
    assert host.config["companion_imprint_takeover"] is False
    assert _FakeAuthManager.updates == []


def test_repeated_enable_keeps_the_saved_direct_upstream(controller):
    gateway, host = controller
    host.base_url = gateway.endpoint
    host.config.update(
        {
            "companion_imprint_enabled": True,
            "companion_imprint_takeover": True,
            "companion_imprint_original_base_url": "https://upstream.example/v1",
            "companion_imprint_profile": "demo",
        }
    )

    assert gateway.enable() is True

    assert json.loads(gateway.config_path.read_text(encoding="utf-8"))["upstream_base_url"] == "https://upstream.example/v1"


def test_compatible_provider_change_updates_upstream_and_restarts(controller):
    gateway, host = controller
    gateway.enable()
    connect(gateway)

    host.base_url = "https://new-upstream.example/v1"
    gateway.provider_changed("new-profile", "https://new-upstream.example/v1")
    gateway.process.finished.emit(0, 0)

    assert host.config["companion_imprint_original_base_url"] == "https://new-upstream.example/v1"
    assert host.config["companion_imprint_profile"] == "new-profile"
    assert gateway.status == "starting"
    assert json.loads(gateway.config_path.read_text(encoding="utf-8"))["upstream_base_url"] == "https://new-upstream.example/v1"


def test_incompatible_provider_change_releases_takeover_without_restoring_the_old_profile(controller):
    gateway, host = controller
    gateway.enable()
    connect(gateway)

    gateway.provider_changed("local-only", "")

    assert gateway.status == "error"
    assert host.config["companion_imprint_enabled"] is False
    assert host.config["companion_imprint_takeover"] is False
    assert gateway.process.terminated is True
    assert _FakeAuthManager.updates == []


def test_readiness_probe_forwards_the_profile_key_without_persisting_it(controller, monkeypatch):
    gateway, _host = controller
    requests = []
    monkeypatch.setattr(
        imprint,
        "fetch_openai_compatible_models",
        lambda url, api_key="", timeout=1: requests.append((url, api_key, timeout)),
    )

    gateway.enable()
    connect(gateway)

    assert requests == [(gateway.endpoint, "transient-key", 1)]
    assert "transient-key" not in gateway.config_path.read_text(encoding="utf-8")


def test_repeated_enable_while_connected_keeps_direct_state(controller):
    gateway, host = controller
    gateway.enable()
    connect(gateway)

    assert gateway.enable() is False
    assert host.config["companion_imprint_takeover"] is False
    gateway.stop()
    gateway.process.finished.emit(0, 0)
    assert _FakeAuthManager.updates == []


def test_previous_sidecar_endpoint_is_not_reused_after_a_port_change(controller):
    gateway, host = controller
    gateway.enable()
    connect(gateway)
    old_endpoint = gateway.endpoint
    host.config["companion_imprint_port"] = 19777
    host.config["companion_imprint_takeover"] = False
    host.base_url = old_endpoint

    assert gateway._original_upstream() == "https://upstream.example/v1"


def test_stale_local_profile_recovers_from_workspace_upstream(controller):
    gateway, host = controller
    host.base_url = gateway.endpoint
    host.config["companion_imprint_original_base_url"] = ""
    host.config["companion_imprint_takeover"] = False

    assert gateway.enable() is True
    assert host.config["companion_imprint_original_base_url"] == "https://fallback.example/v1"
    assert json.loads(gateway.config_path.read_text(encoding="utf-8"))["upstream_base_url"] == "https://fallback.example/v1"


def test_direct_start_saves_upstream_before_takeover(controller):
    gateway, host = controller
    host.config["companion_imprint_enabled"] = True

    assert gateway.start() is True
    assert host.config["companion_imprint_original_base_url"] == "https://upstream.example/v1"
    assert host.config["companion_imprint_profile"] == "demo"
    assert host.config["companion_imprint_takeover"] is False


def test_restore_repairs_local_profile_even_when_takeover_flag_is_stale(controller):
    gateway, host = controller
    host.base_url = gateway.endpoint
    host.config.update(
        {
            "companion_imprint_original_base_url": "https://upstream.example/v1",
            "companion_imprint_profile": "demo",
            "companion_imprint_takeover": False,
        }
    )

    assert gateway._restore_upstream() is True
    assert _FakeAuthManager.updates == [("demo", "https://upstream.example/v1")]
    assert host.config["companion_imprint_takeover"] is False


def test_shutdown_waits_for_an_in_flight_probe(controller, monkeypatch):
    gateway, _host = controller
    probe_started = threading.Event()
    allow_probe_to_finish = threading.Event()

    def delayed_probe(_url, api_key="", timeout=1):
        assert api_key == "transient-key"
        assert timeout == 1
        probe_started.set()
        assert allow_probe_to_finish.wait(timeout=1)
        return ["firefly-test"]

    monkeypatch.setattr(imprint, "fetch_openai_compatible_models", delayed_probe)
    gateway.enable()
    gateway.process.started.emit()
    wait_until(probe_started.is_set)
    threading.Timer(0.05, allow_probe_to_finish.set).start()

    gateway.shutdown()
    application = QApplication.instance()
    assert application is not None
    application.processEvents()

    assert all(not thread.isRunning() for thread, _worker in gateway._probe_tasks)
