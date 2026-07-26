"""Target-role confirmation for a new delivery round."""

from __future__ import annotations

from typing import Any

from jobagent.infra.interaction_protocol import build_interaction_required
from jobagent.infra.protocol import digest_payload
from jobagent.infra.rounds import utc_now

MAX_TARGET_ROLES = 4


def suggested_target_roles(profile: dict[str, Any]) -> list[str]:
    preferences = profile.get("preferences") or {}
    raw_roles = preferences.get("targetRoles") or []
    ordered = sorted(
        (item for item in raw_roles if isinstance(item, dict)),
        key=lambda item: int(item.get("priority") or 999),
    )
    return _normalize_roles([str(item.get("title") or "") for item in ordered])[:3]


def build_round_intent(
    profile: dict[str, Any],
    *,
    accept_suggested: bool,
    target_roles: list[str] | None,
) -> dict[str, Any]:
    suggested = suggested_target_roles(profile) if accept_suggested else []
    explicit = _normalize_roles(target_roles or [])
    roles = _normalize_roles([*suggested, *explicit])
    if not roles:
        raise ValueError("At least one target role must be confirmed before starting a round.")
    if len(roles) > MAX_TARGET_ROLES:
        raise ValueError(f"A round supports at most {MAX_TARGET_ROLES} target roles.")
    if suggested and explicit:
        source = "suggested_plus_explicit"
    elif explicit:
        source = "user_explicit"
    else:
        source = "suggested"
    return {
        "status": "confirmed",
        "target_roles": roles,
        "source": source,
        "profile_digest": digest_payload(profile),
        "confirmed_at": utc_now(),
    }


def target_role_confirmation(
    profile: dict[str, Any],
    *,
    previous_round_id: str | None,
) -> dict[str, Any]:
    suggested = suggested_target_roles(profile)
    profile_digest = digest_payload(profile)
    context = previous_round_id or "initial"
    interaction_key = digest_payload(
        {
            "product_id": "job_agent",
            "kind": "target_role_confirmation",
            "profile_digest": profile_digest,
            "previous_round_id": context,
        }
    ).split(":", 1)[1][:20]
    interaction_id = f"jobagent:target-role:{interaction_key}"
    if suggested:
        roles_text = "、".join(suggested)
        prompt = (
            f"根据对你简历经历和能力的综合分析，我建议本轮优先投递：{roles_text}。"
            "除此以外，你还想投递其他岗位吗？"
        )
        fallback = (
            f"根据对你简历经历和能力的综合分析，我建议本轮优先投递：{roles_text}。\n\n"
            "请选择：\n"
            "1. 按照建议岗位开始投递\n"
            "2. 其他（直接回复岗位名称）\n\n"
            "你也可以回复“再加数据运营经理”或“只投数据运营经理”。"
        )
        fields = [
            {
                "field_id": "target_role_choice",
                "type": "single",
                "label": "本轮目标岗位",
                "required": True,
                "options": [
                    {
                        "option_id": "accept_suggested",
                        "label": "按照建议岗位开始投递",
                    }
                ],
                "allow_other": True,
                "other_label": "其他（用户输入）",
                "other_placeholder": "例如：数据运营经理",
                "known_values": suggested,
            }
        ]
    else:
        prompt = "没有得到足够可靠的默认岗位建议。请输入本轮想投递的目标岗位。"
        fallback = (
            "请输入本轮想投递的目标岗位，例如：\n"
            "数据运营经理\n\n"
            "收到岗位后，Agent 应执行 jobagent round start --target-role <岗位名称>。"
        )
        fields = [
            {
                "field_id": "target_roles",
                "type": "text",
                "label": "本轮目标岗位",
                "required": True,
                "placeholder": "例如：数据运营经理",
            }
        ]
    interaction = build_interaction_required(
        interaction_id=interaction_id,
        product_id="job_agent",
        kind="target_role_confirmation",
        title="确认本轮目标岗位",
        prompt=prompt,
        fields=fields,
        fallback_text=fallback,
        continuation_action="jobagent.round.start",
        idempotency_key=interaction_id,
    )
    return {
        "ok": False,
        "error": "interaction_required",
        "interaction": interaction,
        "suggested_roles": suggested,
        "next_suggested": (
            "jobagent round start --accept-suggested"
            if suggested
            else 'jobagent round start --target-role "<target role>"'
        ),
    }


def _normalize_roles(values: list[str]) -> list[str]:
    roles: list[str] = []
    seen: set[str] = set()
    for value in values:
        role = " ".join(value.split()).strip()
        key = role.casefold()
        if not role or len(role) > 80 or not any(character.isalpha() for character in role):
            continue
        if key in seen:
            continue
        seen.add(key)
        roles.append(role)
    return roles
