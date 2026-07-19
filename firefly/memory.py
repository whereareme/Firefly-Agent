"""Memory adapters for Firefly."""

from __future__ import annotations

import hashlib
import json
import re
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from openharness.memory.manager import add_memory_entry
from openharness.memory.paths import get_project_memory_dir
from openharness.memory.scan import scan_memory_files
from openharness.memory.search import find_relevant_memories
from openharness.services.session_memory import get_session_memory_content, get_session_memory_path

MEMORY_RECALL_MARKERS = ("记得", "还记得", "记住", "记忆", "长期记忆", "之前", "以前", "告诉过", "说过", "提过")
MEMORY_SUBJECT_MARKERS = ("喜欢", "喜好", "偏好", "爱吃", "爱喝", "讨厌", "名字", "称呼", "生日", "习惯", "目标", "项目", "配置")
MEMORY_QUESTION_MARKERS = ("?", "？", "吗", "么", "什么", "为什么", "怎么", "哪里", "哪")


@dataclass(frozen=True)
class EverOSConfig:
    enabled: bool
    base_url: str
    user_id: str
    app_id: str
    project_id: str
    session_id: str
    method: str
    fallback_method: str
    top_k: int
    flush_each_turn: bool
    timeout_sec: int
    local_fallback_enabled: bool
    local_fallback_path: Path
    local_fallback_max_tokens: int


class EverOSMemoryClient:
    def __init__(self, config: EverOSConfig) -> None:
        self.config = config
        self.base_url = config.base_url.rstrip("/")
        self.last_status = "disabled" if not config.enabled else "ready"
        self.local_store = LocalMemoryStore(config.local_fallback_path, config.local_fallback_max_tokens)

    @property
    def enabled(self) -> bool:
        return self.config.enabled

    def search_context(self, query: str) -> str:
        context = self.search_everos_context(query)
        if context:
            return context
        return self.local_store.search_context(query, self.config.top_k) if self.config.local_fallback_enabled else ""

    def search_everos_context(self, query: str) -> str:
        """Search EverOS only; narrative memory must never use local fallbacks."""
        if not self.enabled or not query.strip():
            return ""
        try:
            context = format_everos_context(self.search(query, self.config.method))
            self.last_status = f"search:{self.config.method}"
            if context:
                return context
        except Exception as error:
            self.last_status = f"search failed: {type(error).__name__}"
        if self.config.fallback_method and self.config.fallback_method != self.config.method:
            try:
                context = format_everos_context(self.search(query, self.config.fallback_method))
                self.last_status = f"search:{self.config.fallback_method}"
                if context:
                    return context
            except Exception as error:
                self.last_status = f"search failed: {type(error).__name__}"
        return ""

    def search(self, query: str, method: str) -> dict[str, Any]:
        return self._post(
            "/api/v1/memory/search",
            {
                "user_id": self.config.user_id,
                "app_id": self.config.app_id,
                "project_id": self.config.project_id,
                "query": query,
                "method": method,
                "top_k": self.config.top_k,
                "include_profile": True,
            },
        )

    def remember_turn(self, user_message: str, assistant_reply: str) -> None:
        if not self.enabled or not user_message.strip() or not assistant_reply.strip():
            return
        try:
            now_ms = int(time.time() * 1000)
            self._post(
                "/api/v1/memory/add",
                {
                    "session_id": self.config.session_id,
                    "app_id": self.config.app_id,
                    "project_id": self.config.project_id,
                    "messages": [
                        {"sender_id": self.config.user_id, "role": "user", "timestamp": now_ms, "content": user_message},
                        {"sender_id": "firefly", "role": "assistant", "timestamp": now_ms + 1, "content": assistant_reply},
                    ],
                },
            )
            if self.config.flush_each_turn:
                self._post("/api/v1/memory/flush", {"session_id": self.config.session_id, "app_id": self.config.app_id, "project_id": self.config.project_id})
            self.last_status = "remembered"
        except Exception as error:
            self.last_status = f"remember failed: {type(error).__name__}"
        if self.config.local_fallback_enabled:
            self.local_store.remember_turn(user_message, assistant_reply)

    def health(self, timeout_sec: int | None = None) -> tuple[bool, str]:
        if not self.enabled:
            return False, "disabled"
        try:
            request = urllib.request.Request(f"{self.base_url}/health", method="GET")
            with urllib.request.urlopen(request, timeout=timeout_sec or self.config.timeout_sec) as response:
                ok = 200 <= response.status < 300
            self.last_status = "ok" if ok else f"http {response.status}"
            return ok, self.last_status
        except Exception as error:
            self.last_status = f"health failed: {type(error).__name__}"
            return False, self.last_status

    def _post(self, path: str, payload: dict[str, Any]) -> dict[str, Any]:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        request = urllib.request.Request(f"{self.base_url}{path}", data=body, headers={"Content-Type": "application/json"}, method="POST")
        try:
            with urllib.request.urlopen(request, timeout=self.config.timeout_sec) as response:
                data = json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as error:
            detail = error.read().decode("utf-8", errors="replace")
            raise RuntimeError(detail or str(error)) from error
        if not isinstance(data, dict):
            raise ValueError("EverOS response JSON must be an object")
        return data


