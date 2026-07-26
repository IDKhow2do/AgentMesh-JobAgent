from __future__ import annotations

import json

import pytest

from jobagent.cli import _dispatch, build_parser
from jobagent.infra import rounds, state
from jobagent.infra.interaction_protocol import validate_interaction_required


def _profile() -> dict:
    return {
        "schema_version": 1,
        "basic": {"currentCity": "深圳", "totalExperience": 6},
        "career": {"currentJob": {"title": "数据分析师"}},
        "preferences": {
            "targetRoles": [
                {
                    "title": "数据分析师",
                    "confidence": "inferred",
                    "priority": 1,
                },
                {
                    "title": "商业分析师",
                    "confidence": "inferred",
                    "priority": 2,
                },
            ]
        },
    }


@pytest.fixture
def isolated_round_state(tmp_path, monkeypatch):
    profile_path = tmp_path / "profile.json"
    current_path = tmp_path / "current-round.json"
    history_dir = tmp_path / "rounds"
    profile_path.write_text(json.dumps(_profile(), ensure_ascii=False), encoding="utf-8")
    monkeypatch.setattr(state, "profile_path", lambda: profile_path)
    monkeypatch.setattr(state, "current_round_path", lambda: current_path)
    monkeypatch.setattr(rounds, "current_round_path", lambda: current_path)
    monkeypatch.setattr(rounds, "rounds_dir", lambda: history_dir)
    return current_path


def test_round_start_without_answer_returns_shared_interaction(isolated_round_state):
    result = _dispatch(build_parser().parse_args(["round", "start"]))

    assert result["ok"] is False
    assert result["error"] == "interaction_required"
    interaction = validate_interaction_required(result["interaction"])
    assert interaction["protocol"] == "agentmesh360.interaction_required"
    assert interaction["preferred_presentation"] == "card"
    assert interaction["allow_text_fallback"] is True
    assert interaction["fields"][0]["allow_other"] is True
    assert interaction["fields"][0]["known_values"] == ["数据分析师", "商业分析师"]
    assert "1. 按照建议岗位开始投递" in interaction["fallback_text"]
    assert not isolated_round_state.exists()


def test_accept_suggested_creates_confirmed_round(isolated_round_state):
    result = _dispatch(
        build_parser().parse_args(["round", "start", "--accept-suggested"])
    )

    assert result["ok"] is True
    intent = result["workflow"]["intent"]
    assert intent["status"] == "confirmed"
    assert intent["source"] == "suggested"
    assert intent["target_roles"] == ["数据分析师", "商业分析师"]
    assert isolated_round_state.exists()


def test_explicit_role_replaces_suggestions(isolated_round_state):
    result = _dispatch(
        build_parser().parse_args(
            ["round", "start", "--target-role", "数据运营经理"]
        )
    )

    assert result["workflow"]["intent"]["source"] == "user_explicit"
    assert result["workflow"]["intent"]["target_roles"] == ["数据运营经理"]


def test_accept_and_explicit_role_append_in_stable_order(isolated_round_state):
    result = _dispatch(
        build_parser().parse_args(
            [
                "round",
                "start",
                "--accept-suggested",
                "--target-role",
                "数据运营经理",
            ]
        )
    )

    assert result["workflow"]["intent"]["source"] == "suggested_plus_explicit"
    assert result["workflow"]["intent"]["target_roles"] == [
        "数据分析师",
        "商业分析师",
        "数据运营经理",
    ]


def test_active_round_is_idempotent_and_rejects_retargeting(isolated_round_state):
    first = _dispatch(
        build_parser().parse_args(["round", "start", "--target-role", "数据运营经理"])
    )
    repeated = _dispatch(build_parser().parse_args(["round", "start"]))

    assert repeated["workflow"]["round_id"] == first["workflow"]["round_id"]

    with pytest.raises(rounds.RoundOrderError) as error:
        _dispatch(
            build_parser().parse_args(
                ["round", "start", "--target-role", "AI产品经理"]
            )
        )
    assert error.value.payload["error"] == "round_intent_conflict"


def test_schema_v2_active_round_is_preserved_with_legacy_intent():
    payload = {
        "schema_version": 2,
        "round_id": "round-existing",
        "status": "active",
        "created_at": "2026-07-20T00:00:00+00:00",
        "updated_at": "2026-07-20T00:00:00+00:00",
        "platform_order": list(rounds.DEFAULT_PLATFORM_ORDER),
        "browser_session_id": "local-cdp-19222",
        "platforms": {
            "boss": {"status": "completed"},
            "liepin": {"status": "discovered"},
            "zhilian": {"status": "pending"},
            "51job": {"status": "pending"},
        },
    }

    migrated = rounds.migrate_round_payload(payload)

    assert migrated["schema_version"] == 3
    assert migrated["platforms"] == payload["platforms"]
    assert migrated["intent"]["status"] == "legacy_implicit"
    assert migrated["migration"]["reason"] == "preserve_active_round_and_mark_legacy_intent"
