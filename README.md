# Firefly Agent

Firefly Agent is a local desktop AI companion centered on the Firefly character experience.

It brings a Live2D Firefly-inspired companion to the desktop. Users can chat with her, share daily thoughts, keep an ongoing conversation, and enable long-term memory for preferences they choose to retain. The app also provides practical Agent capabilities for reading files, summarizing documents, searching the web, loading skills, and handling simple desktop tasks with explicit permissions.

This is an unofficial fan-made project, not an official HoYoverse application or service.

中文说明：[README.zh-CN.md](README.zh-CN.md)

## What It Does

- Live2D desktop companion with chat and interaction
- Firefly-inspired persona and configurable conversation behavior
- Session history and optional long-term memory through EverOS
- File upload, document reading, local library indexing, and summaries
- Optional web search for current external information
- Skills, model profiles, and permission settings
- Optional Windows desktop awareness and simple computer controls
- Local workspace and session storage

The project is built on [OpenHarness](https://github.com/HKUDS/OpenHarness), which provides the underlying Agent loop, tools, skills, memory, providers, permissions, and multi-agent infrastructure.

## Quick Start

Requirements: Windows, Python 3.10+, and `uv`.

```powershell
uv sync --extra dev
uv run firefly check
uv run firefly desktop
```

On Windows, you can also run:

```powershell
.\启动流萤桌面.cmd
```

`firefly check` validates the workspace, persona data, Live2D assets, Qt dependencies, document support, resource attribution, and lockfile before launch.

## Project Layout

```text
firefly/                 Firefly desktop app and runtime
firefly/assets/           Live2D, UI, and attribution files
src/openharness/          Agent infrastructure used by Firefly
tests/                    OpenHarness and Firefly tests
启动流萤桌面.cmd           Windows desktop launcher
```

## Design Direction

Firefly Agent is designed as a companion first and a tool second. The Live2D character, tone, memory, and interaction should feel present and personal; file handling, search, skills, and task execution exist to make that companionship useful in everyday work and study.

## Memory Experience

Firefly Agent can connect to [EverOS](https://github.com/EverMind-AI/EverOS) as its long-term memory service. EverOS helps store and retrieve user-approved preferences, facts, and conversation context across sessions. This makes the companion more continuous: Firefly can better remember how the user likes to interact, pick up previous topics, and provide responses that feel less like a fresh chat every time.

EverOS is optional. When it is unavailable, Firefly Agent can fall back to local memory and session storage according to the configured settings.

## Attribution

- Live2D and bundled resource attribution: [firefly/assets/ATTRIBUTION.md](firefly/assets/ATTRIBUTION.md)
- Agent infrastructure: [OpenHarness](https://github.com/HKUDS/OpenHarness)
- Long-term memory service: [EverOS](https://github.com/EverMind-AI/EverOS)
- Firefly persona reference: [HeartEase1/firefly-skill](https://github.com/HeartEase1/firefly-skill)
- Character inspiration: Firefly from *Honkai: Star Rail*

Please review the attribution and license files before redistributing bundled assets.
