"""Validated Galgame visual assets for generated story lines."""

from __future__ import annotations

import json
import os
import shutil
import tempfile
import threading
from functools import lru_cache
from pathlib import Path
from typing import Any
from uuid import uuid4


ASSET_ROOT = Path(__file__).with_name("assets") / "galgame" / "chapter-01"
MANIFEST_PATH = ASSET_ROOT / "manifest.json"
TITLE_ASSET_ROOT = Path(__file__).with_name("assets") / "galgame" / "title-backgrounds"
DEFAULT_BACKGROUNDS = (
    ("firefly-title-background", "清晨公寓", TITLE_ASSET_ROOT / "firefly-title-background.png"),
    ("firefly-title-riverside", "河畔午后", TITLE_ASSET_ROOT / "firefly-title-riverside.png"),
    ("firefly-title-rain", "雨夜归途", TITLE_ASSET_ROOT / "firefly-title-rain.png"),
    ("firefly-title-gift", "礼物与花", TITLE_ASSET_ROOT / "firefly-title-gift.png"),
)
IMAGE_SUFFIXES = frozenset((".jpg", ".jpeg", ".png", ".webp"))
MAX_CHAPTER_CGS = 3
FACE_REFERENCE_PATH = ASSET_ROOT / "characters" / "source" / "firefly-face-reference.png"


@lru_cache(maxsize=1)
def visual_manifest() -> dict[str, Any]:
    with MANIFEST_PATH.open("r", encoding="utf-8") as manifest_file:
        manifest = json.load(manifest_file)
    if not isinstance(manifest, dict) or manifest.get("id") != "chapter-01":
        raise ValueError("剧情资源清单版本无效")
    for group in ("scenes", "sprites"):
        if not isinstance(manifest.get(group), dict) or not manifest[group]:
            raise ValueError("剧情资源清单缺少资源")
    return manifest


def visual_asset_ids(group: str) -> frozenset[str]:
    return frozenset(visual_manifest()[group])


def default_scene_id() -> str:
    value = visual_manifest().get("recommended_defaults", {}).get("scene")
    return value if isinstance(value, str) and value in visual_asset_ids("scenes") else next(iter(visual_asset_ids("scenes")))


def default_sprite_id() -> str:
    value = visual_manifest().get("recommended_defaults", {}).get("sprite")
    return value if isinstance(value, str) and value in visual_asset_ids("sprites") else next(iter(visual_asset_ids("sprites")))


def visual_asset_path(group: str, asset_id: str) -> Path:
    manifest = visual_manifest()
    assets = manifest[group]
    if asset_id not in assets:
        raise KeyError(asset_id)
    value = assets[asset_id].get("file")
    if not isinstance(value, str):
        raise ValueError("剧情资源路径无效")
    root = ASSET_ROOT.resolve()
    path = (root / value).resolve()
    try:
        path.relative_to(root)
    except ValueError as error:
        raise ValueError("剧情资源路径越界") from error
    if not path.is_file():
        raise FileNotFoundError(path)
    return path


def visual_prompt_context() -> dict[str, Any]:
    manifest = visual_manifest()
    return {
        "rules": manifest.get("rules", {}),
        "scenes": {
            asset_id: {
                "name_zh": item.get("name_zh"),
                "location": item.get("location"),
                "time": item.get("time"),
                "weather": item.get("weather"),
                "mood": item.get("mood", []),
                "tags": item.get("tags", []),
            }
            for asset_id, item in manifest["scenes"].items()
        },
        "sprites": {
            asset_id: {
                "outfit": item.get("outfit"),
                "pose": item.get("pose"),
                "expression": item.get("expression"),
                "mood": item.get("mood", []),
                "tags": item.get("tags", []),
            }
            for asset_id, item in manifest["sprites"].items()
        },
        "recommended_defaults": manifest.get("recommended_defaults", {}),
    }


