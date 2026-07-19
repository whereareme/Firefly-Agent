"""Generate the four small loopable chapter-one BGM variants."""

from __future__ import annotations

import math
import random
import struct
import wave
from pathlib import Path


RATE = 22_050
ROOT = Path(__file__).resolve().parents[1] / "relationship_gateway" / "assets" / "galgame" / "chapter-01" / "audio" / "bgm"
AMBIENT_ROOT = ROOT.parent / "ambient"
CHORDS = {
    "Cmaj7": (48, 55, 59, 64),
    "Am7": (45, 52, 55, 60),
    "Fmaj7": (41, 48, 52, 57),
    "Gsus": (43, 50, 55, 60),
    "Dm7": (38, 45, 48, 53),
}
MOTIF = (64, 67, 69, 67, 64, 62, 64, 67)


def frequency(note: int) -> float:
    return 440.0 * 2 ** ((note - 69) / 12)


def envelope(position: float, length: float, attack: float = 0.08, release: float = 0.26) -> float:
    return min(1.0, position / attack, max(0.0, (length - position) / release))


def tone(note: int, time_value: float, position: float, length: float, brightness: float = 0.25) -> float:
    phase = 2 * math.pi * frequency(note) * time_value
    body = math.sin(phase) + brightness * math.sin(phase * 2) + brightness * 0.12 * math.sin(phase * 3)
    return body * envelope(position, length)


def render(name: str, *, bpm: int, progression: tuple[str, ...], sparse: int, warmth: float, ending: bool = False) -> None:
    beat_length = 60 / bpm
    beats = 32
    duration = beat_length * beats
    samples = int(duration * RATE)
    output = bytearray()
    for index in range(samples):
        current = index / RATE
        beat = min(beats - 1, int(current / beat_length))
        beat_position = current - beat * beat_length
        chord = CHORDS[progression[(beat // 4) % len(progression)]]
        chord_gain = envelope(beat_position, beat_length, 0.16, 0.22)
        value = sum(math.sin(2 * math.pi * frequency(note) * current) for note in chord) * 0.045 * warmth * chord_gain
        if beat % sparse == 0:
            note = MOTIF[beat % len(MOTIF)] + (12 if ending and beat >= 24 else 0)
            value += tone(note, current, beat_position, beat_length, 0.32) * (0.20 if ending else 0.16)
        if beat % 4 == 0:
            value += tone(chord[0] - 12, current, beat_position, beat_length * 2, 0.08) * 0.10
        master_fade = min(1.0, current / 0.18, max(0.0, (duration - current) / 0.18))
        sample = max(-1.0, min(1.0, value * master_fade))
        output.extend(struct.pack("<h", round(sample * 32767)))
    ROOT.mkdir(parents=True, exist_ok=True)
    with wave.open(str(ROOT / name), "wb") as target:
        target.setnchannels(1)
        target.setsampwidth(2)
        target.setframerate(RATE)
        target.writeframes(output)


def render_ambient(name: str, kind: str) -> None:
    duration = 20
    samples = duration * RATE
    output = bytearray()
    randomizer = random.Random(42)
    smooth_noise = 0.0
    for index in range(samples):
        current = index / RATE
        noise = randomizer.uniform(-1, 1)
        smooth_noise = smooth_noise * 0.94 + noise * 0.06
        if kind == "rain":
            value = noise * 0.045 + smooth_noise * 0.10
        elif kind == "cafe":
            clink_position = current % 5.0
            clink = math.sin(2 * math.pi * 1500 * current) * max(0.0, 1 - clink_position / 0.08) if clink_position < 0.08 else 0.0
            value = smooth_noise * 0.055 + math.sin(2 * math.pi * 82 * current) * 0.012 + clink * 0.045
        elif kind == "station":
            chime_position = current % 8.0
            chime = math.sin(2 * math.pi * 660 * current) * max(0.0, 1 - chime_position / 0.5) if chime_position < 0.5 else 0.0
            value = smooth_noise * 0.045 + math.sin(2 * math.pi * 55 * current) * 0.018 + chime * 0.025
        else:
            value = smooth_noise * 0.06 + math.sin(2 * math.pi * (42 + 4 * math.sin(current / 3)) * current) * 0.012
        master_fade = min(1.0, current / 0.18, max(0.0, (duration - current) / 0.18))
        output.extend(struct.pack("<h", round(max(-1.0, min(1.0, value * master_fade)) * 32767)))
    AMBIENT_ROOT.mkdir(parents=True, exist_ok=True)
    with wave.open(str(AMBIENT_ROOT / name), "wb") as target:
        target.setnchannels(1)
        target.setsampwidth(2)
        target.setframerate(RATE)
        target.writeframes(output)


def main() -> None:
    render("firefly_theme_daily.wav", bpm=80, progression=("Cmaj7", "Am7", "Fmaj7", "Gsus"), sparse=1, warmth=0.95)
    render("firefly_theme_hesitant.wav", bpm=72, progression=("Am7", "Fmaj7", "Dm7", "Gsus"), sparse=2, warmth=0.62)
    render("firefly_theme_repair.wav", bpm=76, progression=("Fmaj7", "Cmaj7", "Am7", "Gsus"), sparse=1, warmth=0.82)
    render("firefly_theme_ending.wav", bpm=82, progression=("Cmaj7", "Fmaj7", "Am7", "Gsus"), sparse=1, warmth=1.15, ending=True)
    render_ambient("rain.wav", "rain")
    render_ambient("cafe.wav", "cafe")
    render_ambient("street.wav", "street")
    render_ambient("station.wav", "station")


if __name__ == "__main__":
    main()
