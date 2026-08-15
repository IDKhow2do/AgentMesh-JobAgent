from __future__ import annotations

from jobagent.platforms.job51.apply import (
    Job51ApplySender,
    _job51_apply_inspect_script,
)
from jobagent.platforms.job51.audit import Job51AuditLog
from jobagent.platforms.job51.audit import Job51AuditEvent
from jobagent.domain.models import SendAttempt


class RecoveryDriver:
    def __init__(self):
        self.opened: list[str] = []
        self.snapshots = [
            {"ok": True, "loginRequired": False, "delivered": False, "pageReady": True, "cardFound": True},
            {"ok": False, "error": "job51_card_not_found", "jobId": "J172480001"},
            {"ok": True, "loginRequired": False, "delivered": False, "pageReady": True, "cardFound": True},
            {"ok": True, "clicked": "投递", "jobId": "J172480001"},
            {"ok": True, "delivered": True, "bodySnippet": "投递成功"},
        ]

    def open_url_in_new_tab(self, url: str, wait_seconds: int = 0):
        self.opened.append(url)
        return {"ok": True, "url": url, "wait_seconds": wait_seconds}

    def _exec_js(self, script: str):
        return self.snapshots.pop(0)


def test_job51_apply_recovers_when_search_ranking_moves_card(monkeypatch, tmp_path):
    monkeypatch.setattr("jobagent.platforms.job51.apply.time.sleep", lambda _: None)
    driver = RecoveryDriver()
    attempts = Job51ApplySender(
        driver=driver,
        audit_log=Job51AuditLog(path=tmp_path / "audit.json"),
    ).send_batch(
        [{
            "name": "AI产品经理(J10389)",
            "company": "Example",
            "url": "https://we.51job.com/pc/search?keyword=AI%E4%BA%A7%E5%93%81%E7%BB%8F%E7%90%86&jobArea=010000#jobId=J172480001",
        }]
    )

    assert attempts[0].delivered is True
    assert len(driver.opened) == 2
    assert "keyword=AI%E4%BA%A7%E5%93%81%E7%BB%8F%E7%90%86%28J10389%29" in driver.opened[1]
    assert "jobArea=010000" in driver.opened[1]
    assert any(step["step"] == "click_51job_apply_recovery" for step in attempts[0].steps)


def test_job51_resume_intervention_only_uses_visible_dialogs():
    script = _job51_apply_inspect_script("J172480001")

    assert "visibleDialogs" in script
    assert "resumeDialogText" in script
    assert ".test(resumeDialogText)" in script


def test_job51_delivery_detection_is_scoped_to_target_card_or_visible_notice():
    script = _job51_apply_inspect_script("J172480001")

    assert "targetText" in script
    assert "applyControls" in script
    assert "applyText" in script
    assert "applyAvailable" in script
    assert "/已投递|已申请/.test(targetText + ' ' + applyText)" in script
    assert "/已投递/.test(bodyText)" not in script
    assert "visibleNotices" in script


def test_job51_unavailable_job_is_audited_as_skip_and_does_not_stop_batch(monkeypatch, tmp_path):
    audit_log = Job51AuditLog(path=tmp_path / "audit.json")
    sender = Job51ApplySender(driver=object(), audit_log=audit_log)
    results = iter(
        [
            SendAttempt(
                job_url="https://example/one",
                message="",
                delivered=False,
                error="job_unavailable",
            ),
            SendAttempt(job_url="https://example/two", message="", delivered=True),
        ]
    )
    monkeypatch.setattr(sender, "_send_one", lambda *_args, **_kwargs: next(results))

    attempts = sender.send_batch(
        [
            {"job_id": "one", "url": "https://example/one"},
            {"job_id": "two", "url": "https://example/two"},
        ],
        limit=2,
        stop_on_failure=True,
    )

    assert [attempt.error for attempt in attempts] == ["job_unavailable", ""]
    assert [event["status"] for event in audit_log.list_recent(10)] == ["skipped", "delivered"]


