"""CLI entry point for the Firefly app."""

from __future__ import annotations

import json
import platform
import sys
import importlib.util
from pathlib import Path

import typer

from firefly import __version__
from firefly.live2d.module import Live2DModule
from firefly.persona import CharacterModule
from firefly.prompts import DEFAULT_PERSONA_PATH
from firefly.workspace import get_workspace_root, initialize_workspace, workspace_health

PACKAGE_ROOT = Path(__file__).resolve().parent
REPO_ROOT = PACKAGE_ROOT.parent
LIVE2D_ROOT = PACKAGE_ROOT / "assets" / "live2d"

for _stream in (sys.stdout, sys.stderr):
    if hasattr(_stream, "reconfigure"):
        _stream.reconfigure(encoding="utf-8")

app = typer.Typer(
    name="firefly",
    help="Firefly personal-agent app built on OpenHarness.",
    invoke_without_command=True,
    add_completion=False,
)


def _module_available(name: str) -> bool:
    return importlib.util.find_spec(name) is not None


@app.callback(invoke_without_command=True)
def main(
    ctx: typer.Context,
    print_mode: str | None = typer.Option(None, "--print", "-p", help="Run one prompt and exit"),
    model: str | None = typer.Option(None, "--model", help="Model override for this session"),
    profile: str | None = typer.Option(None, "--profile", help="OpenHarness provider profile"),
    workspace: str | None = typer.Option(None, "--workspace", help="Path to the Firefly workspace"),
    max_turns: int | None = typer.Option(None, "--max-turns", help="Override max turns"),
    cwd: str = typer.Option(str(Path.cwd()), "--cwd", help="Working directory"),
    version: bool = typer.Option(False, "--version", help="Show version and exit"),
) -> None:
    if version:
        print(f"firefly {__version__}")
        raise typer.Exit()
    if ctx.invoked_subcommand is not None:
        return
    if print_mode is not None:
        try:
            from firefly.runtime import run_firefly_print_mode
        except ImportError as error:
            print(f"OpenHarness dependencies are not installed: {error}", file=sys.stderr)
            print("Install this repo first, for example with `uv sync`.", file=sys.stderr)
            raise typer.Exit(1) from error

        raise typer.Exit(
            run_firefly_print_mode(
                prompt=print_mode,
                cwd=cwd,
                workspace=workspace,
                model=model,
                max_turns=max_turns,
                provider_profile=profile,
            )
        )
    print(ctx.get_help())
    raise typer.Exit()


@app.command("init")
def init_cmd(workspace: str | None = typer.Option(None, "--workspace", help="Path to the Firefly workspace")) -> None:
    root = initialize_workspace(workspace)
    print(f"Initialized Firefly workspace at {root}")


@app.command("config")
def config_cmd(workspace: str | None = typer.Option(None, "--workspace", help="Path to the Firefly workspace")) -> None:
    root = initialize_workspace(workspace)
    print(f"Firefly workspace: {root}")
    try:
        from openharness.auth.manager import AuthManager
        from openharness.config import load_settings

        settings = load_settings()
        statuses = AuthManager(settings).get_profile_statuses()
    except ImportError as error:
        print(f"OpenHarness dependencies are not installed: {error}")
        print("Install this repo first, for example with `uv sync`.")
        return
    print("OpenHarness provider profiles:")
    for name, info in statuses.items():
        state = "ready" if info.get("configured") else "missing auth"
        print(f"- {name}: {info.get('label')} ({state})")
    print("Use `oh setup` or `oh provider` to configure model providers.")


@app.command("check")
def check_cmd(
    workspace: str | None = typer.Option(None, "--workspace", help="Path to the Firefly workspace"),
    json_output: bool = typer.Option(False, "--json", help="Print JSON"),
) -> None:
    root = initialize_workspace(workspace)
    persona = CharacterModule(DEFAULT_PERSONA_PATH)
    live2d = Live2DModule(LIVE2D_ROOT)
    live2d_config = live2d.client_config()
    packages = {
        "openharness": _module_available("openharness"),
        "ohmo": _module_available("ohmo"),
        "firefly": _module_available("firefly"),
        "PySide6": _module_available("PySide6"),
        "QtWebEngine": _module_available("PySide6.QtWebEngineWidgets"),
        "pypdf": _module_available("pypdf"),
    }
    attribution_path = PACKAGE_ROOT / "assets" / "ATTRIBUTION.md"
    attribution_text = attribution_path.read_text(encoding="utf-8", errors="replace") if attribution_path.exists() else ""
    resources = {
        "uvLock": (REPO_ROOT / "uv.lock").exists(),
        "assetAttribution": attribution_path.exists(),
        "live2dAttribution": "Scighost/Firefly" in attribution_text,
        "vendorLicenses": all(marker in attribution_text for marker in ("PixiJS", "pixi-live2d-display", "Live2D Cubism Core")),
    }
    desktop_control = {
        "enabledByDefault": False,
        "platform": platform.system(),
        "windowsSupported": platform.system().lower() == "windows",
    }
    live2d_ok = bool(live2d_config.get("enabled")) and not bool(live2d_config.get("missingAssets") or [])
    resources_ok = all(resources.values())
    payload = {
        "ok": bool(persona.prompt_sections()) and live2d_ok and resources_ok and packages["openharness"] and packages["PySide6"] and packages["QtWebEngine"],
        "workspace": str(root),
        "workspaceHealth": workspace_health(root),
        "persona": {
            "name": persona.persona.name,
            "promptSections": len(persona.prompt_sections()),
            "forbidden": persona.persona.forbidden,
        },
        "live2d": live2d_config,
        "packages": packages,
        "resources": resources,
        "desktopControl": desktop_control,
    }
    if json_output:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        raise typer.Exit(0 if payload["ok"] else 1)
    print("Firefly check")
    print(f"- workspace: {get_workspace_root(root)}")
    print(f"- persona: {persona.persona.name}, prompt sections={len(persona.prompt_sections())}")
    print(
        "- live2d: "
        f"{'enabled' if live2d_config.get('enabled') else 'disabled'}, "
        f"model={live2d_config.get('modelName')}, "
        f"files={live2d_config.get('fileCount')}, "
        f"missing={len(live2d_config.get('missingAssets') or [])}"
    )
    print("- packages: " + ", ".join(f"{name}={'ok' if ok else 'missing'}" for name, ok in packages.items()))
    print("- resources: " + ", ".join(f"{name}={'ok' if ok else 'missing'}" for name, ok in resources.items()))
    print(f"- desktop control: platform={desktop_control['platform']}, windowsSupported={desktop_control['windowsSupported']}")
    print("- desktop: " + ("ready" if packages["PySide6"] and packages["QtWebEngine"] and live2d_ok else "not ready"))
    print("- launch: firefly desktop")
    raise typer.Exit(0 if payload["ok"] else 1)


@app.command("desktop")
def desktop_cmd(
    workspace: str | None = typer.Option(None, "--workspace", help="Path to the Firefly workspace"),
    model: str | None = typer.Option(None, "--model", help="Model override for this session"),
    profile: str | None = typer.Option(None, "--profile", help="OpenHarness provider profile"),
    cwd: str = typer.Option(str(Path.cwd()), "--cwd", help="Working directory"),
) -> None:
    from firefly.desktop.app import main as desktop_main

    raise typer.Exit(desktop_main(cwd=cwd, workspace=workspace, model=model, provider_profile=profile))
