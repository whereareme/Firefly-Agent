import os
import tempfile
import time
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

import firefly.desktop.chat_window as chat_window_module
from firefly.desktop.chat_window import ChatWindow
from firefly.runtime import FireflyRuntime


def _process_until(predicate, timeout: float = 2.0) -> None:
    app = QApplication.instance()
    assert app is not None
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        app.processEvents()
        if predicate():
            return
        time.sleep(0.01)
    assert predicate()


def test_relationship_popup_appears_after_reply_and_dismiss_does_not_record() -> None:
    QApplication.instance() or QApplication([])
    with tempfile.TemporaryDirectory() as temporary_directory:
        workspace = Path(temporary_directory) / ".firefly"
        window = ChatWindow(FireflyRuntime(cwd=temporary_directory, workspace=workspace), workspace)
        proposal = {"kind": "gift", "summary": "用户送给流萤一只纸鹤。"}

        window.handle_reply("送给你", "谢谢你，我会好好收着。", {"relationship_proposal": proposal})
        _process_until(lambda: window._relationship_dialog is not None)

        assert window.messages[-1]["content"] == "谢谢你，我会好好收着。"
        assert window._relationship_dialog is not None
        assert window._relationship_dialog.isModal() is False
        assert window._relationship_dialog.proposal == proposal
        window._relationship_dialog.dismiss_button.click()
        _process_until(lambda: window._relationship_dialog is None)
        window.close()


def test_relationship_popup_records_in_background_and_closes_on_success(monkeypatch) -> None:
    QApplication.instance() or QApplication([])
    recorded: list[dict[str, str]] = []

    def record(_config: dict[str, object], proposal: dict[str, str]) -> dict[str, object]:
        recorded.append(dict(proposal))
        return {"recorded": True, "stage": "trusted"}

    monkeypatch.setattr(chat_window_module, "record_companion_imprint_event", record)
    with tempfile.TemporaryDirectory() as temporary_directory:
        workspace = Path(temporary_directory) / ".firefly"
        window = ChatWindow(FireflyRuntime(cwd=temporary_directory, workspace=workspace), workspace)
        proposal = {"kind": "memory", "summary": "用户认真听流萤说完了心事。"}

        window.handle_reply("我会听你说", "那我就慢慢告诉你。", {"relationship_proposal": proposal})
        _process_until(lambda: window._relationship_dialog is not None)
        assert window._relationship_dialog is not None
        window._relationship_dialog.confirm_button.click()
        _process_until(lambda: window._relationship_dialog is None and window._relationship_record_thread is None)

        assert recorded == [proposal]
        window.close()


def test_relationship_popup_queues_multiple_candidates_without_overlap() -> None:
    QApplication.instance() or QApplication([])
    with tempfile.TemporaryDirectory() as temporary_directory:
        workspace = Path(temporary_directory) / ".firefly"
        window = ChatWindow(FireflyRuntime(cwd=temporary_directory, workspace=workspace), workspace)
        first = {"kind": "gift", "summary": "用户送给流萤一只纸鹤。"}
        second = {"kind": "anniversary", "summary": "用户和流萤约定今天作为纪念日。"}

        window.enqueue_relationship_proposal(first)
        window.enqueue_relationship_proposal(second)
        _process_until(lambda: window._relationship_dialog is not None)
        assert window._relationship_dialog is not None
        assert window._relationship_dialog.proposal == first
        assert window._relationship_queue == [second]
        window._relationship_dialog.dismiss_button.click()
        _process_until(
            lambda: window._relationship_dialog is not None and window._relationship_dialog.proposal == second
        )
        window._relationship_dialog.dismiss_button.click()
        _process_until(lambda: window._relationship_dialog is None)
        window.close()
