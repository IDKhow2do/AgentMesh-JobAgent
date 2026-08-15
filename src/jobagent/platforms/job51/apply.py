"""51Job apply/open and controlled resume-submit flows."""

from __future__ import annotations

import json
import math
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any
from urllib.parse import parse_qsl, urlencode, urldefrag, urlsplit, urlunsplit

from jobagent.domain.models import SendAttempt
from jobagent.drivers.boss import create_driver

from .audit import (
    JOB51_DELIVERY_STATE_VERSION,
    JOB51_RECONCILE_LIMIT,
    JOB51_RECONCILE_MAX_AGE_SECONDS,
    Job51AuditEvent,
    Job51AuditLog,
)


_JOB51_INDETERMINATE_ERROR = "delivery_indeterminate"
_JOB51_UNRESOLVED_ERROR = "delivery_unresolved"


@dataclass
class Job51ApplyOpenResult:
    ok: bool
    opened: int
    planned: int
    failed: int
    total: int
    events: list[dict[str, Any]] = field(default_factory=list)
    handoff: list[dict[str, Any]] = field(default_factory=list)
    mode: str = "manual_apply_open"
    platform: str = "51job"
    next_suggested: str = "Review opened 51Job pages manually, then run `jobagent 51job audit`."
    requires_user_action: bool = False
    user_prompt: str = ""

    def to_payload(self) -> dict[str, Any]:
        payload = {
            "ok": self.ok,
            "platform": self.platform,
            "mode": self.mode,
            "total": self.total,
            "planned": self.planned,
            "opened": self.opened,
            "failed": self.failed,
            "requires_user_action": self.requires_user_action,
            "handoff": self.handoff,
            "events": self.events,
            "next_suggested": self.next_suggested,
        }
        if self.user_prompt:
            payload["user_prompt"] = self.user_prompt
        return payload


class Job51ApplyOpener:
    def __init__(self, driver: Any | None = None, audit_log: Job51AuditLog | None = None):
        self.driver = driver
        self.audit_log = audit_log or Job51AuditLog()

    def open_jobs(self, jobs: list[dict[str, Any]], limit: int = 5, start: int = 0, wait_seconds: int = 3, dry_run: bool = False) -> Job51ApplyOpenResult:
        selected = jobs[max(0, start): max(0, start) + max(1, limit)]
        events: list[dict[str, Any]] = []
        handoff_items: list[dict[str, Any]] = []
        opened = planned = failed = 0
        for index, job in enumerate(selected, start=max(0, start)):
            url = _job51_open_url(job)
            handoff = _handoff_evidence(job)
            if not url:
                failed += 1
                event = self._event_from_job(job, status="failed", error="missing_job_url", message="Cannot open 51Job job without url.", evidence={"index": index, **handoff})
            elif dry_run:
                planned += 1
                event = self._event_from_job(job, status="planned", message="dry_run", evidence={"index": index, **handoff})
            else:
                driver = self.driver or create_driver(platform="51job")
                self.driver = driver
                result = driver.open_url_in_new_tab(url, wait_seconds=wait_seconds)
                if result.get("ok"):
                    opened += 1
                    event = self._event_from_job(job, status="opened", message="Opened for manual review.", evidence={"index": index, **handoff, "open_result": result})
                else:
                    failed += 1
                    event = self._event_from_job(job, status="failed", error=str(result.get("error") or "open_failed"), message="Failed to open 51Job page.", evidence={"index": index, **handoff, "open_result": result})
            self.audit_log.append(event)
            events.append(event.to_dict())
            handoff_items.append(_handoff_item(job, index=index, status=event.status, error=event.error))

        return Job51ApplyOpenResult(
            ok=failed == 0,
            opened=opened,
            planned=planned,
            failed=failed,
            total=len(selected),
            events=events,
            handoff=handoff_items,
            next_suggested="Review handoff, then rerun without `--dry-run` to open 51Job pages." if dry_run else "Review opened 51Job pages manually, then run `jobagent 51job audit`.",
            requires_user_action=opened > 0,
            user_prompt="" if dry_run else "请在已打开的前程无忧/51Job 页面中人工确认岗位。51Job 网页端“去聊聊”只是扫码引导，handoff 里的 greeting 仅作为投递前审阅备注，不会发送到 51Job 页面。",
        )

    def _event_from_job(self, job: dict[str, Any], status: str, message: str = "", error: str = "", evidence: dict[str, Any] | None = None) -> Job51AuditEvent:
        return Job51AuditEvent(
            action="apply_open",
            status=status,
            job_url=str(job.get("url") or ""),
            job_name=str(job.get("name") or job.get("title") or ""),
            company=str(job.get("company") or ""),
            error=error,
            message=message,
            evidence=evidence or {},
        )


