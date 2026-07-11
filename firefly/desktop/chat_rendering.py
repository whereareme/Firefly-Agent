"""Chat message rendering helpers for the Firefly desktop UI."""

from __future__ import annotations

import html
import re
from typing import Any

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import QFrame, QSizePolicy, QWidget


def format_skill_status(skills: list[str]) -> str:
    return "本轮使用 Skill: " + ", ".join(f"/{name}" for name in skills) if skills else ""


def normalize_chat_text(text: str) -> str:
    """Normalize line endings without discarding Markdown syntax."""
    lines = text.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    while lines and not lines[0].strip():
        lines.pop(0)
    while lines and not lines[-1].strip():
        lines.pop()
    return "\n".join(lines)


def format_chat_text(text: str) -> str:
    lines = [
        clean_chat_markdown(line.rstrip())
        for line in normalize_chat_text(text).split("\n")
    ]
    return "\n".join(lines)


def clean_chat_markdown(line: str) -> str:
    indent = line[: len(line) - len(line.lstrip())]
    text = line.lstrip()
    text = re.sub(r"^#{1,6}\s*", "", text)
    text = re.sub(r"`([^`\n]+)`", r"\1", text)
    text = re.sub(r"\*\*([^*\n]+)\*\*", r"\1", text)
    text = re.sub(r"__([^_\n]+)__", r"\1", text)
    text = re.sub(r"(?<!\*)\*([^*\n]+)\*(?!\*)", r"\1", text)
    return indent + text.replace("**", "").replace("__", "")


def render_chat_inline(text: str, *, dark_theme: bool = False) -> str:
    accent = "#9ce5dc" if dark_theme else "#08786f"
    underline = "#5eb8ae" if dark_theme else "#65bdb4"
    rendered = html.escape(text.strip())
    rendered = re.sub(
        r"`([^`\n]+)`",
        rf"<span style='color:{accent}; font-weight:700; border-bottom:1px solid {underline};'>\1</span>",
        rendered,
    )
    rendered = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", rendered)
    rendered = re.sub(r"__(.+?)__", r"<b>\1</b>", rendered)
    rendered = re.sub(r"(?<!\*)\*([^*\n]+)\*(?!\*)", r"\1", rendered)
    return rendered.replace("**", "").replace("*", "")


