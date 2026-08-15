"""51Job platform event audit log."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from typing import Any

from jobagent.domain.models import now_iso
from jobagent.infra.state import STATE_DIR, ensure_dirs


JOB51_DELIVERY_STATE_VERSION = 1
JOB51_RECONCILE_LIMIT = 2
JOB51_RECONCILE_MAX_AGE_SECONDS = 24 * 60 * 60


def job51_audit_log_path():
    ensure_dirs()
    return STATE_DIR / "job51_audit_log.json"


@dataclass
class Job51AuditEvent:
    action: str
    status: str
    job_url: str = ""
    job_name: str = ""
    company: str = ""
    error: str = ""
    message: str = ""
    evidence: dict[str, Any] = field(default_factory=dict)
    platform: str = "51job"
    created_at: str = field(default_factory=now_iso)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class Job51AuditLog:
    def __init__(self, path=None):
        self.path = path or job51_audit_log_path()

    def _load(self) -> list[dict[str, Any]]:
        if not self.path.exists():
            return []
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
            return data if isinstance(data, list) else []
        except Exception:
            return []

    def append(self, event: Job51AuditEvent) -> None:
        records = self._load()
        records.append(event.to_dict())
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(records, ensure_ascii=False, indent=2), encoding="utf-8")

    def append_event(self, action: str, status: str, **kwargs) -> None:
        self.append(Job51AuditEvent(action=action, status=status, **kwargs))

    def delivered_apply_send_keys(self) -> set[str]:
        return {
            key
            for key, state in self.apply_send_outcomes().items()
            if state.get("outcome") == "delivered"
        }

    def apply_send_outcomes(self) -> dict[str, dict[str, Any]]:
        """Return the latest cumulative outcome for each audited job.

        The log is append-only. This reducer keeps successful delivery proof,
        preserves clicked-but-unverified evidence across later card misses, and
        exposes terminal unavailable/unresolved outcomes without counting retry
        events as additional jobs.
        """
        outcomes: dict[str, dict[str, Any]] = {}
        for record in self._load():
            if record.get("action") != "apply_send":
                continue
            evidence = record.get("evidence") if isinstance(record.get("evidence"), dict) else {}
            key = str(evidence.get("job_id") or record.get("job_url") or "").strip()
            if not key:
                continue
            state = outcomes.setdefault(
                key,
                {
                    "outcome": "failed",
                    "terminal": False,
                    "click_observed": False,
                    "transition_observed": False,
                    "reconcile_attempt": 0,
                    "first_indeterminate_at": "",
                    "last_updated_at": "",
                },
            )
            status = str(record.get("status") or "")
            error = str(record.get("error") or "")
            created_at = str(record.get("created_at") or "")
            steps = evidence.get("steps") if isinstance(evidence.get("steps"), list) else []
            click_observed = any(
                isinstance(step, dict)
                and str(step.get("step") or "")
                in {"click_51job_apply", "click_51job_apply_recovery"}
                and step.get("ok") is True
                for step in steps
            )
            transition_observed = any(
                isinstance(step, dict)
                and str(step.get("step") or "")
                in {"inspect_after_apply", "observe_51job_apply_transition"}
                and (
                    step.get("observed_transition_stable") is True
                    or (
                        step.get("cardFound") is True
                        and step.get("applyAvailable") is False
                    )
                )
                for step in steps
            )
            resume_steps = [
                step
                for step in steps
                if isinstance(step, dict)
                and str(step.get("step") or "") == "resume_51job_indeterminate_delivery"
            ]
            explicit_attempts = [
                int(value)
                for value in [
                    evidence.get("reconcile_attempt"),
                    *[step.get("reconcile_attempt") for step in resume_steps],
                ]
                if isinstance(value, int) and not isinstance(value, bool)
            ]
            if explicit_attempts:
                state["reconcile_attempt"] = max(
                    int(state.get("reconcile_attempt") or 0),
                    max(explicit_attempts),
                )
            elif resume_steps:
                state["reconcile_attempt"] = int(state.get("reconcile_attempt") or 0) + 1
            if click_observed:
                state["click_observed"] = True
                if not state.get("first_indeterminate_at"):
                    state["first_indeterminate_at"] = str(
                        evidence.get("first_indeterminate_at") or created_at
                    )
            elif evidence.get("first_indeterminate_at") and not state.get("first_indeterminate_at"):
                state["first_indeterminate_at"] = str(evidence["first_indeterminate_at"])
            if transition_observed:
                state["transition_observed"] = True
            state["last_updated_at"] = created_at

            if status == "delivered" or error == "already_delivered":
                state["outcome"] = "delivered"
                state["terminal"] = True
                continue
            if state.get("outcome") == "delivered":
                continue
            if status == "unresolved" or error == "delivery_unresolved":
                state["outcome"] = "unresolved"
                state["terminal"] = True
                continue
            if state.get("outcome") == "unresolved":
                continue
            if (
                status == "indeterminate"
                or error in {"delivery_indeterminate", "delivery_not_verified"}
                or state.get("click_observed")
            ):
                state["outcome"] = "pending"
                state["terminal"] = False
                continue
            if error == "job_unavailable":
                state["outcome"] = "unavailable"
                state["terminal"] = True
                continue
            if status == "planned" or error == "dry_run":
                state["outcome"] = "planned"
                state["terminal"] = False
                continue
            state["outcome"] = "failed"
            state["terminal"] = False
        return outcomes

    def outcome_summary(self, job_keys: set[str] | None = None) -> dict[str, int]:
        outcomes = self.apply_send_outcomes()
        if job_keys is not None:
            outcomes = {key: value for key, value in outcomes.items() if key in job_keys}
        counts = {
            "total": len(outcomes),
            "terminal": 0,
            "delivered": 0,
            "unavailable": 0,
            "unresolved": 0,
            "pending": 0,
            "failed": 0,
        }
        for state in outcomes.values():
            outcome = str(state.get("outcome") or "failed")
            if state.get("terminal"):
                counts["terminal"] += 1
            if outcome in counts:
                counts[outcome] += 1
            elif outcome != "planned":
                counts["failed"] += 1
        return counts

    def indeterminate_apply_send_evidence(self) -> dict[str, dict[str, Any]]:
        """Return clicked-but-unverified jobs that have no later delivery proof.

        Older clients wrote `delivery_not_verified` after a successful click when
        the legacy history domain redirected to login. A later card-missing retry
        must not erase that click evidence.
        """
        return {
            key: {
                "click_observed": bool(state.get("click_observed")),
                "transition_observed": bool(state.get("transition_observed")),
                "reconcile_attempt": int(state.get("reconcile_attempt") or 0),
                "reconcile_limit": JOB51_RECONCILE_LIMIT,
                "first_indeterminate_at": str(state.get("first_indeterminate_at") or ""),
                "source_created_at": str(state.get("last_updated_at") or ""),
            }
            for key, state in self.apply_send_outcomes().items()
            if state.get("outcome") == "pending"
        }

    def list_recent(self, limit: int = 20) -> list[dict[str, Any]]:
        return self._load()[-max(1, int(limit)):]

    def summary(self) -> dict[str, Any]:
        event_counts = {
            "total": 0,
            "delivered": 0,
            "planned": 0,
            "failed": 0,
            "skipped": 0,
            "indeterminate": 0,
            "unresolved": 0,
        }
        summary = {
            "platform": "51job",
            "total": 0,
            "apply_open": {"total": 0, "opened": 0, "planned": 0, "failed": 0},
            "apply_send": {},
        }
        for record in self._load():
            action = record.get("action")
            status = record.get("status")
            summary["total"] += 1
            if action == "apply_open":
                bucket = summary["apply_open"]
                bucket["total"] += 1
                if status in bucket:
                    bucket[status] += 1
            if action == "apply_send":
                event_counts["total"] += 1
                if status in event_counts:
                    event_counts[status] += 1
        outcomes = self.outcome_summary()
        summary["apply_send"] = {
            "total": outcomes["total"],
            "terminal": outcomes["terminal"],
            "delivered": outcomes["delivered"],
            "planned": event_counts["planned"],
            "failed": outcomes["failed"],
            "skipped": outcomes["unavailable"],
            "indeterminate": outcomes["pending"],
            "unavailable": outcomes["unavailable"],
            "unresolved": outcomes["unresolved"],
            "pending": outcomes["pending"],
            "outcomes": outcomes,
            "events": event_counts,
        }
        return summary
