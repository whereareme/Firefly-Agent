"""Runtime helpers for Firefly."""

from __future__ import annotations

import asyncio
import contextlib
import io
import inspect
import re
import sys
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from openharness.config import load_settings
from openharness.engine.messages import ConversationMessage, ImageBlock, TextBlock
from openharness.engine.stream_events import AssistantTextDelta, ErrorEvent, StatusEvent
from openharness.tools.base import ToolExecutionContext
from openharness.tools.image_generation_tool import ImageGenerationTool, ImageGenerationToolInput
from openharness.ui.runtime import build_runtime, close_runtime, handle_line, start_runtime
from openharness.ui.runtime import _resolve_image_generation_config

from firefly.context import (
    build_openharness_context,
    build_upload_context,
    firefly_settings_transform,
    library_write_allowed,
    openharness_environment,
    openharness_skill_dirs,
    permission_mode_value,
)
from firefly.desktop_tools import firefly_desktop_tools
from firefly.memory import build_memory_context, remember_turn
from firefly.prompts import build_firefly_system_prompt
from firefly.session_storage import FireflySessionBackend, NullSessionBackend
from firefly.workspace import initialize_workspace, load_config

IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp"}
IMAGE_GENERATION_MARKERS = (
    "生图",
    "出图",
    "生成图片",
    "生成一张图片",
    "生成一张图",
    "生成一幅图",
    "画一张",
    "画张",
    "画个",
    "绘制",
    "generate image",
    "create an image",
    "draw a",
)
IMAGE_QUESTION_MARKERS = ("怎么", "怎样", "如何", "为什么", "是什么", "能不能", "可不可以", "how to", "what is")
IMAGE_COMMAND_MARKERS = ("帮我", "请", "给我", "生成一", "画一", "画张", "画个", "生图", "出图", "generate image", "create an image")
FIREFLY_SELF_IMAGE_MARKERS = (
    "流萤",
    "firefly",
    "小萤",
    "想看你",
    "看看你",
    "看你",
    "画你",
    "你现在",
    "你在干嘛",
    "你在做什么",
    "你的样子",
    "你自己",
    "self portrait",
    "yourself",
)
FIREFLY_IMPLICIT_SELF_IMAGE_MARKERS = (
    "睡觉穿",
    "穿这么多",
    "穿这么厚",
    "被窝",
    "被子",
)
EXPLICIT_NON_FIREFLY_IMAGE_SUBJECT_MARKERS = (
    "猫",
    "狗",
    "动物",
    "机器人",
    "风景",
    "建筑",
    "车辆",
    "食物",
    "女孩",
    "男孩",
    "女生",
    "男生",
    "男人",
    "女人",
)
FIREFLY_SELF_IMAGE_ANCHOR = (
    "自指生图锚点：画面主体是流萤本人，不是猫、动物、机器人、通用 AI 助手或 OpenAI/ChatGPT 标志。"
    "脸型与眼睛瞳孔特征必须保持为可辨认的流萤；其余外观与场景以用户要求为准。"
)
FIREFLY_FACE_REFERENCE_PROMPT = (
    "附件 1 只用于锁定流萤的脸型和眼睛瞳孔特征，不约束服装、发型、发饰、画风、姿势或场景。"
    "脸部为偏短的柔和鹅蛋脸，双颊自然饱满、下巴圆润收窄；鼻子小巧，嘴唇是轻微上扬的细小闭口微笑。"
    "眼睛必须横向偏长、略呈水滴形而非大圆眼；上眼线为清晰柔和的深蓝紫弧线，眉眼距离较近。"
    "虹膜外圈为青蓝至蓝紫，内部通透偏青蓝；中央瞳孔是小而清楚的玫红或洋红色竖椭圆，"
    "下半虹膜有粉紫渐变，并带位置明确的白色和青色玻璃高光。"
    "表情保持平静、温和、自然，不使用夸张成熟、羞怯或性感化的脸部表情。"
    "除脸型和眼睛瞳孔外，其他全部遵从用户的描述与后续用户附图。"
)
FIREFLY_FACE_REFERENCE_IMAGE = (
    Path(__file__).parent / "assets" / "skills" / "firefly-face-reference" / "assets" / "firefly-face-reference.png"
)
STALE_PERMISSION_HISTORY_MARKERS = (
    "/permissions full_auto",
    "请你先输入",
    "然后再发",
    "权限层还是拦住",
    "没有把“允许”传给写入工具",
    "没有把\"允许\"传给写入工具",
)