class Job51ApplySender:
    """Controlled 51Job resume submission.

    51Job's web page exposes a real `投递` button and a `去聊聊` QR handoff.
    The greeting generated by `greet preview` is therefore a review note only;
    it is never filled into the 51Job web page.
    """

    def __init__(self, driver: Any | None = None, audit_log: Job51AuditLog | None = None):
        self.driver = driver
        self.audit_log = audit_log or Job51AuditLog()

    def send_batch(
        self,
        jobs: list[dict[str, Any]],
        limit: int = 5,
        start: int = 0,
        wait_seconds: int = 3,
        dry_run: bool = False,
        skip_delivered: bool = True,
        stop_on_failure: bool = True,
        on_attempt=None,
    ) -> list[SendAttempt]:
        selected = jobs[max(0, start): max(0, start) + max(1, limit)]
        delivered_keys = self.audit_log.delivered_apply_send_keys() if skip_delivered else set()
        indeterminate_evidence = self.audit_log.indeterminate_apply_send_evidence()
        prior_outcomes = self.audit_log.apply_send_outcomes() if skip_delivered else {}
        attempts: list[SendAttempt] = []
        for index, job in enumerate(selected, start=max(0, start)):
            message = str(job.get("cloud_greeting") or job.get("greeting") or "")
            key = _job51_job_key(job)
            url = _job51_open_url(job)
            prior_outcome = str((prior_outcomes.get(key) or {}).get("outcome") or "")
            if skip_delivered and key and prior_outcome in {"delivered", "unavailable", "unresolved"}:
                terminal_error = {
                    "delivered": "already_delivered",
                    "unavailable": "job_unavailable",
                    "unresolved": _JOB51_UNRESOLVED_ERROR,
                }[prior_outcome]
                attempt = SendAttempt(job_url=url, message=message, delivered=False, error="already_delivered")
                attempt.error = terminal_error
                attempt.steps = [
                    {
                        "step": "skip_51job_terminal_delivery",
                        "ok": True,
                        "reason": terminal_error,
                        "will_click": False,
                        "job_id": key,
                    }
                ]
                status = "unresolved" if terminal_error == _JOB51_UNRESOLVED_ERROR else "skipped"
                audit_message = {
                    "already_delivered": "Skipped because this 51Job job was already delivered.",
                    "job_unavailable": "Skipped because this 51Job job was already unavailable.",
                    _JOB51_UNRESOLVED_ERROR: (
                        "Skipped because bounded reconciliation already ended unresolved."
                    ),
                }[terminal_error]
            else:
                if not dry_run and key and key in indeterminate_evidence:
                    attempt = self._reconcile_indeterminate(
                        job,
                        message,
                        evidence=indeterminate_evidence[key],
                        wait_seconds=wait_seconds,
                    )
                else:
                    attempt = self._send_one(
                        job,
                        message,
                        wait_seconds=wait_seconds,
                        dry_run=dry_run,
                    )
                status = (
                    "planned"
                    if dry_run
                    else (
                        "delivered"
                        if attempt.delivered
                        else (
                            "indeterminate"
                            if attempt.error == _JOB51_INDETERMINATE_ERROR
                            else (
                                "unresolved"
                                if attempt.error == _JOB51_UNRESOLVED_ERROR
                                else ("skipped" if attempt.error == "job_unavailable" else "failed")
                            )
                        )
                    )
                )
                audit_message = (
                    "dry_run"
                    if dry_run
                    else (
                        "Delivered."
                        if attempt.delivered
                        else (
                            "Skipped because the job is no longer available in live search."
                            if attempt.error == "job_unavailable"
                            else (
                                "Apply action was observed; final verification remains indeterminate."
                                if attempt.error == _JOB51_INDETERMINATE_ERROR
                                else (
                                    "Bounded verification ended without enough evidence; no retry will click again."
                                    if attempt.error == _JOB51_UNRESOLVED_ERROR
                                    else "Failed."
                                )
                            )
                        )
                    )
                )
                if attempt.delivered and key:
                    delivered_keys.add(key)
                    indeterminate_evidence.pop(key, None)
                elif attempt.error == _JOB51_INDETERMINATE_ERROR and key:
                    state_evidence = _job51_attempt_delivery_state_evidence(attempt)
                    indeterminate_evidence[key] = {
                        "click_observed": True,
                        "transition_observed": any(
                            isinstance(step, dict)
                            and step.get("step") == "observe_51job_apply_transition"
                            and step.get("ok") is True
                            for step in attempt.steps
                        ),
                        **state_evidence,
                    }
            attempts.append(attempt)
            self.audit_log.append(
                Job51AuditEvent(
                    action="apply_send",
                    status=status,
                    job_url=attempt.job_url,
                    job_name=str(job.get("name") or job.get("title") or ""),
                    company=str(job.get("company") or ""),
                    error=attempt.error,
                    message=audit_message,
                    evidence={
                        "index": index,
                        "job_id": key,
                        "has_greeting": bool(message.strip()),
                        "greeting_generated": bool(message.strip()),
                        "greeting": message,
                        "greeting_role": "review_note",
                        "submit_action": "resume_submit",
                        "chat_action": "qr_only",
                        "score": job.get("score"),
                        "match_level": job.get("match_level") or job.get("recommendation") or job.get("cloud_recommendation"),
                        "steps": attempt.steps,
                        **_job51_attempt_delivery_state_evidence(attempt),
                    },
                )
            )
            if callable(on_attempt):
                on_attempt(attempt, index - max(0, start) + 1, len(selected))
            if stop_on_failure and not dry_run and status == "failed":
                break
        return attempts

    def _reconcile_indeterminate(
        self,
        job: dict[str, Any],
        message: str,
        *,
        evidence: dict[str, Any],
        wait_seconds: int,
    ) -> SendAttempt:
        url = _job51_open_url(job)
        job_id = _job51_job_key(job)
        attempt = SendAttempt(
            job_url=url,
            message=message,
            delivered=False,
            error=_JOB51_INDETERMINATE_ERROR,
        )
        if not url:
            attempt.error = "missing_job_url"
            return attempt
        prior_reconcile_attempt = int(evidence.get("reconcile_attempt") or 0)
        reconcile_attempt = prior_reconcile_attempt + 1
        first_indeterminate_at = str(
            evidence.get("first_indeterminate_at")
            or evidence.get("source_created_at")
            or attempt.created_at
        )
        steps: list[dict[str, Any]] = [
            {
                "step": "resume_51job_indeterminate_delivery",
                "ok": True,
                "click_observed": bool(evidence.get("click_observed")),
                "transition_observed": bool(evidence.get("transition_observed")),
                "will_click": False,
                "job_id": job_id,
                "delivery_state_version": JOB51_DELIVERY_STATE_VERSION,
                "first_indeterminate_at": first_indeterminate_at,
                "reconcile_attempt": reconcile_attempt,
                "reconcile_limit": JOB51_RECONCILE_LIMIT,
            }
        ]
        if (
            prior_reconcile_attempt >= JOB51_RECONCILE_LIMIT
            or _job51_reconciliation_age_seconds(first_indeterminate_at)
            >= JOB51_RECONCILE_MAX_AGE_SECONDS
        ):
            attempt.error = _JOB51_UNRESOLVED_ERROR
            steps.append(
                {
                    "step": "finalize_51job_delivery_unresolved",
                    "ok": True,
                    "reason": "reconcile_bound_reached_before_navigation",
                    "will_click": False,
                    "job_id": job_id,
                    "reconcile_attempt": prior_reconcile_attempt,
                    "reconcile_limit": JOB51_RECONCILE_LIMIT,
                }
            )
            attempt.steps = steps
            return attempt
        driver = self.driver or create_driver(platform="51job")
        self.driver = driver
        state = self._open_and_inspect_for_reconciliation(
            driver,
            job,
            job_id,
            steps,
            wait_seconds=wait_seconds,
            allow_stable_transition=bool(evidence.get("transition_observed")),
        )
        if _job51_page_requires_login(state):
            attempt.error = "login_required"
        elif state.get("requires_user_action"):
            attempt.error = str(state.get("user_action") or "user_action_required")
        elif _job51_delivery_detected(state):
            attempt.delivered = True
            attempt.error = ""
            steps.append(
                {
                    "step": "verify_51job_indeterminate_delivery",
                    "ok": True,
                    "evidence_source": "current_site_explicit_delivery",
                    "job_id": job_id,
                }
            )
        elif evidence.get("transition_observed") and _job51_stable_current_card_transition(state):
            attempt.delivered = True
            attempt.error = ""
            steps.append(
                {
                    "step": "verify_51job_indeterminate_delivery",
                    "ok": True,
                    "evidence_source": "persisted_click_plus_stable_card_transition",
                    "job_id": job_id,
                }
            )
        else:
            if (
                reconcile_attempt >= JOB51_RECONCILE_LIMIT
                or _job51_reconciliation_age_seconds(first_indeterminate_at)
                >= JOB51_RECONCILE_MAX_AGE_SECONDS
            ):
                attempt.error = _JOB51_UNRESOLVED_ERROR
                steps.append(
                    {
                        "step": "finalize_51job_delivery_unresolved",
                        "ok": True,
                        "reason": "reconcile_bound_reached",
                        "will_click": False,
                        "job_id": job_id,
                        "reconcile_attempt": reconcile_attempt,
                        "reconcile_limit": JOB51_RECONCILE_LIMIT,
                    }
                )
            else:
                steps.append(
                    {
                        "step": "verify_51job_indeterminate_delivery",
                        "ok": False,
                        "error": _JOB51_INDETERMINATE_ERROR,
                        "will_click": False,
                        "job_id": job_id,
                    }
                )
        attempt.steps = steps
        return attempt

    def _open_and_inspect_for_reconciliation(
        self,
        driver: Any,
        job: dict[str, Any],
        job_id: str,
        steps: list[dict[str, Any]],
        *,
        wait_seconds: int,
        allow_stable_transition: bool,
    ) -> dict[str, Any]:
        urls = [_job51_open_url(job)]
        recovery_url = _job51_recovery_url(job)
        if recovery_url and recovery_url not in urls:
            urls.append(recovery_url)
        last: dict[str, Any] = {}
        for position, url in enumerate(urls):
            opened = driver.open_url_in_new_tab(url, wait_seconds=max(1, wait_seconds))
            steps.append(
                {
                    "step": "open_51job_indeterminate_reconciliation",
                    "candidate": "original" if position == 0 else "recovery_search",
                    **opened,
                }
            )
            if not opened.get("ok"):
                continue
            last = _wait_for_job51_apply_state(
                driver,
                job_id,
                wait_seconds=max(8, wait_seconds),
                require_delivery=True,
            )
            steps.append(
                {
                    "step": "inspect_51job_indeterminate_reconciliation",
                    "candidate": "original" if position == 0 else "recovery_search",
                    **last,
                }
            )
            if (
                _job51_page_requires_login(last)
                or last.get("requires_user_action")
                or _job51_delivery_detected(last)
                or (
                    allow_stable_transition
                    and _job51_stable_current_card_transition(last)
                )
            ):
                return last
        return last

    def _send_one(self, job: dict[str, Any], message: str, wait_seconds: int = 3, dry_run: bool = False) -> SendAttempt:
        url = _job51_open_url(job)
        job_id = _job51_job_key(job)
        attempt = SendAttempt(job_url=url, message=message, delivered=False)
        if not url:
            attempt.error = "missing_job_url"
            return attempt
        if dry_run:
            attempt.error = "dry_run"
            attempt.steps = [{"step": "plan_51job_apply_send", "ok": True, "url": url, "job_id": job_id}]
            return attempt

        driver = self.driver or create_driver(platform="51job")
        self.driver = driver
        steps: list[dict[str, Any]] = []
        open_result = driver.open_url_in_new_tab(url, wait_seconds=wait_seconds)
        steps.append({"step": "open_51job_url", **open_result})
        if not open_result.get("ok"):
            attempt.error = str(open_result.get("error") or "open_51job_url_failed")
            attempt.steps = steps
            return attempt

        inspect_before = _wait_for_job51_apply_state(
            driver,
            job_id,
            wait_seconds=max(30, wait_seconds),
        )
        steps.append({"step": "inspect_before_apply", **inspect_before})
        if _job51_page_requires_login(inspect_before):
            attempt.error = "login_required"
            attempt.steps = steps
            return attempt
        if inspect_before.get("requires_user_action"):
            attempt.error = str(inspect_before.get("user_action") or "user_action_required")
            attempt.steps = steps
            return attempt
        if _job51_delivery_detected(inspect_before):
            attempt.delivered = True
            attempt.steps = steps
            return attempt
        if not inspect_before.get("cardFound"):
            retry_state = self._reload_until_card(
                driver,
                job_id,
                steps,
                wait_seconds=wait_seconds,
                step_prefix="original",
            )
            if retry_state:
                inspect_before = retry_state
                if _job51_page_requires_login(inspect_before):
                    attempt.error = "login_required"
                    attempt.steps = steps
                    return attempt
                if inspect_before.get("requires_user_action"):
                    attempt.error = str(inspect_before.get("user_action") or "user_action_required")
                    attempt.steps = steps
                    return attempt
                if _job51_delivery_detected(inspect_before):
                    attempt.delivered = True
                    attempt.steps = steps
                    return attempt

        if message.strip():
            steps.append({"step": "job51_greeting_not_supported", "ok": True, "reason": "job51_chat_is_qr_only"})
        before_click_state = inspect_before
        click_result = _exec_job51_js(driver, _job51_apply_click_script(job_id))
        steps.append({"step": "click_51job_apply", **click_result})
        if not click_result.get("ok") and click_result.get("error") == "job51_card_not_found":
            recovery_url = _job51_recovery_url(job)
            if recovery_url and recovery_url != url:
                recovery_open = driver.open_url_in_new_tab(recovery_url, wait_seconds=wait_seconds)
                steps.append({"step": "open_51job_recovery_url", **recovery_open})
                if not recovery_open.get("ok"):
                    attempt.error = str(recovery_open.get("error") or "open_51job_recovery_url_failed")
                    attempt.steps = steps
                    return attempt
                recovery_state = _wait_for_job51_apply_state(
                    driver,
                    job_id,
                    wait_seconds=max(30, wait_seconds),
                )
                steps.append({"step": "inspect_before_recovery_apply", **recovery_state})
                if _job51_page_requires_login(recovery_state):
                    attempt.error = "login_required"
                    attempt.steps = steps
                    return attempt
                if recovery_state.get("requires_user_action"):
                    attempt.error = str(recovery_state.get("user_action") or "user_action_required")
                    attempt.steps = steps
                    return attempt
                if _job51_delivery_detected(recovery_state):
                    attempt.delivered = True
                    attempt.steps = steps
                    return attempt
                if not recovery_state.get("cardFound"):
                    reloaded_recovery_state = self._reload_until_card(
                        driver,
                        job_id,
                        steps,
                        wait_seconds=wait_seconds,
                        step_prefix="recovery",
                    )
                    if reloaded_recovery_state:
                        recovery_state = reloaded_recovery_state
                        if _job51_page_requires_login(recovery_state):
                            attempt.error = "login_required"
                            attempt.steps = steps
                            return attempt
                        if recovery_state.get("requires_user_action"):
                            attempt.error = str(recovery_state.get("user_action") or "user_action_required")
                            attempt.steps = steps
                            return attempt
                        if _job51_delivery_detected(recovery_state):
                            attempt.delivered = True
                            attempt.steps = steps
                            return attempt
                before_click_state = recovery_state
                click_result = _exec_job51_js(driver, _job51_apply_click_script(job_id))
                steps.append({"step": "click_51job_apply_recovery", **click_result})
        if not click_result.get("ok"):
            attempt.error = (
                "job_unavailable"
                if click_result.get("error") == "job51_card_not_found"
                else str(click_result.get("error") or "job51_apply_button_not_found")
            )
            attempt.steps = steps
            return attempt
        after = _wait_for_job51_apply_state(
            driver,
            job_id,
            wait_seconds=max(8, wait_seconds),
            require_delivery=True,
        )
        steps.append({"step": "inspect_after_apply", **after})
        transition_evidence = _job51_apply_transition_evidence(
            before_click_state,
            click_result,
            after,
            job_id=job_id,
        )
        steps.append(transition_evidence)
        if _job51_delivery_detected(after):
            attempt.delivered = True
        elif transition_evidence["ok"] and _job51_stable_current_card_transition(after):
            attempt.delivered = True
        elif _job51_page_requires_login(after):
            attempt.error = "login_required"
        elif after.get("requires_user_action"):
            attempt.error = str(after.get("user_action") or "user_action_required")
        else:
            attempt.error = _JOB51_INDETERMINATE_ERROR
        attempt.steps = steps
        return attempt

    def _reload_until_card(
        self,
        driver: Any,
        job_id: str,
        steps: list[dict[str, Any]],
        *,
        wait_seconds: int,
        step_prefix: str,
    ) -> dict[str, Any]:
        if not hasattr(driver, "reload_current_page"):
            return {}
        last: dict[str, Any] = {}
        for retry in range(1, 3):
            reload_result = driver.reload_current_page(wait_seconds=max(3, wait_seconds))
            steps.append({
                "step": f"reload_51job_{step_prefix}_search",
                "retry": retry,
                **reload_result,
            })
            if not reload_result.get("ok"):
                continue
            last = _wait_for_job51_apply_state(
                driver,
                job_id,
                wait_seconds=max(30, wait_seconds),
            )
            steps.append({
                "step": f"inspect_after_51job_{step_prefix}_reload",
                "retry": retry,
                **last,
            })
            if (
                last.get("cardFound")
                or _job51_page_requires_login(last)
                or last.get("requires_user_action")
                or _job51_delivery_detected(last)
            ):
                return last
        return last


