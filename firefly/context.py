"""OpenHarness-backed context adapters for Firefly."""

from __future__ import annotations

import re
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

from openharness.auth.storage import load_credential
from openharness.config.settings import (
    ImageGenerationConfig,
    PathRuleConfig,
    VisionModelConfig,
    credential_storage_provider_name,
    resolve_auth_env_value,
)
from openharness.permissions.modes import PermissionMode
from openharness.skills.loader import get_user_skills_dir, load_skill_registry
from openharness.skills.types import SkillDefinition
from openharness.tools.base import ToolExecutionContext
from openharness.tools.web_fetch_tool import WebFetchTool, WebFetchToolInput
from openharness.tools.web_search_tool import WebSearchTool, WebSearchToolInput

from firefly.documents import is_document_candidate, read_document_sample
from firefly.library_index import search_library_index

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
URL_RE = re.compile(r"https?://[^\s<>'\")]+", re.IGNORECASE)
WEB_MARKERS = (
    "搜索",
    "联网",
    "查一下",
    "查找",
    "官网",
    "最新",
    "最近",
    "近况",
    "动态",
    "新消息",
    "新形态",
    "新版本",
    "今天",
    "昨天",
    "新闻",
    "价格",
    "版本",
    "发布",
    "latest",
    "today",
    "news",
    "price",
    "official",
    "search",
)


async def build_openharness_context(
    prompt: str,
    config: dict[str, object],
    workspace: Path,
    cwd: str | Path | None = None,
) -> str:
    """Build Firefly's extra prompt context from OpenHarness-backed features."""
    cwd_path = Path(cwd or workspace).expanduser().resolve()
    parts = [
        build_library_context(prompt, config, workspace),
        await build_web_context(prompt, config, cwd_path),
        build_skill_context(prompt, config, workspace, cwd_path),
        build_permission_context(config, workspace),
    ]
    return "\n\n".join(part for part in parts if part.strip())


def build_library_context(prompt: str, config: dict[str, object], workspace: Path) -> str:
    if not bool(config.get("library_allow_read", True)):
        return ""
    indexed = search_library_index(prompt, config, workspace)
    if indexed:
        return indexed
    terms = extract_terms(prompt)
    max_hits = int_config(config, "library_max_hits", 5, minimum=1, maximum=20)
    max_chars = int_config(config, "library_context_max_chars", 6000, minimum=500, maximum=30000)
    scored: list[tuple[int, Path, Path, str]] = []
    fallback: list[tuple[Path, Path, str]] = []
    for root, path in iter_library_files(config, workspace):
        text = read_file_sample(path, int_config(config, "library_file_sample_chars", 12000, minimum=1000, maximum=50000))
        if not text:
            continue
        target = f"{path.name}\n{path}\n{text}".lower()
        score = sum(3 if term in path.name.lower() else 1 for term in terms if term in target)
        if score:
            scored.append((score, root, path, excerpt_for_terms(text, terms)))
        elif len(fallback) < max_hits:
            fallback.append((root, path, text[:900].strip()))

    use_hits = [(root, path, excerpt) for _score, root, path, excerpt in sorted(scored, reverse=True)[:max_hits]]
    if not use_hits and should_show_library_fallback(prompt):
        use_hits = fallback[:max_hits]
    if not use_hits:
        return ""

    lines = ["## 资料舱上下文", "以下内容来自用户在 Firefly 资料舱中允许读取的目录，只把它当作本地资料参考。"]
    used_chars = 0
    for root, path, excerpt in use_hits:
        rel = safe_relative(path, root)
        clean = compact_text(excerpt)
        if not clean:
            continue
        remaining = max_chars - used_chars
        if remaining <= 0:
            break
        clean = clean[:remaining]
        used_chars += len(clean)
        lines.append(f"- {rel}: {clean}")
    return "\n".join(lines) if len(lines) > 2 else ""