@dataclass
class FireflyResponse:
    text: str
    status: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    invoked_skills: list[str] = field(default_factory=list)
    provider: str = ""
    model: str = ""


def _history_block(history: list[dict[str, str]] | None) -> str:
    if not history:
        return ""
    lines = ["## Previous Conversation"]
    for item in history[-10:]:
        role = item.get("role")
        text = str(item.get("content", "")).strip()
        if role not in {"user", "assistant"} or not text:
            continue
        if role == "assistant" and any(marker in text for marker in STALE_PERMISSION_HISTORY_MARKERS):
            continue
        label = "User" if role == "user" else "Firefly"
        lines.append(f"{label}: {text[:1200]}")
    return "\n".join(lines)


def _prompt_with_history(prompt: str, history: list[dict[str, str]] | None) -> str:
    block = _history_block(history)
    if not block:
        return prompt
    return f"{block}\n\n## Current User Message\n{prompt}"


def _user_message_with_attachments(text: str, attachments: list[str] | None) -> ConversationMessage:
    content = [TextBlock(text=text)]
    for raw_path in attachments or []:
        path = Path(raw_path)
        if path.suffix.lower() not in IMAGE_EXTENSIONS:
            continue
        try:
            content.append(ImageBlock.from_path(path))
        except (OSError, ValueError):
            continue
    return ConversationMessage.from_user_content(content)


def image_generation_prompt(prompt: str, history: list[dict[str, str]] | None = None) -> str:
    text = prompt.strip()
    for marker in ("\n\n临场感知：", "\n\n萤火巡望："):
        text = text.split(marker, 1)[0].strip()
    if is_firefly_self_image_request(text, history):
        context = _history_block(history)
        if context:
            return f"{context}\n\n## Current Image Request\n{text}\n\n{FIREFLY_SELF_IMAGE_ANCHOR}"
        return f"{text}\n\n{FIREFLY_SELF_IMAGE_ANCHOR}"
    return text or prompt.strip()


def is_firefly_self_image_request(prompt: str, history: list[dict[str, str]] | None = None) -> bool:
    lowered = prompt.lower()
    if any(marker in lowered for marker in FIREFLY_SELF_IMAGE_MARKERS):
        return True
    if any(marker in lowered for marker in EXPLICIT_NON_FIREFLY_IMAGE_SUBJECT_MARKERS):
        return False
    return any(marker in lowered for marker in FIREFLY_IMPLICIT_SELF_IMAGE_MARKERS) and not any(
        marker in lowered for marker in EXPLICIT_NON_FIREFLY_IMAGE_SUBJECT_MARKERS
    ) or history_mentions_firefly_self(history)


def history_mentions_firefly_self(history: list[dict[str, str]] | None) -> bool:
    if not history:
        return False
    recent = "\n".join(str(item.get("content") or "") for item in history[-6:]).lower()
    return any(marker in recent for marker in FIREFLY_SELF_IMAGE_MARKERS) or "画面主体是流萤本人" in recent


def image_generation_reply(prompt: str) -> str:
    text = image_generation_prompt(prompt)
    marker_pattern = "|".join(re.escape(marker) for marker in IMAGE_GENERATION_MARKERS)
    text = re.sub(rf"[\(（][^()（）]*(?:{marker_pattern})[^()（）]*[\)）]", "", text, flags=re.IGNORECASE).strip()
    if "这么晚" in text and "在干嘛" in text:
        return "我在灯下整理今晚的想法，也把这一刻画给你看。"
    if any(word in text for word in ("你现在在干嘛", "你在干嘛", "你现在在做什么", "你在做什么")):
        return "给你看我现在在做什么。"
    if "在干嘛" in text:
        return "给你看我正在做什么。"
    if "看看" in text:
        return "给你看。"
    return ""