def _handoff_evidence(job: dict[str, Any]) -> dict[str, Any]:
    greeting = str(job.get("cloud_greeting") or job.get("greeting") or "")
    return {
        "job_id": _job51_job_key(job),
        "has_greeting": bool(greeting),
        "greeting": greeting,
        "score": job.get("score"),
        "match_level": job.get("match_level") or job.get("recommendation") or job.get("cloud_recommendation"),
        "chat_action": "qr_only",
        "submit_action": "resume_submit",
    }


def _handoff_item(job: dict[str, Any], index: int, status: str, error: str = "") -> dict[str, Any]:
    return {
        "index": index,
        "status": status,
        "action": "review_51job_fit_before_resume_submit",
        "job_name": str(job.get("name") or job.get("title") or ""),
        "company": str(job.get("company") or ""),
        "url": str(job.get("url") or ""),
        "error": error,
        **_handoff_evidence(job),
    }


def _job51_job_key(job: dict[str, Any]) -> str:
    raw = job.get("raw_data") if isinstance(job.get("raw_data"), dict) else {}
    return str(job.get("job_id") or job.get("jobId") or raw.get("jobId") or _fragment_job_id(str(job.get("url") or "")) or job.get("url") or "").strip()


def _job51_attempt_delivery_state_evidence(attempt: SendAttempt) -> dict[str, Any]:
    if attempt.error not in {_JOB51_INDETERMINATE_ERROR, _JOB51_UNRESOLVED_ERROR}:
        return {}
    resume = next(
        (
            step
            for step in attempt.steps
            if isinstance(step, dict)
            and step.get("step") == "resume_51job_indeterminate_delivery"
        ),
        {},
    )
    return {
        "delivery_state_version": JOB51_DELIVERY_STATE_VERSION,
        "first_indeterminate_at": str(
            resume.get("first_indeterminate_at") or attempt.created_at
        ),
        "reconcile_attempt": int(resume.get("reconcile_attempt") or 0),
        "reconcile_limit": JOB51_RECONCILE_LIMIT,
    }


