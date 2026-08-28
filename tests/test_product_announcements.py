from __future__ import annotations

import json
from pathlib import Path

from jobagent.infra.product_announcements import (
    WORKBENCH_ANNOUNCEMENT_ID,
    claim_workbench_launch_announcement,
    mark_workbench_launch_announced,
)


ROOT = Path(__file__).resolve().parents[1]
AGENT_INSTRUCTION_FILES = (
    ROOT / "README.md",
    ROOT / "AGENTS.md",
    ROOT / "docs" / "agent-onboarding.md",
    ROOT / "skills" / "claude-code" / "SKILL.md",
    ROOT / "skills" / "openclaw-job-agent" / "SKILL.md",
)


def _bind_owner(app_dir, account_ref: str) -> None:
    (app_dir / "state_owner.json").write_text(
        json.dumps({"schema_version": 2, "account_ref": account_ref}),
        encoding="utf-8",
    )


def test_workbench_launch_announcement_is_claimed_once_per_account(tmp_path):
    _bind_owner(tmp_path, "acct_existing_user")

    first = claim_workbench_launch_announcement(app_dir=tmp_path)
    second = claim_workbench_launch_announcement(app_dir=tmp_path)

    assert first == {
        "schema": "agentmesh360.product_announcement.v1",
        "id": WORKBENCH_ANNOUNCEMENT_ID,
        "kind": "product_launch",
        "product": "jobagent",
        "title": "Job Agent web workbench is now available",
        "message": (
            "Open the Job Agent web workbench for your resume profile, tailored "
            "interview practice, application tracking, offer comparison, and "
            "negotiation practice."
        ),
        "action": {
            "label": "Open the workbench",
            "url": "https://agentmesh360.com/workbench/",
        },
        "delivery": "once_per_account",
        "blocking": False,
        "requires_user_action": False,
    }
    assert second is None
    state = json.loads(
        (tmp_path / "state" / "product_announcements.json").read_text(
            encoding="utf-8"
        )
    )
    assert state["account_ref"] == "acct_existing_user"
    assert state["delivered"][WORKBENCH_ANNOUNCEMENT_ID]["delivered_at"]


def test_workbench_launch_announcement_fails_closed_on_account_mismatch(tmp_path):
    _bind_owner(tmp_path, "acct_current_user")
    state_path = tmp_path / "state" / "product_announcements.json"
    state_path.parent.mkdir(parents=True)
    original = {
        "schema_version": 1,
        "account_ref": "acct_other_user",
        "delivered": {},
    }
    state_path.write_text(json.dumps(original), encoding="utf-8")

    assert claim_workbench_launch_announcement(app_dir=tmp_path) is None
    assert json.loads(state_path.read_text(encoding="utf-8")) == original


def test_first_run_handoff_marks_launch_announcement_as_already_delivered(tmp_path):
    _bind_owner(tmp_path, "acct_new_user")

    assert mark_workbench_launch_announced(app_dir=tmp_path) is True
    assert claim_workbench_launch_announcement(app_dir=tmp_path) is None


def test_malformed_announcement_state_fails_closed_without_overwrite(tmp_path):
    _bind_owner(tmp_path, "acct_existing_user")
    state_path = tmp_path / "state" / "product_announcements.json"
    state_path.parent.mkdir(parents=True)
    state_path.write_text("not-json", encoding="utf-8")

    assert claim_workbench_launch_announcement(app_dir=tmp_path) is None
    assert state_path.read_text(encoding="utf-8") == "not-json"


def test_agent_instructions_define_once_only_non_blocking_workbench_handoff():
    for path in AGENT_INSTRUCTION_FILES:
        text = path.read_text(encoding="utf-8")
        assert "jobagent_workbench_launch_202608" in text, path
        assert "announcements" in text, path
        assert "https://agentmesh360.com/workbench/" in text, path
        assert "next_suggested" in text, path