def image_generation_followup_prompt(prompt: str, history: list[dict[str, str]] | None = None) -> str:
    text = strip_awareness_context(prompt)
    identity_guard = "流萤不是猫、动物、机器人或通用 AI 助手；不要把附件里的动物当成“我”。"
    if is_firefly_self_image_request(text, history):
        identity_guard += " 这次如果画面主体不像流萤本人，就承认画面跑偏，不要顺着错误主体自称。"
    context = _history_block(history)
    context_text = f"\n\n当前对话上下文：\n{context}" if context else ""
    return (
        "刚刚已经按用户要求生成了一张图片，并作为附件发给你。"
        "请先看这张图片，再用流萤的第一人称自然回答用户。"
        "不要再调用工具，不要再生成图片，不要提图片保存路径。"
        f"{identity_guard}\n\n"
        f"用户原话：{text}"
        f"{context_text}"
    )


def safe_image_generation_prompt(prompt: str, history: list[dict[str, str]] | None = None) -> str:
    text = strip_awareness_context(prompt)
    if is_firefly_self_image_request(text, history):
        return (
            "生成一张符合安全规范的流萤日常插画：流萤穿着完整、保守、普通的日常服装，"
            "在明亮温暖的室内坐着休息或整理东西，姿势自然端正，氛围平静生活化。"
            "不要裸露、性感、挑逗、暧昧构图、床上姿势或容易被误判的衣着。"
            "保持银色长发、蓝粉层次眼睛、灰绿色日常装束、清冷柔软的气质。"
        )
    return (
        f"根据用户想法生成一张符合安全规范的日常插画：{text}。"
        "请改写为保守、非性感、非挑逗、无裸露、普通生活氛围的画面。"
    )


def image_generation_moderation_blocked(message: str) -> bool:
    lowered = message.lower()
    return "moderation_blocked" in lowered or "safety system" in lowered or "content_policy" in lowered


def image_generation_moderation_reply(prompt: str) -> str:
    suggestion = safe_image_generation_prompt(prompt)
    return (
        "这次图片生成被安全审核拦下了。我已经试着改成更日常、更保守的版本重试，但还是没能通过。"
        "可以把描述再往普通生活场景靠一点，比如：\n"
        f"{suggestion}"
    )


def should_direct_image_generation(prompt: str) -> bool:
    if prompt.lstrip().startswith(("临场感知：", "萤火巡望：")):
        return False
    text = strip_awareness_context(prompt).lower()
    if any(marker in text for marker in IMAGE_QUESTION_MARKERS) and not any(marker in text for marker in IMAGE_COMMAND_MARKERS):
        return False
    return any(marker in text for marker in IMAGE_GENERATION_MARKERS)


def image_attachments(attachments: list[str] | None) -> list[str]:
    return [str(Path(path)) for path in attachments or [] if Path(path).suffix.lower() in IMAGE_EXTENSIONS]


def strip_awareness_context(prompt: str) -> str:
    text = prompt
    for marker in ("\n\n临场感知：", "\n\n萤火巡望："):
        text = text.split(marker, 1)[0]
    return text.strip()


def strip_awareness_attachments(attachments: list[str] | None, workspace: Path) -> list[str]:
    screenshots = workspace / "screenshots"
    kept: list[str] = []
    for raw_path in attachments or []:
        path = Path(raw_path).expanduser()
        try:
            resolved = path.resolve()
        except OSError:
            kept.append(raw_path)
            continue
        if resolved.parent == screenshots and resolved.name.startswith(("chat_context_", "firefly_watch_")):
            continue
        kept.append(raw_path)
    return kept


def has_awareness_context(prompt: str, attachments: list[str] | None, workspace: Path) -> bool:
    return strip_awareness_context(prompt) != prompt.strip() or strip_awareness_attachments(attachments, workspace) != list(attachments or [])


def chat_timeout_seconds(config: dict[str, object]) -> float:
    try:
        return max(10.0, float(config.get("chat_timeout_sec") or 300))
    except (TypeError, ValueError):
        return 90.0


def normalize_error_message(message: str) -> str:
    if "Model returned an empty assistant message" in message:
        return "模型这次没有返回可显示内容，本轮已跳过。请重试一次。"
    return message


async def maybe_await(value: Any) -> Any:
    return await value if inspect.isawaitable(value) else value