def _job51_reconciliation_age_seconds(value: str) -> float:
    if not value:
        return 0.0
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return max(0.0, (datetime.now(timezone.utc) - parsed.astimezone(timezone.utc)).total_seconds())
    except ValueError:
        return 0.0


def _fragment_job_id(url: str) -> str:
    if "#jobId=" in url:
        return url.split("#jobId=", 1)[-1].strip()
    return ""


def _job51_open_url(job: dict[str, Any]) -> str:
    url = str(job.get("url") or "")
    base, _frag = urldefrag(url)
    return base or url


def _job51_recovery_url(job: dict[str, Any]) -> str:
    title = str(job.get("name") or job.get("title") or "").strip()
    base_url = _job51_open_url(job)
    if not title or not base_url:
        return ""
    parts = urlsplit(base_url)
    query = dict(parse_qsl(parts.query, keep_blank_values=True))
    query["keyword"] = title
    query.pop("pageNum", None)
    return urlunsplit((parts.scheme, parts.netloc, parts.path, urlencode(query), ""))


def _exec_job51_js(driver: Any, script: str) -> dict[str, Any]:
    if not hasattr(driver, "_exec_js"):
        return {"ok": False, "error": "driver_js_not_supported"}
    result = driver._exec_js(script)
    if isinstance(result, dict) and isinstance(result.get("raw"), str):
        try:
            parsed = json.loads(result["raw"])
            return parsed if isinstance(parsed, dict) else {"ok": False, "error": "unexpected_js_result"}
        except Exception as e:
            return {"ok": False, "error": str(e)}
    return result if isinstance(result, dict) else {"ok": False, "error": "unexpected_js_result"}


