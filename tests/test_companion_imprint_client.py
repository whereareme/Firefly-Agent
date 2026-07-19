import json
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from firefly.companion_imprint import (
    enqueue_companion_imprint_memory_context,
    fetch_companion_imprint_context,
    record_companion_imprint_event,
    strip_companion_imprint_markers,
    submit_companion_imprint_proposal,
)


class _Sidecar(ThreadingHTTPServer):
    def __init__(self) -> None:
        self.proposals: list[dict[str, str]] = []
        self.memory_context: list[dict[str, str]] = []
        super().__init__(("127.0.0.1", 0), _Handler)


class _Handler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:
        self._json(200, {"context": "relationship context"})

    def do_POST(self) -> None:
        body = self.rfile.read(int(self.headers["Content-Length"]))
        payload = json.loads(body)
        if self.path == "/relationship/memory-context":
            self.server.memory_context.append(payload)  # type: ignore[attr-defined]
            self._json(202, {"accepted": True})
            return
        self.server.proposals.append(payload)  # type: ignore[attr-defined]
        if self.path == "/relationship/records":
            self._json(201, {"recorded": True, "stage": "trusted"})
        else:
            self._json(202, {"accepted": True})

    def _json(self, status: int, payload: object) -> None:
        body = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, _format: str, *_args: object) -> None:
        pass


def test_context_and_proposal_use_the_sidecar_without_model_proxying() -> None:
    sidecar = _Sidecar()
    thread = threading.Thread(target=sidecar.serve_forever, daemon=True)
    thread.start()
    config = {"companion_imprint_enabled": True, "companion_imprint_port": sidecar.server_port}
    proposal = {"kind": "memory", "summary": "用户认真听流萤说完了心事。"}
    try:
        assert fetch_companion_imprint_context(config) == "relationship context"
        assert submit_companion_imprint_proposal(config, proposal) is True
        assert record_companion_imprint_event(config, proposal)["recorded"] is True
        assert sidecar.proposals == [proposal, proposal]
    finally:
        sidecar.shutdown()
        sidecar.server_close()
        thread.join(timeout=2)


def test_marker_filter_hides_markers_and_accepts_only_one_final_valid_candidate() -> None:
    marker = '<!--FIREFLY_RELATIONSHIP:{"kind":"gift","summary":"用户送给流萤一只纸鹤。"}-->'

    visible, proposal = strip_companion_imprint_markers(f"谢谢你。{marker}")
    trailing_visible, trailing_proposal = strip_companion_imprint_markers(f"谢谢你。{marker}还有文字")
    multi_visible, multi_proposal = strip_companion_imprint_markers(f"{marker}{marker}")

    assert visible == "谢谢你。"
    assert proposal == {"kind": "gift", "summary": "用户送给流萤一只纸鹤。"}
    assert trailing_visible == "谢谢你。还有文字"
    assert trailing_proposal is None
    assert multi_visible == ""
    assert multi_proposal is None


def test_disabled_or_unavailable_sidecar_is_non_blocking() -> None:
    assert fetch_companion_imprint_context({"companion_imprint_enabled": False}) == ""
    assert submit_companion_imprint_proposal({"companion_imprint_enabled": False}, None) is False
    assert fetch_companion_imprint_context(
        {"companion_imprint_enabled": True, "companion_imprint_port": 1}
    ) == ""


def test_memory_context_is_sent_asynchronously_and_bounded() -> None:
    sidecar = _Sidecar()
    thread = threading.Thread(target=sidecar.serve_forever, daemon=True)
    thread.start()
    config = {"companion_imprint_enabled": True, "companion_imprint_port": sidecar.server_port}
    try:
        started = time.monotonic()
        enqueue_companion_imprint_memory_context(
            config, " EverOS 标题 \n" + "甲" * 1_100 + "\n" + ("记忆\n" * 3_000)
        )
        assert time.monotonic() - started < 0.1
        for _ in range(100):
            if sidecar.memory_context:
                break
            time.sleep(0.01)
        payload = sidecar.memory_context[0]
        assert set(payload) == {"context", "revision", "activity_date"}
        assert payload["context"].splitlines()[:2] == ["EverOS 标题", "甲" * 1_000]
        assert len(payload["context"]) == 8_000
        assert isinstance(payload["revision"], int)
        assert len(payload["activity_date"].split("-")) == 3
    finally:
        sidecar.shutdown()
        sidecar.server_close()
        thread.join(timeout=2)


def test_memory_context_failure_returns_without_blocking_chat() -> None:
    started = time.monotonic()
    enqueue_companion_imprint_memory_context(
        {"companion_imprint_enabled": True, "companion_imprint_port": 1}, "EverOS 记忆"
    )
    assert time.monotonic() - started < 0.1


def test_memory_context_queue_preserves_revision_order() -> None:
    sidecar = _Sidecar()
    thread = threading.Thread(target=sidecar.serve_forever, daemon=True)
    thread.start()
    config = {"companion_imprint_enabled": True, "companion_imprint_port": sidecar.server_port}
    try:
        enqueue_companion_imprint_memory_context(config, "first")
        enqueue_companion_imprint_memory_context(config, "second")
        for _ in range(100):
            if len(sidecar.memory_context) >= 2:
                break
            time.sleep(0.01)
        first, second = sidecar.memory_context[-2:]
        assert [first["context"], second["context"]] == ["first", "second"]
        assert first["revision"] < second["revision"]
    finally:
        sidecar.shutdown()
        sidecar.server_close()
        thread.join(timeout=2)
