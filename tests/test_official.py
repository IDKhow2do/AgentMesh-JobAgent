from jobagent.official import (
    BrowserLimits,
    authorize_final_review,
    build_official_queue,
    claim_items,
    detect_ats,
    review_is_valid,
    update_item,
)


def _official_job(company: str, url_suffix: str):
    return {
        "platform": "boss",
        "company": company,
        "title": "AI Engineer",
        "city": "上海",
        "url": f"https://boss/{url_suffix}",
        "decision": "selected",
        "official_url": f"https://boards.greenhouse.io/{company.lower()}/jobs/{url_suffix}",
        "official_match_confidence": 0.95,
        "official_evidence": {"company_match": True, "title_match": True, "location_match": True},
        "resume_variant": "AI版",
    }


def test_detect_known_ats_hosts():
    assert detect_ats("https://boards.greenhouse.io/acme/jobs/1") == "greenhouse"
    assert detect_ats("https://acme.wd5.myworkdayjobs.com/jobs/1") == "workday"
    assert detect_ats("https://jobs.lever.co/acme/1") == "lever"


def test_cross_channel_duplicate_becomes_one_queue_item():
    jobs = [
        {"platform": "boss", "company": "Acme", "title": "AI Engineer", "city": "上海", "url": "https://boss/1", "decision": "selected"},
        {"platform": "liepin", "company": "Acme", "title": "AI Engineer", "city": "上海", "url": "https://liepin/2", "decision": "selected"},
    ]
    queue = build_official_queue(jobs)
    assert len(queue["items"]) == 1
    assert queue["items"][0]["preferred_channel"] == "platform"
    assert queue["items"][0]["status"] == "fallback_platform"
    assert len(queue["items"][0]["sources"]) == 2


def test_verified_official_route_is_preferred():
    queue = build_official_queue([_official_job("Acme", "1")])
    item = queue["items"][0]
    assert item["preferred_channel"] == "official"
    assert item["ats"] == "greenhouse"
    assert item["resume_variant"] == "AI版"


def test_form_claim_respects_two_active_forms_and_skips_platform_fallbacks():
    jobs = [_official_job(f"C{index}", str(index)) for index in range(5)]
    jobs.append({"platform": "boss", "company": "Fallback", "title": "AI", "city": "上海", "url": "https://boss/fallback", "decision": "selected"})
    queue = build_official_queue(jobs)
    first_claim = claim_items(queue, kind="form")
    assert len(first_claim) == 2
    assert all(item["preferred_channel"] == "official" for item in first_claim)
    assert len(claim_items(queue, kind="form")) == 0


def test_submit_requires_review_then_is_serial():
    queue = build_official_queue([_official_job("A", "a"), _official_job("B", "b")])
    first, second = queue["items"]
    try:
        update_item(queue, first["canonical_job_key"], "submitting")
    except ValueError as exc:
        assert "final_user_review_required" in str(exc)
    else:
        raise AssertionError("submit should be blocked before final review")

    authorize_final_review(queue)
    assert review_is_valid(queue)
    update_item(queue, first["canonical_job_key"], "submitting")
    try:
        update_item(queue, second["canonical_job_key"], "submitting")
    except ValueError as exc:
        assert "concurrency is 1" in str(exc)
    else:
        raise AssertionError("second simultaneous submit should be rejected")

    update_item(queue, first["canonical_job_key"], "submitted", submitted_via="official")
    assert review_is_valid(queue), "execution status must not invalidate the approved materials"
    update_item(queue, second["canonical_job_key"], "submitting")


def test_material_change_invalidates_review_but_status_change_does_not():
    queue = build_official_queue([_official_job("A", "a")])
    authorize_final_review(queue)
    assert review_is_valid(queue)
    item = queue["items"][0]
    item["status"] = "filling"
    assert review_is_valid(queue)
    item["resume_variant"] = "Different Resume"
    assert not review_is_valid(queue)


def test_browser_limits_reject_parallel_submit_configuration():
    try:
        BrowserLimits(max_submits=2)
    except ValueError:
        pass
    else:
        raise AssertionError("max_submits must remain one")
