"""Deterministic contracts for graded Zhilian session evidence."""

from jobagent.platforms.zhilian.collect import _snapshot_failure
from jobagent.platforms.zhilian.session_evidence import classify_zhilian_session_evidence


def _probe(**overrides):
    payload = {
        "sessionEvidenceVersion": 2,
        "readyState": "complete",
        "sessionState": "unknown",
        "weakLoginEvidence": [],
        "strongLoginEvidence": [],
        "accountEvidence": [],
        "strongAccountEvidence": [],
        "contentEvidence": [],
    }
    payload.update(overrides)
    return payload


def test_strong_account_evidence_overrides_a_persistent_weak_login_control():
    payload = _probe(
        loginRequired=True,
        weakLoginEvidence=["visible_login_control"],
        accountEvidence=["account_navigation"],
        strongAccountEvidence=["resume_management", "application_activity"],
        contentEvidence=["search_input", "job_results"],
    )

    assert classify_zhilian_session_evidence(payload) == "logged_in"
    assert _snapshot_failure(payload) == ""


def test_strong_login_and_strong_account_evidence_remain_unknown():
    payload = _probe(
        strongLoginEvidence=["visible_credential_form"],
        accountEvidence=["account_navigation"],
        strongAccountEvidence=["resume_management"],
    )

    assert classify_zhilian_session_evidence(payload) == "unknown"
    assert _snapshot_failure(payload) == "zhilian_page_state_unknown"


def test_strong_login_evidence_without_authenticated_account_requires_login():
    payload = _probe(strongLoginEvidence=["visible_credential_form"])

    assert classify_zhilian_session_evidence(payload) == "login_required"
    assert _snapshot_failure(payload) == "zhilian_login_required"


def test_authentication_route_is_authoritative_even_before_document_complete():
    payload = _probe(
        readyState="loading",
        strongLoginEvidence=["auth_route"],
        accountEvidence=["account_navigation"],
        strongAccountEvidence=["resume_management"],
    )

    assert classify_zhilian_session_evidence(payload) == "login_required"


def test_weak_login_with_only_account_navigation_is_inconclusive():
    payload = _probe(
        weakLoginEvidence=["visible_login_control"],
        accountEvidence=["account_navigation"],
    )

    assert classify_zhilian_session_evidence(payload) == "unknown"


def test_weak_login_without_account_evidence_requires_login():
    payload = _probe(weakLoginEvidence=["visible_login_control"])

    assert classify_zhilian_session_evidence(payload) == "login_required"


def test_loading_document_is_not_classified_from_transient_account_controls():
    payload = _probe(
        readyState="loading",
        accountEvidence=["account_navigation"],
        strongAccountEvidence=["resume_management", "application_activity"],
    )

    assert classify_zhilian_session_evidence(payload) == "loading"


def test_legacy_probe_keeps_its_declared_state_for_compatibility():
    payload = {"sessionState": "logged_in", "accountEvidence": ["account_navigation"]}

    assert classify_zhilian_session_evidence(payload) == "logged_in"


def test_legacy_snapshot_without_session_fields_keeps_collection_compatible():
    payload = {"ok": True, "candidateCount": 1}

    assert classify_zhilian_session_evidence(payload) == ""
    assert _snapshot_failure(payload) == ""
