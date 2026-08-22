from jobagent.platforms.zhilian.collect import ZhilianCollectResult
from scripts.ci.zhilian_headed_public_gate import (
    _evaluate_one_page_collection_boundary,
    _explicit_public_login_wall_observed,
    _safe_collector_gate_payload,
)


def test_public_login_wall_preserves_route_gate_and_names_unverified_boundary():
    outcome = _evaluate_one_page_collection_boundary(
        explicit_login_wall=True,
        parsed_candidate_count=1,
        collector_ok=True,
        collector_candidate_count=1,
        page_two_attempted=False,
        collection_budget_satisfied=True,
        all_parser_candidates_reviewable=False,
        all_collector_candidates_reviewable=False,
    )

    assert outcome == {
        "ok": True,
        "status": "passed_route_only_login_wall",
        "remaining_unverified": "candidate_reviewability",
    }


def test_login_wall_that_appears_during_collection_is_classified_explicitly():
    collected = ZhilianCollectResult(
        query="产品经理",
        city="深圳",
        url="https://www.zhaopin.com/jobs",
        jobs=[],
        snapshot={"loginRequired": True},
        ok=False,
        error="zhilian_login_required",
    )

    assert _explicit_public_login_wall_observed(False, collected) is True


def test_missing_reviewability_still_fails_without_a_login_wall():
    outcome = _evaluate_one_page_collection_boundary(
        explicit_login_wall=False,
        parsed_candidate_count=1,
        collector_ok=True,
        collector_candidate_count=1,
        page_two_attempted=False,
        collection_budget_satisfied=True,
        all_parser_candidates_reviewable=False,
        all_collector_candidates_reviewable=False,
    )

    assert outcome == {
        "ok": False,
        "status": "failed_one_page_collection_boundary",
        "remaining_unverified": "candidate_reviewability",
    }


def test_reviewable_candidates_pass_the_full_collection_boundary():
    outcome = _evaluate_one_page_collection_boundary(
        explicit_login_wall=False,
        parsed_candidate_count=5,
        collector_ok=True,
        collector_candidate_count=20,
        page_two_attempted=False,
        collection_budget_satisfied=True,
        all_parser_candidates_reviewable=True,
        all_collector_candidates_reviewable=True,
    )

    assert outcome == {
        "ok": True,
        "status": "continue",
        "remaining_unverified": "",
    }


def test_collector_gate_payload_uses_public_result_contract():
    collected = ZhilianCollectResult(
        query="产品经理",
        city="郑州",
        url="https://www.zhaopin.com/jobs",
        jobs=[],
        snapshot={
            "readyState": "complete",
            "candidateCount": 0,
            "jobSurfaceCount": 2,
        },
        ok=False,
        error="zhilian_job_cards_not_found",
    )

    assert _safe_collector_gate_payload(collected) == {
        "collector_error": "zhilian_job_cards_not_found",
        "collector_retryable": True,
        "collector_requires_user_action": False,
        "collector_diagnostics": {
            "ready_state": "complete",
            "candidate_count": 0,
            "job_surface_count": 2,
        },
    }