def _wait_for_job51_apply_state(
    driver: Any,
    job_id: str,
    *,
    wait_seconds: float,
    require_delivery: bool = False,
) -> dict[str, Any]:
    poll_interval = 0.75
    attempts = max(2, int(math.ceil(max(0.0, float(wait_seconds)) / poll_interval)) + 1)
    last: dict[str, Any] = {}
    stable_ready_hits = 0
    stable_transition_hits = 0
    for attempt in range(attempts):
        last = _exec_job51_js(driver, _job51_apply_inspect_script(job_id))
        if (
            last.get("ok") is False
            or _job51_page_requires_login(last)
            or last.get("requires_user_action")
            or _job51_delivery_detected(last)
        ):
            return last
        if not require_delivery:
            if last.get("cardFound"):
                return last
            stable_ready_hits = stable_ready_hits + 1 if last.get("pageReady") else 0
            if stable_ready_hits >= 5:
                return last
        elif (
            _job51_is_current_surface(last)
            and last.get("pageReady") is True
            and last.get("cardFound") is True
            and last.get("applyAvailable") is False
        ):
            stable_transition_hits += 1
            if stable_transition_hits >= 3:
                return {
                    **last,
                    "observedTransitionStable": True,
                    "transitionStableHits": stable_transition_hits,
                }
        else:
            stable_transition_hits = 0
        if attempt < attempts - 1:
            time.sleep(poll_interval)
    return last


