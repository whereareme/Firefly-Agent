"""Persistent Galgame playback settings, read history, and optional Windows audio."""

from __future__ import annotations

import ctypes
import hashlib
import json
import os
import tempfile
import threading
import time
from pathlib import Path

from .state import StoryLine


DEFAULT_PLAYBACK_SETTINGS = {
    "text_speed_ms": 24,
    "auto_wait_ms": 1_100,
    "bgm_volume": 70,
    "ambient_volume": 55,
}
MAX_READ_LINES = 8_000


def story_line_key(line: StoryLine) -> str:
    payload = json.dumps(line.to_dict(), ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:24]


def is_cinematic_line(line: StoryLine) -> bool:
    text = line.text
    return line.speaker == "旁白" and any(word in text for word in (
        "离开", "走出", "来到", "抵达", "到达", "回到", "沉默", "安静", "没有说话", "停顿",
        "列车", "雨停", "夕阳", "回过头",
    ))


class StoryPlaybackStore:
    def __init__(self, data_dir: str | Path) -> None:
        self.path = Path(os.path.abspath(data_dir)) / "story-playback.json"
        self._lock = threading.RLock()

    def load(self) -> dict[str, object]:
        with self._lock:
            try:
                value = json.loads(self.path.read_text(encoding="utf-8"))
            except FileNotFoundError:
                return self.save({"version": 1, **DEFAULT_PLAYBACK_SETTINGS, "read_lines": []})
            except (OSError, UnicodeDecodeError, json.JSONDecodeError):
                return {"version": 1, **DEFAULT_PLAYBACK_SETTINGS, "read_lines": []}
            try:
                return self._validate(value)
            except ValueError:
                return self.save({"version": 1, **DEFAULT_PLAYBACK_SETTINGS, "read_lines": []})

    def save(self, value: dict[str, object]) -> dict[str, object]:
        value = self._validate(value)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = (json.dumps(value, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
        with self._lock:
            descriptor, name = tempfile.mkstemp(dir=self.path.parent, prefix=".story-playback.", suffix=".tmp")
            try:
                with os.fdopen(descriptor, "wb") as file:
                    file.write(payload)
                    file.flush()
                    os.fsync(file.fileno())
                os.replace(name, self.path)
            finally:
                if os.path.exists(name):
                    os.unlink(name)
        return value

    def update_settings(self, **changes: int) -> dict[str, object]:
        value = self.load()
        for key in DEFAULT_PLAYBACK_SETTINGS:
            if key in changes:
                value[key] = changes[key]
        return self.save(value)

    def is_read(self, line: StoryLine) -> bool:
        return story_line_key(line) in self.load()["read_lines"]

    def mark_read(self, line: StoryLine) -> None:
        value = self.load()
        key = story_line_key(line)
        read = list(value["read_lines"])
        if key not in read:
            read.append(key)
            value["read_lines"] = read[-MAX_READ_LINES:]
            self.save(value)

    @staticmethod
    def _validate(value: object) -> dict[str, object]:
        expected = {"version", *DEFAULT_PLAYBACK_SETTINGS, "read_lines"}
        if not isinstance(value, dict) or set(value) != expected or value["version"] != 1:
            raise ValueError("story playback settings are invalid")
        limits = {
            "text_speed_ms": (5, 100),
            "auto_wait_ms": (300, 4_000),
            "bgm_volume": (0, 100),
            "ambient_volume": (0, 100),
        }
        for key, (minimum, maximum) in limits.items():
            if type(value[key]) is not int or not minimum <= value[key] <= maximum:
                raise ValueError("story playback setting is outside its limit")
        read = value["read_lines"]
        if (
            not isinstance(read, list)
            or len(read) > MAX_READ_LINES
            or any(not isinstance(item, str) or len(item) != 24 for item in read)
            or len(set(read)) != len(read)
        ):
            raise ValueError("story read history is invalid")
        return value


class StoryAudioPlayer:
    """Use native Windows MCI; other platforms stay silent without affecting playback."""

    def __init__(self) -> None:
        self._send = getattr(getattr(ctypes, "windll", None), "winmm", None)
        self._alias: str | None = None
        self._path: str | None = None
        self._token = 0
        self._lock = threading.Lock()

    def play(self, path: str | Path, volume: int) -> None:
        path = str(Path(path).resolve())
        if self._send is None or not Path(path).is_file():
            return
        with self._lock:
            if path == self._path:
                self._set_volume(self._alias, volume)
                return
            self._token += 1
            token = self._token
            old_alias = self._alias
            alias = f"firefly_bgm_{token}"
            if self._command(f'open "{path}" type waveaudio alias {alias}'):
                return
            self._command(f"setaudio {alias} volume to 0")
            self._command(f"play {alias} repeat")
            self._alias, self._path = alias, path
        threading.Thread(
            target=self._crossfade,
            args=(token, old_alias, alias, max(0, min(100, volume))),
            name="story-bgm-crossfade",
            daemon=True,
        ).start()

    def set_volume(self, volume: int) -> None:
        with self._lock:
            self._set_volume(self._alias, volume)

    def stop(self) -> None:
        with self._lock:
            self._token += 1
            alias, self._alias, self._path = self._alias, None, None
        if alias:
            self._command(f"stop {alias}")
            self._command(f"close {alias}")

    def _crossfade(self, token: int, old_alias: str | None, alias: str, volume: int) -> None:
        for step in range(1, 11):
            with self._lock:
                if token != self._token:
                    return
            self._set_volume(alias, round(volume * step / 10))
            if old_alias:
                self._set_volume(old_alias, round(volume * (10 - step) / 10))
            time.sleep(0.05)
        if old_alias:
            self._command(f"stop {old_alias}")
            self._command(f"close {old_alias}")

    def _set_volume(self, alias: str | None, volume: int) -> None:
        if alias:
            self._command(f"setaudio {alias} volume to {max(0, min(100, int(volume))) * 10}")

    def _command(self, command: str) -> int:
        if self._send is None:
            return 1
        return int(self._send.mciSendStringW(command, None, 0, None))