def path_inside(path: str | Path, root: str | Path) -> bool:
    try:
        Path(path).expanduser().resolve().relative_to(Path(root).expanduser().resolve())
        return True
    except (OSError, ValueError):
        return False


async def run_direct_image_generation(
    *,
    prompt: str,
    cwd: str | None = None,
    workspace: str | Path | None = None,
    attachments: list[str] | None = None,
    history: list[dict[str, str]] | None = None,
) -> FireflyResponse:
    cwd_path = Path(cwd or Path.cwd()).resolve()
    workspace_root = initialize_workspace(workspace)
    workspace_config = load_config(workspace_root)
    response = FireflyResponse(text="", provider="openharness", model=str(workspace_config.get("image_generation_model") or ""))
    use_face_reference = is_firefly_self_image_request(strip_awareness_context(prompt), history)
    image_paths = image_attachments(attachments)
    with openharness_environment(workspace_config):
        settings = firefly_settings_transform(workspace_config, workspace_root, cwd_path)(load_settings())
        config = _resolve_image_generation_config(settings)
        if use_face_reference and FIREFLY_FACE_REFERENCE_IMAGE.is_file():
            image_paths.insert(0, str(FIREFLY_FACE_REFERENCE_IMAGE))
        stamp = time.strftime("%Y%m%d_%H%M%S") + f"_{time.time_ns() % 1_000_000:06d}"

        async def execute_generation(prompt_text: str, suffix: str = ""):
            output_path = cwd_path / "generated_images" / f"firefly_{stamp}{suffix}.png"
            model = str(config.get("model") or "")
            arguments = ImageGenerationToolInput(
                prompt=prompt_text,
                image_paths=image_paths,
                output_path=str(output_path),
                model=model or None,
                quality="high" if use_face_reference and model.lower().startswith("gpt-image") else "medium",
                input_fidelity="high" if use_face_reference and model.lower().startswith("gpt-image") else None,
            )
            return await ImageGenerationTool().execute(
                arguments,
                ToolExecutionContext(cwd=cwd_path, metadata={"image_generation_config": config}),
            )

        initial_prompt = image_generation_prompt(prompt, history)
        if use_face_reference:
            initial_prompt = f"{initial_prompt}\n\n{FIREFLY_FACE_REFERENCE_PROMPT}"
        result = await execute_generation(initial_prompt)
        if result.is_error and image_generation_moderation_blocked(result.output):
            retry_prompt = safe_image_generation_prompt(prompt, history)
            if use_face_reference:
                retry_prompt = f"{retry_prompt}\n\n{FIREFLY_FACE_REFERENCE_PROMPT}"
            result = await execute_generation(retry_prompt, "_safe")
            if result.is_error:
                response.text = image_generation_moderation_reply(prompt)
                return response
    if result.is_error:
        response.errors.append(result.output)
        return response
    response.invoked_skills = ["image_generation"]
    if use_face_reference:
        response.invoked_skills.append("firefly-face-reference")
    paths = [str(path) for path in result.metadata.get("paths", [])] if isinstance(result.metadata, dict) else []
    if paths:
        followup = await run_firefly_prompt(
            prompt=image_generation_followup_prompt(prompt, history),
            cwd=str(cwd_path),
            workspace=workspace_root,
            attachments=paths,
            history=history,
            remember=False,
        )
        response.status.extend(followup.status)
        response.errors.extend(followup.errors)
        reply = followup.text.strip() or image_generation_reply(prompt)
        notices = "\n".join(f"生成的图片已保存到 `{path}`。" for path in paths)
        response.text = f"{reply}\n{notices}" if reply else notices
    else:
        response.text = result.output
    return response


