"""Strict, secret-free configuration for the local gateway."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlparse


PROJECT_ROOT = Path(__file__).resolve().parent.parent


class ConfigError(ValueError):
    """Raised when the local configuration is unsafe or incomplete."""


@dataclass(frozen=True)
class Config:
    host: str
    port: int
    upstream_base_url: str
    data_dir: Path

    def __post_init__(self) -> None:
        """Keep direct construction as constrained as JSON-loaded configuration."""
        if self.host != "127.0.0.1":
            raise ConfigError("host must be 127.0.0.1")

    @classmethod
    def from_mapping(cls, value: object) -> "Config":
        if not isinstance(value, dict):
            raise ConfigError("config must be a JSON object")

        required = {"host", "port", "upstream_base_url", "data_dir"}
        if set(value) != required:
            raise ConfigError("config must contain only host, port, upstream_base_url, and data_dir")

        host = value["host"]
        port = value["port"]
        upstream_base_url = value["upstream_base_url"]
        data_dir = value["data_dir"]
        if not isinstance(port, int) or isinstance(port, bool) or not 1 <= port <= 65535:
            raise ConfigError("port must be an integer from 1 to 65535")
        if not isinstance(upstream_base_url, str):
            raise ConfigError("upstream_base_url must be a string")
        if any(ord(character) < 32 or ord(character) == 127 for character in upstream_base_url):
            raise ConfigError("upstream_base_url must not contain ASCII control characters")
        if "?" in upstream_base_url or "#" in upstream_base_url:
            raise ConfigError("upstream_base_url must not contain query or fragment delimiters")

        try:
            parsed = urlparse(upstream_base_url)
            hostname = parsed.hostname
            upstream_port = parsed.port
        except ValueError as error:
            raise ConfigError("upstream_base_url has an invalid host or port") from error
        if (
            upstream_base_url != upstream_base_url.strip()
            or parsed.scheme not in {"http", "https"}
            or not parsed.netloc
            or not hostname
            or any(character.isspace() for character in hostname)
            or "@" in parsed.netloc
            or parsed.query
            or parsed.fragment
            or parsed.params
            or parsed.netloc.endswith(":")
            or (upstream_port is not None and not 1 <= upstream_port <= 65535)
        ):
            raise ConfigError("upstream_base_url must be an http(s) URL without credentials, query, or fragment")
        if not isinstance(data_dir, str) or not data_dir.strip() or "\0" in data_dir:
            raise ConfigError("data_dir must be a non-empty path")
        configured_data_dir = Path(data_dir)
        if configured_data_dir.is_absolute():
            raise ConfigError("data_dir must be a relative path inside the Sidecar project")
        resolved_base_dir = PROJECT_ROOT.resolve()
        resolved_data_dir = (resolved_base_dir / configured_data_dir).resolve()
        try:
            resolved_data_dir.relative_to(resolved_base_dir)
        except ValueError as error:
            raise ConfigError("data_dir must stay inside the Sidecar project") from error
        if resolved_data_dir == resolved_base_dir:
            raise ConfigError("data_dir must be a directory inside the Sidecar project")
        if resolved_data_dir.exists() and not resolved_data_dir.is_dir():
            raise ConfigError("data_dir must be a directory")
        for ancestor in resolved_data_dir.parents:
            if ancestor.is_file():
                raise ConfigError("data_dir must not have a regular-file ancestor")
            if ancestor == resolved_base_dir:
                break

        return cls(
            host=host,
            port=port,
            upstream_base_url=upstream_base_url.rstrip("/"),
            data_dir=resolved_data_dir,
        )


def load_config(path: str | Path) -> Config:
    """Load and validate a JSON config without accepting API keys."""
    config_path = Path(path)
    try:
        value = json.loads(config_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ConfigError(f"could not load config: {error}") from error
    return Config.from_mapping(value)