def build_upload_context(attachments: list[str] | None, max_chars_per_file: int = 6000) -> str:
    if not attachments:
        return ""
    blocks: list[str] = []
    for raw_path in attachments:
        try:
            path = Path(raw_path).expanduser().resolve(strict=True)
            size = path.stat().st_size
        except OSError:
            continue
        if not path.is_file():
            continue
        if is_context_candidate(path):
            content = read_file_sample(path, max_chars_per_file).strip()
        elif path.suffix.lower() in {".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp"}:
            content = (
                f"图片文件已上传并会作为 OpenHarness 图像附件发送。路径: {path}；大小: {size} bytes。"
                "如果当前模型不是多模态模型，OpenHarness 会在配置 vision model 后自动转成文字描述。"
            )
        else:
            content = f"文件已上传。路径: {path}；大小: {size} bytes。"
        blocks.append(f"[上传文件 | {path.name}]\n{content[:max_chars_per_file]}")
    return "## 上传文件上下文\n" + "\n\n".join(blocks) if blocks else ""


async def build_web_context(prompt: str, config: dict[str, object], cwd: Path) -> str:
    if not bool(config.get("web_search_enabled", False)):
        return ""
    context = ToolExecutionContext(cwd=cwd)
    parts: list[str] = []
    max_fetch_chars = int_config(config, "web_fetch_max_chars", 6000, minimum=500, maximum=50000)
    if bool(config.get("web_fetch_enabled", True)):
        for url in extract_urls(prompt)[:2]:
            result = await WebFetchTool().execute(WebFetchToolInput(url=url, max_chars=max_fetch_chars), context)
            parts.append(format_tool_output("web_fetch", result.output, result.is_error, 5000))

    if should_search_web(prompt, bool(config.get("web_search_auto", True))):
        result = await WebSearchTool().execute(
            WebSearchToolInput(
                query=clean_web_query(prompt),
                max_results=int_config(config, "web_search_max_results", 5, minimum=1, maximum=10),
                search_url=str(config.get("web_search_url") or "").strip() or None,
            ),
            context,
        )
        parts.append(format_tool_output("web_search", result.output, result.is_error, 4000))

    parts = [part for part in parts if part.strip()]
    if not parts:
        return ""
    return "## 星网检索上下文\n" + "\n\n".join(parts)


def build_skill_context(
    prompt: str,
    config: dict[str, object],
    workspace: Path,
    cwd: str | Path | None = None,
) -> str:
    if not bool(config.get("skills_enabled", False)):
        return ""
    try:
        registry = load_firefly_skill_registry(config, workspace, cwd)
        skills = registry.list_skills()
    except Exception as error:
        return f"## 技能库上下文\nSkillRegistry 加载失败: {type(error).__name__}"
    if not skills:
        return "## 技能库上下文\nOpenHarness SkillRegistry 已启用，但当前目录没有加载到 Skill。"

    matches = match_skills(prompt, skills, limit=int_config(config, "skills_context_max_matches", 3, minimum=1, maximum=8))
    lines = ["## 技能库上下文", f"OpenHarness SkillRegistry 已加载 {len(skills)} 个 Skill。"]
    if matches:
        lines.append("和本轮请求最相关的 Skill:")
        for skill in matches:
            name = skill.command_name or skill.name
            description = compact_text(skill.description)[:260]
            path = f" ({skill.path})" if skill.path else ""
            lines.append(f"- /{name}{path}: {description}")
    else:
        root = skills_root(config, workspace)
        lines.append(f"当前技能目录: {root}")
    return "\n".join(lines)


def build_permission_context(config: dict[str, object], workspace: Path) -> str:
    mode = permission_mode_value(config)
    sandbox_state = "enabled" if bool(config.get("sandbox_enabled", False)) else "disabled"
    sandbox_backend = str(config.get("sandbox_backend") or "srt")
    read_roots = library_roots(config, workspace) if bool(config.get("library_allow_read", True)) else []
    write_roots = library_write_roots(config, workspace)
    read_state = ", ".join(str(root) for root in read_roots) if read_roots else "none"
    write_state = ", ".join(str(root) for root in write_roots) if write_roots else "none"
    return (
        "## 行动权限上下文\n"
        f"- OpenHarness permission mode: {mode}\n"
        f"- OpenHarness sandbox: {sandbox_state}, backend={sandbox_backend}\n"
        f"- Firefly library read roots: {read_state}\n"
        f"- Firefly library write allowlist: {write_state}\n"
        "- Firefly desktop shows a local confirmation dialog for mutating tools; do not ask the user to type full_auto or 继续 just to approve permissions."
    )


