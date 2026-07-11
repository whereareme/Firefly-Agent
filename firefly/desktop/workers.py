"""Qt worker objects for Firefly desktop."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from PySide6.QtCore import QObject, Signal, Slot

from firefly.runtime import FireflyRuntime


class ChatWorker(QObject):
    finished = Signal(str, str, object)
    failed = Signal(str)

    def __init__(
        self,
        runtime: FireflyRuntime,
        message: str,
        history: list[dict[str, str]],
        attachments: list[str] | None = None,
        remember: bool = True,
        use_memory_context: bool = True,
        permission_prompt=None,
        edit_approval_prompt=None,
    ) -> None:
        super().__init__()
        self.runtime = runtime
        self.message = message
        self.history = [dict(item) for item in history]
        self.attachments = list(attachments or [])
        self.remember = remember
        self.use_memory_context = use_memory_context
        self.permission_prompt = permission_prompt
        self.edit_approval_prompt = edit_approval_prompt

    @Slot()
    def run(self) -> None:
        try:
            response = self.runtime.chat(
                self.message,
                self.history,
                self.attachments,
                remember=self.remember,
                use_memory_context=self.use_memory_context,
                permission_prompt=self.permission_prompt,
                edit_approval_prompt=self.edit_approval_prompt,
            )
            if response.errors:
                raise RuntimeError("\n".join(response.errors))
            reply = response.text.strip() or "我没有收到可显示的回复。"
            self.finished.emit(self.message, reply, response.invoked_skills)
        except Exception as error:
            self.failed.emit(str(error))


class TaskWorker(QObject):
    """Run one blocking callable outside the Qt UI thread."""

    finished = Signal(object)
    failed = Signal(str)

    def __init__(self, task: Callable[[], Any]) -> None:
        super().__init__()
        self.task = task

    @Slot()
    def run(self) -> None:
        try:
            self.finished.emit(self.task())
        except Exception as error:
            self.failed.emit(f"{type(error).__name__}: {error}")


def live2d_mood_for_reply(reply: str) -> str:
    text = reply.strip()
    if not text:
        return "idle"
    if any(word in text for word in ("失败", "出错", "找不到", "没找到", "不能", "无法", "权限")):
        return "sweat"
    if "?" in text or "？" in text or any(word in text for word in ("什么", "怎么", "为什么", "哪里", "是否")):
        return "question"
    if any(word in text for word in ("完成", "成功", "好了", "可以", "没问题")):
        return "happy"
    return "idle"
