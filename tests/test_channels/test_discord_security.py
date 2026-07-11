"""Security regressions for Discord channel media handling."""

from __future__ import annotations

from pathlib import Path

import pytest

from openharness.channels.bus.queue import MessageBus
from openharness.channels.impl.discord import DiscordChannel
from openharness.config.schema import DiscordConfig


class _FakeResponse:
    content = b"ATTACKER_OVERWRITE"

    def raise_for_status(self) -> None:
        return None


class _FakeHttp:
    async def get(self, url: str) -> _FakeResponse:
        assert url == "https://cdn.example/file"
        return _FakeResponse()


@pytest.mark.asyncio
async def test_discord_attachment_filename_cannot_escape_media_dir(tmp_path: Path, monkeypatch):
    workspace = tmp_path / "ohmo"
    workspace.mkdir()
    protected_file = workspace / "soul.md"
    protected_file.write_text("ORIGINAL", encoding="utf-8")
    monkeypatch.setenv("OHMO_WORKSPACE", str(workspace))

    channel = DiscordChannel(DiscordConfig(allow_from=["user-id"]), MessageBus())
    channel._http = _FakeHttp()

    async def fake_start_typing(channel_id: str) -> None:
        assert channel_id == "channel-id"

    monkeypatch.setattr(channel, "_start_typing", fake_start_typing)

    forwarded = {}

    async def fake_handle_message(**kwargs):
        forwarded.update(kwargs)

    monkeypatch.setattr(channel, "_handle_message", fake_handle_message)

    await channel._handle_message_create(
        {
            "id": "message-id",
            "channel_id": "channel-id",
            "content": "",
            "author": {"id": "user-id", "bot": False},
            "attachments": [
                {
                    "id": "../../attachment-id",
                    "url": "https://cdn.example/file",
                    "filename": "../../soul.md",
                    "size": 10,
                }
            ],
        }
    )

    media_dir = (workspace / "attachments" / "discord").resolve()
    saved_paths = [Path(path).resolve() for path in forwarded["media"]]
    assert protected_file.read_text(encoding="utf-8") == "ORIGINAL"
    assert saved_paths == [media_dir / "attachment-id_soul.md"]
    assert saved_paths[0].read_bytes() == b"ATTACKER_OVERWRITE"
    assert saved_paths[0].is_relative_to(media_dir)
    assert "../" not in forwarded["content"]
