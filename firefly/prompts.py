"""Prompt assembly for Firefly."""

from __future__ import annotations

from pathlib import Path

from openharness.prompts.system_prompt import get_base_system_prompt

from firefly.persona import CharacterModule

PACKAGE_ROOT = Path(__file__).resolve().parent
DEFAULT_PERSONA_PATH = PACKAGE_ROOT / "data" / "character" / "firefly.persona.json"


def build_firefly_system_prompt(
    cwd: str | Path,
    *,
    persona_path: str | Path | None = None,
    extra_prompt: str | None = None,
) -> str:
    persona = CharacterModule(Path(persona_path) if persona_path else DEFAULT_PERSONA_PATH)
    sections = [
        get_base_system_prompt(),
        "# Firefly Persona",
        persona.system_prompt(),
        "# Firefly App Boundary",
        "\n".join(
            [
                "- You are running as the Firefly personal-agent app on top of OpenHarness.",
                "- Keep OpenHarness tool use, permission handling, and task execution behavior intact.",
                "- Do not claim local reader, memory, skill management UI, or computer-control migration is complete unless tools prove it.",
                f"- Current working directory: {Path(cwd).resolve()}",
            ]
        ),
    ]
    if extra_prompt:
        sections.extend(["# Additional Firefly Instructions", extra_prompt.strip()])
    return "\n\n".join(section for section in sections if section.strip())