def _job51_page_requires_login(state: dict[str, Any]) -> bool:
    if state.get("loginRequired") is True:
        return True
    text = f"{state.get('title') or ''}\n{state.get('bodySnippet') or ''}"
    return any(token in text for token in ("登录/注册", "请登录", "扫码登录", "验证码登录", "手机验证码", "安全验证", "滑块"))


def _job51_delivery_detected(state: dict[str, Any]) -> bool:
    if state.get("delivered") is True:
        return True
    text = f"{state.get('title') or ''}\n{state.get('bodySnippet') or ''}"
    return any(token in text for token in ("投递成功", "已投递", "简历投递成功", "申请成功"))


def _job51_is_current_surface(state: dict[str, Any]) -> bool:
    try:
        return (urlsplit(str(state.get("href") or "")).hostname or "").lower() == "we.51job.com"
    except ValueError:
        return False


def _job51_stable_current_card_transition(state: dict[str, Any]) -> bool:
    return bool(
        _job51_is_current_surface(state)
        and state.get("pageReady") is True
        and state.get("cardFound") is True
        and state.get("applyAvailable") is False
        and state.get("observedTransitionStable") is True
        and not _job51_page_requires_login(state)
        and not state.get("requires_user_action")
    )


def _job51_apply_transition_evidence(
    before: dict[str, Any],
    click: dict[str, Any],
    after: dict[str, Any],
    *,
    job_id: str,
) -> dict[str, Any]:
    click_matches = bool(
        click.get("ok") is True
        and (not click.get("jobId") or str(click.get("jobId")) == str(job_id))
    )
    transition = bool(
        click_matches
        and before.get("cardFound") is True
        and before.get("applyAvailable") is True
        and _job51_is_current_surface(after)
        and after.get("cardFound") is True
        and after.get("applyAvailable") is False
    )
    return {
        "step": "observe_51job_apply_transition",
        "ok": transition,
        "job_id": job_id,
        "click_observed": click_matches,
        "current_surface": _job51_is_current_surface(after),
        "cardFound": after.get("cardFound") is True,
        "applyAvailable": after.get("applyAvailable"),
        "explicit_delivery": _job51_delivery_detected(after),
        "observed_transition_stable": after.get("observedTransitionStable") is True,
    }


