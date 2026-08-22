"""Focused public contracts for Zhilian session-state recovery."""

import json
from pathlib import Path

from jobagent.platforms.zhilian.selectors import (
    build_zhilian_city_filter_script,
    build_zhilian_keyword_search_script,
    build_zhilian_snapshot_script,
)
from jobagent.platforms.zhilian.session import ZhilianSessionGuide


FIXTURES = Path(__file__).parent / "fixtures" / "zhilian"


class _SlowPhasedSessionDriver:
    def __init__(self):
        self.inspect_count = 0

    def open_url_in_new_tab(self, url: str, wait_seconds: int = 5):
        return {"ok": True, "url": url, "wait_seconds": wait_seconds}

    def _exec_js(self, _script: str):
        self.inspect_count += 1
        states = [
            {
                "ok": True,
                "url": "https://www.zhaopin.com/jobs?jl=765&kw=产品经理",
                "title": "智联招聘",
                "readyState": "loading",
                "sessionState": "loading",
                "loginRequired": True,
                "loginEvidence": ["header_login_link"],
            },
            {
                "ok": True,
                "url": "https://www.zhaopin.com/jobs?jl=765&kw=产品经理",
                "title": "深圳热门职位招聘 - 智联招聘",
                "readyState": "complete",
                "sessionState": "unknown",
                "loginRequired": False,
                "loginEvidence": ["header_login_link"],
                "accountEvidence": ["account_navigation"],
            },
            {
                "ok": True,
                "url": "https://www.zhaopin.com/jobs?jl=765&kw=产品经理",
                "title": "深圳热门职位招聘 - 智联招聘",
                "readyState": "complete",
                "sessionState": "logged_in",
                "loginRequired": False,
                "accountEvidence": ["account_navigation"],
            },
        ]
        state = states[min(self.inspect_count - 1, len(states) - 1)]
        return {"raw": json.dumps(state, ensure_ascii=False)}


def test_session_check_waits_for_slow_phased_evidence(monkeypatch):
    driver = _SlowPhasedSessionDriver()
    monkeypatch.setattr("jobagent.platforms.zhilian.session.time.sleep", lambda _: None)

    status = ZhilianSessionGuide(driver=driver).check(wait_seconds=8)

    assert status.ok is True
    assert status.logged_in is True
    assert status.login_required is False
    assert driver.inspect_count == 3


def test_loading_page_is_unknown_instead_of_login_required():
    status = ZhilianSessionGuide(
        driver=_SlowPhasedSessionDriver()
    ).inspect_current_page(settle_timeout=0)

    assert status.ok is False
    assert status.login_required is False
    assert status.error == "zhilian_session_state_unknown"


class _AuthenticatedHomeWithPersistentLoginControlDriver:
    def _exec_js(self, _script: str):
        return {
            "raw": json.dumps(
                {
                    "ok": True,
                    "url": "https://www.zhaopin.com/",
                    "title": "深圳招聘网_深圳人才网_2026年深圳最新招聘信息-智联招聘",
                    "readyState": "complete",
                    "navigationElapsedMs": 41000,
                    "sessionEvidenceVersion": 2,
                    "sessionState": "unknown",
                    "sessionReason": "strong_account_overrides_weak_login_control",
                    "loginRequired": False,
                    "loginEvidence": ["visible_login_control"],
                    "weakLoginEvidence": ["visible_login_control"],
                    "strongLoginEvidence": [],
                    "accountEvidence": ["account_navigation"],
                    "strongAccountEvidence": [
                        "resume_management",
                        "application_activity",
                    ],
                    "contentEvidence": ["search_input", "job_results"],
                    "bodySnippet": "个人中心 在线简历 上传附件 投递 12 面试 3",
                }
            )
        }


def test_complete_authenticated_home_ignores_persistent_weak_login_control():
    status = ZhilianSessionGuide(
        driver=_AuthenticatedHomeWithPersistentLoginControlDriver()
    ).inspect_current_page(settle_timeout=0)

    assert status.ok is True
    assert status.logged_in is True
    assert status.login_required is False
    assert status.evidence["sessionState"] == "logged_in"
    assert status.evidence["sessionReason"] == "strong_account_overrides_weak_login_control"
    assert status.evidence["navigationElapsedMs"] == 41000
    assert status.evidence["strongLoginEvidence"] == []
    assert status.evidence["strongAccountEvidence"] == [
        "resume_management",
        "application_activity",
    ]


class _AuthenticatedHomeWithNormalizedAccountSignalsDriver:
    def _exec_js(self, _script: str):
        payload = json.loads(
            (FIXTURES / "authenticated_home_mixed_session_evidence.json").read_text(
                encoding="utf-8"
            )
        )
        return {
            "raw": json.dumps(payload, ensure_ascii=False)
        }


def test_session_guide_reclassifies_normalized_authenticated_account_signals():
    status = ZhilianSessionGuide(
        driver=_AuthenticatedHomeWithNormalizedAccountSignalsDriver()
    ).inspect_current_page(settle_timeout=0)

    assert status.ok is True
    assert status.logged_in is True
    assert status.login_required is False
    assert status.evidence["sessionState"] == "logged_in"
    assert (
        status.evidence["sessionReason"]
        == "strong_account_overrides_weak_login_control"
    )
    assert status.evidence["accountSignals"]["deliveryActivity"] is True
    assert status.evidence["evidenceDecision"]["hasStrongAccount"] is True


def test_selectors_expose_page_session_and_city_evidence():
    keyword = build_zhilian_keyword_search_script("产品经理")
    city = build_zhilian_city_filter_script("深圳")
    snapshot = build_zhilian_snapshot_script(limit=5)

    assert "readyState" in keyword
    assert "sessionState" in keyword
    assert "sessionEvidenceVersion" in keyword
    assert "weakLoginEvidence" in keyword
    assert "strongLoginEvidence" in keyword
    assert "strongAccountEvidence" in keyword
    assert "accountSignals" in keyword
    assert "deliveryActivity" in keyword
    assert "strong_account_overrides_weak_login_control" in keyword
    assert "accountEvidence" in city
    assert "accountSignals: session.accountSignals" in snapshot
    assert "visibleCity" in snapshot
