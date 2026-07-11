"""Workspace helpers for the Firefly app."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Mapping

WORKSPACE_DIRNAME = ".firefly"

IDENTITY_TEMPLATE = """# IDENTITY.md - Firefly

- Name: Firefly
- Kind: OpenHarness personal-agent app
- Persona source: `firefly/data/character/firefly.persona.json`
"""

USER_TEMPLATE = """# user.md - About The User

Keep only durable preferences that help Firefly respond better.
"""


def get_workspace_root(workspace: str | Path | None = None) -> Path:
    explicit = workspace or os.environ.get("FIREFLY_WORKSPACE")
    if explicit:
        return Path(explicit).expanduser().resolve()
    return (Path.home() / WORKSPACE_DIRNAME).resolve()


def get_sessions_dir(workspace: str | Path | None = None) -> Path:
    return get_workspace_root(workspace) / "sessions"


def get_logs_dir(workspace: str | Path | None = None) -> Path:
    return get_workspace_root(workspace) / "logs"


def get_identity_path(workspace: str | Path | None = None) -> Path:
    return get_workspace_root(workspace) / "identity.md"


def get_user_path(workspace: str | Path | None = None) -> Path:
    return get_workspace_root(workspace) / "user.md"


def get_state_path(workspace: str | Path | None = None) -> Path:
    return get_workspace_root(workspace) / "state.json"


def get_config_path(workspace: str | Path | None = None) -> Path:
    return get_workspace_root(workspace) / "config.json"


DEFAULT_CONFIG: dict[str, object] = {
    "llm_base_url": "https://api.openai.com/v1",
    "llm_model": "gpt-4o-mini",
    "llm_api_key": "",
    "provider_profile": "",
    "model": "",
    "image_generation_model": "",
    "max_turns": None,
    "library_locations": [],
    "library_allow_read": True,
    "library_allow_write": False,
    "library_max_hits": 5,
    "library_context_max_chars": 6000,
    "library_max_scan_files": 250,
    "library_max_file_bytes": 5_000_000,
    "library_index_enabled": True,
    "library_index_max_files": 500,
    "library_index_max_chars_per_file": 20_000,
    "web_search_enabled": False,
    "web_search_auto": True,
    "web_search_max_results": 5,
    "web_search_url": "",
    "web_fetch_enabled": True,
    "web_fetch_max_chars": 6000,
    "skills_enabled": False,
    "skills_root": "",
    "skills_context_max_matches": 3,
    "permission_mode": "default",
    "sandbox_enabled": False,
    "sandbox_backend": "srt",
    "sandbox_fail_if_unavailable": False,
    "desktop_control_enabled": False,
    "autostart_enabled": False,
    "firefly_watch_enabled": False,
    "firefly_watch_interval_sec": 300,
    "chat_window_context_enabled": False,
    "chat_timeout_sec": 300,
    "theme_mode": "system",
    "starfire_music_dir": "",
    "starfire_music_mode": "sequence",
    "memory_enabled": False,
    "memory_context_link_enabled": True,
    "everos_memory_enabled": True,
    "memory_base_url": "http://127.0.0.1:8000",
    "memory_user_id": "firefly_user",
    "memory_app_id": "fire-agent",
    "memory_project_id": "default",
    "memory_session_id": "fire-agent-default",
    "memory_method": "agentic",
    "memory_fallback_method": "keyword",
    "memory_top_k": 8,
    "memory_flush_each_turn": True,
    "memory_timeout_sec": 8,
    "memory_local_fallback_enabled": True,
    "memory_local_fallback_path": "",
    "memory_local_fallback_max_tokens": 1_000_000,
    "openharness_memdir_enabled": True,
    "openharness_session_memory_enabled": True,
    "openharness_memory_cwd": "",
    "openharness_memory_max_results": 5,
    "openharness_session_id": "firefly",
    "openharness_session_memory_path": "",
}


def load_config(workspace: str | Path | None = None) -> dict[str, object]:
    path = get_config_path(workspace)
    if not path.exists():
        return dict(DEFAULT_CONFIG)
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return dict(DEFAULT_CONFIG)
    if not isinstance(data, dict):
        return dict(DEFAULT_CONFIG)
    config = dict(DEFAULT_CONFIG)
    config.update(data)
    return config


def save_config(config: Mapping[str, object], workspace: str | Path | None = None) -> Path:
    path = get_config_path(workspace)
    path.parent.mkdir(parents=True, exist_ok=True)
    merged = dict(DEFAULT_CONFIG)
    merged.update(config)
    path.write_text(json.dumps(merged, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return path


def initialize_workspace(workspace: str | Path | None = None) -> Path:
    root = get_workspace_root(workspace)
    root.mkdir(parents=True, exist_ok=True)
    get_sessions_dir(root).mkdir(parents=True, exist_ok=True)
    get_logs_dir(root).mkdir(parents=True, exist_ok=True)
    templates = {
        get_identity_path(root): IDENTITY_TEMPLATE,
        get_user_path(root): USER_TEMPLATE,
    }
    for path, content in templates.items():
        if not path.exists():
            path.write_text(content.strip() + "\n", encoding="utf-8")
    state_path = get_state_path(root)
    if not state_path.exists():
        state_path.write_text(
            json.dumps({"app": "firefly", "workspace": str(root)}, indent=2) + "\n",
            encoding="utf-8",
        )
    config_path = get_config_path(root)
    if not config_path.exists():
        save_config(DEFAULT_CONFIG, root)
    return root


def workspace_health(workspace: str | Path | None = None) -> dict[str, bool]:
    root = get_workspace_root(workspace)
    return {
        "workspace": root.exists(),
        "sessions_dir": get_sessions_dir(root).exists(),
        "logs_dir": get_logs_dir(root).exists(),
        "identity": get_identity_path(root).exists(),
        "user": get_user_path(root).exists(),
        "state": get_state_path(root).exists(),
        "config": get_config_path(root).exists(),
    }
