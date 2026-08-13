"""Fail-closed authorization for real delivery after a user-reviewed preview."""

from __future__ import annotations

import shlex
from datetime import datetime, timezone
from typing import Any

from jobagent.infra.protocol import digest_payload

DELIVERY_AUTHORIZATION_PROTOCOL = "agentmesh360.delivery_authorization"
DELIVERY_AUTHORIZATION_PROTOCOL_VERSION = 1


class DeliveryAuthorizationError(RuntimeError):
    def __init__(self, payload: dict[str, Any]):
        super().__init__(
            str(payload.get("message") or payload.get("error") or "delivery authorization error")
        )
        self.payload = payload


def _authorization_error(message: str) -> DeliveryAuthorizationError:
    return DeliveryAuthorizationError(
        {
            "ok": False,
            "error": "delivery_authorization_invalid",
            "message": message,
            "requires_user_action": True,
            "request_preserved": True,
        }
    )


def _authorization_body(
    *,
    account_ref: str,
    round_id: str,
    platform: str,
    discover_id: str,
    preview: dict[str, Any],
    send_candidates: list[dict[str, Any]],
    interaction_id: str,
    authorized_at: str,
) -> dict[str, Any]:
    return {
        "account_ref": account_ref,
        "round_id": round_id,
        "platform": platform,
        "discover_id": discover_id,
        "preview_id": str(preview.get("preview_id") or ""),
        "preview_digest": digest_payload(preview),
        "candidate_digest": digest_payload(send_candidates),
        "interaction_id": interaction_id,
        "authorized_at": authorized_at,
    }


def build_delivery_authorization(
    *,
    account_ref: str,
    round_id: str,
    platform: str,
    discover_id: str,
    preview: dict[str, Any],
    send_candidates: list[dict[str, Any]],
    interaction_id: str,
) -> dict[str, Any]:
    if not all((account_ref, round_id, platform, discover_id, interaction_id)):
        raise ValueError("Delivery authorization binding is incomplete.")
    authorized_at = datetime.now(timezone.utc).isoformat()
    body = _authorization_body(
        account_ref=account_ref,
        round_id=round_id,
        platform=platform,
        discover_id=discover_id,
        preview=preview,
        send_candidates=send_candidates,
        interaction_id=interaction_id,
        authorized_at=authorized_at,
    )
    authorization_id = "dau_" + digest_payload(body).removeprefix("sha256:")[:32]
    return {
        "protocol": DELIVERY_AUTHORIZATION_PROTOCOL,
        "protocol_version": DELIVERY_AUTHORIZATION_PROTOCOL_VERSION,
        "authorization_id": authorization_id,
        **body,
    }


def validate_delivery_authorization(
    payload: dict[str, Any],
    *,
    expected_authorization_id: str,
    account_ref: str,
    round_id: str,
    platform: str,
    discover_id: str,
    preview: dict[str, Any],
    send_candidates: list[dict[str, Any]],
) -> dict[str, Any]:
    if payload.get("protocol") != DELIVERY_AUTHORIZATION_PROTOCOL:
        raise _authorization_error("Delivery authorization protocol mismatch.")
    if payload.get("protocol_version") != DELIVERY_AUTHORIZATION_PROTOCOL_VERSION:
        raise _authorization_error("Delivery authorization protocol version mismatch.")
    authorized_at = str(payload.get("authorized_at") or "")
    interaction_id = str(payload.get("interaction_id") or "")
    if not authorized_at or not interaction_id:
        raise _authorization_error("Delivery authorization receipt is incomplete.")
    expected_body = _authorization_body(
        account_ref=account_ref,
        round_id=round_id,
        platform=platform,
        discover_id=discover_id,
        preview=preview,
        send_candidates=send_candidates,
        interaction_id=interaction_id,
        authorized_at=authorized_at,
    )
    expected_id = "dau_" + digest_payload(expected_body).removeprefix("sha256:")[:32]
    if str(payload.get("authorization_id") or "") != expected_id:
        raise _authorization_error("Delivery authorization binding mismatch.")
    if expected_authorization_id != expected_id:
        raise _authorization_error("Delivery authorization handoff ID mismatch.")
    for key, value in expected_body.items():
        if payload.get(key) != value:
            raise _authorization_error(f"Delivery authorization {key} mismatch.")
    return payload


def confirmation_required_payload(
    platform: str,
    input_path: str | None,
    *,
    message: str = "Review the complete delivery list and explicitly confirm it before delivery.",
) -> dict[str, Any]:
    source = f" --input {shlex.quote(input_path)}" if input_path else ""
    review_command = (
        f"jobagent boss greet preview{source}"
        if platform == "boss"
        else f"jobagent {platform} apply review{source}"
    )
    return {
        "ok": False,
        "error": "delivery_confirmation_required",
        "platform": platform,
        "message": message,
        "request_preserved": True,
        "requires_user_action": True,
        "next_suggested": review_command,
    }
