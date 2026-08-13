"""Zhilian read-only session checks and login guide."""

from __future__ import annotations

import json
import time
from dataclasses import asdict, dataclass
from typing import Any

from jobagent.drivers.boss import create_driver

from .collect import build_zhilian_search_url, normalize_zhilian_keyword
from .constants import ZHILIAN_BROWSER_JS_USER_PROMPT, ZHILIAN_LOGIN_URL, ZHILIAN_LOGIN_USER_PROMPT
from .selectors import build_zhilian_session_probe_script


ZHILIAN_SESSION_SETTLE_TIMEOUT_SECONDS = 45
ZHILIAN_SESSION_POLL_INTERVAL_SECONDS = 0.5


@dataclass(frozen=True)
class ZhilianSessionStatus:
    ok: bool
    logged_in: bool
    login_required: bool
    url: str = ""
    title: str = ""
    error: str = ""
    evidence: dict[str, Any] | None = None

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        if _browser_js_permission_required(self.error):
            payload["requires_user_action"] = True
            payload["user_action"] = "enable_chrome_javascript_automation"
            payload["user_prompt"] = ZHILIAN_BROWSER_JS_USER_PROMPT
            payload["next_suggested"] = "jobagent zhilian login --check"
        elif self.login_required:
            payload["requires_user_action"] = True
            payload["user_action"] = "login_zhilian"
            payload["user_prompt"] = ZHILIAN_LOGIN_USER_PROMPT
            payload["next_suggested"] = "jobagent zhilian login"
        return payload


class ZhilianSessionGuide:
    """Open Zhilian and inspect login state without applying or sending."""

    def __init__(self, driver: Any | None = None):
        self.driver = driver or create_driver(platform="zhilian")

    def check(
        self,
        query: str = "AI产品经理",
        city: str = "深圳",
        wait_seconds: int = 5,
    ) -> ZhilianSessionStatus:
        url = build_zhilian_search_url(normalize_zhilian_keyword(query, city), city)
        open_result = self.driver.open_url_in_new_tab(url, wait_seconds=wait_seconds)
        if not open_result.get("ok"):
            return ZhilianSessionStatus(
                ok=False,
                logged_in=False,
                login_required=False,
                url=url,
                error=str(open_result.get("error", "open_url_failed")),
                evidence={"open_result": open_result},
            )
        return self.inspect_current_page(
            settle_timeout=max(ZHILIAN_SESSION_SETTLE_TIMEOUT_SECONDS, wait_seconds)
        )

    def open_login(self, wait_seconds: int = 3) -> ZhilianSessionStatus:
        open_result = self.driver.open_url_in_new_tab(ZHILIAN_LOGIN_URL, wait_seconds=wait_seconds)
        if not open_result.get("ok"):
            return ZhilianSessionStatus(
                ok=False,
                logged_in=False,
                login_required=False,
                url=ZHILIAN_LOGIN_URL,
                error=str(open_result.get("error", "open_url_failed")),
                evidence={"open_result": open_result},
            )
        return self.inspect_current_page(settle_timeout=max(0, wait_seconds))

    def wait_for_login(
        self,
        timeout: int = 300,
        poll_interval: int = 3,
        wait_seconds: int = 3,
    ) -> ZhilianSessionStatus:
        status = self.open_login(wait_seconds=wait_seconds)
        if status.logged_in:
            return status
        if not status.ok and not status.login_required:
            return status

        deadline = time.time() + timeout
        last = status
        while time.time() < deadline:
            time.sleep(max(1, poll_interval))
            last = self.inspect_current_page(settle_timeout=0)
            if last.logged_in:
                return last

        return ZhilianSessionStatus(
            ok=False,
            logged_in=False,
            login_required=True,
            url=last.url,
            title=last.title,
            error="zhilian_login_timeout",
            evidence=last.evidence,
        )

    def inspect_current_page(
        self,
        *,
        settle_timeout: float = 0,
        poll_interval: float = ZHILIAN_SESSION_POLL_INTERVAL_SECONDS,
    ) -> ZhilianSessionStatus:
        deadline = time.monotonic() + max(0.0, float(settle_timeout))
        last: dict[str, Any] = {}
        while True:
            result = self.driver._exec_js(build_zhilian_session_probe_script())
            data = _unwrap_js_result(result)
            last = data
            if not data.get("ok"):
                error = str(data.get("error", "zhilian_session_inspect_failed"))
                return ZhilianSessionStatus(
                    ok=False,
                    logged_in=False,
                    login_required=False,
                    error=error,
                    evidence=data,
                )

            state = _session_state(data)
            if state == "logged_in":
                return _status_from_probe(data, ok=True, logged_in=True, login_required=False)
            if state == "login_required":
                return _status_from_probe(data, ok=True, logged_in=False, login_required=True)
            if time.monotonic() >= deadline:
                break
            time.sleep(max(0.05, float(poll_interval)))

        return ZhilianSessionStatus(
            ok=False,
            logged_in=False,
            login_required=False,
            url=str(last.get("url", "")),
            title=str(last.get("title", "")),
            error="zhilian_session_state_unknown",
            evidence=_probe_evidence(last),
        )


def _unwrap_js_result(result: Any) -> dict[str, Any]:
    if isinstance(result, dict) and "raw" in result:
        try:
            parsed = json.loads(result["raw"])
            return parsed if isinstance(parsed, dict) else {}
        except (json.JSONDecodeError, TypeError):
            return {"ok": False, "error": "zhilian_session_parse_failed"}
    return result if isinstance(result, dict) else {"ok": False, "error": "zhilian_session_empty_result"}


def _browser_js_permission_required(error: str) -> bool:
    return "JavaScript through AppleScript is turned off" in error or "Allow JavaScript from Apple Events" in error


def _session_state(data: dict[str, Any]) -> str:
    state = str(data.get("sessionState") or "")
    if state:
        return state
    if data.get("loginRequired"):
        return "login_required"
    if data.get("loggedIn"):
        return "logged_in"
    return "unknown"


def _status_from_probe(
    data: dict[str, Any],
    *,
    ok: bool,
    logged_in: bool,
    login_required: bool,
) -> ZhilianSessionStatus:
    return ZhilianSessionStatus(
        ok=ok,
        logged_in=logged_in,
        login_required=login_required,
        url=str(data.get("url", "")),
        title=str(data.get("title", "")),
        evidence=_probe_evidence(data),
    )


def _probe_evidence(data: dict[str, Any]) -> dict[str, Any]:
    return {
        "readyState": data.get("readyState", ""),
        "sessionState": _session_state(data),
        "loginEvidence": list(data.get("loginEvidence") or []),
        "accountEvidence": list(data.get("accountEvidence") or []),
        "contentEvidence": list(data.get("contentEvidence") or []),
        "bodySnippet": data.get("bodySnippet", ""),
    }
