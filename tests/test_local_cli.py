"""Tests for the local-only Codex workflow added in the IDKhow2do fork."""

from jobagent.local_cli import _make_plan, _selected_jobs


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
    selected = _selected_jobs([
        {"id": "a", "recommendation": "SELECTED"},
        {"id": "b", "recommendation": "review"},
    ])
    assert [item["id"] for item in selected] == ["a"]