def _job51_apply_inspect_script(job_id: str = "") -> str:
    safe_job_id = json.dumps(job_id)
    return f"""
    (function(){{
      const jobId = {safe_job_id};
      const clean = (value) => String(value || '').replace(/\\s+/g, ' ').trim();
      const href = location.href || '';
      const title = document.title || '';
      const bodyText = clean(document.body && (document.body.innerText || document.body.textContent));
      function visible(el) {{
        if (!el) return false;
        const style = window.getComputedStyle(el);
        const rect = el.getBoundingClientRect();
        return style.display !== 'none' && style.visibility !== 'hidden' && rect.width > 8 && rect.height > 8;
      }}
      function parseSensors(el) {{
        const raw = el && el.getAttribute && el.getAttribute('sensorsdata');
        if (!raw) return {{}};
        try {{ return JSON.parse(raw); }} catch (e) {{ return {{}}; }}
      }}
      const placeholder = /doesn't work properly without JavaScript enabled/i.test(bodyText);
      const loginPromptPresent = /登录[/]注册|请登录|扫码登录|验证码登录/.test(bodyText.slice(0, 1200));
      const loginRequired = /passport|login/.test(href) || loginPromptPresent;
      const cards = Array.from(document.querySelectorAll('.joblist-item'));
      const card = jobId ? cards.find((item) => {{
        const data = parseSensors(item.querySelector('[sensorsdata]'));
        return String(data.jobId || '') === String(jobId);
      }}) : null;
      const targetText = clean(card && (card.innerText || card.textContent));
      const applyControls = card
        ? Array.from(card.querySelectorAll('button.apply, .btn.apply, button'))
            .filter(visible)
            .filter((node) => /投递|申请/.test(clean(node.innerText || node.textContent)))
        : [];
      const applyText = clean(applyControls.map((node) => node.innerText || node.textContent).join(' '));
      const applyAvailable = applyControls.some((node) =>
        !node.disabled &&
        node.getAttribute('aria-disabled') !== 'true' &&
        /^投递$|立即投递|申请职位|投递简历/.test(clean(node.innerText || node.textContent))
      );
      const visibleDialogs = Array.from(document.querySelectorAll('[role="dialog"], .el-dialog, .ant-modal, .dialog, .modal'))
        .filter(visible);
      const resumeDialogText = clean(visibleDialogs.map((node) => node.innerText || node.textContent).join(' '));
      const visibleNotices = Array.from(document.querySelectorAll('[role="status"], .el-message, .el-notification, .message, .toast'))
        .filter(visible);
      const noticeText = clean(visibleNotices.map((node) => node.innerText || node.textContent).join(' '));
      const delivered = /已投递|已申请/.test(targetText + ' ' + applyText) || /投递成功|简历投递成功|申请成功/.test(noticeText);
      const requiresResume = /请选择简历|上传简历|完善简历|创建简历|选择附件简历/.test(resumeDialogText) && !delivered;
      const requiresCaptcha = /验证码登录|手机验证码|安全验证|滑块|Security Verification|check the box below/.test(title + '\\n' + bodyText);
      const app = document.querySelector('#app');
      const appMounted = Boolean(app && app.children.length > 0 && !placeholder);
      const pageReady = !placeholder && (loginRequired || cards.length > 0 || appMounted);
      return JSON.stringify({{
        ok: true,
        href,
        title,
        jobId,
        pageReady,
        placeholder,
        appMounted,
        cardFound: Boolean(card),
        cardCount: cards.length,
        targetText: targetText.slice(0, 500),
        applyText: applyText.slice(0, 100),
        applyAvailable,
        noticeText: noticeText.slice(0, 500),
        loginRequired,
        delivered,
        requires_user_action: requiresResume || requiresCaptcha,
        user_action: requiresCaptcha ? 'captcha_required' : (requiresResume ? 'resume_selection_required' : ''),
        bodySnippet: bodyText.slice(0, 1400)
      }});
    }})()
    """


