"""Local full-text index for Firefly library folders."""

from __future__ import annotations

import json
import os
import re
import threading
import time
from pathlib import Path
from typing import Any, Iterator

from openharness.utils.fs import atomic_write_text

from firefly.documents import is_document_candidate, read_document_sample

TEXT_EXTENSIONS = {
    ".cfg",
    ".conf",
    ".csv",
    ".ini",
    ".json",
    ".log",
    ".md",
    ".py",
    ".rst",
    ".toml",
    ".tsv",
    ".txt",
    ".xml",
    ".yaml",
    ".yml",
}
INDEX_VERSION = 1
INDEX_REFRESH_INTERVAL_SECONDS = 60
_INDEX_LOCK = threading.Lock()


def index_path(workspace: Path) -> Path:
    return workspace / "library_index.json"


def refresh_library_index(config: dict[str, object], workspace: Path) -> dict[str, Any]:
    """Refresh the library index and return a compact summary."""
    with _INDEX_LOCK:
        path = index_path(workspace)
        data = _load_index(path)
        old_entries = data.get("files", {}) if isinstance(data.get("files"), dict) else {}
        entries: dict[str, dict[str, Any]] = {}
        added = updated = skipped = scanned = 0
        max_chars = _int_config(config, "library_index_max_chars_per_file", 20000, 1000, 100000)
        max_bytes = _int_config(config, "library_max_file_bytes", 5_000_000, 1024, 20_000_000)
        max_files = _int_config(config, "library_index_max_files", 500, 1, 10000)

        for root in _library_roots(config, workspace):
            for file_path in _iter_candidate_files(root):
                if scanned >= max_files:
                    break
                if not _is_context_candidate(file_path):
                    continue
                try:
                    stat = file_path.stat()
                    key = str(file_path.resolve())
                except OSError:
                    skipped += 1
                    continue
                scanned += 1
                if stat.st_size > max_bytes:
                    skipped += 1
                    continue
                existing = old_entries.get(key)
                if existing and existing.get("mtime_ns") == stat.st_mtime_ns and existing.get("size") == stat.st_size:
                    entries[key] = existing
                    continue
                text = _read_file_sample(file_path, max_chars).strip()
                if not text:
                    skipped += 1
                    continue
                entries[key] = {
                    "path": key,
                    "root": str(root),
                    "mtime_ns": stat.st_mtime_ns,
                    "size": stat.st_size,
                    "text": text[:max_chars],
                    "summary": _compact(text)[:400],
                }
                if existing:
                    updated += 1
                else:
                    added += 1
            if scanned >= max_files:
                break

        removed = len(set(old_entries) - set(entries))
        path.parent.mkdir(parents=True, exist_ok=True)
        atomic_write_text(
            path,
            json.dumps({"version": INDEX_VERSION, "files": entries}, ensure_ascii=False, indent=2) + "\n",
        )
        return {
            "files": len(entries),
            "added": added,
            "updated": updated,
            "removed": removed,
            "skipped": skipped,
            "path": str(path),
        }


def search_library_index(prompt: str, config: dict[str, object], workspace: Path) -> str:
    if not bool(config.get("library_index_enabled", True)):
        return ""
    if not bool(config.get("library_allow_read", True)):
        return ""
    path = index_path(workspace)
    if _index_is_stale(path):
        refresh_library_index(config, workspace)
    entries = _load_index(path).get("files", {})
    if not isinstance(entries, dict) or not entries:
        return ""

    terms = _extract_terms(prompt)
    max_hits = _int_config(config, "library_max_hits", 5, 1, 20)
    max_chars = _int_config(config, "library_context_max_chars", 6000, 500, 30000)
    scored: list[tuple[int, str, dict[str, Any]]] = []
    fallback: list[dict[str, Any]] = []
    for key, raw in entries.items():
        if not isinstance(raw, dict):
            continue
        text = str(raw.get("text") or "")
        haystack = f"{raw.get('path')}\n{text}".lower()
        score = sum(3 if term in Path(key).name.lower() else 1 for term in terms if term in haystack)
        if score:
            scored.append((score, key, raw))
        elif len(fallback) < max_hits:
            fallback.append(raw)

    hits = [raw for _score, _key, raw in sorted(scored, reverse=True)[:max_hits]]
    if not hits and _should_show_fallback(prompt):
        hits = fallback[:max_hits]
    if not hits:
        return ""

    lines = ["## 资料舱上下文", "以下内容来自 Firefly 本地全文索引。"]
    used = 0
    for raw in hits:
        text = str(raw.get("text") or "")
        display_path = str(raw.get("path") or "")
        excerpt = _excerpt(text, terms)
        remaining = max_chars - used
        if remaining <= 0:
            break
        excerpt = _compact(excerpt)[:remaining]
        used += len(excerpt)
        lines.append(f"- {display_path}: {excerpt}")
    return "\n".join(lines) if len(lines) > 2 else ""