class CurrentSurfaceVerificationDriver:
    def __init__(self):
        self.opened: list[str] = []
        self.inspect_calls = 0

    def open_url_in_new_tab(self, url: str, wait_seconds: int = 0):
        self.opened.append(url)
        return {"ok": True, "url": url, "wait_seconds": wait_seconds}

    def _exec_js(self, script: str):
        if "const candidates" in script:
            return {"ok": True, "clicked": "投递", "jobId": "172706410"}
        self.inspect_calls += 1
        if self.inspect_calls == 1:
            return {
                "ok": True,
                "href": "https://we.51job.com/pc/search",
                "pageReady": True,
                "cardFound": True,
                "applyAvailable": True,
                "delivered": False,
                "loginRequired": False,
            }
        return {
            "ok": True,
            "href": "https://we.51job.com/pc/search",
            "pageReady": True,
            "cardFound": True,
            "applyAvailable": False,
            "delivered": False,
            "loginRequired": False,
        }


def test_job51_stable_button_removal_is_verified_on_current_surface(monkeypatch, tmp_path):
    monkeypatch.setattr("jobagent.platforms.job51.apply.time.sleep", lambda _: None)
    driver = CurrentSurfaceVerificationDriver()

    attempts = Job51ApplySender(
        driver=driver,
        audit_log=Job51AuditLog(path=tmp_path / "audit.json"),
    ).send_batch(
        [{
            "job_id": "172706410",
            "name": "高级数据平台工程师（151563）",
            "company": "任仕达企业管理（上海）有限公司",
            "url": "https://we.51job.com/pc/search?keyword=data&jobArea=010000#jobId=172706410",
        }]
    )

    assert attempts[0].delivered is True
    assert driver.opened == ["https://we.51job.com/pc/search?keyword=data&jobArea=010000"]
    assert any(
        step.get("step") == "observe_51job_apply_transition"
        and step.get("ok") is True
        and step.get("observed_transition_stable") is True
        for step in attempts[0].steps
    )


def _append_legacy_indeterminate(log: Job51AuditLog, job_id: str) -> None:
    log.append(
        Job51AuditEvent(
            action="apply_send",
            status="failed",
            error="delivery_not_verified",
            evidence={
                "job_id": job_id,
                "steps": [
                    {"step": "click_51job_apply", "ok": True, "jobId": job_id},
                    {
                        "step": "inspect_after_apply",
                        "ok": True,
                        "href": "https://we.51job.com/pc/search",
                        "cardFound": True,
                        "applyAvailable": False,
                        "delivered": False,
                    },
                    {
                        "step": "verify_51job_application_history",
                        "ok": True,
                        "href": "https://login.51job.com/login.php",
                        "loginRequired": True,
                        "delivered": False,
                    },
                ],
            },
        )
    )


def _append_reconcile_indeterminate(
    log: Job51AuditLog,
    job_id: str,
    *,
    reconcile_attempt: int,
) -> None:
    log.append(
        Job51AuditEvent(
            action="apply_send",
            status="indeterminate",
            error="delivery_indeterminate",
            evidence={
                "job_id": job_id,
                "steps": [
                    {
                        "step": "resume_51job_indeterminate_delivery",
                        "ok": True,
                        "will_click": False,
                        "reconcile_attempt": reconcile_attempt,
                    },
                    {
                        "step": "verify_51job_indeterminate_delivery",
                        "ok": False,
                        "error": "delivery_indeterminate",
                        "will_click": False,
                    },
                ],
            },
        )
    )


def test_job51_legacy_clicked_failure_survives_later_unavailable_audit(tmp_path):
    log = Job51AuditLog(path=tmp_path / "audit.json")
    _append_legacy_indeterminate(log, "job-pending")
    log.append(
        Job51AuditEvent(
            action="apply_send",
            status="skipped",
            error="job_unavailable",
            evidence={
                "job_id": "job-pending",
                "steps": [
                    {
                        "step": "click_51job_apply",
                        "ok": False,
                        "error": "job51_card_not_found",
                        "jobId": "job-pending",
                    }
                ],
            },
        )
    )

    pending = log.indeterminate_apply_send_evidence()

    assert set(pending) == {"job-pending"}
    assert pending["job-pending"]["click_observed"] is True
    assert pending["job-pending"]["transition_observed"] is True