def firefly_settings_transform(config: dict[str, object], workspace: Path, cwd: str | Path | None = None):
    """Return a settings transform that folds Firefly scopes into OpenHarness."""
    cwd_path = Path(cwd or workspace).expanduser().resolve()
    read_roots = library_roots(config, workspace) if bool(config.get("library_allow_read", True)) else []
    denied_roots = [] if bool(config.get("library_allow_read", True)) else _all_configured_library_roots(config, workspace)
    write_roots = library_write_roots(config, workspace)

    def transform(settings):
        path_rules = list(settings.permission.path_rules)
        for root in read_roots:
            path_rules.extend(PathRuleConfig(pattern=pattern, allow=True) for pattern in path_rule_patterns(root))
        for root in denied_roots:
            path_rules.extend(PathRuleConfig(pattern=pattern, allow=False) for pattern in path_rule_patterns(root))
        allowed_tools = list(dict.fromkeys([*settings.permission.allowed_tools, "image_generation"]))
        permission = settings.permission.model_copy(update={"path_rules": path_rules, "allowed_tools": allowed_tools})

        filesystem = settings.sandbox.filesystem
        allow_read = unique_paths([*filesystem.allow_read, str(cwd_path), *(str(root) for root in read_roots)])
        allow_write = unique_paths([*filesystem.allow_write, str(cwd_path), *(str(root) for root in write_roots)])
        sandbox = settings.sandbox.model_copy(
            update={
                "enabled": bool(config.get("sandbox_enabled", False)),
                "backend": str(config.get("sandbox_backend") or "srt"),
                "fail_if_unavailable": bool(config.get("sandbox_fail_if_unavailable", False)),
                "filesystem": filesystem.model_copy(
                    update={"allow_read": allow_read, "allow_write": allow_write}
                )
            }
        )
        return settings.model_copy(
            update={
                "timeout": chat_timeout_value(config, settings.timeout),
                "permission": permission,
                "sandbox": sandbox,
                "vision": firefly_vision_config(config, settings),
                "image_generation": firefly_image_generation_config(config, settings),
            }
        )

    return transform


def chat_timeout_value(config: dict[str, object], default: float) -> float:
    try:
        return max(10.0, float(config.get("chat_timeout_sec") or default))
    except (TypeError, ValueError):
        return default


def firefly_vision_config(config: dict[str, object], settings) -> VisionModelConfig:
    current = settings.vision
    if current.is_configured:
        return current
    profile_name, profile = settings.resolve_profile(str(config.get("provider_profile") or "") or None)
    api_key = str(config.get("llm_api_key") or "").strip()
    env_resolved = resolve_auth_env_value(profile.auth_source)
    if env_resolved:
        api_key = env_resolved[1]
    if not api_key:
        api_key = load_credential(credential_storage_provider_name(profile_name, profile), "api_key") or ""
    model = str(config.get("model") or config.get("llm_model") or "").strip() or profile.resolved_model or current.model
    base_url = profile.base_url or str(config.get("llm_base_url") or "").strip() or current.base_url
    if not model or not api_key:
        return current
    return current.model_copy(update={"model": model, "api_key": api_key, "base_url": base_url})


def firefly_image_generation_config(config: dict[str, object], settings) -> ImageGenerationConfig:
    current = settings.image_generation
    profile_name, profile = settings.resolve_profile(str(config.get("provider_profile") or "") or None)
    model = str(config.get("image_generation_model") or "").strip() or first_image_model(profile.allowed_models) or current.model
    api_key = ""
    env_resolved = resolve_auth_env_value(profile.auth_source)
    if env_resolved:
        api_key = env_resolved[1]
    if not api_key:
        api_key = load_credential(credential_storage_provider_name(profile_name, profile), "api_key") or ""
    return current.model_copy(
        update={
            "provider": "openai",
            "model": model,
            "api_key": api_key or current.api_key,
            "base_url": profile.base_url or current.base_url,
        }
    )


def first_image_model(models: list[str]) -> str:
    for model in models:
        lowered = model.lower()
        if "image" in lowered or lowered.startswith("gpt-image"):
            return model
    return ""


def iter_library_files(config: dict[str, object], workspace: Path, max_files: int | None = None) -> Iterator[tuple[Path, Path]]:
    max_bytes = int_config(config, "library_max_file_bytes", 5_000_000, minimum=1024, maximum=5_000_000)
    if max_files is None:
        max_files = int_config(config, "library_max_scan_files", 250, minimum=1, maximum=5000)
    yielded = 0
    for root in library_roots(config, workspace):
        try:
            candidates = root.rglob("*")
            for path in candidates:
                if max_files is not None and yielded >= max_files:
                    return
                if not path.is_file() or not is_context_candidate(path):
                    continue
                try:
                    if path.stat().st_size > max_bytes:
                        continue
                except OSError:
                    continue
                yielded += 1
                yield root, path
        except OSError:
            continue


