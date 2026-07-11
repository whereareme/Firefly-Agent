"""Starfire music playlist helpers."""

from __future__ import annotations

from pathlib import Path

AUDIO_EXTENSIONS = {".mp3", ".wav", ".ogg", ".m4a", ".flac"}
DEFAULT_STARFIRE_SONG = (
    Path(__file__).resolve().parents[1]
    / "assets"
    / "live2d"
    / "firefly"
    / "sounds"
    / "FileReferences_Motions_表情组_1_Sound_0.mp3"
)
DEFAULT_STARFIRE_SONG_URL = "/assets/live2d/firefly/sounds/FileReferences_Motions_%E8%A1%A8%E6%83%85%E7%BB%84_1_Sound_0.mp3"


def starfire_music_tracks(config: dict[str, object]) -> list[Path]:
    tracks: list[Path] = []
    if DEFAULT_STARFIRE_SONG.exists():
        tracks.append(DEFAULT_STARFIRE_SONG.resolve())
    directory_text = str(config.get("starfire_music_dir") or "").strip()
    directory = Path(directory_text).expanduser() if directory_text else None
    if directory and directory.is_dir():
        for path in sorted(directory.rglob("*")):
            if path.is_file() and path.suffix.lower() in AUDIO_EXTENSIONS:
                tracks.append(path.resolve())
    seen: set[Path] = set()
    unique: list[Path] = []
    for path in tracks:
        if path not in seen:
            seen.add(path)
            unique.append(path)
    return unique