class LocalMemoryStore:
    def __init__(self, path: Path, max_tokens: int = 1_000_000) -> None:
        self.path = path
        self.max_chars = max(1, max_tokens) * 4

    def remember_turn(self, user_message: str, assistant_reply: str) -> None:
        del assistant_reply
        for text in extract_memory_lines(user_message):
            self.add(text)

    def add(self, text: str) -> None:
        text = text.strip()[:1000]
        if not text:
            return
        self.path.parent.mkdir(parents=True, exist_ok=True)
        existing = {normalize_memory_text(item.get("text", "")) for item in self._items()}
        if normalize_memory_text(text) in existing:
            return
        with self.path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps({"timestamp": int(time.time() * 1000), "text": text}, ensure_ascii=False) + "\n")
        self._trim()

    def search_context(self, query: str, top_k: int) -> str:
        terms = expanded_memory_terms(query)
        recall_query = is_memory_recall_query(query)
        scored: list[tuple[int, int, str]] = []
        recent: list[tuple[int, str]] = []
        for item in self._items():
            text = str(item.get("text") or "").strip()
            if not text:
                continue
            timestamp = int(item.get("timestamp") or 0)
            recent.append((timestamp, text))
            score = sum(2 if len(term) > 2 else 1 for term in terms if term in text.lower())
            if score:
                scored.append((score, timestamp, text))
        if not scored and recall_query:
            scored = [(1, timestamp, text) for timestamp, text in sorted(recent, reverse=True)]
        scored.sort(reverse=True)
        lines = [text for _score, _timestamp, text in scored[:top_k]]
        return "## 长期记忆上下文\n" + "\n".join(f"- {line}" for line in lines) if lines else ""

    def _items(self) -> list[dict[str, Any]]:
        if not self.path.exists():
            return []
        rows = []
        for line in self.path.read_text(encoding="utf-8", errors="ignore").splitlines():
            try:
                item = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(item, dict):
                rows.append(item)
        return rows

    def _trim(self) -> None:
        if not self.path.exists() or self.path.stat().st_size <= self.max_chars:
            return
        lines = self.path.read_text(encoding="utf-8", errors="ignore").splitlines()
        kept: list[str] = []
        size = 0
        for line in reversed(lines):
            size += len(line) + 1
            if size > self.max_chars:
                break
            kept.append(line)
        self.path.write_text("\n".join(reversed(kept)) + "\n", encoding="utf-8")


def build_memory_context(prompt: str, history: list[dict[str, str]] | None, config: dict[str, object], workspace: Path, cwd: str | Path | None = None) -> str:
    del history
    if not config_enabled(config, "memory_enabled", False):
        return ""
    if channel_enabled(config, "everos_memory_enabled"):
        return create_everos_client(config, workspace).search_context(prompt)
    if channel_enabled(config, "openharness_session_memory_enabled"):
        return session_memory_context(config, workspace, cwd)
    return openharness_memdir_context(prompt, config, workspace, cwd)