async def run_firefly_prompt(
    *,
    prompt: str,
    cwd: str | None = None,
    workspace: str | Path | None = None,
    model: str | None = None,
    max_turns: int | None = None,
    provider_profile: str | None = None,
    history: list[dict[str, str]] | None = None,
    attachments: list[str] | None = None,
    remember: bool = True,
    use_memory_context: bool = True,
    permission_prompt=None,
    edit_approval_prompt=None,
) -> FireflyResponse:
    cwd_path = str(Path(cwd or Path.cwd()).resolve())
    workspace_root = initialize_workspace(workspace)
    response = FireflyResponse(text="")
    workspace_config = load_config(workspace_root)
    memory_context = build_memory_context(prompt, history, workspace_config, workspace_root, cwd_path) if use_memory_context else ""
    openharness_context = await build_openharness_context(prompt, workspace_config, workspace_root, cwd_path)
    upload_context = build_upload_context(attachments)
    extra_context = "\n\n".join(part for part in (memory_context, upload_context, openharness_context) if part.strip())
    with openharness_environment(workspace_config):
        try:
            skill_dirs = openharness_skill_dirs(workspace_config, workspace_root)
            permission_mode = permission_mode_value(workspace_config)
            settings_transform = firefly_settings_transform(workspace_config, workspace_root, cwd_path)
            if not should_direct_image_generation(prompt):
                base_transform = settings_transform

                def settings_transform(settings, base_transform=base_transform):
                    settings = base_transform(settings)
                    allowed_tools = [tool for tool in settings.permission.allowed_tools if tool != "image_generation"]
                    return settings.model_copy(update={"permission": settings.permission.model_copy(update={"allowed_tools": allowed_tools})})

            if not remember:
                base_transform = settings_transform

                def settings_transform(settings, base_transform=base_transform):
                    settings = base_transform(settings)
                    memory = settings.memory.model_copy(update={"enabled": False, "session_memory_enabled": False, "auto_extract_enabled": False})
                    return settings.model_copy(update={"memory": memory})

            extra_tools = firefly_desktop_tools(workspace_config, workspace_root)

            async def approve_firefly_permission(tool_name: str, reason: str) -> bool:
                if tool_name in {"write_file", "edit_file"}:
                    return True
                if permission_prompt is None:
                    return False
                return bool(await maybe_await(permission_prompt(tool_name, reason)))

            async def approve_firefly_edit(path: str, diff: str, added: int, removed: int) -> str:
                if not (library_write_allowed(path, workspace_config, workspace_root) or path_inside(path, cwd_path)):
                    return "reject"
                if edit_approval_prompt is not None:
                    return str(await maybe_await(edit_approval_prompt(path, diff, added, removed)))
                return "approve" if library_write_allowed(path, workspace_config, workspace_root) else "reject"

            with contextlib.redirect_stderr(io.StringIO()):
                bundle = await build_runtime(
                    cwd=cwd_path,
                    model=model,
                    max_turns=max_turns,
                    system_prompt=build_firefly_system_prompt(cwd_path, extra_prompt=extra_context),
                    active_profile=provider_profile,
                    session_backend=FireflySessionBackend(workspace_root) if remember else NullSessionBackend(),
                    enforce_max_turns=max_turns is not None,
                    include_project_memory=False,
                    permission_mode=permission_mode,
                    permission_prompt=approve_firefly_permission,
                    extra_skill_dirs=skill_dirs,
                    edit_approval_prompt=approve_firefly_edit,
                    settings_transform=settings_transform,
                    extra_tools=extra_tools,
                )
        except SystemExit:
            response.errors.append("OpenHarness provider 尚未配置。请先在回应核心中配置 OpenHarness，或运行 `oh setup` / `oh auth status`。")
            return response

        try:
            await start_runtime(bundle)

            async def print_system(message: str) -> None:
                response.status.append(message)

            async def render_event(event: Any) -> None:
                if isinstance(event, AssistantTextDelta):
                    response.text += event.text
                elif isinstance(event, ErrorEvent):
                    response.errors.append(normalize_error_message(event.message))
                elif isinstance(event, StatusEvent):
                    response.status.append(event.message)

            async def clear_output() -> None:
                response.text = ""

            prompt_with_history = _prompt_with_history(prompt, history)
            await handle_line(
                bundle,
                prompt_with_history,
                print_system=print_system,
                render_event=render_event,
                clear_output=clear_output,
                user_message=_user_message_with_attachments(prompt_with_history, attachments),
            )
            response.provider = "openharness"
            response.model = str(model or "")
            invoked = bundle.engine.tool_metadata.get("invoked_skills")
            if isinstance(invoked, list):
                response.invoked_skills = [str(item) for item in invoked if str(item).strip()]
            if remember:
                remember_turn(prompt, response.text, workspace_config, workspace_root, cwd_path)
            return response
        finally:
            await close_runtime(bundle)


