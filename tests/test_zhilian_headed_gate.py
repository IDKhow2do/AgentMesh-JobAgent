from jobagent.domain.models import Job
from jobagent.platforms.zhilian.collect import ZhilianCollectResult
from scripts.ci.zhilian_headed_public_gate import (
    _bounded_public_detail_candidates,
    _candidates_safe_after_detail_gate,
    _evaluate_one_page_collection_boundary,
    _explicit_public_login_wall_observed,
    _fixture_document_attachable,
    _fixture_document_retained,
    _fixture_search_control_layout_ready,
    _fixture_search_action_target_opened,
    _safe_collector_gate_payload,
    _safe_reviewability_summary,
)


def test_fixture_can_stop_an_official_committed_document():
    assert _fixture_document_attachable(
        {
            "hostname": "www.zhaopin.com",
            "readyState": "loading",
            "documentReady": True,
        }
    ) is True
    assert _fixture_document_attachable(
        {
            "hostname": "www.zhaopin.com",
            "readyState": "interactive",
            "documentReady": True,
        }
    ) is True
    assert _fixture_document_attachable(
        {
            "hostname": "example.com",
            "readyState": "complete",
            "documentReady": True,
        }
    ) is False


def test_fixture_accepts_native_or_user_gesture_search_targets():
    assert _fixture_search_action_target_opened(
        ["search_action_target_opened"]
    ) is True
    assert _fixture_search_action_target_opened(
        ["search_action_target_blocked", "search_action_target_gesture_opened"]
    ) is True
    assert _fixture_search_action_target_opened(
        ["search_action_target_blocked", "search_action_target_gesture_blocked"]
    ) is False


def test_fixture_waits_for_search_controls_to_have_committed_layout():
    assert _fixture_search_control_layout_ready(
        {"documentReady": True, "inputReady": True, "buttonReady": True}
    ) is True
    assert _fixture_search_control_layout_ready(
        {"documentReady": True, "inputReady": True, "buttonReady": False}
    ) is False


def test_fixture_retention_requires_official_origin_and_exact_kind():
    retained = {
        "fixtureReady": True,
        "officialOrigin": True,
        "kind": "entry",
    }
    assert _fixture_document_retained(retained, "entry") is True
    assert _fixture_document_retained(retained, "target_results") is False
    assert _fixture_document_retained(
        {**retained, "officialOrigin": False}, "entry"
    ) is False


def test_public_detail_gate_uses_a_bounded_sample_without_rejecting_large_sets():
    candidates = [object() for _ in range(20)]
    sampled = _bounded_public_detail_candidates(candidates)

    assert len(sampled) == 3
    assert sampled == candidates[:3]


def test_public_login_wall_preserves_route_gate_and_names_unverified_boundary():
    outcome = _evaluate_one_page_collection_boundary(
        explicit_login_wall=True,
        parsed_candidate_count=1,
        collector_ok=True,
        collector_candidate_count=1,
        page_two_attempted=False,
        collection_budget_satisfied=True,
        all_parser_candidates_safe=False,
        all_collector_candidates_safe=False,
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
        all_parser_candidates_safe=False,
        all_collector_candidates_safe=False,
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
        all_parser_candidates_safe=True,
        all_collector_candidates_safe=True,
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


def test_reviewability_summary_is_aggregate_and_redacted():
    jobs = [
        Job(
            name="产品经理",
            company="示例科技有限公司",
            salary="20-30K",
            city="深圳",
            url="https://www.zhaopin.com/jobdetail/SAFE-1.htm",
            platform="zhilian",
            raw_data={"cardSource": "job_anchor"},
        ),
        Job(
            name="运营经理",
            company="",
            salary="",
            city="深圳",
            url="https://www.zhaopin.com/jobdetail/SAFE-2.htm",
            platform="zhilian",
            raw_data={"cardSource": "job_surface"},
        ),
    ]

    summary = _safe_reviewability_summary(jobs)

    assert summary == {
        "candidate_count": 2,
        "reviewable_count": 1,
        "missing_field_counts": {"title": 0, "company": 1, "salary": 1},
        "issue_pattern_counts": {"company+salary": 1},
        "card_source_counts": {"job_anchor": 1, "job_surface": 1},
        "incomplete_card_source_counts": {"job_surface": 1},
        "incomplete_official_detail_count": 1,
    }
    encoded = str(summary)
    assert "示例科技" not in encoded
    assert "SAFE-" not in encoded


def test_incomplete_official_candidate_requires_bounded_detail_gate():
    candidate = Job(
        name="运营经理",
        company="示例科技有限公司",
        salary="",
        city="深圳",
        url="https://www.zhaopin.com/jobdetail/SAFE.htm",
        platform="zhilian",
    )

    assert _candidates_safe_after_detail_gate([candidate], {"ok": False}) is False
    assert _candidates_safe_after_detail_gate([candidate], {"ok": True}) is True


def test_incomplete_non_detail_candidate_stays_fail_closed():
    candidate = Job(
        name="运营经理",
        company="示例科技有限公司",
        salary="",
        city="深圳",
        url="https://www.zhaopin.com/jobs",
        platform="zhilian",
    )

    assert _candidates_safe_after_detail_gate([candidate], {"ok": True}) is False
