"""Tests for the local-only Codex workflow added in the IDKhow2do fork."""

import argparse
import json

from jobagent.local_cli import _make_plan, _platform_delivery_jobs, _selected_jobs, cmd_apply


def test_make_plan_cross_product_and_caps_limit():
    plan = _make_plan(
        "boss",
        ["上海", "苏州"],
        ["FDE", "AI应用工程师"],
        page_limit=2,
        candidate_limit=500,
    )
    assert plan["platform"] == "boss"
    assert plan["candidate_limit"] == 100
    assert plan["source"] == "codex-local"
    assert plan["queries"] == [
        {"city": "上海", "keyword": "FDE", "page_limit": 2},
        {"city": "上海", "keyword": "AI应用工程师", "page_limit": 2},
        {"city": "苏州", "keyword": "FDE", "page_limit": 2},
        {"city": "苏州", "keyword": "AI应用工程师", "page_limit": 2},
    ]


def test_selected_jobs_accepts_only_explicit_selection():
    payload = {
        "jobs": [
            {"id": "a", "decision": "selected"},
            {"id": "b", "decision": "review"},
            {"id": "c", "decision": "rejected"},
            {"id": "d", "selected": True},
            {"id": "e"},
        ]
    }
    selected = _selected_jobs(payload)
    assert [item["id"] for item in selected] == ["a", "d"]


def test_selected_jobs_accepts_bare_list():
    selected = _selected_jobs(
        [
            {"id": "a", "recommendation": "SELECTED"},
            {"id": "b", "recommendation": "review"},
        ]
    )
    assert [item["id"] for item in selected] == ["a"]


def test_official_preferred_resume_is_not_repeated_on_platform():
    jobs = [
        {"platform": "zhilian", "company": "A", "title": "AI", "decision": "selected", "preferred_channel": "official"},
        {"platform": "boss", "company": "B", "title": "AI", "decision": "selected", "preferred_channel": "official", "platform_action": "message_only"},
        {"platform": "liepin", "company": "C", "title": "AI", "decision": "selected", "preferred_channel": "platform"},
    ]
    deliver, skipped = _platform_delivery_jobs(jobs)
    assert [job["company"] for job in deliver] == ["B", "C"]
    assert skipped[0]["company"] == "A"
    assert skipped[0]["reason"] == "official_channel_preferred"


def test_real_platform_send_is_blocked_without_final_review(tmp_path, capsys):
    review = tmp_path / "review.json"
    review.write_text(
        json.dumps(
            {
                "jobs": [
                    {
                        "platform": "boss",
                        "company": "A",
                        "title": "AI",
                        "city": "上海",
                        "url": "https://boss/a",
                        "decision": "selected",
                        "greeting": "hello",
                    }
                ],
                "final_review_authorization": None,
            }
        ),
        encoding="utf-8",
    )
    args = argparse.Namespace(input=str(review), send=True, limit=20, out=None)
    assert cmd_apply(args) == 2
    output = json.loads(capsys.readouterr().out)
    assert output["mode"] == "send_blocked"
    assert "final_user_review_required" in output["error"]