def library_roots(config: dict[str, object], workspace: Path) -> list[Path]:
    roots: list[Path] = []
    raw_locations = config.get("library_locations")
    if not isinstance(raw_locations, list):
        return roots
    for item in raw_locations:
        allow_read = True
        raw_path: object = item
        if isinstance(item, dict):
            raw_path = item.get("path")
            allow_read = bool(item.get("read", True))
        if not allow_read:
            continue
        value = str(raw_path or "").strip()
        if not value:
            continue
        path = Path(value).expanduser()
        if not path.is_absolute():
            path = workspace / path
        try:
            resolved = path.resolve()
        except OSError:
            continue
        if resolved.is_dir() and resolved not in roots:
            roots.append(resolved)
    return roots


def _all_configured_library_roots(config: dict[str, object], workspace: Path) -> list[Path]:
    roots: list[Path] = []
    raw_locations = config.get("library_locations")
    if not isinstance(raw_locations, list):
        return roots
    for item in raw_locations:
        raw_path = item.get("path") if isinstance(item, dict) else item
        value = str(raw_path or "").strip()
        if not value:
            continue
        path = Path(value).expanduser()
        if not path.is_absolute():
            path = workspace / path
        try:
            resolved = path.resolve()
        except OSError:
            continue
        if resolved.is_dir() and resolved not in roots:
            roots.append(resolved)
    return roots


def library_write_roots(config: dict[str, object], workspace: Path) -> list[Path]:
    if not bool(config.get("library_allow_write", False)):
        return []
    raw_locations = config.get("library_locations")
    if not isinstance(raw_locations, list):
        return []
    writable = [item for item in raw_locations if not isinstance(item, dict) or bool(item.get("write", True))]
    return _all_configured_library_roots({**config, "library_locations": writable}, workspace)


def library_write_allowed(path: str | Path, config: dict[str, object], workspace: Path) -> bool:
    try:
        target = Path(path).expanduser().resolve()
    except OSError:
        return False
    for root in library_write_roots(config, workspace):
        try:
            target.relative_to(root)
            return True
        except ValueError:
            continue
    return False


def path_rule_patterns(root: Path) -> tuple[str, str]:
    value = str(root)
    return value, value.rstrip("\\/") + "/*"


