"""AgentMesh360 host interaction protocol helpers."""

from __future__ import annotations

from typing import Any

INTERACTION_PROTOCOL = "agentmesh360.interaction_required"
INTERACTION_PROTOCOL_VERSION = 1
SUPPORTED_FIELD_TYPES = {"single", "multi", "text"}


class InteractionProtocolError(ValueError):
    pass


def build_interaction_required(
    *,
    interaction_id: str,
    product_id: str,
    kind: str,
    title: str,
    prompt: str,
    fields: list[dict[str, Any]],
    fallback_text: str,
    continuation_action: str,
    idempotency_key: str,
) -> dict[str, Any]:
    payload = {
        "event": "interaction_required",
        "protocol": INTERACTION_PROTOCOL,
        "protocol_version": INTERACTION_PROTOCOL_VERSION,
        "interaction_id": interaction_id,
        "product_id": product_id,
        "kind": kind,
        "title": title,
        "prompt": prompt,
        "required": True,
        "preferred_presentation": "card",
        "allow_text_fallback": True,
        "fields": fields,
        "fallback_text": fallback_text,
        "continuation": {
            "action": continuation_action,
            "idempotency_key": idempotency_key,
        },
    }
    validate_interaction_required(payload)
    return payload


def validate_interaction_required(payload: dict[str, Any]) -> dict[str, Any]:
    if payload.get("event") != "interaction_required":
        raise InteractionProtocolError("interaction event must be interaction_required")
    if payload.get("protocol") != INTERACTION_PROTOCOL:
        raise InteractionProtocolError("interaction protocol mismatch")
    if payload.get("protocol_version") != INTERACTION_PROTOCOL_VERSION:
        raise InteractionProtocolError("interaction protocol version mismatch")
    for key in ("interaction_id", "product_id", "kind", "title", "prompt", "fallback_text"):
        if not str(payload.get(key) or "").strip():
            raise InteractionProtocolError(f"interaction {key} is required")
    fields = payload.get("fields")
    if not isinstance(fields, list) or not fields:
        raise InteractionProtocolError("interaction fields must be a non-empty list")
    field_ids: set[str] = set()
    for field in fields:
        if not isinstance(field, dict):
            raise InteractionProtocolError("interaction field must be an object")
        field_id = str(field.get("field_id") or "").strip()
        if not field_id or field_id in field_ids:
            raise InteractionProtocolError("interaction field ids must be unique and non-empty")
        field_ids.add(field_id)
        field_type = str(field.get("type") or "")
        if field_type not in SUPPORTED_FIELD_TYPES:
            raise InteractionProtocolError(f"unsupported interaction field type: {field_type}")
        if not str(field.get("label") or "").strip():
            raise InteractionProtocolError("interaction field label is required")
        options = field.get("options")
        if field_type in {"single", "multi"}:
            if not isinstance(options, list) or not options:
                raise InteractionProtocolError("choice fields require options")
            option_ids = [str(option.get("option_id") or "") for option in options]
            if any(not value for value in option_ids) or len(option_ids) != len(set(option_ids)):
                raise InteractionProtocolError("interaction option ids must be unique and non-empty")
    continuation = payload.get("continuation")
    if not isinstance(continuation, dict):
        raise InteractionProtocolError("interaction continuation is required")
    if not str(continuation.get("action") or "").strip():
        raise InteractionProtocolError("interaction continuation action is required")
    if not str(continuation.get("idempotency_key") or "").strip():
        raise InteractionProtocolError("interaction idempotency key is required")
    return payload


def build_host_presentations(payload: dict[str, Any]) -> dict[str, Any]:
    """Build optional host-native arguments without changing the shared protocol."""

    validate_interaction_required(payload)
    fields = payload["fields"]
    codex: dict[str, Any] = {
        "tool": "request_user_input",
        "requires_callable_tool_in_current_mode": True,
        "fallback_field": "interaction.fallback_text",
        "supported": False,
    }
    if len(fields) == 1:
        field = fields[0]
        options = field.get("options") or []
        if field.get("type") == "single" and 2 <= len(options) <= 3:
            defaults = set(field.get("default_option_ids") or [])
            rendered_options: list[dict[str, str]] = []
            answer_mapping: dict[str, str] = {}
            for option in options:
                label = str(option["label"])
                if option["option_id"] in defaults:
                    label = f"{label} (Recommended)"
                rendered_options.append(
                    {
                        "label": label,
                        "description": str(option.get("description") or option["label"]),
                    }
                )
                answer_mapping[label] = str(option["option_id"])
            codex.update(
                {
                    "supported": True,
                    "arguments": {
                        "questions": [
                            {
                                "header": str(field["label"])[:12],
                                "id": str(field["field_id"]),
                                "question": str(payload["prompt"]),
                                "options": rendered_options,
                            }
                        ]
                    },
                    "answer_mapping": answer_mapping,
                    "free_text_other": {
                        "field_id": str(field["field_id"]),
                        "response_key": "other_text",
                        "default_option_id": (
                            "replace_roles"
                            if "replace_roles"
                            in {str(option["option_id"]) for option in options}
                            else None
                        ),
                        "target_role_source": "other_text",
                    },
                }
            )
        else:
            codex["unsupported_reason"] = "current_interaction_requires_free_text"
    else:
        codex["unsupported_reason"] = "current_interaction_has_multiple_fields"
    return {
        "preferred": "native_card",
        "fallback": "text",
        "adapters": {"codex": codex},
    }