def _job51_apply_click_script(job_id: str = "") -> str:
    safe_job_id = json.dumps(job_id)
    return f"""
    (function(){{
      const jobId = {safe_job_id};
      const clean = (value) => String(value || '').replace(/\\s+/g, ' ').trim();
      function visible(el) {{
        if (!el) return false;
        const style = window.getComputedStyle(el);
        const rect = el.getBoundingClientRect();
        return style.display !== 'none' && style.visibility !== 'hidden' && rect.width > 8 && rect.height > 8;
      }}
      function parseSensors(el) {{
        const raw = el && el.getAttribute && el.getAttribute('sensorsdata');
        if (!raw) return {{}};
        try {{ return JSON.parse(raw); }} catch (e) {{ return {{}}; }}
      }}
      const cards = Array.from(document.querySelectorAll('.joblist-item'));
      let card = null;
      if (jobId) {{
        card = cards.find((item) => {{
          const data = parseSensors(item.querySelector('[sensorsdata]'));
          return String(data.jobId || '') === String(jobId);
        }});
      }}
      if (!card && cards.length === 1) card = cards[0];
      if (!card && jobId) {{
        return JSON.stringify({{ok:false, error:'job51_card_not_found', jobId, cardCount:cards.length}});
      }}
      const root = card || document;
      const candidates = Array.from(root.querySelectorAll('button.apply, .btn.apply, button, a, div'))
        .filter(visible)
        .filter((el) => /^投递$|立即投递|申请职位|投递简历/.test(clean(el.innerText || el.textContent)));
      const button = candidates[0];
      if (!button) return JSON.stringify({{ok:false, error:'job51_apply_button_not_found', jobId, cardText: clean(root.innerText || '').slice(0, 300)}});
      button.dispatchEvent(new MouseEvent('click', {{bubbles:true, cancelable:true, view:window}}));
      return JSON.stringify({{ok:true, clicked:clean(button.innerText || button.textContent), jobId}});
    }})()
    """
