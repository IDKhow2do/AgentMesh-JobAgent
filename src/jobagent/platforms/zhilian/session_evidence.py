"""Deterministic Zhilian session-evidence classification."""

from __future__ import annotations

from typing import Any


ZHILIAN_SESSION_EVIDENCE_VERSION = 2


def classify_zhilian_session_evidence(data: dict[str, Any]) -> str:
    """Recheck graded browser evidence without trusting a single page control."""

    try:
        evidence_version = int(data.get("sessionEvidenceVersion") or 0)
    except (TypeError, ValueError):
        evidence_version = 0
    if evidence_version < ZHILIAN_SESSION_EVIDENCE_VERSION:
        return _legacy_session_state(data)

    ready_state = str(data.get("readyState") or "unknown")
    weak_login = _evidence_set(data, "weakLoginEvidence")
    strong_login = _evidence_set(data, "strongLoginEvidence")
    account = _evidence_set(data, "accountEvidence")
    strong_account = _evidence_set(data, "strongAccountEvidence")
    content = _evidence_set(data, "contentEvidence")

    if "auth_route" in strong_login:
        return "login_required"
    if ready_state != "complete":
        return "loading"

    has_account_navigation = "account_navigation" in account
    has_strong_account = len(strong_account) >= 2 or (
        has_account_navigation and len(strong_account) >= 1
    )
    has_strong_login = bool(strong_login)

    if has_strong_login and has_strong_account:
        return "unknown"
    if has_strong_login:
        return "login_required"
    if has_strong_account:
        return "logged_in"
    if weak_login and account:
        return "unknown"
    if weak_login:
        return "login_required"
    if account:
        return "unknown"
    if content:
        return "page_ready"
    return "unknown"


def _evidence_set(data: dict[str, Any], key: str) -> set[str]:
    values = data.get(key)
    if not isinstance(values, list):
        return set()
    return {str(value) for value in values if value}


def _legacy_session_state(data: dict[str, Any]) -> str:
    state = str(data.get("sessionState") or "")
    if state:
        return state
    if data.get("loginRequired"):
        return "login_required"
    if data.get("loggedIn"):
        return "logged_in"
    return ""