def build_everos_memory_context(prompt: str, config: dict[str, object], workspace: Path) -> str:
    """Return only a live EverOS retrieval for the Sidecar narrative."""
    if not config_enabled(config, "memory_enabled", False) or not channel_enabled(config, "everos_memory_enabled"):
        return ""
    return create_everos_client(config, workspace).search_everos_context(prompt)


def remember_turn(prompt: str, reply: str, config: dict[str, object], workspace: Path, cwd: str | Path | None = None) -> None:
    if not config_enabled(config, "memory_enabled", False):
        return
    if channel_enabled(config, "everos_memory_enabled"):
        create_everos_client(config, workspace).remember_turn(prompt, reply)
    if channel_enabled(config, "openharness_memdir_enabled") and should_store_memory(prompt):
        remember_openharness_memdir(prompt, reply, config, workspace, cwd)
    if channel_enabled(config, "openharness_session_memory_enabled"):
        remember_session_memory(prompt, reply, config, workspace, cwd)


def create_everos_client(config: dict[str, object], workspace: Path) -> EverOSMemoryClient:
    fallback_path = Path(str(config.get("memory_local_fallback_path") or workspace / "memory" / "everos_local_memory.jsonl")).expanduser()
    return EverOSMemoryClient(
        EverOSConfig(
            enabled=config_enabled(config, "memory_enabled", False) and channel_enabled(config, "everos_memory_enabled"),
            base_url=str(config.get("memory_base_url") or "http://127.0.0.1:8000"),
            user_id=str(config.get("memory_user_id") or "firefly_user"),
            app_id=str(config.get("memory_app_id") or "fire-agent"),
            project_id=str(config.get("memory_project_id") or "default"),
            session_id=str(config.get("memory_session_id") or "fire-agent-default"),
            method=str(config.get("memory_method") or "agentic").lower(),
            fallback_method=str(config.get("memory_fallback_method") or "keyword").lower(),
            top_k=int(config.get("memory_top_k") or 8),
            flush_each_turn=bool(config.get("memory_flush_each_turn", True)),
            timeout_sec=int(config.get("memory_timeout_sec") or 8),
            local_fallback_enabled=bool(config.get("memory_local_fallback_enabled", True)),
            local_fallback_path=fallback_path,
            local_fallback_max_tokens=int(config.get("memory_local_fallback_max_tokens") or 1_000_000),
        )
    )


def openharness_memdir_context(prompt: str, config: dict[str, object], workspace: Path, cwd: str | Path | None = None) -> str:
    if not channel_enabled(config, "openharness_memdir_enabled"):
        return ""
    try:
        hits = find_relevant_memories(prompt, openharness_memory_cwd(config, workspace, cwd), max_results=int(config.get("openharness_memory_max_results") or 5))
    except Exception:
        return ""
    lines = []
    for item in hits:
        text = item.description or item.body_preview
        if text:
            lines.append(f"{item.title}: {text[:500]}")
    return "## OpenHarness memdir 记忆\n" + "\n".join(f"- {line}" for line in lines) if lines else ""


def remember_openharness_memdir(prompt: str, reply: str, config: dict[str, object], workspace: Path, cwd: str | Path | None = None) -> None:
    memory_text = "\n".join(extract_memory_lines(prompt)) or f"用户: {prompt[:800]}\n流萤: {reply[:800]}"
    title_seed = next(iter(extract_memory_lines(prompt)), prompt).strip()[:40] or "firefly memory"
    title = re.sub(r"\s+", " ", title_seed)
    try:
        add_memory_entry(openharness_memory_cwd(config, workspace, cwd), title, memory_text, tags=("firefly",))
    except Exception:
        return


