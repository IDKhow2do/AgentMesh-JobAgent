"""Read-only headed-browser gate for 51Job delivery reconciliation.

The gate runs in disposable Linux CI Chrome. It never uses an account, clicks
an apply control, or reads user data. A same-origin fixture exercises the
production reconciliation path only after the public 51Job page is ready.
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
import time
import urllib.request
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from jobagent.drivers.boss.cdp_driver import CDPBossDriver
from jobagent.platforms.job51.apply import Job51ApplySender
from jobagent.platforms.job51.audit import Job51AuditEvent, Job51AuditLog


PORT = 19222
REPORT_PATH = Path(
    os.environ.get("JOB51_GATE_REPORT", "/tmp/job51-headed-delivery-recovery.json")
)
TIMEOUT_SECONDS = 120.0


class AttachedChromeManager:
    port = PORT

    def ensure_running(self) -> str:
        deadline = time.monotonic() + 30.0
        last_error = ""
        while time.monotonic() < deadline:
            try:
                with urllib.request.urlopen(
                    f"http://127.0.0.1:{self.port}/json/version", timeout=2
                ) as response:
                    payload = json.loads(response.read().decode("utf-8"))
                return str(payload.get("webSocketDebuggerUrl") or "")
            except Exception as exc:
                last_error = type(exc).__name__
                time.sleep(0.25)
        raise RuntimeError(f"CI Chrome CDP did not start: {last_error}")

    def is_running(self) -> bool:
        try:
            self.ensure_running()
        except RuntimeError:
            return False
        return True


class ReadOnlyReconciliationDriver:
    """Delegate inspection while refusing every apply-click script."""

    def __init__(self, driver: CDPBossDriver):
        self.driver = driver
        self.open_requests = 0
        self.mutating_script_attempts = 0

    def open_url_in_new_tab(self, _url: str, wait_seconds: int = 0) -> dict[str, Any]:
        del wait_seconds
        self.open_requests += 1
        current = self.driver._exec_js("location.href")
        return {"ok": True, "url": _safe_page(current.get("raw"))}

    def _exec_js(self, script: str) -> dict[str, Any]:
        if "const candidates" in script and "clicked:" in script:
            self.mutating_script_attempts += 1
            return {"ok": False, "error": "gate_blocked_recruiting_action"}
        return self.driver._exec_js(script)


def _safe_page(value: Any) -> str:
    try:
        parsed = urlsplit(str(value or ""))
    except ValueError:
        return ""
    if parsed.scheme != "https" or parsed.hostname != "we.51job.com":
        return ""
    return f"{parsed.scheme}://{parsed.hostname}{parsed.path}"


def _probe(driver: CDPBossDriver) -> dict[str, Any]:
    return driver._exec_js(
        """
        (function(){
          const text = String(document.body && document.body.innerText || '');
          return JSON.stringify({
            href: location.href || '',
            readyState: document.readyState || '',
            bodyLength: text.length,
            placeholder: /doesn't work properly without JavaScript enabled/i.test(text),
            securityPage: /访问异常|安全验证|Security Verification|Access Denied/i.test(
              (document.title || '') + '\\n' + text.slice(0, 2000)
            ),
            cardCount: document.querySelectorAll('.joblist-item').length
          });
        })()
        """
    )


def _install_reconciliation_fixture(driver: CDPBossDriver, job_id: str) -> dict[str, Any]:
    safe_job_id = json.dumps(job_id)
    return driver._exec_js(
        f"""
        (function(){{
          const jobId = {safe_job_id};
          document.body.innerHTML = `
            <main id="app">
              <section class="joblist-item">
                <span class="job-name" sensorsdata='${{JSON.stringify({{jobId}})}}'>Example role</span>
                <span class="company-name">Example company</span>
                <span class="delivery-state">Processed</span>
              </section>
            </main>`;
          return JSON.stringify({{
            ok: true,
            readyState: document.readyState,
            cardCount: document.querySelectorAll('.joblist-item').length,
            applyControlCount: Array.from(document.querySelectorAll('button')).filter(
              (node) => /投递|申请/.test(node.textContent || '')
            ).length
          }});
        }})()
        """
    )


def _seed_legacy_indeterminate(log: Job51AuditLog, job_id: str) -> None:
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
                    },
                    {
                        "step": "verify_legacy_history",
                        "ok": False,
                        "loginRequired": True,
                    },
                ],
            },
        )
    )


def _write_report(report: dict[str, Any]) -> None:
    REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    REPORT_PATH.write_text(json.dumps(report, indent=2, sort_keys=True), encoding="utf-8")
    print(json.dumps(report, sort_keys=True))


def main() -> int:
    stage = "attach_chrome"
    report: dict[str, Any] = {
        "gate": "job51_headed_delivery_recovery",
        "browser_mode": "headed_xvfb",
        "uses_account": False,
        "uses_user_data": False,
        "uses_recruiting_action": False,
    }
    try:
        driver = CDPBossDriver(
            manager=AttachedChromeManager(),
            platform="51job",
            track_round=False,
        )
        stage = "wait_public_page"
        deadline = time.monotonic() + TIMEOUT_SECONDS
        public_state: dict[str, Any] = {}
        while time.monotonic() < deadline:
            public_state = _probe(driver)
            if public_state.get("securityPage"):
                report.update(status="blocked_security_page")
                _write_report(report)
                return 78
            if (
                public_state.get("readyState") == "complete"
                and not public_state.get("placeholder")
                and int(public_state.get("bodyLength") or 0) > 0
            ):
                break
            time.sleep(1)
        else:
            report.update(status="failed_public_page_not_ready")
            _write_report(report)
            return 1

        report.update(
            public_page=_safe_page(public_state.get("href")),
            public_ready_state=str(public_state.get("readyState") or ""),
            public_card_signal=int(public_state.get("cardCount") or 0),
        )
        if not report["public_page"]:
            report["status"] = "failed_unexpected_public_host"
            _write_report(report)
            return 1

        stage = "install_same_origin_fixture"
        job_id = "isolated-gate-job"
        fixture = _install_reconciliation_fixture(driver, job_id)
        if not (
            fixture.get("ok")
            and int(fixture.get("cardCount") or 0) == 1
            and int(fixture.get("applyControlCount") or 0) == 0
        ):
            report["status"] = "failed_fixture_install"
            _write_report(report)
            return 1

        stage = "run_production_reconciliation"
        with tempfile.TemporaryDirectory(prefix="job51-reconciliation-gate-") as directory:
            audit = Job51AuditLog(path=Path(directory) / "audit.json")
            _seed_legacy_indeterminate(audit, job_id)
            guarded_driver = ReadOnlyReconciliationDriver(driver)
            attempt = Job51ApplySender(
                driver=guarded_driver,
                audit_log=audit,
            ).send_batch(
                [
                    {
                        "job_id": job_id,
                        "name": "Example role",
                        "company": "Example company",
                        "url": "https://we.51job.com/pc/search#jobId=isolated-gate-job",
                    }
                ],
                wait_seconds=1,
            )[0]

        evidence_sources = [
            str(step.get("evidence_source") or "")
            for step in attempt.steps
            if isinstance(step, dict)
        ]
        report.update(
            reconciled=bool(attempt.delivered),
            mutating_script_attempts=guarded_driver.mutating_script_attempts,
            reconciliation_open_requests=guarded_driver.open_requests,
            evidence_source=(evidence_sources[-1] if evidence_sources else ""),
        )
        if (
            not attempt.delivered
            or guarded_driver.mutating_script_attempts != 0
            or report["evidence_source"]
            != "persisted_click_plus_stable_card_transition"
        ):
            report["status"] = "failed_read_only_reconciliation"
            _write_report(report)
            return 1

        report["status"] = "passed_full"
        _write_report(report)
        return 0
    except Exception as exc:
        report.update(
            status="failed_exception",
            failure_stage=stage,
            error_type=type(exc).__name__,
        )
        _write_report(report)
        return 1


if __name__ == "__main__":
    sys.exit(main())