class CurrentSurfaceReconciliationDriver:
    def __init__(self, pending_card_found: bool):
        self.pending_card_found = pending_card_found
        self.opened: list[str] = []
        self.clicked_job_ids: list[str] = []
        self.next_inspect_count = 0

    def open_url_in_new_tab(self, url: str, wait_seconds: int = 0):
        self.opened.append(url)
        return {"ok": True, "url": url, "wait_seconds": wait_seconds}

    def _exec_js(self, script: str):
        if "const candidates" in script:
            job_id = "job-next" if "job-next" in script else "job-pending"
            self.clicked_job_ids.append(job_id)
            return {"ok": True, "clicked": "投递", "jobId": job_id}
        if "job-pending" in script:
            return {
                "ok": True,
                "href": "https://we.51job.com/pc/search",
                "pageReady": True,
                "cardFound": self.pending_card_found,
                "applyAvailable": False,
                "delivered": False,
                "loginRequired": False,
            }
        self.next_inspect_count += 1
        if self.next_inspect_count == 1:
            return {
                "ok": True,
                "href": "https://we.51job.com/pc/search",
                "pageReady": True,
                "cardFound": True,
                "applyAvailable": True,
                "delivered": False,
                "loginRequired": False,
            }
        return {
            "ok": True,
            "href": "https://we.51job.com/pc/search",
            "pageReady": True,
            "cardFound": True,
            "applyAvailable": False,
            "delivered": True,
            "loginRequired": False,
            "noticeText": "投递成功",
        }


def test_job51_pending_delivery_is_not_reclicked_and_does_not_stop_batch(monkeypatch, tmp_path):
    monkeypatch.setattr("jobagent.platforms.job51.apply.time.sleep", lambda _: None)
    log = Job51AuditLog(path=tmp_path / "audit.json")
    _append_legacy_indeterminate(log, "job-pending")
    driver = CurrentSurfaceReconciliationDriver(pending_card_found=False)
    sender = Job51ApplySender(driver=driver, audit_log=log)

    attempts = sender.send_batch(
        [
            {
                "job_id": "job-pending",
                "name": "Example pending role",
                "company": "Example A",
                "url": "https://we.51job.com/pc/search#jobId=job-pending",
            },
            {
                "job_id": "job-next",
                "name": "Example next role",
                "company": "Example B",
                "url": "https://we.51job.com/pc/search#jobId=job-next",
            },
        ],
        limit=2,
        wait_seconds=1,
        stop_on_failure=True,
    )

    assert attempts[0].delivered is False
    assert attempts[0].error == "delivery_indeterminate"
    assert attempts[1].delivered is True
    assert driver.clicked_job_ids == ["job-next"]
    assert [record["status"] for record in log.list_recent(2)] == [
        "indeterminate",
        "delivered",
    ]


def test_job51_pending_stable_card_transition_confirms_without_reclick(monkeypatch, tmp_path):
    monkeypatch.setattr("jobagent.platforms.job51.apply.time.sleep", lambda _: None)
    log = Job51AuditLog(path=tmp_path / "audit.json")
    _append_legacy_indeterminate(log, "job-pending")
    driver = CurrentSurfaceReconciliationDriver(pending_card_found=True)

    attempt = Job51ApplySender(driver=driver, audit_log=log).send_batch(
        [
            {
                "job_id": "job-pending",
                "name": "Example pending role",
                "company": "Example A",
                "url": "https://we.51job.com/pc/search#jobId=job-pending",
            }
        ],
        wait_seconds=1,
    )[0]

    assert attempt.delivered is True
    assert driver.clicked_job_ids == []
    assert any(
        step.get("evidence_source") == "persisted_click_plus_stable_card_transition"
        for step in attempt.steps
    )


class AmbiguousClickDriver:
    def __init__(self):
        self.opened: list[str] = []
        self.inspect_count = 0

    def open_url_in_new_tab(self, url: str, wait_seconds: int = 0):
        self.opened.append(url)
        return {"ok": True, "url": url, "wait_seconds": wait_seconds}

    def _exec_js(self, script: str):
        if "const candidates" in script:
            return {"ok": True, "clicked": "投递", "jobId": "job-new"}
        self.inspect_count += 1
        return {
            "ok": True,
            "href": "https://we.51job.com/pc/search",
            "pageReady": True,
            "cardFound": self.inspect_count == 1,
            "applyAvailable": self.inspect_count == 1,
            "delivered": False,
            "loginRequired": False,
        }


def test_job51_new_ambiguous_click_is_persisted_without_opening_legacy_history(monkeypatch, tmp_path):
    monkeypatch.setattr("jobagent.platforms.job51.apply.time.sleep", lambda _: None)
    log = Job51AuditLog(path=tmp_path / "audit.json")
    driver = AmbiguousClickDriver()

    attempt = Job51ApplySender(driver=driver, audit_log=log).send_batch(
        [
            {
                "job_id": "job-new",
                "name": "Example role",
                "company": "Example",
                "url": "https://we.51job.com/pc/search#jobId=job-new",
            }
        ],
        wait_seconds=1,
    )[0]

    assert attempt.delivered is False
    assert attempt.error == "delivery_indeterminate"
    assert "https://i.51job.com/userset/my_apply.php" not in driver.opened
    assert log.list_recent(1)[0]["status"] == "indeterminate"


