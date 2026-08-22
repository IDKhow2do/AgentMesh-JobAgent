"""Deterministic Zhilian session-evidence classification."""

from __future__ import annotations

from typing import Any


ZHILIAN_SESSION_EVIDENCE_VERSION = 2


def classify_zhilian_session_evidence(data: dict[str, Any]) -> str:
    """Recheck graded browser evidence without trusting a single page control."""

    return normalize_zhilian_session_evidence(data)["state"]


def normalize_zhilian_session_evidence(data: dict[str, Any]) -> dict[str, Any]:
    """Normalize public, non-sensitive account signals before classifying them."""

    try:
        evidence_version = int(data.get("sessionEvidenceVersion") or 0)
    except (TypeError, ValueError):
        evidence_version = 0
    if evidence_version < ZHILIAN_SESSION_EVIDENCE_VERSION:
        return {
            "state": _legacy_session_state(data),
            "reason": "legacy_session_evidence",
            "weak_login": _evidence_list(data, "weakLoginEvidence"),
            "strong_login": _evidence_list(data, "strongLoginEvidence"),
            "account": _evidence_list(data, "accountEvidence"),
            "strong_account": _evidence_list(data, "strongAccountEvidence"),
            "content": _evidence_list(data, "contentEvidence"),
            "account_signals": _account_signals(data),
            "decision": {},
        }

    ready_state = str(data.get("readyState") or "unknown")
    weak_login = _evidence_list(data, "weakLoginEvidence")
    strong_login = _evidence_list(data, "strongLoginEvidence")
    account = _evidence_list(data, "accountEvidence")
    strong_account = _evidence_list(data, "strongAccountEvidence")
    content = _evidence_list(data, "contentEvidence")
    account_signals = _account_signals(data)

    if account_signals["accountNavigation"]:
        _append_unique(account, "account_navigation")
    if account_signals["profileIdentity"]:
        _append_unique(strong_account, "profile_identity")
    if account_signals["resumeManagement"]:
        _append_unique(strong_account, "resume_management")
    if account_signals["deliveryActivity"]:
        _append_unique(strong_account, "delivery_activity")
    if account_signals["interviewActivity"]:
        _append_unique(strong_account, "interview_activity")

    has_account_navigation = "account_navigation" in account
    has_strong_account = len(strong_account) >= 2 or (
        has_account_navigation and len(strong_account) >= 1
    )
    has_strong_login = bool(strong_login)

    if "auth_route" in strong_login:
        state = "login_required"
        reason = "authentication_route"
    elif ready_state != "complete":
        state = "loading"
        reason = "document_loading"
    elif has_strong_login and has_strong_account:
        state = "unknown"
        reason = "strong_login_and_account_conflict"
    elif has_strong_login:
        state = "login_required"
        reason = "strong_login_evidence"
    elif has_strong_account:
        state = "logged_in"
        reason = (
            "strong_account_overrides_weak_login_control"
            if weak_login
            else "strong_account_evidence"
        )
    elif weak_login and account:
        state = "unknown"
        reason = "weak_login_and_account_evidence"
    elif weak_login:
        state = "login_required"
        reason = "weak_login_without_account_evidence"
    elif account:
        state = "unknown"
        reason = "account_evidence_below_threshold"
    elif content:
        state = "page_ready"
        reason = "public_content_ready"
    else:
        state = "unknown"
        reason = "insufficient_evidence"

    return {
        "state": state,
        "reason": reason,
        "weak_login": weak_login,
        "strong_login": strong_login,
        "account": account,
        "strong_account": strong_account,
        "content": content,
        "account_signals": account_signals,
        "decision": {
            "reason": reason,
            "hasStrongLogin": has_strong_login,
            "hasStrongAccount": has_strong_account,
            "hasAccountNavigation": has_account_navigation,
            "strongAccountThreshold": 1 if has_account_navigation else 2,
        },
    }


def _evidence_list(data: dict[str, Any], key: str) -> list[str]:
    values = data.get(key)
    if not isinstance(values, list):
        return []
    normalized: list[str] = []
    for value in values:
        if value:
            _append_unique(normalized, str(value))
    return normalized


def _account_signals(data: dict[str, Any]) -> dict[str, bool]:
    raw = data.get("accountSignals")
    values = raw if isinstance(raw, dict) else {}
    return {
        "accountNavigation": values.get("accountNavigation") is True,
        "profileIdentity": values.get("profileIdentity") is True,
        "resumeManagement": values.get("resumeManagement") is True,
        "deliveryActivity": values.get("deliveryActivity") is True,
        "interviewActivity": values.get("interviewActivity") is True,
    }


def _append_unique(values: list[str], value: str) -> None:
    if value not in values:
        values.append(value)


def _legacy_session_state(data: dict[str, Any]) -> str:
    state = str(data.get("sessionState") or "")
    if state:
        return state
    if data.get("loginRequired"):
        return "login_required"
    if data.get("loggedIn"):
        return "logged_in"
    return ""