def run_firefly_print_mode(
    *,
    prompt: str,
    cwd: str | None = None,
    workspace: str | Path | None = None,
    model: str | None = None,
    max_turns: int | None = None,
    provider_profile: str | None = None,
) -> int:
    try:
        response = asyncio.run(
            run_firefly_prompt(
                prompt=prompt,
                cwd=cwd,
                workspace=workspace,
                model=model,
                max_turns=max_turns,
                provider_profile=provider_profile,
            )
        )
    except RuntimeError as error:
        print(str(error), file=sys.stderr)
        return 1
    for message in response.status:
        print(message, file=sys.stderr)
    for message in response.errors:
        print(message, file=sys.stderr)
    if response.text.strip():
        print(response.text.strip())
    return 1 if response.errors else 0


class FireflyRuntime:
    def __init__(
        self,
        *,
        cwd: str | None = None,
        workspace: str | Path | None = None,
        model: str | None = None,
        provider_profile: str | None = None,
        max_turns: int | None = None,
    ) -> None:
        self.cwd = cwd
        self.workspace = workspace
        self.model = model
        self.provider_profile = provider_profile
        self.max_turns = max_turns
        self._chat_lock = threading.Lock()

    def configure(
        self,
        *,
        model: str | None = None,
        provider_profile: str | None = None,
        max_turns: int | None = None,
    ) -> None:
        with self._chat_lock:
            self.model = model
            self.provider_profile = provider_profile
            self.max_turns = max_turns

    def chat(
        self,
        prompt: str,
        history: list[dict[str, str]] | None = None,
        attachments: list[str] | None = None,
        remember: bool = True,
        use_memory_context: bool = True,
        permission_prompt=None,
        edit_approval_prompt=None,
    ) -> FireflyResponse:
        with self._chat_lock:
            return self._chat(
                prompt,
                history,
                attachments,
                remember=remember,
                use_memory_context=use_memory_context,
                permission_prompt=permission_prompt,
                edit_approval_prompt=edit_approval_prompt,
            )

    def _chat(
        self,
        prompt: str,
        history: list[dict[str, str]] | None = None,
        attachments: list[str] | None = None,
        remember: bool = True,
        use_memory_context: bool = True,
        permission_prompt=None,
        edit_approval_prompt=None,
    ) -> FireflyResponse:
        if should_direct_image_generation(prompt):
            return asyncio.run(
                run_direct_image_generation(
                    prompt=prompt,
                    cwd=self.cwd,
                    workspace=self.workspace,
                    attachments=attachments,
                    history=history,
                )
            )
        workspace_root = initialize_workspace(self.workspace)
        timeout = chat_timeout_seconds(load_config(workspace_root))
        request = {
            "prompt": prompt,
            "cwd": self.cwd,
            "workspace": workspace_root,
            "model": self.model,
            "provider_profile": self.provider_profile,
            "max_turns": self.max_turns,
            "history": history,
            "attachments": attachments,
            "remember": remember,
            "use_memory_context": use_memory_context,
            "permission_prompt": permission_prompt,
            "edit_approval_prompt": edit_approval_prompt,
        }
        if has_awareness_context(prompt, attachments, workspace_root):
            try:
                return asyncio.run(asyncio.wait_for(run_firefly_prompt(**request), timeout=timeout))
            except TimeoutError:
                try:
                    retry_request = {
                        **request,
                        "prompt": strip_awareness_context(prompt),
                        "attachments": strip_awareness_attachments(attachments, workspace_root),
                    }
                    return asyncio.run(
                        asyncio.wait_for(run_firefly_prompt(**retry_request), timeout=timeout),
                    )
                except TimeoutError:
                    pass
                return FireflyResponse(text="", errors=[f"请求超时（{int(timeout)} 秒）。请稍后重试；图片整理这类任务可以分批处理。"])
        try:
            return asyncio.run(asyncio.wait_for(run_firefly_prompt(**request), timeout=timeout))
        except TimeoutError:
            return FireflyResponse(text="", errors=[f"请求超时（{int(timeout)} 秒）。请稍后重试；图片整理这类任务可以分批处理。"])