def unique_paths(paths: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for path in paths:
        text = str(path).strip()
        if not text or text in seen:
            continue
        seen.add(text)
        result.append(text)
    return result


def skill_registry_summary(config: dict[str, object], workspace: Path, cwd: str | Path | None = None) -> str:
    state = "已开启" if bool(config.get("skills_enabled", False)) else "已关闭"
    root = skills_root(config, workspace)
    try:
        registry = load_firefly_skill_registry(config, workspace, cwd)
        skills = registry.list_skills() if bool(config.get("skills_enabled", False)) else []
        detail = f"已加载: {len(skills)} 个 OpenHarness Skill"
        external_skills = [skill for skill in skills if skill.source != "bundled"]
        if external_skills:
            lines = []
            for skill in external_skills[:12]:
                path = f" - {skill.path}" if skill.path else ""
                lines.append(f"- /{skill.command_name or skill.name}{path}")
            detail = f"{detail}\n外部技能:\n" + "\n".join(lines)
    except Exception as error:
        detail = f"加载失败: {type(error).__name__}: {error}"
    return f"状态: {state}\n目录: {root}\n{detail}"


def load_firefly_skill_registry(config: dict[str, object], workspace: Path, cwd: str | Path | None = None):
    return load_skill_registry(
        cwd or workspace,
        extra_skill_dirs=openharness_skill_dirs(config, workspace),
    )


def openharness_skill_dirs(config: dict[str, object], workspace: Path) -> tuple[str, ...]:
    if not bool(config.get("skills_enabled", False)):
        return ()
    return (str(skills_root(config, workspace)),)


def skills_root(config: dict[str, object], workspace: Path) -> Path:
    default = get_user_skills_dir().resolve()
    legacy = (workspace / "skills").expanduser().resolve()
    value = str(config.get("skills_root") or "").strip()
    if not value:
        return default
    path = Path(value).expanduser()
    if not path.is_absolute():
        path = workspace / path
    resolved = path.resolve()
    return default if resolved == legacy else resolved


def permission_mode_value(config: dict[str, object]) -> str:
    value = str(config.get("permission_mode") or "default").strip() or "default"
    valid = {mode.value for mode in PermissionMode}
    return value if value in valid else PermissionMode.DEFAULT.value


@contextmanager
def openharness_environment(config: dict[str, object]) -> Iterator[None]:
    # Kept as a compatibility wrapper for callers; sandbox settings are now
    # applied directly by firefly_settings_transform instead of process-wide env.
    del config
    yield


def match_skills(prompt: str, skills: list[SkillDefinition], limit: int) -> list[SkillDefinition]:
    terms = extract_terms(prompt)
    scored: list[tuple[int, str, SkillDefinition]] = []
    for skill in skills:
        haystack = "\n".join(
            part
            for part in (
                skill.name,
                skill.command_name or "",
                skill.display_name or "",
                skill.description,
                skill.content[:4000],
            )
            if part
        ).lower()
        score = sum(4 if term in (skill.name.lower(), str(skill.command_name or "").lower()) else 1 for term in terms if term in haystack)
        if score:
            scored.append((score, skill.command_name or skill.name, skill))
    scored.sort(reverse=True, key=lambda item: (item[0], item[1]))
    return [skill for _score, _name, skill in scored[:limit]]


def should_search_web(prompt: str, auto: bool) -> bool:
    if not auto:
        return True
    lowered = prompt.lower()
    return bool(extract_urls(prompt)) or any(marker in lowered for marker in WEB_MARKERS)


def clean_web_query(prompt: str) -> str:
    query = URL_RE.sub("", prompt).strip()
    query = re.sub(r"\s+", " ", query)
    return query[:300] or prompt[:300]


def extract_urls(prompt: str) -> list[str]:
    urls: list[str] = []
    for match in URL_RE.finditer(prompt):
        url = match.group(0).rstrip("。。，,")
        if url not in urls:
            urls.append(url)
    return urls


def format_tool_output(name: str, output: str, is_error: bool, limit: int) -> str:
    clean = output.strip()
    if not clean:
        return ""
    prefix = f"{name} 失败" if is_error else name
    return f"### {prefix}\n{clean[:limit]}"


def extract_terms(text: str) -> set[str]:
    lowered = text.lower()
    terms = {part for part in re.findall(r"[a-z0-9_./-]{2,}|[\u4e00-\u9fff]{2,}", lowered)}
    for word in re.findall(r"[\u4e00-\u9fff]{3,}", lowered):
        terms.update(word[index : index + 2] for index in range(len(word) - 1))
    return {term for term in terms if term.strip()}


def excerpt_for_terms(text: str, terms: set[str]) -> str:
    lowered = text.lower()
    hits = [lowered.find(term) for term in terms if term in lowered]
    hits = [hit for hit in hits if hit >= 0]
    if not hits:
        return text[:900]
    start = max(0, min(hits) - 260)
    end = min(len(text), start + 1100)
    return text[start:end]


def should_show_library_fallback(prompt: str) -> bool:
    lowered = prompt.lower()
    return any(marker in lowered for marker in ("资料", "文件", "文档", "library", "workspace"))


def read_text_sample(path: Path, max_chars: int) -> str:
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


def read_file_sample(path: Path, max_chars: int) -> str:
    return read_document_sample(path, max_chars) if is_document_candidate(path) else read_text_sample(path, max_chars)


def compact_text(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def safe_relative(path: Path, root: Path) -> str:
    try:
        return str(path.relative_to(root))
    except ValueError:
        return str(path)


def is_text_candidate(path: Path) -> bool:
    return path.suffix.lower() in TEXT_EXTENSIONS or not path.suffix


def is_context_candidate(path: Path) -> bool:
    return is_text_candidate(path) or is_document_candidate(path)


def int_config(config: dict[str, object], key: str, default: int, *, minimum: int, maximum: int) -> int:
    try:
        value = int(config.get(key) or default)
    except (TypeError, ValueError):
        value = default
    return max(minimum, min(maximum, value))
