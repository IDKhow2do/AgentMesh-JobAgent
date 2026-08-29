from jobagent.official import BrowserLimits, build_official_queue, canonical_job_key, claim_items, detect_ats, update_item


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


def test_verified_official_route_is_preferred():
    job = {
        "platform": "boss",
        "company": "Acme",
        "title": "AI Engineer",
        "city": "上海",
        "url": "https://boss/1",
        "decision": "selected",
        "official_url": "https://boards.greenhouse.io/acme/jobs/1",
        "official_match_confidence": 0.95,
        "official_evidence": {"company_match": True, "title_match": True},
    }
    queue = build_official_queue([job])
    item = queue["items"][0]
    assert item["preferred_channel"] == "official"
    assert item["ats"] == "greenhouse"


def test_form_claim_respects_two_active_forms():
    jobs = []
    for index in range(5):
        jobs.append({"platform": "boss", "company": f"C{index}", "title": "AI", "city": "上海", "url": f"https://boss/{index}", "decision": "selected"})
    queue = build_official_queue(jobs)
    assert len(claim_items(queue, kind="form")) == 2
    assert len(claim_items(queue, kind="form")) == 0


def test_submit_is_serial():
    jobs = [
        {"platform": "boss", "company": "A", "title": "AI", "city": "上海", "url": "https://boss/a", "decision": "selected"},
        {"platform": "boss", "company": "B", "title": "AI", "city": "上海", "url": "https://boss/b", "decision": "selected"},
    ]
    queue = build_official_queue(jobs)
    first, second = queue["items"]
    update_item(queue, first["canonical_job_key"], "submitting")
    try:
        update_item(queue, second["canonical_job_key"], "submitting")
    except ValueError as exc:
        assert "concurrency is 1" in str(exc)
    else:
        raise AssertionError("second simultaneous submit should be rejected")


def test_browser_limits_reject_parallel_submit_configuration():
    try:
        BrowserLimits(max_submits=2)
    except ValueError:
        pass
    else:
        raise AssertionError("max_submits must remain one")