def session_memory_context(config: dict[str, object], workspace: Path, cwd: str | Path | None = None) -> str:
    if not channel_enabled(config, "openharness_session_memory_enabled"):
        return ""
    content = get_session_memory_content(openharness_session_path(config, workspace, cwd))
    return "## OpenHarness session memory\n" + content.strip() if content.strip() else ""


def remember_session_memory(prompt: str, reply: str, config: dict[str, object], workspace: Path, cwd: str | Path | None = None) -> None:
    path = openharness_session_path(config, workspace, cwd)
    existing = path.read_text(encoding="utf-8", errors="replace").splitlines() if path.exists() else ["# Session Memory", "", "## Recent Conversation"]
    recent = [line for line in existing if line.startswith("- user:") or line.startswith("- assistant:")]
    recent.extend([f"- user: {' '.join(prompt.split())[:220]}", f"- assistant: {' '.join(reply.split())[:220]}"])
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("# Session Memory\n\n## Recent Conversation\n" + "\n".join(recent[-80:]) + "\n", encoding="utf-8")


def openharness_memory_cwd(config: dict[str, object], workspace: Path, cwd: str | Path | None = None) -> Path:
    return Path(str(config.get("openharness_memory_cwd") or cwd or workspace)).expanduser().resolve()


def openharness_memdir_path(config: dict[str, object], workspace: Path, cwd: str | Path | None = None) -> Path:
    return get_project_memory_dir(openharness_memory_cwd(config, workspace, cwd))


def openharness_session_path(config: dict[str, object], workspace: Path, cwd: str | Path | None = None) -> Path:
    explicit = str(config.get("openharness_session_memory_path") or "").strip()
    if explicit:
        return Path(explicit).expanduser().resolve()
    return get_session_memory_path(openharness_memory_cwd(config, workspace, cwd), str(config.get("openharness_session_id") or "firefly"))


def memory_status_summary(config: dict[str, object], workspace: Path, cwd: str | Path | None = None) -> str:
    active = config_enabled(config, "memory_enabled", False)
    global_state = "已开启" if active else "已关闭"
    everos_state = channel_state(active, channel_enabled(config, "everos_memory_enabled"))
    memdir_state = channel_state(active, channel_enabled(config, "openharness_memdir_enabled"))
    session_state = channel_state(active, channel_enabled(config, "openharness_session_memory_enabled"))
    memdir_path = openharness_memdir_path(config, workspace, cwd)
    session_path = openharness_session_path(config, workspace, cwd)
    memdir_count = len(scan_memory_files(openharness_memory_cwd(config, workspace, cwd), max_files=None)) if memdir_path.exists() else 0
    return (
        f"状态: {global_state}\n"
        f"EverOS: {everos_state} ({config.get('memory_base_url') or 'http://127.0.0.1:8000'})\n"
        f"OpenHarness memdir: {memdir_state} ({memdir_path})，{memdir_count} 条\n"
        f"OpenHarness session memory: {session_state} ({session_path})"
    )


def config_enabled(config: dict[str, object], key: str, default: bool) -> bool:
    return bool(config.get(key, default))


def channel_enabled(config: dict[str, object], key: str) -> bool:
    return bool(config.get(key, config.get("memory_enabled", False)))


def channel_state(active: bool, enabled: bool) -> str:
    if not enabled:
        return "关闭"
    return "开启" if active else "待启用"


def should_store_memory(text: str) -> bool:
    lowered = text.lower()
    return is_identity_setting(text) or any(marker in lowered for marker in ("记住", "我喜欢", "我爱", "我叫", "我的名字", "我的偏好", "以后", "项目", "配置"))


def extract_memory_lines(text: str) -> list[str]:
    stripped = " ".join(text.split())
    if not stripped:
        return []
    match = re.search(r"记住[：:，,。\s]*(.+)$", stripped)
    if match:
        return [match.group(1).strip()]
    if is_identity_setting(stripped):
        return [stripped]
    return [stripped] if should_store_memory(stripped) else []