def library_index_summary(config: dict[str, object], workspace: Path) -> str:
    state = "已开启" if bool(config.get("library_index_enabled", True)) else "已关闭"
    data = _load_index(index_path(workspace))
    entries = data.get("files", {})
    count = len(entries) if isinstance(entries, dict) else 0
    return f"本地全文索引: {state}，{count} 个文件\n索引文件: {index_path(workspace)}"


def _load_index(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {"version": INDEX_VERSION, "files": {}}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {"version": INDEX_VERSION, "files": {}}
    if not isinstance(data, dict) or data.get("version") != INDEX_VERSION:
        return {"version": INDEX_VERSION, "files": {}}
    return data


def _index_is_stale(path: Path) -> bool:
    try:
        return time.time() - path.stat().st_mtime >= INDEX_REFRESH_INTERVAL_SECONDS
    except OSError:
        return True


def _iter_candidate_files(root: Path) -> Iterator[Path]:
    try:
        walker = os.walk(root, followlinks=False)
        for directory, dirnames, filenames in walker:
            dirnames.sort()
            for filename in sorted(filenames):
                yield Path(directory) / filename
    except OSError:
        return


def _library_roots(config: dict[str, object], workspace: Path) -> list[Path]:
    roots: list[Path] = []
    raw_locations = config.get("library_locations")
    if not isinstance(raw_locations, list):
        return roots
    for item in raw_locations:
        value = item.get("path") if isinstance(item, dict) else item
        if not str(value or "").strip():
            continue
        path = Path(str(value)).expanduser()
        if not path.is_absolute():
            path = workspace / path
        try:
            resolved = path.resolve()
        except OSError:
            continue
        if resolved.is_dir() and resolved not in roots:
            roots.append(resolved)
    return roots


def _read_text_sample(path: Path, max_chars: int) -> str:
    try:
        data = path.read_bytes()[: max_chars * 4]
    except OSError:
        return ""
    for encoding in ("utf-8-sig", "utf-16", "utf-16-le", "utf-16-be", "gb18030"):
        try:
            text = data.decode(encoding)
        except UnicodeDecodeError:
            continue
        if text.count("\x00") <= max(2, len(text) // 20):
            return text[:max_chars]
    return data.decode("utf-8", errors="replace")[:max_chars]


def _read_file_sample(path: Path, max_chars: int) -> str:
    return read_document_sample(path, max_chars) if is_document_candidate(path) else _read_text_sample(path, max_chars)


def _is_context_candidate(path: Path) -> bool:
    return path.suffix.lower() in TEXT_EXTENSIONS or not path.suffix or is_document_candidate(path)


def _extract_terms(text: str) -> set[str]:
    lowered = text.lower()
    terms = {part for part in re.findall(r"[a-z0-9_./-]{2,}|[\u4e00-\u9fff]{2,}", lowered)}
    for word in re.findall(r"[\u4e00-\u9fff]{3,}", lowered):
        terms.update(word[index : index + 2] for index in range(len(word) - 1))
    return {term for term in terms if term.strip()}


def _excerpt(text: str, terms: set[str]) -> str:
    lowered = text.lower()
    hits = [lowered.find(term) for term in terms if term in lowered]
    hits = [hit for hit in hits if hit >= 0]
    if not hits:
        return text[:900]
    start = max(0, min(hits) - 300)
    return text[start : start + 1200]


def _compact(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def _should_show_fallback(prompt: str) -> bool:
    lowered = prompt.lower()
    return any(marker in lowered for marker in ("资料", "文件", "文档", "library", "workspace"))


def _int_config(config: dict[str, object], key: str, default: int, minimum: int, maximum: int) -> int:
    try:
        value = int(str(config.get(key) or default))
    except (TypeError, ValueError):
        value = default
    return max(minimum, min(maximum, value))
