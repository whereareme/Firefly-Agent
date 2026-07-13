"""Low-frequency Firefly sticker helpers."""

from __future__ import annotations

import re
from pathlib import Path

DEFAULT_STICKER_EMOTIONS = (
    "happy",
    "shy",
    "surprised",
    "worried",
    "sleepy",
    "speechless",
)
STICKER_EMOTIONS = {
    "happy": "开心",
    "shy": "害羞",
    "surprised": "惊讶",
    "worried": "担心",
    "sleepy": "困倦",
    "speechless": "无奈",
}
STICKER_MARKER_RE = re.compile(r"\[\[sticker:(" + "|".join(DEFAULT_STICKER_EMOTIONS) + r")\]\]", re.IGNORECASE)


def sticker_reply_instruction() -> str:
    return (
        "互动表情规则：完成正常回复后，仅在情绪明确且表情能自然增添互动时，偶尔在最后单独附加一个内部标签，"
        "格式必须是 [[sticker:happy]]、[[sticker:shy]]、[[sticker:surprised]]、[[sticker:worried]]、"
        "[[sticker:sleepy]] 或 [[sticker:speechless]]。普通说明、提问、长任务回复不要附加标签。"
        "标签不会展示给用户，不要解释它。"
    )


def extract_sticker_emotion(text: str) -> tuple[str, str | None]:
    match = STICKER_MARKER_RE.search(text)
    if match is None:
        return text, None
    return (text[: match.start()] + text[match.end() :]).strip(), match.group(1).lower()


def sticker_prompt(emotion: str) -> str:
    label = STICKER_EMOTIONS[emotion]
    return (
        f"生成一张无文字、无水印、单角色、1:1 构图的 Q 版流萤表情包，情绪是{label}。"
        "构图简洁、角色清晰、适合在聊天中作为小表情直接展示。"
    )


def sticker_path(workspace: str | Path, emotion: str) -> Path:
    return Path(workspace) / "stickers" / f"firefly_{emotion}.png"
