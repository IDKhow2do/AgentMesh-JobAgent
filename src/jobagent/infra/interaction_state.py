"""Persist one account-bound host interaction until it is answered."""

from __future__ import annotations

from typing import Any

from jobagent.infra import state
from jobagent.infra.rounds import utc_now

PENDING_INTERACTION_SCHEMA_VERSION = 1


def save_pending_interaction(
    interaction: dict[str, Any],
    *,
    stage: str,
    profile_digest: str,
    suggested_roles: list[str],
    previous_round_id: str | None,
    root_interaction_id: str | None = None,
    choice: str | None = None,
) -> dict[str, Any]:
    payload = {
        "schema_version": PENDING_INTERACTION_SCHEMA_VERSION,
        "product_id": "job_agent",
        "kind": str(interaction["kind"]),
        "stage": stage,
        "interaction_id": str(interaction["interaction_id"]),
        "root_interaction_id": root_interaction_id or str(interaction["interaction_id"]),
        "choice": choice,
        "profile_digest": profile_digest,
        "suggested_roles": list(suggested_roles),
        "previous_round_id": previous_round_id,
        "created_at": utc_now(),
        "interaction": interaction,
    }
    state.save_json(state.pending_interaction_path(), payload)
    return payload


def load_pending_interaction() -> dict[str, Any] | None:
    return state.load_json(state.pending_interaction_path())


def clear_pending_interaction() -> None:
    path = state.pending_interaction_path()
    if path.exists():
        path.unlink()