def render_chat_html(text: str, *, dark_theme: bool = False, is_user: bool = False) -> str:
    content = normalize_chat_text(text)
    if not content:
        return ""
    body_color = "#edf8f5" if dark_theme else "#10231f"
    heading_color = "#dcf5ef" if dark_theme else "#173c37"
    accent = "#8fe0d5" if dark_theme else "#2b8f88"
    code_background = "#102824" if dark_theme else "#f2f8f6"
    code_border = "#315e56" if dark_theme else "#dceae7"
    quote_background = "#17342f" if dark_theme else "#f2f8f6"
    quote_border = "#68b9ae" if dark_theme else "#9fd4ce"
    quote_color = "#d9f2ec" if dark_theme else "#2d4a45"
    if is_user and dark_theme:
        body_color = "#f1fbf8"
    blocks: list[str] = []
    code_lines: list[str] = []
    in_code = False
    pending_gap = False

    def block_margin(default: int = 5) -> str:
        return f"{10 if pending_gap and blocks else default}px 0 {default}px 0"

    def append_code_block() -> None:
        if not code_lines:
            return
        code = html.escape("\n".join(code_lines).rstrip())
        blocks.append(
            f"<pre style='margin:8px 0; padding:9px 10px; background:{code_background}; "
            f"border:1px solid {code_border}; border-radius:7px; color:{body_color}; "
            "font-family:Consolas,monospace; font-size:12px; white-space:pre-wrap;'>"
            f"{code}</pre>"
        )

    for raw_line in content.split("\n"):
        line = raw_line.rstrip()
        stripped = line.strip()
        if stripped.startswith("```"):
            if in_code:
                append_code_block()
                code_lines = []
                in_code = False
            else:
                in_code = True
                code_lines = []
            pending_gap = True
            continue
        if in_code:
            code_lines.append(line)
            continue
        if not stripped:
            pending_gap = True
            continue
        if stripped in {"#", "##", "###", "####", "#####", "######", "-", "*"} or re.fullmatch(r"\d+[.)、]", stripped):
            continue
        heading_match = re.match(r"^(#{1,6})\s*(.*)$", stripped)
        if heading_match:
            heading = render_chat_inline(heading_match.group(2), dark_theme=dark_theme)
            if heading:
                blocks.append(f"<p style='margin:{block_margin(6)}; color:{heading_color}; font-size:15px; font-weight:700;'>{heading}</p>")
            pending_gap = False
            continue
        if re.fullmatch(r"(?:[-*_]\s*){3,}", stripped):
            blocks.append("<hr style='border:0; height:1px; background:#dceae7; margin:10px 0;' />")
            pending_gap = False
            continue
        numbered_match = re.match(r"^(\d+)[.)、]\s+(.+)$", stripped)
        if numbered_match:
            number = html.escape(numbered_match.group(1))
            item = render_chat_inline(numbered_match.group(2), dark_theme=dark_theme)
            blocks.append(
                f"<table cellspacing='0' cellpadding='0' style='margin:{block_margin(4)};'>"
                f"<tr><td width='26' valign='top' style='color:{accent}; font-weight:700;'>{number}.</td>"
                f"<td valign='top'>{item}</td></tr></table>"
            )
            pending_gap = False
            continue
        bullet_match = re.match(r"^[-*•]\s+(.+)$", stripped)
        if bullet_match:
            item = render_chat_inline(bullet_match.group(1), dark_theme=dark_theme)
            blocks.append(
                f"<table cellspacing='0' cellpadding='0' style='margin:{block_margin(4)};'>"
                f"<tr><td width='18' valign='top' style='color:{accent}; font-weight:700;'>•</td>"
                f"<td valign='top'>{item}</td></tr></table>"
            )
            pending_gap = False
            continue
        quote_match = re.match(r"^>\s+(.+)$", stripped)
        if quote_match:
            quote = render_chat_inline(quote_match.group(1), dark_theme=dark_theme)
            blocks.append(
                f"<p style='margin:{block_margin(5)}; padding:6px 9px; background:{quote_background}; "
                f"border-left:3px solid {quote_border}; color:{quote_color};'>{quote}</p>"
            )
            pending_gap = False
            continue
        paragraph = render_chat_inline(stripped, dark_theme=dark_theme)
        if paragraph:
            blocks.append(f"<p style='margin:{block_margin(5)};'>{paragraph}</p>")
        pending_gap = False

    if in_code:
        append_code_block()
    return (
        "<div style='font-family:Microsoft YaHei UI, Microsoft YaHei, Segoe UI, sans-serif; "
        f"color:{body_color}; font-size:15px; font-weight:400; line-height:1.62;'>"
        + "".join(blocks)
        + "</div>"
    )


def chat_bubble_colors(is_user: bool, dark_theme: bool) -> tuple[str, str]:
    if dark_theme:
        return ("#1f6f68", "#4ab4aa") if is_user else ("#17342f", "#417a70")
    return ("#dff3ee", "#74bdb4") if is_user else ("#eefaf7", "#8acbc2")


class ChatBubble(QFrame):
    def __init__(self, is_user: bool, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.is_user = is_user
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        self.setSizePolicy(QSizePolicy.Maximum, QSizePolicy.Preferred)

    def paintEvent(self, event: Any) -> None:
        del event
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing, True)
        rect = self.rect().adjusted(7 if not self.is_user else 1, 1, -7 if self.is_user else -1, -3)
        body_path = QPainterPath()
        body_path.addRoundedRect(rect, 17, 17)
        tail_path = QPainterPath()
        if self.is_user:
            tail_path.moveTo(rect.right() - 12, rect.bottom() - 4)
            tail_path.cubicTo(rect.right() + 1, rect.bottom() - 4, rect.right() + 7, rect.bottom() - 7, rect.right() + 9, rect.bottom() - 13)
            tail_path.cubicTo(rect.right() + 4, rect.bottom() - 10, rect.right() + 1, rect.bottom() - 14, rect.right() - 2, rect.bottom() - 20)
            tail_path.lineTo(rect.right() - 10, rect.bottom() - 16)
        else:
            tail_path.moveTo(rect.left() + 12, rect.bottom() - 4)
            tail_path.cubicTo(rect.left() - 1, rect.bottom() - 4, rect.left() - 7, rect.bottom() - 7, rect.left() - 9, rect.bottom() - 13)
            tail_path.cubicTo(rect.left() - 4, rect.bottom() - 10, rect.left() - 1, rect.bottom() - 14, rect.left() + 2, rect.bottom() - 20)
            tail_path.lineTo(rect.left() + 10, rect.bottom() - 16)
        tail_path.closeSubpath()
        bubble_path = body_path.united(tail_path)
        fill, border = chat_bubble_colors(self.is_user, bool(self.window().property("darkTheme")))
        painter.fillPath(bubble_path, QColor(fill))
        painter.setPen(QPen(QColor(border), 1))
        painter.drawPath(bubble_path)
