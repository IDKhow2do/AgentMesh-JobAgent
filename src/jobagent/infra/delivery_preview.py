"""User-visible delivery preview derived from a verified decision manifest."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from jobagent.infra.protocol import digest_payload

DELIVERY_PREVIEW_PROTOCOL = "agentmesh360.delivery_preview"
DELIVERY_PREVIEW_PROTOCOL_VERSION = 1

_PLATFORM_LABELS = {
    "boss": "Boss直聘",
    "liepin": "猎聘",
    "zhilian": "智联招聘",
    "51job": "51Job / 前程无忧",
}
_DELIVERY_ACTIONS = {
    "boss": ["personalized_greeting"],
    "liepin": ["resume", "personalized_greeting"],
    "zhilian": ["resume"],
    "51job": ["resume"],
}


class DeliveryPreviewError(RuntimeError):
    def __init__(self, payload: dict[str, Any]):
        super().__init__(str(payload.get("message") or payload.get("error") or "delivery preview error"))
        self.payload = payload


def _clean(value: Any) -> str:
    return " ".join(str(value or "").split())


def _preview_item(platform: str, item: dict[str, Any], index: int) -> dict[str, Any]:
    return {
        "index": index,
        "job_id": _clean(item.get("job_id") or item.get("id") or item.get("jobId")),
        "title": _clean(item.get("title") or item.get("name")) or "未命名岗位",
        "company": _clean(item.get("company")) or "公司未标注",
        "area": _clean(item.get("area")) or "地点未标注",
        "salary": _clean(item.get("salary")) or "薪资未标注",
        "url": _clean(item.get("url")),
        "score": item.get("score"),
        "reason": _clean(item.get("reason")),
        "risk": _clean(item.get("risk")),
        "delivery_actions": list(_DELIVERY_ACTIONS[platform]),
    }


def _preview_id(
    platform: str,
    discover_id: str,
    items: list[dict[str, Any]],
) -> str:
    digest = digest_payload(
        {
            "platform": platform,
            "discover_id": discover_id,
            "items": [
                {
                    "job_id": item["job_id"],
                    "url": item["url"],
                    "delivery_actions": item["delivery_actions"],
                }
                for item in items
            ],
        }
    )
    return "dpv_" + digest.removeprefix("sha256:")[:24]


def _fallback_text(
    *,
    platform: str,
    items: list[dict[str, Any]],
    next_suggested: str,
) -> str:
    label = _PLATFORM_LABELS[platform]
    lines = [
        f"{label}待投递岗位清单（共 {len(items)} 个）",
        "以下岗位已经完成云端匹配与签名审核，将按本轮授权自动投递。",
        "这是投递前告知，不需要再次确认；请先向用户完整展示清单，再立即继续执行投递。",
        "",
    ]
    if items:
        lines.extend(
            (
                f"{item['index']}. {item['title']}｜{item['company']}｜"
                f"{item['area']}｜{item['salary']}"
            )
            for item in items
        )
    else:
        lines.append("本平台没有待投递岗位。")
    lines.extend(["", f"展示完成后自动继续：{next_suggested}"])
    return "\n".join(lines)


def build_delivery_preview(
    *,
    platform: str,
    discover_id: str,
    send_candidates: list[dict[str, Any]],
    send_command: str,
    selected_count: int,
    promoted_count: int,
    review_count: int,
    rejected_count: int,
    skipped_delivered_count: int,
) -> dict[str, Any]:
    if platform not in _PLATFORM_LABELS:
        raise ValueError(f"Unsupported delivery preview platform: {platform}")
    items = [
        _preview_item(platform, item, index)
        for index, item in enumerate(send_candidates, start=1)
    ]
    preview_id = _preview_id(platform, discover_id, items)
    next_suggested = f"{send_command} --preview-id {preview_id}"
    payload = {
        "event": "delivery_preview",
        "protocol": DELIVERY_PREVIEW_PROTOCOL,
        "protocol_version": DELIVERY_PREVIEW_PROTOCOL_VERSION,
        "preview_id": preview_id,
        "product_id": "job-agent",
        "platform": platform,
        "platform_label": _PLATFORM_LABELS[platform],
        "discover_id": discover_id,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "title": f"{_PLATFORM_LABELS[platform]}待投递岗位清单",
        "message": (
            f"以下 {len(items)} 个岗位将按本轮授权自动投递。"
            "请先完整展示清单，然后自动继续；不要再次询问用户是否投递。"
        ),
        "display_required": True,
        "requires_user_action": False,
        "requires_user_confirmation": False,
        "automatic_continuation": True,
        "preferred_presentation": "table",
        "allow_text_fallback": True,
        "columns": [
            {"field": "index", "label": "序号"},
            {"field": "title", "label": "岗位"},
            {"field": "company", "label": "公司"},
            {"field": "area", "label": "地点"},
            {"field": "salary", "label": "薪资"},
        ],
        "summary": {
            "selected": selected_count,
            "promoted_from_review": promoted_count,
            "send_count": len(items),
            "remaining_review": max(0, review_count - promoted_count),
            "rejected": rejected_count,
            "skipped_delivered": skipped_delivered_count,
        },
        "items": items,
        "continuation": {
            "action": next_suggested,
            "automatic": True,
            "requires_user_confirmation": False,
        },
    }
    payload["fallback_text"] = _fallback_text(
        platform=platform,
        items=items,
        next_suggested=next_suggested,
    )
    validate_delivery_preview(
        payload,
        send_candidates=send_candidates,
        expected_platform=platform,
        expected_discover_id=discover_id,
    )
    return payload


def validate_delivery_preview(
    payload: dict[str, Any],
    *,
    send_candidates: list[dict[str, Any]],
    expected_platform: str,
    expected_discover_id: str,
    expected_preview_id: str | None = None,
) -> dict[str, Any]:
    if payload.get("event") != "delivery_preview":
        raise ValueError("delivery preview event mismatch")
    if payload.get("protocol") != DELIVERY_PREVIEW_PROTOCOL:
        raise ValueError("delivery preview protocol mismatch")
    if payload.get("protocol_version") != DELIVERY_PREVIEW_PROTOCOL_VERSION:
        raise ValueError("delivery preview protocol version mismatch")
    platform = str(payload.get("platform") or "")
    discover_id = str(payload.get("discover_id") or "")
    if platform not in _PLATFORM_LABELS or not discover_id:
        raise ValueError("delivery preview binding is incomplete")
    if platform != expected_platform or discover_id != expected_discover_id:
        raise ValueError("delivery preview platform or Discover binding mismatch")
    items = [
        _preview_item(platform, item, index)
        for index, item in enumerate(send_candidates, start=1)
    ]
    preview_id = _preview_id(platform, discover_id, items)
    if payload.get("preview_id") != preview_id:
        raise ValueError("delivery preview candidate binding mismatch")
    if expected_preview_id is not None and expected_preview_id != preview_id:
        raise ValueError("delivery preview handoff id mismatch")
    if payload.get("items") != items:
        raise ValueError("delivery preview items do not match reviewed candidates")
    if payload.get("display_required") is not True:
        raise ValueError("delivery preview must be displayed")
    if payload.get("requires_user_confirmation") is not False:
        raise ValueError("delivery preview must not request another confirmation")
    continuation = payload.get("continuation")
    if not isinstance(continuation, dict) or preview_id not in str(continuation.get("action") or ""):
        raise ValueError("delivery preview continuation is not bound to the preview")
    return payload


def preview_required_payload(platform: str, input_path: str | None) -> dict[str, Any]:
    source = f" --input {input_path}" if input_path else ""
    review_command = (
        f"jobagent boss greet preview{source}"
        if platform == "boss"
        else f"jobagent {platform} apply review{source}"
    )
    return {
        "ok": False,
        "error": "delivery_preview_required",
        "platform": platform,
        "message": (
            "The reviewed delivery list must be displayed before automatic delivery. "
            "Run the review command, show its complete delivery_preview, then follow its next_suggested."
        ),
        "request_preserved": True,
        "requires_user_action": False,
        "next_suggested": review_command,
    }
