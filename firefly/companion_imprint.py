"""Non-proxy client for the local companion imprint Sidecar."""

from __future__ import annotations

import json
import re
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


CONTROL_MARKER_PREFIX = "<!--FIREFLY_RELATIONSHIP:"
CONTROL_MARKER_PATTERN = re.compile(r"<!--FIREFLY_RELATIONSHIP:(.*?)-->", re.DOTALL)
EVENT_KINDS = frozenset(("memory", "gift", "anniversary"))
MAX_SUMMARY_LENGTH = 500
SIDECAR_TIMEOUT_SECONDS = 0.5


def companion_imprint_endpoint(config: dict[str, object]) -> str:
    try:
        port = int(config.get("companion_imprint_port") or 8787)
    except (TypeError, ValueError):
        port = 8787
    return f"http://127.0.0.1:{port}"


def fetch_companion_imprint_context(config: dict[str, object]) -> str:
    """Return relationship prompt context without blocking chat on Sidecar errors."""
    if not bool(config.get("companion_imprint_enabled", False)):
        return ""
    request = Request(f"{companion_imprint_endpoint(config)}/relationship/context", method="GET")
    try:
        with urlopen(request, timeout=SIDECAR_TIMEOUT_SECONDS) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except (HTTPError, URLError, OSError, UnicodeDecodeError, json.JSONDecodeError, TimeoutError):
        return ""
    context = payload.get("context") if isinstance(payload, dict) else None
    return context if isinstance(context, str) else ""


def strip_companion_imprint_markers(text: str) -> tuple[str, dict[str, str] | None]:
    """Hide reserved markers and return one valid final proposal, if present."""
    matches = list(CONTROL_MARKER_PATTERN.finditer(text))
    visible = CONTROL_MARKER_PATTERN.sub("", text)
    if len(matches) != 1 or text[matches[0].end() :].strip():
        return visible, None
    try:
        payload: Any = json.loads(matches[0].group(1))
    except (json.JSONDecodeError, RecursionError):
        return visible, None
    if not isinstance(payload, dict) or set(payload) != {"kind", "summary"}:
        return visible, None
    kind = payload.get("kind")
    summary = payload.get("summary")
    if (
        kind not in EVENT_KINDS
        or not isinstance(summary, str)
        or not summary.strip()
        or summary != summary.strip()
        or len(summary) > MAX_SUMMARY_LENGTH
        or any(ord(character) < 32 or 127 <= ord(character) <= 159 for character in summary)
    ):
        return visible, None
    return visible, {"kind": kind, "summary": summary}


def submit_companion_imprint_proposal(config: dict[str, object], proposal: dict[str, str] | None) -> bool:
    """Submit a validated proposal; failures never affect the visible reply."""
    if not bool(config.get("companion_imprint_enabled", False)) or proposal is None:
        return False
    body = json.dumps(proposal, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    request = Request(
        f"{companion_imprint_endpoint(config)}/relationship/proposals",
        data=body,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urlopen(request, timeout=SIDECAR_TIMEOUT_SECONDS) as response:
            return response.status == 202
    except (HTTPError, URLError, OSError, TimeoutError):
        return False


def record_companion_imprint_event(config: dict[str, object], proposal: dict[str, str]) -> dict[str, object]:
    """Persist one event after the user confirms it in Firefly."""
    if not bool(config.get("companion_imprint_enabled", False)):
        raise RuntimeError("同行印记尚未启用")
    body = json.dumps(proposal, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    request = Request(
        f"{companion_imprint_endpoint(config)}/relationship/records",
        data=body,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urlopen(request, timeout=SIDECAR_TIMEOUT_SECONDS) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except HTTPError as error:
        raise RuntimeError(f"同行印记服务拒绝记录（HTTP {error.code}）") from error
    except (URLError, OSError, TimeoutError) as error:
        raise RuntimeError("同行印记服务未响应") from error
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise RuntimeError("同行印记服务返回了无效数据") from error
    if not isinstance(payload, dict) or payload.get("recorded") is not True:
        raise RuntimeError("同行印记没有确认保存结果")
    return payload