class VisualLibraryStore:
    """Small validated store for title backgrounds and generated chapter CGs."""

    def __init__(self, data_dir: str | Path) -> None:
        self.root = Path(os.path.abspath(data_dir))
        self.path = self.root / "visual-library.json"
        self.background_dir = self.root / "visuals" / "backgrounds"
        self.chapter_cg_dir = self.root / "visuals" / "chapter-cg"
        self._lock = threading.RLock()

    def _default(self) -> dict[str, object]:
        return {
            "version": 2,
            "enabled_background_ids": [item[0] for item in DEFAULT_BACKGROUNDS],
            "user_backgrounds": [],
            "story_cgs": [],
            "chapter_cgs": [],
            "chapter_cg_briefs": [],
            "chapter_jobs": [],
            "image_model_available": False,
        }

    def load(self) -> dict[str, object]:
        with self._lock:
            migrated = False
            try:
                value = json.loads(self.path.read_text(encoding="utf-8"))
            except FileNotFoundError:
                return self.save(self._default())
            except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
                raise ValueError("visual library is unavailable") from error
            if isinstance(value, dict) and value.get("version") == 1:
                value = self._migrate_v1(value)
                migrated = True
            self._validate(value)
            known = {item[0] for item in DEFAULT_BACKGROUNDS} | {item["id"] for item in value["user_backgrounds"]}
            if not any(item in known for item in value["enabled_background_ids"]):
                value["enabled_background_ids"] = [item[0] for item in DEFAULT_BACKGROUNDS]
                return self.save(value)
            if migrated:
                return self.save(value)
            return value

    def save(self, value: dict[str, object]) -> dict[str, object]:
        self._validate(value)
        self.root.mkdir(parents=True, exist_ok=True)
        payload = (json.dumps(value, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
        descriptor, name = tempfile.mkstemp(dir=self.root, prefix=".visual-library.", suffix=".tmp")
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

    def backgrounds(self) -> tuple[dict[str, object], ...]:
        value = self.load()
        enabled = set(value["enabled_background_ids"])
        builtin = tuple(
            {"id": item_id, "title": title, "path": str(path), "builtin": True, "enabled": item_id in enabled}
            for item_id, title, path in DEFAULT_BACKGROUNDS if path.is_file()
        )
        users = tuple(
            {**item, "path": str(self._data_path(item["file"])), "builtin": False, "enabled": item["id"] in enabled}
            for item in value["user_backgrounds"]
            if self._data_path(item["file"]).is_file()
        )
        return (*builtin, *users)

    def set_enabled_backgrounds(self, ids: list[str]) -> None:
        value = self.load()
        known = {item[0] for item in DEFAULT_BACKGROUNDS} | {item["id"] for item in value["user_backgrounds"]}
        selected = list(dict.fromkeys(ids))
        if not selected or any(item not in known for item in selected):
            raise ValueError("at least one known background is required")
        value["enabled_background_ids"] = selected
        self.save(value)

    def add_background(self, source: str | Path) -> dict[str, object]:
        source_path = Path(source).expanduser().resolve()
        if not source_path.is_file() or source_path.suffix.lower() not in IMAGE_SUFFIXES:
            raise ValueError("background image is invalid")
        item_id = f"user-{uuid4().hex}"
        self.background_dir.mkdir(parents=True, exist_ok=True)
        destination = self.background_dir / f"{item_id}{source_path.suffix.lower()}"
        temporary = destination.with_suffix(destination.suffix + ".tmp")
        shutil.copyfile(source_path, temporary)
        os.replace(temporary, destination)
        value = self.load()
        item = {"id": item_id, "title": source_path.stem[:80] or "用户背景", "file": self._relative(destination)}
        value["user_backgrounds"].append(item)
        value["enabled_background_ids"].append(item_id)
        self.save(value)
        return item

    def delete_background(self, item_id: str) -> None:
        value = self.load()
        item = next((item for item in value["user_backgrounds"] if item["id"] == item_id), None)
        if item is None:
            raise ValueError("background is not removable")
        remaining = [value_id for value_id in value["enabled_background_ids"] if value_id != item_id]
        if not remaining:
            raise ValueError("at least one background is required")
        value["user_backgrounds"] = [value_item for value_item in value["user_backgrounds"] if value_item["id"] != item_id]
        value["enabled_background_ids"] = remaining
        self.save(value)
        self._data_path(item["file"]).unlink(missing_ok=True)

    def set_image_model_available(self, available: bool) -> None:
        value = self.load()
        value["image_model_available"] = bool(available)
        self.save(value)

    def save_chapter_brief(self, chapter_id: str, title: str, prompt: str) -> dict[str, object]:
        brief = {
            "chapter_id": chapter_id[:120],
            "title": title[:120],
            "prompt": prompt[:6000],
            "last_error": "",
        }
        value = self.load()
        value["chapter_cg_briefs"] = [
            item for item in value["chapter_cg_briefs"] if item["chapter_id"] != chapter_id
        ]
        value["chapter_cg_briefs"].append(brief)
        self.save(value)
        return brief

    def create_chapter_job(
        self, chapter_id: str, title: str | None = None, prompt: str | None = None
    ) -> dict[str, object] | None:
        if title is not None and prompt is not None:
            self.save_chapter_brief(chapter_id, title, prompt)
        value = self.load()
        brief = next((item for item in value["chapter_cg_briefs"] if item["chapter_id"] == chapter_id), None)
        if not value["image_model_available"] or brief is None:
            return None
        if sum(item["chapter_id"] == chapter_id for item in value["chapter_cgs"]) >= MAX_CHAPTER_CGS:
            return None
        if any(item["chapter_id"] == chapter_id and item["status"] == "pending" for item in value["chapter_jobs"]):
            return None
        self.chapter_cg_dir.mkdir(parents=True, exist_ok=True)
        job_id = uuid4().hex
        job = {
            "id": job_id,
            "chapter_id": chapter_id,
            "title": brief["title"],
            "prompt": brief["prompt"],
            "file": self._relative(self.chapter_cg_dir / f"{chapter_id}-{job_id}.png"),
            "status": "pending",
            "error": "",
        }
        value["chapter_jobs"].append(job)
        self.save(value)
        return job

    def pending_chapter_job(self) -> dict[str, object] | None:
        value = self.load()
        job = next((item for item in value["chapter_jobs"] if item["status"] == "pending"), None)
        if job is None:
            return None
        return {
            **job,
            "output_path": str(self._data_path(job["file"])),
            "attachments": [str(FACE_REFERENCE_PATH)] if FACE_REFERENCE_PATH.is_file() else [],
        }

    def finish_chapter_job(self, job_id: str, error: str = "") -> bool:
        value = self.load()
        job = next((item for item in value["chapter_jobs"] if item["id"] == job_id), None)
        if job is None:
            return False
        if error:
            brief = next((item for item in value["chapter_cg_briefs"] if item["chapter_id"] == job["chapter_id"]), None)
            if brief is not None:
                brief["last_error"] = error[:500]
            value["chapter_jobs"] = [item for item in value["chapter_jobs"] if item["id"] != job_id]
        else:
            path = self._data_path(job["file"])
            if not path.is_file():
                raise ValueError("generated chapter CG is missing")
            value["chapter_cgs"].append({
                "id": job["id"],
                "chapter_id": job["chapter_id"],
                "title": job["title"],
                "file": job["file"],
                "selected": True,
            })
            value["chapter_jobs"] = [item for item in value["chapter_jobs"] if item["id"] != job_id]
            brief = next((item for item in value["chapter_cg_briefs"] if item["chapter_id"] == job["chapter_id"]), None)
            if brief is not None:
                brief["last_error"] = ""
        self.save(value)
        return True

    def chapter_cgs(self) -> tuple[dict[str, object], ...]:
        value = self.load()
        return tuple(
            {**item, "path": str(self._data_path(item["file"]))}
            for item in value["chapter_cgs"] if self._data_path(item["file"]).is_file()
        )

    def chapter_cg_status(self, chapter_id: str) -> dict[str, object]:
        value = self.load()
        brief = next((item for item in value["chapter_cg_briefs"] if item["chapter_id"] == chapter_id), None)
        count = sum(item["chapter_id"] == chapter_id for item in value["chapter_cgs"])
        pending = any(item["chapter_id"] == chapter_id and item["status"] == "pending" for item in value["chapter_jobs"])
        return {
            "available": value["image_model_available"],
            "has_brief": brief is not None,
            "count": count,
            "remaining": max(0, MAX_CHAPTER_CGS - count),
            "pending": pending,
            "last_error": "" if brief is None else brief["last_error"],
        }

    def set_chapter_cg_selected(self, item_id: str, selected: bool) -> None:
        value = self.load()
        item = next((item for item in value["chapter_cgs"] if item["id"] == item_id), None)
        if item is None:
            raise ValueError("chapter CG is unknown")
        if not selected and item["selected"] and sum(
            other["chapter_id"] == item["chapter_id"] and other["selected"]
            for other in value["chapter_cgs"]
        ) <= 1:
            return
        item["selected"] = bool(selected)
        self.save(value)

    def _relative(self, path: Path) -> str:
        return path.resolve().relative_to(self.root.resolve()).as_posix()

    def _data_path(self, value: object) -> Path:
        if not isinstance(value, str) or not value:
            raise ValueError("visual path is invalid")
        path = (self.root / value).resolve()
        path.relative_to(self.root.resolve())
        return path

    @staticmethod
    def _validate(value: object) -> None:
        keys = {"version", "enabled_background_ids", "user_backgrounds", "story_cgs", "chapter_cgs", "chapter_cg_briefs", "chapter_jobs", "image_model_available"}
        if not isinstance(value, dict) or set(value) != keys or value["version"] != 2:
            raise ValueError("visual library schema is invalid")
        if not isinstance(value["image_model_available"], bool):
            raise ValueError("image capability is invalid")
        for name in ("enabled_background_ids", "user_backgrounds", "story_cgs", "chapter_cgs", "chapter_cg_briefs", "chapter_jobs"):
            if not isinstance(value[name], list):
                raise ValueError("visual library list is invalid")
        if any(
            not isinstance(item, dict)
            or set(item) != {"id", "chapter_id", "title", "file", "selected"}
            or type(item["selected"]) is not bool
            for item in value["chapter_cgs"]
        ):
            raise ValueError("chapter CG list is invalid")
        if any(
            not isinstance(item, dict)
            or set(item) != {"chapter_id", "title", "prompt", "last_error"}
            for item in value["chapter_cg_briefs"]
        ):
            raise ValueError("chapter CG brief list is invalid")

    @staticmethod
    def _migrate_v1(value: dict[str, object]) -> dict[str, object]:
        migrated = dict(value)
        migrated["version"] = 2
        migrated["chapter_cg_briefs"] = []
        migrated["chapter_cgs"] = [
            {
                "id": uuid4().hex,
                "chapter_id": item["chapter_id"],
                "title": item["title"],
                "file": item["file"],
                "selected": True,
            }
            for item in value.get("chapter_cgs", [])
            if isinstance(item, dict) and {"chapter_id", "title", "file"}.issubset(item)
        ]
        return migrated
