from pathlib import Path

from firefly.session_storage import FireflySessionBackend, get_session_dir
from firefly.workspace import initialize_workspace
from openharness.api.usage import UsageSnapshot
from openharness.engine.messages import ConversationMessage


def test_firefly_session_backend_preserves_app_and_session_key(tmp_path: Path) -> None:
    workspace = initialize_workspace(tmp_path / ".firefly-home")
    backend = FireflySessionBackend(workspace)
    message = ConversationMessage.from_user_text("hello firefly")

    backend.save_snapshot(
        cwd=tmp_path,
        model="gpt-5.4",
        system_prompt="system",
        messages=[message],
        usage=UsageSnapshot(),
        session_id="abc123",
        session_key="desktop:chat-1",
    )

    loaded = backend.load_latest_for_session_key("desktop:chat-1")
    transcript = backend.export_markdown(cwd=tmp_path, messages=[message])

    assert get_session_dir(workspace) == workspace / "sessions"
    assert loaded is not None
    assert loaded["app"] == "firefly"
    assert loaded["session_id"] == "abc123"
    assert transcript.read_text(encoding="utf-8").startswith("# Firefly Session Transcript")
