from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

MUTED_MOTION_SOUNDS = {"表情组:点燃星海（点击）"}


@dataclass
class Live2DAsset:
    type: str
    path: str
    exists: bool


@dataclass
class Live2DManifest:
    model_path: Path
    model_url: str
    model_name: str
    assets: list[Live2DAsset]
    expression_names: list[str]
    motion_groups: dict[str, list[str]]
    motion_durations: dict[str, float]
    motion_sounds: dict[str, str]
    motion_sound_delays: dict[str, int]

    @property
    def missing_assets(self) -> list[str]:
        return [asset.path for asset in self.assets if not asset.exists]

    @property
    def valid(self) -> bool:
        return self.model_path.exists() and not self.missing_assets


class Live2DModule:
    def __init__(self, asset_root: Path, configured_model: str | None = None):
        self.asset_root = asset_root.resolve()
        self.asset_root.mkdir(parents=True, exist_ok=True)
        self.configured_model = configured_model

    def client_config(self) -> dict[str, object]:
        external_model_url = self._configured_external_model_url()
        if external_model_url:
            config = self._empty_config()
            config.update(
                {
                    "enabled": True,
                    "modelUrl": external_model_url,
                    "modelName": Path(urlparse(external_model_url).path).name or "configured-model",
                    "message": "Live2D model configured by URL",
                }
            )
            return config

        model_path = self._configured_model_path() or self._discover_model_path()
        if not model_path:
            return self._empty_config()

        manifest = self._build_manifest(model_path)
        return {
            "enabled": manifest.valid,
            "modelUrl": manifest.model_url,
            "assetRoot": "/assets/live2d/",
            "canvasId": "firefly-live2d",
            "runtimeCoreUrl": "/assets/live2d/Core/live2dcubismcore.min.js",
            "modelName": manifest.model_name,
            "modelDirectory": model_path.parent.relative_to(self.asset_root).as_posix(),
            "fileCount": len(manifest.assets),
            "missingAssets": manifest.missing_assets,
            "textureCount": sum(1 for asset in manifest.assets if asset.type == "texture"),
            "motionGroups": manifest.motion_groups,
            "motionDurations": manifest.motion_durations,
            "motionSounds": manifest.motion_sounds,
            "motionSoundDelays": manifest.motion_sound_delays,
            "expressionNames": manifest.expression_names,
            "source": {
                "repository": "Scighost/Firefly",
                "url": "https://github.com/Scighost/Firefly",
                "commit": "2d92ce5b2394cd993828b91afad6545156f14927",
            },
            "message": "Live2D model ready" if manifest.valid else "Live2D model has missing assets",
        }

    def _empty_config(self) -> dict[str, object]:
        return {
            "enabled": False,
            "modelUrl": None,
            "assetRoot": "/assets/live2d/",
            "canvasId": "firefly-live2d",
            "runtimeCoreUrl": "/assets/live2d/Core/live2dcubismcore.min.js",
            "modelName": None,
            "modelDirectory": None,
            "fileCount": 0,
            "missingAssets": [],
            "textureCount": 0,
            "motionGroups": {},
            "motionDurations": {},
            "motionSounds": {},
            "motionSoundDelays": {},
            "expressionNames": [],
            "source": None,
            "message": "Live2D assets are not installed yet",
        }

    def _configured_model_path(self) -> Path | None:
        if not self.configured_model:
            return None
        parsed = urlparse(self.configured_model)
        if parsed.scheme in {"http", "https"} or self.configured_model.startswith("/"):
            return None

        candidate = Path(self.configured_model).expanduser()
        if not candidate.is_absolute():
            candidate = self.asset_root / candidate
        candidate = candidate.resolve()
        if candidate.exists() and candidate.is_file() and candidate.is_relative_to(self.asset_root):
            return candidate
        return None

    def _configured_external_model_url(self) -> str | None:
        if not self.configured_model:
            return None
        parsed = urlparse(self.configured_model)
        if parsed.scheme in {"http", "https"} or self.configured_model.startswith("/"):
            return self.configured_model
        return None

    def _discover_model_path(self) -> Path | None:
        patterns = ("*.model3.json", "*.model.json", "model3.json", "model.json")
        candidates: list[Path] = []
        for pattern in patterns:
            candidates.extend(path for path in self.asset_root.rglob(pattern) if path.is_file())
        if not candidates:
            return None
        candidates.sort(key=self._model_sort_key)
        return candidates[0].resolve()

    def _model_sort_key(self, path: Path) -> tuple[int, int, str]:
        relative = path.resolve().relative_to(self.asset_root).as_posix()
        firefly_rank = 0 if relative.startswith("firefly/") else 1
        return (firefly_rank, len(path.parts), relative)

    def _build_manifest(self, model_path: Path) -> Live2DManifest:
        model_path = model_path.resolve()
        data = self._load_model_json(model_path)
        references = data.get("FileReferences", {}) if isinstance(data, dict) else {}
        if not isinstance(references, dict):
            references = {}

        assets = self._collect_referenced_assets(model_path.parent, references)
        return Live2DManifest(
            model_path=model_path,
            model_url=self._asset_url(model_path),
            model_name=model_path.stem.removesuffix(".model3"),
            assets=assets,
            expression_names=self._expression_names(references),
            motion_groups=self._motion_groups(model_path.parent, references),
            motion_durations=self._motion_durations(model_path.parent, references),
            motion_sounds=self._motion_sounds(references),
            motion_sound_delays=self._motion_sound_delays(references),
        )

    def _load_model_json(self, model_path: Path) -> dict[str, Any]:
        try:
            data = json.loads(model_path.read_text(encoding="utf-8-sig"))
        except json.JSONDecodeError:
            return {}
        return data if isinstance(data, dict) else {}

    def _collect_referenced_assets(self, model_dir: Path, references: dict[str, Any]) -> list[Live2DAsset]:
        assets: list[Live2DAsset] = []

        self._add_asset(assets, model_dir, "moc", references.get("Moc"))
        self._add_asset(assets, model_dir, "physics", references.get("Physics"))
        physics_v2 = references.get("PhysicsV2")
        if isinstance(physics_v2, dict):
            self._add_asset(assets, model_dir, "physics", physics_v2.get("File"))

        for texture in self._as_list(references.get("Textures")):
            self._add_asset(assets, model_dir, "texture", texture)

        for expression in self._as_list(references.get("Expressions")):
            if isinstance(expression, dict):
                self._add_asset(assets, model_dir, "expression", expression.get("File"))

        motions = references.get("Motions")
        if isinstance(motions, dict):
            for entries in motions.values():
                for motion in self._as_list(entries):
                    if not isinstance(motion, dict):
                        continue
                    self._add_asset(assets, model_dir, "motion", motion.get("File"))
                    self._add_asset(assets, model_dir, "sound", motion.get("Sound"))

        return self._dedupe_assets(assets)

    def _add_asset(self, assets: list[Live2DAsset], model_dir: Path, asset_type: str, value: Any) -> None:
        if not isinstance(value, str) or not value.strip():
            return
        relative = value.strip()
        candidate = (model_dir / relative).resolve()
        exists = candidate.exists() and candidate.is_file() and candidate.is_relative_to(self.asset_root)
        assets.append(Live2DAsset(asset_type, relative, exists))

    @staticmethod
    def _dedupe_assets(assets: list[Live2DAsset]) -> list[Live2DAsset]:
        deduped: dict[tuple[str, str], Live2DAsset] = {}
        for asset in assets:
            deduped[(asset.type, asset.path)] = asset
        return list(deduped.values())

    def _expression_names(self, references: dict[str, Any]) -> list[str]:
        names: list[str] = []
        for expression in self._as_list(references.get("Expressions")):
            if isinstance(expression, dict) and expression.get("Name"):
                names.append(str(expression["Name"]))
        return names

    def _motion_groups(self, model_dir: Path, references: dict[str, Any]) -> dict[str, list[str]]:
        groups: dict[str, list[str]] = {}
        motions = references.get("Motions")
        if not isinstance(motions, dict):
            return groups
        for group, entries in motions.items():
            groups[str(group)] = [
                str(motion.get("Name") or motion.get("File") or "motion") if self._motion_file_exists(model_dir, motion) else ""
                for motion in self._as_list(entries)
                if isinstance(motion, dict)
            ]
        return groups

    def _motion_file_exists(self, model_dir: Path, motion: dict[str, Any]) -> bool:
        file = motion.get("File")
        if not isinstance(file, str) or not file.strip():
            return False
        path = (model_dir / file.strip()).resolve()
        return path.exists() and path.is_file() and path.is_relative_to(self.asset_root)

    def _motion_durations(self, model_dir: Path, references: dict[str, Any]) -> dict[str, float]:
        durations: dict[str, float] = {}
        motions = references.get("Motions")
        if not isinstance(motions, dict):
            return durations
        for group, entries in motions.items():
            for motion in self._as_list(entries):
                if not isinstance(motion, dict):
                    continue
                name = str(motion.get("Name") or motion.get("File") or "motion")
                duration = self._motion_duration(model_dir, motion)
                if duration > 0:
                    durations[f"{group}:{name}"] = duration
        return durations

    def _motion_duration(self, model_dir: Path, motion: dict[str, Any]) -> float:
        file = motion.get("File")
        if isinstance(file, str) and file.strip():
            path = (model_dir / file.strip()).resolve()
            if path.exists() and path.is_file() and path.is_relative_to(self.asset_root):
                try:
                    data = json.loads(path.read_text(encoding="utf-8-sig"))
                    duration = data.get("Meta", {}).get("Duration") if isinstance(data, dict) else None
                    return float(duration or 0)
                except (OSError, ValueError, TypeError, json.JSONDecodeError):
                    return 0.0
        try:
            return float(motion.get("MotionDuration") or 0)
        except (TypeError, ValueError):
            return 0.0

    def _motion_sounds(self, references: dict[str, Any]) -> dict[str, str]:
        sounds: dict[str, str] = {}
        motions = references.get("Motions")
        if not isinstance(motions, dict):
            return sounds
        for group, entries in motions.items():
            for motion in self._as_list(entries):
                if not isinstance(motion, dict) or not isinstance(motion.get("Sound"), str):
                    continue
                name = str(motion.get("Name") or motion.get("File") or "motion")
                key = f"{group}:{name}"
                if key not in MUTED_MOTION_SOUNDS:
                    sounds[key] = motion["Sound"].strip()
        return sounds

    def _motion_sound_delays(self, references: dict[str, Any]) -> dict[str, int]:
        delays: dict[str, int] = {}
        motions = references.get("Motions")
        if not isinstance(motions, dict):
            return delays
        for group, entries in motions.items():
            for motion in self._as_list(entries):
                if not isinstance(motion, dict) or not motion.get("Sound"):
                    continue
                name = str(motion.get("Name") or motion.get("File") or "motion")
                key = f"{group}:{name}"
                if key in MUTED_MOTION_SOUNDS:
                    continue
                try:
                    delays[key] = int(motion.get("SoundDelay") or 0)
                except (TypeError, ValueError):
                    delays[key] = 0
        return delays

    @staticmethod
    def _as_list(value: Any) -> list[Any]:
        return value if isinstance(value, list) else []

    def _asset_url(self, path: Path) -> str:
        relative = path.resolve().relative_to(self.asset_root).as_posix()
        return f"/assets/live2d/{relative}"
