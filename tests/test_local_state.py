from pathlib import Path

from jobagent.local_state import (
    annotate_job_history,
    authorize_platform_review,
    authorized_selected_jobs,
    hydrate_decision_cache,
    platform_review_is_valid,
    profile_digest,
    render_final_review,
    save_decision_cache,
)


def _job(**overrides):
    base = {
        "platform": "boss",
        "company": "Acme",
        "title": "AI Engineer",
        "city": "上海",
        "url": "https://boss/1",
        "jd": "Build AI applications",
    }
    base.update(overrides)
    return base


def test_history_marks_new_then_seen_then_changed(tmp_path: Path):
    index = tmp_path / "index.json"
    first = [_job()]
    stats = annotate_job_history(first, index)
    assert stats["new"] == 1
    assert first[0]["history"]["is_new"] is True

    second = [_job()]
    stats = annotate_job_history(second, index)
    assert stats["seen"] == 1
    assert second[0]["history"]["seen_count"] == 2

    third = [_job(jd="Changed JD")]
    stats = annotate_job_history(third, index)
    assert stats["changed"] == 1
    assert third[0]["history"]["is_changed"] is True


def test_decision_cache_is_profile_and_job_sensitive(tmp_path: Path):
    career = tmp_path / "career"
    career.mkdir()
    (career / "TARGETS.md").write_text("AI", encoding="utf-8")
    digest = profile_digest(career)
    cache = tmp_path / "decisions.json"
    jobs = [_job(decision="selected", score=90, reasons=["fit"])]
    annotate_job_history(jobs, tmp_path / "index.json")
    assert save_decision_cache(jobs, cache, digest) == 1

    fresh = [_job()]
    annotate_job_history(fresh, tmp_path / "index.json")
    assert hydrate_decision_cache(fresh, cache, digest) == 1
    assert fresh[0]["decision"] == "selected"
    assert fresh[0]["decision_cached"] is True

    (career / "TARGETS.md").write_text("Different target", encoding="utf-8")
    changed_profile = [_job()]
    annotate_job_history(changed_profile, tmp_path / "index.json")
    assert hydrate_decision_cache(changed_profile, cache, profile_digest(career)) == 0


def test_platform_send_authorization_binds_exact_plan():
    payload = {"jobs": [_job(decision="selected", score=88, greeting="hello")]}
    auth = authorize_platform_review(payload)
    assert auth["approved"] is True
    assert platform_review_is_valid(payload)
    assert len(authorized_selected_jobs(payload)) == 1

    payload["jobs"][0]["greeting"] = "changed after approval"
    assert not platform_review_is_valid(payload)
    try:
        authorized_selected_jobs(payload)
    except ValueError as exc:
        assert "final_user_review_required" in str(exc)
    else:
        raise AssertionError("changed plan must require a new approval")


def test_partial_approval_delivers_only_approved_key():
    payload = {
        "jobs": [
            _job(decision="selected"),
            _job(company="Beta", url="https://boss/2", decision="selected"),
        ]
    }
    from jobagent.official import canonical_job_key

    approved = canonical_job_key(payload["jobs"][1])
    authorize_platform_review(payload, [approved])
    selected = authorized_selected_jobs(payload)
    assert len(selected) == 1
    assert selected[0]["company"] == "Beta"


def test_final_review_markdown_contains_user_visible_details():
    payload = {
        "jobs": [
            _job(
                decision="selected",
                score=91,
                risks=["software years"],
                reasons=["domain fit"],
                greeting="你好",
                resume_variant="FDE版",
                preferred_channel="official",
                official_url="https://jobs.example.com/1",
                screening_answers={"可接受出差?": "30%以内"},
            )
        ]
    }
    text = render_final_review(payload)
    assert "最终投递评审" in text
    assert "Acme" in text
    assert "FDE版" in text
    assert "30%以内" in text