def is_identity_setting(text: str) -> bool:
    stripped = text.strip().strip("。.!！")
    if not stripped or any(marker in stripped for marker in MEMORY_QUESTION_MARKERS):
        return False
    direct = re.match(r"^(?:流萤|你)\s*(?:是|叫|叫做)\s*([\w\u4e00-\u9fff·\-]{1,24})$", stripped)
    if direct and direct.group(1) not in {"谁", "什么"}:
        return True
    return bool(re.match(r"^(?:以后|今后|之后)?\s*(?:就)?\s*(?:叫你|称呼你为|把你叫(?:作|做)?)\s*[\w\u4e00-\u9fff·\-]{1,24}$", stripped))


def is_memory_recall_query(text: str) -> bool:
    lowered = text.strip().lower()
    if not lowered:
        return False
    if re.match(r"^(请|帮我|你)?记住", lowered) and not any(marker in lowered for marker in ("吗", "什么", "哪些", "没有", "了吗", "之前", "以前")):
        return False
    if any(pattern in lowered for pattern in ("我喜欢什么", "我的喜好", "我的偏好", "我爱吃什么", "我叫什么", "我是谁", "记住了什么")):
        return True
    has_recall = any(marker in lowered for marker in MEMORY_RECALL_MARKERS)
    has_subject = any(marker in lowered for marker in MEMORY_SUBJECT_MARKERS)
    asks_question = any(marker in lowered for marker in ("什么", "哪些", "多少", "吗", "么", "？", "?"))
    return has_recall and (has_subject or asks_question)


def expanded_memory_terms(text: str) -> set[str]:
    lowered = text.lower()
    terms = {part for part in re.findall(r"[a-z0-9_]+|[\u4e00-\u9fff]{2,}", lowered) if len(part) >= 2}
    for word in re.findall(r"[\u4e00-\u9fff]{2,}", lowered):
        terms.update(word[index : index + 2] for index in range(max(0, len(word) - 1)))
    if any(marker in lowered for marker in ("喜欢", "喜好", "偏好", "爱吃", "爱喝", "口味")):
        terms.update({"喜欢", "喜好", "偏好", "爱吃", "爱喝", "口味", "饮食", "食物"})
    if any(marker in lowered for marker in ("名字", "称呼", "叫我", "怎么叫")):
        terms.update({"名字", "称呼", "叫", "用户"})
    return {term for term in terms if term.strip()}


def normalize_memory_text(text: str) -> str:
    return re.sub(r"\s+", "", text.strip().lower())


def format_everos_context(response: dict[str, Any]) -> str:
    data = response.get("data", response)
    if not isinstance(data, dict):
        return ""
    lines: list[str] = []
    for item in data.get("profiles") or []:
        if isinstance(item, dict):
            lines.extend(format_profile_memory(item.get("profile_data")))
    for item in data.get("episodes") or []:
        if not isinstance(item, dict):
            continue
        subject = str(item.get("subject") or "").strip()
        summary = str(item.get("summary") or item.get("episode") or "").strip()
        facts = [str(fact.get("content", "")).strip() for fact in item.get("atomic_facts") or [] if isinstance(fact, dict) and str(fact.get("content", "")).strip()]
        text = "；".join(part for part in [subject, summary, "；".join(facts[:3])] if part)
        if text:
            lines.append(text[:1200])
    return "## 长期记忆上下文\n" + "\n".join(f"- {line}" for line in lines[:8]) if lines else ""


def format_profile_memory(profile_data: Any) -> list[str]:
    if not isinstance(profile_data, dict):
        return []
    lines = []
    for entry in [item for item in profile_data.get("explicit_info") or [] if isinstance(item, dict)][:6]:
        category = str(entry.get("category") or "画像").strip()
        description = str(entry.get("description") or "").strip()
        if description:
            lines.append(f"{category}：{description[:260]}")
    summary = str(profile_data.get("summary") or "").strip()
    return lines or ([f"用户画像：{summary[:260]}"] if summary else [])


def stable_suffix(text: str) -> str:
    return hashlib.sha1(text.encode("utf-8")).hexdigest()[:8]
