"""Session persistence for ``firefly``."""

from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Any

from openharness.api.usage import UsageSnapshot
from openharness.engine.messages import ConversationMessage
from openharness.services.session_backend import SessionBackend
from openharness.services.session_storage import (
    _export_app_session_markdown,
    _list_app_session_snapshots,
    _load_app_session_by_id,
    _load_latest_for_session_key_from_dir,
    _load_latest_from_dir,
    _save_app_session_snapshot,
)
from openharness.utils.fs import atomic_write_text

from firefly.workspace import get_sessions_dir


def get_session_dir(workspace: str | Path | None = None) -> Path:
    """Return the Firefly sessions directory."""
    session_dir = get_sessions_dir(workspace)
    session_dir.mkdir(parents=True, exist_ok=True)
    return session_dir


def get_desktop_conversations_path(workspace: str | Path | None = None) -> Path:
    return get_session_dir(workspace) / "desktop_conversations.json"


def load_desktop_conversations(workspace: str | Path | None = None) -> tuple[list[dict[str, Any]], int]:
    path = get_desktop_conversations_path(workspace)
    if not path.exists():
        return _default_desktop_conversations(), 0
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return _default_desktop_conversations(), 0
    conversations = _sanitize_desktop_conversations(payload.get("conversations") if isinstance(payload, dict) else None)
    raw_index = payload.get("current_index") if isinstance(payload, dict) else 0
    current_index = raw_index if isinstance(raw_index, int) else 0
    current_index = min(max(current_index, 0), len(conversations) - 1)
    return conversations, current_index


def save_desktop_conversations(
    workspace: str | Path | None,
    conversations: list[dict[str, Any]],
    current_index: int,
) -> Path:
    path = get_desktop_conversations_path(workspace)
    data = {
        "app": "firefly",
        "version": 1,
        "current_index": min(max(current_index, 0), max(len(conversations) - 1, 0)),
        "updated_at": time.time(),
        "conversations": _sanitize_desktop_conversations(conversations),
    }
    atomic_write_text(path, json.dumps(data, ensure_ascii=False, indent=2) + "\n")
    return path


def _default_desktop_conversations() -> list[dict[str, Any]]:
    return [{"title": "对话 1", "history": [], "messages": []}]


def _sanitize_desktop_conversations(raw: object) -> list[dict[str, Any]]:
    conversations: list[dict[str, Any]] = []
    if isinstance(raw, list):
        for index, item in enumerate(raw):
            if not isinstance(item, dict):
                continue
            conversations.append(
                {
                    "title": str(item.get("title") or f"对话 {index + 1}")[:64],
                    "history": _sanitize_chat_messages(item.get("history")),
                    "messages": _sanitize_chat_messages(item.get("messages")),
                }
            )
    return conversations or _default_desktop_conversations()


def _sanitize_chat_messages(raw: object) -> list[dict[str, str]]:
    messages: list[dict[str, str]] = []
    if not isinstance(raw, list):
        return messages
    for item in raw:
        if not isinstance(item, dict):
            continue
        role = str(item.get("role") or "").strip()
        content = item.get("content")
        if role and content is not None:
            message = {"role": role, "content": str(content)}
            timestamp = str(item.get("timestamp") or "").strip()
            if timestamp:
                message["timestamp"] = timestamp
            messages.append(message)
    return messages


def save_session_snapshot(
    *,
    cwd: str | Path,
    workspace: str | Path | None = None,
    model: str,
    system_prompt: str,
    messages: list[ConversationMessage],
    usage: UsageSnapshot,
    session_id: str | None = None,
    session_key: str | None = None,
    tool_metadata: dict[str, object] | None = None,
) -> Path:
    """Persist the latest Firefly session snapshot."""
    return _save_app_session_snapshot(
        app="firefly",
        session_dir=get_session_dir(workspace),
        cwd=cwd,
        model=model,
        system_prompt=system_prompt,
        messages=messages,
        usage=usage,
        session_id=session_id,
        session_key=session_key,
        tool_metadata=tool_metadata,
    )


def load_latest(workspace: str | Path | None = None) -> dict[str, Any] | None:
    return _load_latest_from_dir(get_session_dir(workspace))


def load_latest_for_session_key(workspace: str | Path | None, session_key: str) -> dict[str, Any] | None:
    return _load_latest_for_session_key_from_dir(get_session_dir(workspace), session_key)


def list_snapshots(workspace: str | Path | None = None, limit: int = 20) -> list[dict[str, Any]]:
    return _list_app_session_snapshots(get_session_dir(workspace), limit)


def load_by_id(workspace: str | Path | None, session_id: str) -> dict[str, Any] | None:
    return _load_app_session_by_id(get_session_dir(workspace), session_id)


def export_session_markdown(
    *,
    cwd: str | Path,
    workspace: str | Path | None = None,
    messages: list[ConversationMessage],
) -> Path:
    del cwd
    return _export_app_session_markdown(
        app="Firefly",
        session_dir=get_session_dir(workspace),
        messages=messages,
    )


class FireflySessionBackend(SessionBackend):
    """Session backend rooted in ``.firefly/sessions``."""

    def __init__(self, workspace: str | Path | None = None) -> None:
        self._workspace = workspace

    def get_session_dir(self, cwd: str | Path) -> Path:
        return get_session_dir(self._workspace)

    def save_snapshot(
        self,
        *,
        cwd: str | Path,
        model: str,
        system_prompt: str,
        messages: list[ConversationMessage],
        usage: UsageSnapshot,
        session_id: str | None = None,
        session_key: str | None = None,
        tool_metadata: dict[str, object] | None = None,
    ) -> Path:
        return save_session_snapshot(
            cwd=cwd,
            workspace=self._workspace,
            model=model,
            system_prompt=system_prompt,
            messages=messages,
            usage=usage,
            session_id=session_id,
            session_key=session_key,
            tool_metadata=tool_metadata,
        )

    def load_latest(self, cwd: str | Path) -> dict[str, Any] | None:
        return load_latest(self._workspace)

    def list_snapshots(self, cwd: str | Path, limit: int = 20) -> list[dict[str, Any]]:
        return list_snapshots(self._workspace, limit=limit)

    def load_by_id(self, cwd: str | Path, session_id: str) -> dict[str, Any] | None:
        return load_by_id(self._workspace, session_id)

    def load_latest_for_session_key(self, session_key: str) -> dict[str, Any] | None:
        return load_latest_for_session_key(self._workspace, session_key)

    def export_markdown(
        self,
        *,
        cwd: str | Path,
        messages: list[ConversationMessage],
    ) -> Path:
        return export_session_markdown(cwd=cwd, workspace=self._workspace, messages=messages)


class NullSessionBackend(SessionBackend):
    def get_session_dir(self, cwd: str | Path) -> Path:
        return Path(os.devnull)

    def save_snapshot(
        self,
        *,
        cwd: str | Path,
        model: str,
        system_prompt: str,
        messages: list[ConversationMessage],
        usage: UsageSnapshot,
        session_id: str | None = None,
        tool_metadata: dict[str, object] | None = None,
    ) -> Path:
        return Path(os.devnull)

    def load_latest(self, cwd: str | Path) -> dict[str, Any] | None:
        return None

    def list_snapshots(self, cwd: str | Path, limit: int = 20) -> list[dict[str, Any]]:
        return []

    def load_by_id(self, cwd: str | Path, session_id: str) -> dict[str, Any] | None:
        return None

    def export_markdown(
        self,
        *,
        cwd: str | Path,
        messages: list[ConversationMessage],
    ) -> Path:
        return Path(os.devnull)