def test_job51_indeterminate_reconciliation_is_bounded_and_terminal_state_never_reopens(
    monkeypatch,
    tmp_path,
):
    monkeypatch.setattr("jobagent.platforms.job51.apply.time.sleep", lambda _: None)
    log = Job51AuditLog(path=tmp_path / "audit.json")
    _append_legacy_indeterminate(log, "job-pending")
    _append_reconcile_indeterminate(log, "job-pending", reconcile_attempt=1)
    driver = CurrentSurfaceReconciliationDriver(pending_card_found=False)
    sender = Job51ApplySender(driver=driver, audit_log=log)
    job = {
        "job_id": "job-pending",
        "name": "Example pending role",
        "company": "Example A",
        "url": "https://we.51job.com/pc/search#jobId=job-pending",
    }

    exhausted = sender.send_batch([job], wait_seconds=1)[0]

    assert exhausted.delivered is False
    assert exhausted.error == "delivery_unresolved"
    assert driver.clicked_job_ids == []
    assert log.list_recent(1)[0]["status"] == "unresolved"
    assert any(
        step.get("step") == "finalize_51job_delivery_unresolved"
        and step.get("reconcile_attempt") == 2
        and step.get("reconcile_limit") == 2
        for step in exhausted.steps
    )

    opened_after_terminal = list(driver.opened)
    repeated = sender.send_batch([job], wait_seconds=1)[0]

    assert repeated.error == "delivery_unresolved"
    assert driver.opened == opened_after_terminal
    assert driver.clicked_job_ids == []
    assert any(
        step.get("step") == "skip_51job_terminal_delivery"
        and step.get("reason") == "delivery_unresolved"
        for step in repeated.steps
    )


def test_job51_stale_indeterminate_state_expires_without_browser_navigation(tmp_path):
    log = Job51AuditLog(path=tmp_path / "audit.json")
    log.append(
        Job51AuditEvent(
            action="apply_send",
            status="indeterminate",
            error="delivery_indeterminate",
            created_at="2026-08-01T00:00:00+00:00",
            evidence={
                "job_id": "job-stale",
                "steps": [{"step": "click_51job_apply", "ok": True}],
            },
        )
    )

    attempt = Job51ApplySender(driver=object(), audit_log=log).send_batch(
        [
            {
                "job_id": "job-stale",
                "url": "https://we.51job.com/pc/search#jobId=job-stale",
            }
        ]
    )[0]

    assert attempt.error == "delivery_unresolved"
    assert any(
        step.get("reason") == "reconcile_bound_reached_before_navigation"
        and step.get("will_click") is False
        for step in attempt.steps
    )


def test_job51_audit_summary_deduplicates_cumulative_terminal_outcomes(tmp_path):
    log = Job51AuditLog(path=tmp_path / "audit.json")
    for index in range(5):
        log.append_event(
            "apply_send",
            "delivered",
            evidence={"job_id": f"delivered-{index}"},
        )
        log.append_event(
            "apply_send",
            "skipped",
            error="already_delivered",
            evidence={"job_id": f"delivered-{index}"},
        )
    for index in range(2):
        log.append_event(
            "apply_send",
            "skipped",
            error="job_unavailable",
            evidence={"job_id": f"unavailable-{index}"},
        )
    for index in range(2):
        _append_legacy_indeterminate(log, f"unresolved-{index}")
        log.append_event(
            "apply_send",
            "unresolved",
            error="delivery_unresolved",
            evidence={
                "job_id": f"unresolved-{index}",
                "reconcile_attempt": 2,
                "reconcile_limit": 2,
                "steps": [
                    {
                        "step": "finalize_51job_delivery_unresolved",
                        "ok": True,
                        "reconcile_attempt": 2,
                        "reconcile_limit": 2,
                    }
                ],
            },
        )

    outcomes = log.summary()["apply_send"]["outcomes"]

    assert outcomes == {
        "total": 9,
        "terminal": 9,
        "delivered": 5,
        "unavailable": 2,
        "unresolved": 2,
        "pending": 0,
        "failed": 0,
    }
