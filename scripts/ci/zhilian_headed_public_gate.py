"""Isolated headed-browser gate for Zhilian's public search component.

This runs only on a disposable Linux CI runner under Xvfb. It uses no account,
cookies, resume, round, or recruiting action and emits only redacted mechanics.
"""

from __future__ import annotations

import json
import os
import re
import sys
import tempfile
import time
import urllib.request
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from jobagent.drivers.boss.cdp_driver import CDPBossDriver
from jobagent.domain.models import Job
from jobagent.domain.reviewability import delivery_reviewability_issues
from jobagent.platforms.zhilian.city_resolver import ZhilianCityResolver
from jobagent.platforms.zhilian.collect import (
    ZhilianReadOnlyCollector,
    _query_page_exhausted,
    _search_transition_ready,
    parse_zhilian_snapshot_jobs,
    zhilian_candidate_collection_completed,
)
from jobagent.platforms.zhilian.parser import is_reviewable_zhilian_job
from jobagent.platforms.zhilian.detail import (
    build_zhilian_detail_snapshot_script,
    merge_zhilian_detail_into_job,
    unwrap_zhilian_detail_js_result,
)
from jobagent.platforms.zhilian.selectors import (
    build_zhilian_city_filter_script,
    build_zhilian_search_control_activation_script,
    build_zhilian_search_transition_script,
    build_zhilian_snapshot_script,
)

PORT = 19222
START_URL = os.environ.get(
    "ZHILIAN_GATE_CITY_URL", "https://www.zhaopin.com/shenzhen/"
)
CITY = os.environ.get("ZHILIAN_GATE_CITY", "深圳")
QUERY = os.environ.get("ZHILIAN_GATE_QUERY", "产品经理")
TARGET_CITIES = tuple(
    city.strip()
    for city in os.environ.get("ZHILIAN_GATE_TARGET_CITIES", "郑州,杭州").split(",")
    if city.strip()
)
REPORT_PATH = Path(
    os.environ.get("ZHILIAN_GATE_REPORT", "/tmp/zhilian-headed-gate.json")
)
TIMEOUT_SECONDS = 240.0
POLL_SECONDS = 1.0
ENTRY_RELOAD_SECONDS = 120.0
RESULT_RELOAD_SECONDS = 120.0


class AttachedChromeManager:
    """Attach the production CDP driver to CI's already running Chrome."""

    port = PORT

    def ensure_running(self) -> str:
        deadline = time.monotonic() + 30.0
        last_error = ""
        while time.monotonic() < deadline:
            try:
                with urllib.request.urlopen(
                    f"http://127.0.0.1:{self.port}/json/version", timeout=2
                ) as response:
                    data = json.loads(response.read().decode("utf-8"))
                return str(data.get("webSocketDebuggerUrl") or "")
            except Exception as exc:  # CI Chrome may still be starting.
                last_error = type(exc).__name__
                time.sleep(0.25)
        raise RuntimeError(f"CI Chrome CDP did not start: {last_error}")

    def is_running(self) -> bool:
        try:
            self.ensure_running()
        except RuntimeError:
            return False
        return True


class BoundResultPageDriver:
    """Run the production collector against the already verified result target."""

    def __init__(self, driver: CDPBossDriver):
        self.driver = driver
        self.pagination_attempts = 0

    def open_url_in_new_tab(self, _url: str, wait_seconds: int = 5) -> dict[str, Any]:
        del wait_seconds
        current = self.driver._exec_js("location.href")
        return {"ok": True, "url": _safe_url(current.get("raw"))}

    def _click_at(self, _x: Any, _y: Any) -> None:
        return None

    def dismiss_javascript_dialog(self) -> dict[str, Any]:
        return {"ok": True, "dismissed": False}

    def _exec_js(self, script: str) -> dict[str, Any]:
        if "zhilian_keyword_search" in script:
            return {
                "ok": True,
                "mode": "zhilian_keyword_search",
                "observedValue": QUERY,
                "readyState": "complete",
                "sessionState": "page_ready",
                "clickPoint": {"x": 1, "y": 1},
            }
        if "zhilian_pagination" in script:
            self.pagination_attempts += 1
            return {"ok": False, "error": "unexpected_page_two_probe"}
        return self.driver._exec_js(script)


def _safe_url(value: Any) -> str:
    try:
        parsed = urlsplit(str(value or ""))
    except ValueError:
        return ""
    if (
        parsed.scheme != "https"
        or parsed.port is not None
        or parsed.username is not None
        or parsed.password is not None
        or not (
            parsed.hostname == "zhaopin.com"
            or str(parsed.hostname or "").endswith(".zhaopin.com")
        )
    ):
        return ""
    segments = []
    for segment in parsed.path.split("/"):
        if re.fullmatch(r"jl\d+", segment, re.IGNORECASE):
            segments.append("<city-token>")
        elif re.fullmatch(r"kw[0-9A-V]+", segment, re.IGNORECASE):
            segments.append("<opaque-keyword>")
        else:
            segments.append(segment)
    return f"{parsed.scheme}://{parsed.netloc}{'/'.join(segments)}"


def _is_search_route(value: Any) -> bool:
    try:
        path = urlsplit(str(value or "")).path
    except ValueError:
        return False
    return path == "/sou" or path.startswith("/sou/") or path in {"/jobs", "/jobs/"}


def _probe_page(driver: CDPBossDriver) -> dict[str, Any]:
    script = r"""
    (function(){
      function visible(el) {
        if (!el || !(el instanceof Element)) return false;
        const style = getComputedStyle(el);
        const rect = el.getBoundingClientRect();
        return style.display !== 'none' && style.visibility !== 'hidden'
          && Number(style.opacity || '1') !== 0 && rect.width > 8 && rect.height > 8;
      }
      const body = document.body
        ? String(document.body.innerText || document.body.textContent || '').slice(0, 6000)
        : '';
      const title = String(document.title || '');
      const input = Array.from(document.querySelectorAll('.search-wrapper__input'))
        .find(visible) || null;
      const anchor = input && input.closest('.search-wrapper')
        ? Array.from(input.closest('.search-wrapper').querySelectorAll('a.search-wrapper__button'))
            .find(visible) || null
        : null;
      const securityPage = /Security Verification|安全验证|访问验证|人机验证/i.test(title + ' ' + body);
      const explicitLoginWall = /登录后查看更多职位|登录后查看职位|请先登录后继续/.test(body);
      return JSON.stringify({
        ok: true,
        url: location.href || '',
        title,
        readyState: document.readyState || '',
        securityPage,
        explicitLoginWall,
        hasSearchInput: !!input,
        hasOfficialSearchAnchor: !!anchor,
        anchorTarget: anchor ? String(anchor.getAttribute('target') || '') : ''
      });
    })()
    """
    return driver._exec_js(script)


def _commit_keyword(driver: CDPBossDriver) -> dict[str, Any]:
    keyword = json.dumps(QUERY, ensure_ascii=False)
    script = f"""
    (function(){{
      const keyword = {keyword};
      function visible(el) {{
        if (!el || !(el instanceof Element)) return false;
        const style = getComputedStyle(el);
        const rect = el.getBoundingClientRect();
        return style.display !== 'none' && style.visibility !== 'hidden'
          && Number(style.opacity || '1') !== 0 && rect.width > 8 && rect.height > 8;
      }}
      const input = Array.from(document.querySelectorAll('.search-wrapper__input')).find(visible);
      if (!input) return JSON.stringify({{ok: false, error: 'search_input_missing'}});
      input.focus();
      const previous = String(input.value || '');
      const setter = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value').set;
      setter.call(input, keyword);
      if (input._valueTracker && typeof input._valueTracker.setValue === 'function') {{
        input._valueTracker.setValue(previous);
      }}
      const event = typeof InputEvent === 'function'
        ? new InputEvent('input', {{
            bubbles: true,
            composed: true,
            inputType: 'insertText',
            data: keyword
          }})
        : new Event('input', {{bubbles: true, composed: true}});
      input.dispatchEvent(event);
      input.dispatchEvent(new Event('change', {{bubbles: true}}));
      return JSON.stringify({{
        ok: String(input.value || '').trim() === keyword,
        observedKeyword: String(input.value || '').trim(),
        inputType: String(input.getAttribute('type') || 'text').toLowerCase()
      }});
    }})()
    """
    return driver._exec_js(script)


def _safe_transition(probe: dict[str, Any]) -> dict[str, Any]:
    evidence = sorted(
        str(item) for item in (probe.get("searchPageEvidence") or []) if item
    )
    return {
        "url": _safe_url(probe.get("url")),
        "ready_state": str(probe.get("readyState") or ""),
        "title_city_match": bool(probe.get("titleCityMatch")),
        "observed_keyword_matches": (
            " ".join(str(probe.get("observedKeyword") or "").split()).casefold()
            == " ".join(QUERY.split()).casefold()
        ),
        "search_page_evidence": evidence,
        "login_required": bool(probe.get("loginRequired")),
        "verification_required": bool(probe.get("verificationRequired")),
    }


def _write_report(report: dict[str, Any]) -> None:
    REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    encoded = json.dumps(report, ensure_ascii=False, sort_keys=True)
    REPORT_PATH.write_text(encoded + "\n", encoding="utf-8")
    print(encoded, flush=True)


def _evaluate_one_page_collection_boundary(
    *,
    explicit_login_wall: bool,
    parsed_candidate_count: int,
    collector_ok: bool,
    collector_candidate_count: int,
    page_two_attempted: bool,
    collection_budget_satisfied: bool,
    all_parser_candidates_reviewable: bool,
    all_collector_candidates_reviewable: bool,
) -> dict[str, Any]:
    """Classify what the disposable public-page gate can prove.

    An explicit login wall makes candidate reviewability unavailable to a
    no-account CI runner. It does not invalidate an independently verified
    result route, city/query continuity, or the live cross-city switch gate.
    Without that wall, the complete production parser boundary remains
    mandatory.
    """

    if explicit_login_wall:
        return {
            "ok": True,
            "status": "passed_route_only_login_wall",
            "remaining_unverified": "candidate_reviewability",
        }
    complete = bool(
        parsed_candidate_count > 0
        and collector_ok
        and collector_candidate_count > 0
        and not page_two_attempted
        and collection_budget_satisfied
        and all_parser_candidates_reviewable
        and all_collector_candidates_reviewable
    )
    return {
        "ok": complete,
        "status": "continue" if complete else "failed_one_page_collection_boundary",
        "remaining_unverified": "" if complete else "candidate_reviewability",
    }


def _dismiss_public_login_overlay(
    driver: CDPBossDriver,
    *,
    target_city: str,
) -> dict[str, Any]:
    """Close one unauthenticated public-page login overlay in disposable CI."""

    script = r"""
    (function(){
      function visible(el) {
        if (!el || !(el instanceof Element)) return false;
        const style = getComputedStyle(el);
        const rect = el.getBoundingClientRect();
        return style.display !== 'none' && style.visibility !== 'hidden'
          && Number(style.opacity || '1') !== 0 && rect.width > 6 && rect.height > 6;
      }
      function clean(value) {
        return String(value || '').replace(/\s+/g, ' ').trim();
      }
      const current = new URL(location.href || '');
      const officialHost = current.protocol === 'https:'
        && (current.hostname === 'zhaopin.com' || current.hostname.endsWith('.zhaopin.com'))
        && !current.port && !current.username && !current.password;
      const authRoute = /passport|(?:^|[/._-])login(?:[/._?=-]|$)/i.test(current.href);
      if (!officialHost || authRoute) {
        return JSON.stringify({ok: false, error: 'public_overlay_route_untrusted'});
      }
      const surfaces = Array.from(document.querySelectorAll(
        'form,[role="dialog"],[aria-modal="true"],[class*="login"],[class*="Login"],[class*="passport"]'
      )).filter(visible).filter((el) => /登录|验证码|扫码|密码/.test(
        clean(el.innerText || el.textContent || '')
      ));
      const globalControls = Array.from(document.querySelectorAll(
        'button,[role="button"],a,[aria-label],[title],[class*="close"],[class*="Close"],svg'
      )).filter(visible);
      const candidates = surfaces.flatMap((surface) => {
        const surfaceRect = surface.getBoundingClientRect();
        return globalControls.map((el) => {
          const text = clean(el.innerText || el.textContent || '');
          const aria = clean(el.getAttribute('aria-label') || '');
          const title = clean(el.getAttribute('title') || '');
          const className = String(el.className || '');
          const rect = el.getBoundingClientRect();
          const closeSignal = /^(?:×|✕|关闭|取消)$/.test(text)
            || /关闭|close/i.test(aria + ' ' + title + ' ' + className);
          const dangerous = /登录|注册|提交|确认|发送|验证码|扫码|密码/.test(
            text + ' ' + aria + ' ' + title
          );
          const bounded = rect.width <= 90 && rect.height <= 90;
          const centerX = rect.left + rect.width / 2;
          const centerY = rect.top + rect.height / 2;
          const nearSurfaceTopRight = centerX >= surfaceRect.left + surfaceRect.width * 0.55
            && centerX <= surfaceRect.right + 50
            && centerY >= surfaceRect.top - 50
            && centerY <= surfaceRect.top + Math.min(surfaceRect.height * 0.35, 140);
          const insideSurface = surface.contains(el);
          return {
            el, rect, closeSignal, dangerous, bounded,
            nearSurfaceTopRight, insideSurface
          };
        });
      }).filter((item) => item.closeSignal && !item.dangerous && item.bounded
          && (item.insideSurface || item.nearSurfaceTopRight))
        .sort((a, b) => (a.rect.width * a.rect.height) - (b.rect.width * b.rect.height));
      if (!candidates.length) {
        return JSON.stringify({
          ok: false,
          error: surfaces.length ? 'public_overlay_close_not_found' : 'public_overlay_not_found',
          surfaceCount: surfaces.length
        });
      }
      const candidate = candidates[0];
      return JSON.stringify({
        ok: true,
        controlType: String(candidate.el.tagName || '').toLowerCase(),
        clickPoint: {
          x: Math.round(candidate.rect.left + candidate.rect.width / 2),
          y: Math.round(candidate.rect.top + candidate.rect.height / 2)
        }
      });
    })()
    """
    result = driver._exec_js(script)
    point = result.get("clickPoint") if isinstance(result.get("clickPoint"), dict) else None
    method = "close_control"
    if result.get("ok") and point:
        driver._click_at(point.get("x"), point.get("y"))
    else:
        method = "escape_key"
        driver.cdp.send(
            "Input.dispatchKeyEvent",
            {
                "type": "keyDown",
                "key": "Escape",
                "code": "Escape",
                "windowsVirtualKeyCode": 27,
                "nativeVirtualKeyCode": 27,
            },
        )
        driver.cdp.send(
            "Input.dispatchKeyEvent",
            {
                "type": "keyUp",
                "key": "Escape",
                "code": "Escape",
                "windowsVirtualKeyCode": 27,
                "nativeVirtualKeyCode": 27,
            },
        )
    deadline = time.monotonic() + 10.0
    probe: dict[str, Any] = {}
    transition_script = build_zhilian_search_transition_script(QUERY, target_city)
    while time.monotonic() < deadline:
        probe = driver._exec_js(transition_script)
        if not probe.get("strongLoginEvidence"):
            return {
                **result,
                "ok": True,
                "dismissed": True,
                "method": method,
                "error": "",
            }
        time.sleep(0.5)
    return {
        **result,
        "ok": False,
        "dismissed": False,
        "method": method,
        "error": "public_overlay_persisted",
        "remainingStrongLoginEvidence": sorted(
            str(item)[:60]
            for item in (probe.get("strongLoginEvidence") or [])
            if item
        ),
    }


def _resume_public_city_transition(
    collector: ZhilianReadOnlyCollector,
    driver: CDPBossDriver,
    *,
    target_city: str,
    city_discovery: dict[str, Any],
    bootstrap_state: dict[str, Any],
) -> tuple[dict[str, Any], dict[str, Any]]:
    overlay = (
        _dismiss_public_login_overlay(driver, target_city=target_city)
        if bootstrap_state.get("strongLoginEvidence")
        else {
            "ok": True,
            "dismissed": False,
            "method": "not_required",
            "error": "",
        }
    )
    if not overlay.get("dismissed"):
        transition, route_receipt = _activate_public_city_result_from_city_page(
            driver,
            target_city=target_city,
        )
        return transition, {**overlay, **route_receipt}
    bootstrap = collector._await_city_bootstrap_destination(
        QUERY,
        city=target_city,
        expected_url=str(city_discovery.get("navigationUrl") or ""),
        wait_seconds=8,
    )
    if not bootstrap.get("ok"):
        return bootstrap, overlay
    submitted = collector._submit_verified_city_keyword(
        QUERY,
        city=target_city,
        wait_seconds=8,
    )
    if not submitted.get("ok"):
        return submitted, overlay
    transition = (
        submitted.get("searchTransitionProbe")
        if isinstance(submitted.get("searchTransitionProbe"), dict)
        else {}
    )
    deadline = time.monotonic() + 45.0
    script = build_zhilian_search_transition_script(QUERY, target_city)
    while not _search_transition_ready(transition, QUERY, target_city):
        if time.monotonic() >= deadline:
            return {
                **transition,
                "ok": False,
                "error": "public_overlay_search_transition_not_verified",
            }, overlay
        time.sleep(POLL_SECONDS)
        transition = driver._exec_js(script)
    return {**transition, "ok": True}, overlay


def _activate_public_city_result_from_city_page(
    driver: CDPBossDriver,
    *,
    target_city: str,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Exercise a verified public city page's own official search destination."""

    current = driver._exec_js(
        build_zhilian_search_transition_script(QUERY, target_city)
    )
    normalized_city = str(target_city).removesuffix("市")
    title = str(current.get("title") or "")
    current_url = _safe_url(current.get("url"))
    try:
        current_path = urlsplit(str(current.get("url") or "")).path
    except ValueError:
        current_path = ""
    evidence = {
        str(item)
        for item in (current.get("searchPageEvidence") or [])
        if item
    }
    if not (
        current.get("readyState") in {"interactive", "complete"}
        and current_url
        and not _is_search_route(current.get("url"))
        and len([segment for segment in current_path.split("/") if segment]) == 1
        and normalized_city
        and normalized_city in title
        and "search_input" in evidence
        and "auth_route" not in (current.get("strongLoginEvidence") or [])
    ):
        return {}, {
            "routeActivationVerified": False,
            "routeActivationError": "public_city_page_not_verified",
        }
    committed = _commit_keyword(driver)
    if not committed.get("ok"):
        return {}, {
            "routeActivationVerified": False,
            "routeActivationError": "public_city_keyword_not_committed",
        }
    activation = driver._exec_js(
        build_zhilian_search_control_activation_script(
            QUERY,
            method="official_destination",
        )
    )
    if not (
        activation.get("ok")
        and activation.get("controlActivated")
        and activation.get("searchDestinationReady")
    ):
        return {}, {
            "routeActivationVerified": False,
            "routeActivationError": str(
                activation.get("error")
                or "public_city_search_destination_not_activated"
            )[:100],
            "routeActivationControlType": str(
                activation.get("buttonCandidateType") or ""
            )[:40],
        }
    deadline = time.monotonic() + 120.0
    transition: dict[str, Any] = {}
    snapshot: dict[str, Any] = {}
    transition_script = build_zhilian_search_transition_script(QUERY, target_city)
    while time.monotonic() < deadline:
        page = _probe_page(driver)
        if page.get("securityPage"):
            return {}, {
                "routeActivationVerified": False,
                "routeActivationError": "public_city_search_security_page",
            }
        transition = driver._exec_js(transition_script)
        if transition.get("readyState") == "complete":
            snapshot = driver._exec_js(build_zhilian_snapshot_script(limit=5))
            observed = " ".join(
                str(
                    transition.get("observedKeyword")
                    or transition.get("searchKeyword")
                    or ""
                ).split()
            ).casefold()
            expected = " ".join(QUERY.split()).casefold()
            list_signal = bool(
                int(snapshot.get("candidateCount") or 0) > 0
                or int(snapshot.get("jobSurfaceCount") or 0) > 0
                or snapshot.get("noResults")
            )
            if (
                _is_search_route(transition.get("url"))
                and transition.get("titleCityMatch")
                and observed == expected
                and list_signal
            ):
                return {**transition, "ok": True}, {
                    "routeActivationVerified": True,
                    "routeActivationError": "",
                    "routeActivationControlType": str(
                        activation.get("buttonCandidateType") or ""
                    )[:40],
                    "routeActivationDestinationKind": str(
                        activation.get("searchDestinationKind") or ""
                    )[:80],
                    "publicLoginOverlayRetained": bool(
                        transition.get("strongLoginEvidence")
                    ),
                    "sourceReadyState": str(
                        current.get("readyState") or ""
                    )[:30],
                }
        time.sleep(POLL_SECONDS)
    return {**transition, "ok": False}, {
        "routeActivationVerified": False,
        "routeActivationError": "public_city_search_transition_not_verified",
        "routeActivationControlType": str(
            activation.get("buttonCandidateType") or ""
        )[:40],
    }


def _run_live_city_switch_gate(driver: CDPBossDriver) -> dict[str, Any]:
    """Exercise production city recovery on the current public result page."""

    if len(TARGET_CITIES) < 2:
        return {"ok": False, "failure": "two_target_cities_required"}

    collector = ZhilianReadOnlyCollector(
        driver=driver,
        login_verification={
            "valid": True,
            "source": "current_collection_homepage",
            "platform": "zhilian",
            "session_scope": "collector_instance",
            "age_seconds": 0,
        },
    )
    attempts: list[dict[str, Any]] = []
    for index, target_city in enumerate(TARGET_CITIES[:2], start=1):
        before = _probe_page(driver)
        first_action = driver._exec_js(
            build_zhilian_city_filter_script(
                target_city,
                allow_unknown_session=True,
            )
        )
        transition = collector._await_search_transition(
            QUERY,
            city=target_city,
            wait_seconds=8,
        )
        public_overlay: dict[str, Any] = {}
        initial_city_discovery = (
            transition.get("cityDiscovery")
            if isinstance(transition.get("cityDiscovery"), dict)
            else {}
        )
        initial_bootstrap = (
            transition.get("cityBootstrap")
            if isinstance(transition.get("cityBootstrap"), dict)
            else {}
        )
        if (
            transition.get("error")
            in {"zhilian_login_required", "zhilian_city_evidence_pending"}
            and initial_city_discovery.get("navigated")
            and (
                initial_bootstrap.get("strongLoginEvidence")
                or (
                    initial_bootstrap.get("readyState") == "interactive"
                    and "search_input"
                    in (initial_bootstrap.get("searchPageEvidence") or [])
                )
            )
        ):
            transition, public_overlay = _resume_public_city_transition(
                collector,
                driver,
                target_city=target_city,
                city_discovery=initial_city_discovery,
                bootstrap_state=initial_bootstrap,
            )
        after = _probe_page(driver)
        snapshot = (
            driver._exec_js(build_zhilian_snapshot_script(limit=5))
            if transition.get("ok")
            else {}
        )
        observed_keyword = " ".join(
            str(
                transition.get("observedKeyword")
                or transition.get("searchKeyword")
                or ""
            ).split()
        ).casefold()
        expected_keyword = " ".join(QUERY.split()).casefold()
        evidence = {
            str(item)
            for item in (transition.get("searchPageEvidence") or [])
            if item
        }
        candidate_count = int(snapshot.get("candidateCount") or 0)
        job_surface_count = int(snapshot.get("jobSurfaceCount") or 0)
        no_results = bool(snapshot.get("noResults"))
        list_signal = bool(
            candidate_count > 0
            or job_surface_count > 0
            or no_results
            or "job_action" in evidence
        )
        route_changed = bool(
            before.get("url")
            and after.get("url")
            and before.get("url") != after.get("url")
        )
        attempt_ok = bool(
            transition.get("ok")
            and _is_search_route(transition.get("url"))
            and transition.get("readyState") == "complete"
            and transition.get("titleCityMatch")
            and observed_keyword == expected_keyword
            and route_changed
            and list_signal
            and (
                not transition.get("loginRequired")
                or public_overlay.get("routeActivationVerified")
            )
            and not transition.get("verificationRequired")
        )
        click_point = (
            first_action.get("clickPoint")
            if isinstance(first_action.get("clickPoint"), dict)
            else {}
        )
        city_discovery = (
            transition.get("cityDiscovery")
            if isinstance(transition.get("cityDiscovery"), dict)
            else initial_city_discovery
        )
        directory_result = (
            city_discovery.get("directoryNavigationResult")
            if isinstance(city_discovery.get("directoryNavigationResult"), dict)
            else {}
        )
        bootstrap = (
            transition.get("cityBootstrap")
            if isinstance(transition.get("cityBootstrap"), dict)
            else initial_bootstrap
        )
        attempts.append(
            {
                "index": index,
                "target_city": target_city,
                "ok": attempt_ok,
                "error": str(transition.get("error") or "")[:100],
                "first_action": str(first_action.get("action") or "")[:80],
                "first_error": str(first_action.get("error") or "")[:100],
                "before_page": _safe_url(before.get("url")),
                "first_action_page": _safe_url(first_action.get("url")),
                "after_page": _safe_url(after.get("url")),
                "first_control_role": str(first_action.get("controlRole") or "")[:40],
                "first_click_tag": str(click_point.get("tag") or "")[:30],
                "first_click_class": str(click_point.get("className") or "")[:120],
                "first_has_navigation_candidate": bool(
                    first_action.get("candidateNavigationUrl")
                ),
                "first_has_directory_candidate": bool(
                    first_action.get("candidateDirectoryUrl")
                ),
                "first_navigation_source": str(
                    first_action.get("candidateNavigationSource") or ""
                )[:100],
                "city_discovery_error": str(city_discovery.get("error") or "")[:100],
                "city_discovery_navigated": bool(city_discovery.get("navigated")),
                "city_discovery_source": str(
                    city_discovery.get("navigationSource") or ""
                )[:80],
                "directory_error": str(directory_result.get("error") or "")[:100],
                "directory_page": bool(directory_result.get("directoryPage")),
                "directory_target_found": bool(
                    directory_result.get("candidateNavigationUrl")
                ),
                "bootstrap_error": str(bootstrap.get("error") or "")[:100],
                "bootstrap_verified": bool(bootstrap.get("bootstrapVerified")),
                "bootstrap_page": _safe_url(bootstrap.get("url")),
                "bootstrap_ready_state": str(
                    bootstrap.get("readyState") or ""
                )[:30],
                "bootstrap_session_reason": str(
                    bootstrap.get("sessionReason") or ""
                )[:80],
                "bootstrap_login_required": bool(bootstrap.get("loginRequired")),
                "bootstrap_weak_login_evidence": sorted(
                    str(item)[:60]
                    for item in (bootstrap.get("weakLoginEvidence") or [])
                    if item
                ),
                "bootstrap_strong_login_evidence": sorted(
                    str(item)[:60]
                    for item in (bootstrap.get("strongLoginEvidence") or [])
                    if item
                ),
                "public_login_overlay_dismissed": bool(
                    public_overlay.get("dismissed")
                ),
                "public_login_overlay_error": str(
                    public_overlay.get("error") or ""
                )[:100],
                "public_login_overlay_control_type": str(
                    public_overlay.get("controlType") or ""
                )[:30],
                "public_login_overlay_method": str(
                    public_overlay.get("method") or ""
                )[:30],
                "public_overlay_route_activation_verified": bool(
                    public_overlay.get("routeActivationVerified")
                ),
                "public_overlay_route_activation_error": str(
                    public_overlay.get("routeActivationError") or ""
                )[:100],
                "public_overlay_route_activation_control_type": str(
                    public_overlay.get("routeActivationControlType") or ""
                )[:40],
                "public_overlay_route_activation_destination_kind": str(
                    public_overlay.get("routeActivationDestinationKind") or ""
                )[:80],
                "public_login_overlay_retained": bool(
                    public_overlay.get("publicLoginOverlayRetained")
                ),
                "public_city_source_ready_state": str(
                    public_overlay.get("sourceReadyState") or ""
                )[:30],
                "route_changed": route_changed,
                "result_route": _is_search_route(transition.get("url")),
                "ready_state": str(transition.get("readyState") or ""),
                "title_city_match": bool(transition.get("titleCityMatch")),
                "query_match": observed_keyword == expected_keyword,
                "candidate_count": candidate_count,
                "job_surface_count": job_surface_count,
                "no_results": no_results,
                "settle_attempts": int(transition.get("settleAttempts") or 0),
            }
        )
        if not attempt_ok:
            return {
                "ok": False,
                "failure": "target_city_transition_not_verified",
                "attempts": attempts,
            }
    return {"ok": True, "attempts": attempts}


def _is_official_detail_url(value: Any) -> bool:
    try:
        parsed = urlsplit(str(value or ""))
    except ValueError:
        return False
    host = str(parsed.hostname or "").casefold()
    return bool(
        parsed.scheme == "https"
        and (host == "zhaopin.com" or host.endswith(".zhaopin.com"))
        and parsed.path.startswith("/jobdetail/")
    )


def _detail_url_kind(value: Any) -> str:
    try:
        parsed = urlsplit(str(value or ""))
    except ValueError:
        return "invalid"
    host = str(parsed.hostname or "").casefold()
    if not (host == "zhaopin.com" or host.endswith(".zhaopin.com")):
        return "cross_origin" if host else "missing"
    return "official_detail" if parsed.path.startswith("/jobdetail/") else "official_other"


def _run_public_detail_reviewability_gate(
    driver: CDPBossDriver,
    jobs: list[Job],
) -> dict[str, Any]:
    candidates = [job for job in jobs if _is_official_detail_url(job.url)][:3]
    if not candidates:
        return {"ok": False, "failure": "official_detail_candidate_missing"}

    attempts = 0
    last_diagnostics: dict[str, Any] = {}
    for candidate in candidates:
        attempts += 1
        stripped = Job(
            name="查看更多信息",
            company="",
            salary="",
            area=candidate.area,
            experience="",
            degree="",
            skills="",
            boss="",
            city=candidate.city,
            url=candidate.url,
            platform="zhilian",
            raw_data={"gate": "isolated_public_detail"},
        )
        before = driver.capture_platform_target_state("zhilian")
        hydrated = ZhilianReadOnlyCollector(driver=driver)._hydrate_from_details(
            [stripped],
            detail_limit=1,
            wait_seconds=8,
        )
        after = driver.capture_platform_target_state("zhilian")
        snapshots = hydrated.get("snapshots")
        snapshot = (
            snapshots[-1]
            if isinstance(snapshots, list) and snapshots and isinstance(snapshots[-1], dict)
            else {}
        )
        hydrated_jobs = hydrated.get("jobs")
        merged = (
            hydrated_jobs[0]
            if isinstance(hydrated_jobs, list) and hydrated_jobs
            else stripped
        )
        issues = delivery_reviewability_issues(
            {"title": merged.name, "company": merged.company, "salary": merged.salary}
        )
        source_names = {
            str(snapshot.get("titleSource") or ""),
            str(snapshot.get("companySource") or ""),
            str(snapshot.get("salarySource") or ""),
        } - {""}
        detail_kind = _detail_url_kind(snapshot.get("url"))
        hard_error = str(hydrated.get("error") or "")
        safe_exclusion_eligible = bool(
            not hard_error
            and detail_kind == "official_detail"
            and snapshot.get("readyState") == "complete"
            and source_names
            and issues
            and set(issues) <= {"title", "company", "salary"}
        )
        fully_reviewable = bool(
            not hard_error
            and detail_kind == "official_detail"
            and snapshot.get("readyState") == "complete"
            and not issues
        )
        last_diagnostics = {
            "detail_navigation_outcome": "loaded" if not hard_error else "failed",
            "hydrator_error": hard_error,
            "official_url_kind": detail_kind,
            "ready_state": str(snapshot.get("readyState") or ""),
            "login_evidence": str(snapshot.get("loginEvidence") or ""),
            "same_cdp_target": bool(
                before.get("current_target_id")
                and before.get("current_target_id") == after.get("current_target_id")
            ),
            "title_source": str(snapshot.get("titleSource") or ""),
            "company_source": str(snapshot.get("companySource") or ""),
            "salary_source": str(snapshot.get("salarySource") or ""),
            "reviewability_issues": sorted(issues),
            "safe_exclusion_eligible": safe_exclusion_eligible,
        }
        if fully_reviewable or safe_exclusion_eligible:
            return {
                "ok": True,
                "attempt_count": attempts,
                "outcome": (
                    "fully_reviewable"
                    if fully_reviewable
                    else "safe_exclusion_eligible"
                ),
                **last_diagnostics,
            }
    return {
        "ok": False,
        "attempt_count": attempts,
        "failure": "public_detail_hydration_unverified",
        **last_diagnostics,
    }


def _run_document_title_fallback_gate(driver: CDPBossDriver) -> dict[str, Any]:
    script = """
    (function(){
      try { delete globalThis.__INITIAL_STATE__; } catch (_error) {}
      history.replaceState({}, '', '/jobdetail/TITLE-FALLBACK-CI.htm');
      document.title = '基础设施运维管理专家招聘_深圳示例云技术服务有限公司招聘 - 智联招聘';
      document.body.innerHTML = `
        <main style="width:1000px;min-height:700px;padding:24px;background:#fff;color:#111">
          <div style="display:block;width:200px;height:40px">薪资不公开</div>
          <section style="display:block;width:800px;height:300px">职位描述与公司介绍</section>
        </main>`;
      return JSON.stringify({ok: true, readyState: document.readyState});
    })()
    """
    installed = driver._exec_js(script)
    if not installed.get("ok"):
        return {"ok": False, "failure": "fixture_install_failed"}
    snapshot = unwrap_zhilian_detail_js_result(
        driver._exec_js(build_zhilian_detail_snapshot_script())
    )
    stripped = Job(
        name="查看更多信息",
        company="",
        salary="",
        area="深圳",
        experience="",
        degree="",
        skills="",
        boss="",
        city="深圳",
        url="https://www.zhaopin.com/jobdetail/TITLE-FALLBACK-CI.htm",
        platform="zhilian",
        raw_data={"gate": "isolated_title_fallback"},
    )
    merged = merge_zhilian_detail_into_job(stripped, snapshot)
    issues = delivery_reviewability_issues(
        {"title": merged.name, "company": merged.company, "salary": merged.salary}
    )
    complete_ok = bool(
        not issues
        and snapshot.get("titleSource") == "document_title"
        and snapshot.get("companySource") == "document_title"
        and snapshot.get("salarySource") == "explicit_disclosure_label"
    )
    driver._exec_js(
        "document.body.innerHTML = '<main style=\"width:1000px;min-height:700px\">职位描述与公司介绍</main>'; JSON.stringify({ok:true})"
    )
    missing_salary_snapshot = unwrap_zhilian_detail_js_result(
        driver._exec_js(build_zhilian_detail_snapshot_script())
    )
    missing_salary_job = merge_zhilian_detail_into_job(
        stripped,
        missing_salary_snapshot,
    )
    missing_salary_issues = delivery_reviewability_issues(
        {
            "title": missing_salary_job.name,
            "company": missing_salary_job.company,
            "salary": missing_salary_job.salary,
        }
    )
    safe_exclusion_ok = bool(
        missing_salary_issues == ["salary"]
        and missing_salary_snapshot.get("titleSource") == "document_title"
        and missing_salary_snapshot.get("companySource") == "document_title"
        and not missing_salary_snapshot.get("salarySource")
    )
    return {
        "ok": complete_ok and safe_exclusion_ok,
        "reviewability_issue_count": len(issues),
        "title_source": str(snapshot.get("titleSource") or ""),
        "company_source": str(snapshot.get("companySource") or ""),
        "salary_source": str(snapshot.get("salarySource") or ""),
        "safe_exclusion_fields": missing_salary_issues,
        "safe_exclusion_eligible": safe_exclusion_ok,
    }


def _install_cross_city_fallback_fixture(driver: CDPBossDriver) -> bool:
    """Install a same-origin, public-safe DOM fixture on disposable CI Chrome."""

    city = json.dumps(CITY, ensure_ascii=False)
    query = json.dumps(QUERY, ensure_ascii=False)
    script = f"""
    (function(){{
      const city = {city};
      const query = {query};
      history.replaceState({{}}, '', '/jobs?jl=991234&kw=fixture');
      document.title = city + '热门职位招聘 2026年热门职位招聘信息-智联招聘';
      document.body.innerHTML = `
        <main style="width:1100px;min-height:700px;padding:24px;background:#fff;color:#111">
          <div class="city-current selected" data-city-code="991234" aria-current="true"
               style="display:block;width:100px;height:32px;line-height:32px">${{city}}</div>
          <div class="search-wrapper" style="display:flex;width:720px;height:48px;margin-top:20px">
            <input class="search-wrapper__input" type="text" name="keyword"
                   placeholder="搜索职位或公司" value="${{query}}"
                   style="display:block;width:560px;height:44px" />
          </div>
          <ul class="job-list" style="display:block;width:900px;margin-top:30px">
            <li class="job-card" data-position-id="FALLBACK-CI-1"
                style="display:block;width:860px;height:180px;padding:20px">
              <a href="/jobdetail/FALLBACK-CI-1.htm"
                 style="display:block;width:800px;height:140px">
                <h3 class="job-name">跨城推荐职位</h3>
                <div>外地推荐示例科技有限公司</div>
                <div>上海 20-30K 经验不限 本科</div>
                <button style="display:block;width:120px;height:36px">立即投递</button>
              </a>
            </li>
          </ul>
        </main>`;
      return JSON.stringify({{
        ok: location.pathname === '/jobs',
        readyState: document.readyState,
        cityVisible: document.body.innerText.includes(city),
        queryCommitted: document.querySelector('.search-wrapper__input').value === query,
        fallbackSurfacePresent: !!document.querySelector('[data-position-id="FALLBACK-CI-1"]')
      }});
    }})()
    """
    result = driver._exec_js(script)
    return bool(
        result.get("ok")
        and result.get("cityVisible")
        and result.get("queryCommitted")
        and result.get("fallbackSurfacePresent")
    )


def _run_cross_city_fallback_gate(driver: CDPBossDriver) -> dict[str, Any]:
    if not _install_cross_city_fallback_fixture(driver):
        return {"ok": False, "failure": "fixture_install_failed"}
    bound_driver = BoundResultPageDriver(driver)
    with tempfile.TemporaryDirectory(prefix="zhilian-gate-city-cache-") as directory:
        cache_path = Path(directory) / "cities.json"
        ZhilianCityResolver(cache_path).remember(
            CITY,
            "991234",
            evidence_url="https://www.zhaopin.com/jobs?jl=991234",
            evidence_sources=["page_title", "visible_city"],
            verification_source="isolated_headed_gate",
        )
        collected = ZhilianReadOnlyCollector(
            driver=bound_driver,
            city_cache_path=cache_path,
            login_verification={
                "valid": True,
                "source": "isolated_headed_gate",
                "platform": "zhilian",
                "round_id": "isolated-public-gate",
                "browser_session_id": "ci-xvfb",
                "age_seconds": 0,
            },
        ).collect(
            query=QUERY,
            city=CITY,
            limit=20,
            wait_seconds=0,
            page=1,
            pages=2,
            page_delay=0,
        )
    snapshot = collected.snapshot if isinstance(collected.snapshot, dict) else {}
    resolution = (
        snapshot.get("cityResolution")
        if isinstance(snapshot.get("cityResolution"), dict)
        else {}
    )
    result = {
        "ok": bool(
            collected.ok
            and not collected.jobs
            and int(snapshot.get("candidateCount") or 0) > 0
            and snapshot.get("crossCityFallbackOnly") is True
            and snapshot.get("paginationExhausted") is True
            and snapshot.get("terminationReason") == "no_results"
            and not bound_driver.pagination_attempts
            and resolution.get("visibleCityConflict") is not True
            and resolution.get("codeEvidenceConflict") is not True
        ),
        "raw_card_count": int(snapshot.get("candidateCount") or 0),
        "accepted_candidate_count": len(collected.jobs),
        "cross_city_fallback_only": bool(snapshot.get("crossCityFallbackOnly")),
        "page_two_attempted": bound_driver.pagination_attempts > 0,
        "termination_reason": str(snapshot.get("terminationReason") or ""),
        "visible_city_conflict": bool(resolution.get("visibleCityConflict")),
        "code_evidence_conflict": bool(resolution.get("codeEvidenceConflict")),
    }
    return result


def _run_generic_link_reviewability_gate(driver: CDPBossDriver) -> dict[str, Any]:
    """Prove the production parser ignores a detail-link CTA beside stable fields."""

    script = """
    (function(){
      history.replaceState({}, '', '/jobs?jl=991234&kw=fixture-reviewability');
      document.title = '深圳热门职位招聘 2026年热门职位招聘信息-智联招聘';
      document.body.innerHTML = `
        <main style="width:1100px;min-height:700px;padding:24px;background:#fff;color:#111">
          <input class="search-wrapper__input" type="text" name="keyword"
                 placeholder="搜索职位或公司" value="产品经理"
                 style="display:block;width:560px;height:44px" />
          <ul class="job-list" style="display:block;width:900px;margin-top:30px">
            <li class="job-card" data-position-id="REVIEWABLE-CI-1"
                style="display:block;width:860px;height:180px;padding:20px">
              <h3 class="job-name">数据运营经理</h3>
              <a class="company-name" href="/company/REVIEWABLE-CI-1"
                 style="display:block;width:300px;height:30px">深圳示例科技有限公司</a>
              <div class="salary">25-35K</div>
              <div>深圳 3-5年 本科</div>
              <a class="detail-link" href="/jobdetail/REVIEWABLE-CI-1.htm"
                 style="display:block;width:180px;height:36px">查看更多信息</a>
              <button style="display:block;width:120px;height:36px">立即投递</button>
            </li>
          </ul>
        </main>`;
      return JSON.stringify({ok: true, readyState: document.readyState});
    })()
    """
    installed = driver._exec_js(script)
    if not installed.get("ok"):
        return {"ok": False, "failure": "fixture_install_failed"}
    snapshot = driver._exec_js(build_zhilian_snapshot_script(limit=5))
    jobs = parse_zhilian_snapshot_jobs(snapshot, city_name=CITY, limit=5)
    cards = snapshot.get("cards") if isinstance(snapshot.get("cards"), list) else []
    first_card = cards[0] if cards and isinstance(cards[0], dict) else {}
    return {
        "ok": bool(
            len(jobs) == 1
            and jobs[0].name == "数据运营经理"
            and jobs[0].company == "深圳示例科技有限公司"
            and jobs[0].salary == "25-35K"
            and is_reviewable_zhilian_job(jobs[0])
            and first_card.get("titleSource") == "stable_title_node"
            and first_card.get("companySource") == "stable_company_node"
        ),
        "candidate_count": len(jobs),
        "reviewable_count": sum(is_reviewable_zhilian_job(job) for job in jobs),
        "title_source": str(first_card.get("titleSource") or ""),
        "company_source": str(first_card.get("companySource") or ""),
        "generic_detail_label_rejected": bool(
            jobs and jobs[0].name != "查看更多信息"
        ),
    }


def main() -> int:
    stage = "initializing"
    report: dict[str, Any] = {
        "gate": "zhilian_headed_public_page",
        "browser_mode": "headed_xvfb",
        "uses_account": False,
        "uses_user_data": False,
        "uses_recruiting_action": False,
        "start_url": _safe_url(START_URL),
    }
    try:
        stage = "attach_chrome"
        manager = AttachedChromeManager()
        driver = CDPBossDriver(
            manager=manager,
            platform="zhilian",
            track_round=False,
        )
        deadline = time.monotonic() + TIMEOUT_SECONDS
        reload_deadline = time.monotonic() + ENTRY_RELOAD_SECONDS
        entry_reload_attempted = False
        entry: dict[str, Any] = {}
        stage = "wait_entry_page"
        while time.monotonic() < deadline:
            entry = _probe_page(driver)
            if entry.get("securityPage"):
                report.update(
                    status="blocked_security_page",
                    entry_ready_state=str(entry.get("readyState") or ""),
                )
                _write_report(report)
                return 78
            if (
                entry.get("readyState") in {"interactive", "complete"}
                and entry.get("hasSearchInput")
                and entry.get("hasOfficialSearchAnchor")
            ):
                break
            if not entry_reload_attempted and time.monotonic() >= reload_deadline:
                driver.cdp.send("Page.reload", {"ignoreCache": True})
                entry_reload_attempted = True
            time.sleep(POLL_SECONDS)
        else:
            report.update(
                status="failed_entry_not_ready",
                entry_ready_state=str(entry.get("readyState") or ""),
                has_search_input=bool(entry.get("hasSearchInput")),
                has_official_search_anchor=bool(entry.get("hasOfficialSearchAnchor")),
                entry_reload_attempted=entry_reload_attempted,
            )
            _write_report(report)
            return 1
        report["entry_reload_attempted"] = entry_reload_attempted

        stage = "commit_keyword"
        commit = _commit_keyword(driver)
        report["keyword_committed"] = bool(commit.get("ok"))
        if not commit.get("ok"):
            report["status"] = "failed_keyword_commit"
            _write_report(report)
            return 1

        destination_deadline = time.monotonic() + 15.0
        activation: dict[str, Any] = {}
        stage = "activate_search_control"
        while time.monotonic() < destination_deadline:
            activation = driver._exec_js(
                build_zhilian_search_control_activation_script(
                    QUERY, method="native_pointer"
                )
            )
            if activation.get("ok") and activation.get("searchDestinationReady"):
                break
            time.sleep(0.25)
        report.update(
            control_type=str(activation.get("buttonCandidateType") or "")[:80],
            control_target=str(activation.get("searchControlTarget") or "")[:20],
            destination_ready=bool(activation.get("searchDestinationReady")),
            destination_kind=str(activation.get("searchDestinationKind") or "")[:80],
        )
        click_point = activation.get("clickPoint")
        if not (
            activation.get("ok")
            and activation.get("searchDestinationReady")
            and isinstance(click_point, dict)
        ):
            report["status"] = "failed_official_search_anchor"
            _write_report(report)
            return 1

        stage = "capture_target_state"
        before = driver.capture_platform_target_state("zhilian")
        stage = "click_search_control"
        driver._click_at(click_point.get("x"), click_point.get("y"))
        stage = "adopt_result_target"
        target = driver.adopt_platform_target_transition(
            before,
            platform="zhilian",
            wait_seconds=5,
        )
        report.update(
            target_outcome=str(target.get("outcome") or "")[:80],
            new_target_count=int(target.get("new_target_count") or 0),
            previous_target_closed=bool(target.get("previous_target_closed")),
        )
        if not target.get("ok"):
            report["status"] = "failed_target_transition"
            _write_report(report)
            return 1

        transition_deadline = time.monotonic() + TIMEOUT_SECONDS
        result_reload_deadline = time.monotonic() + RESULT_RELOAD_SECONDS
        result_reload_attempted = False
        transition: dict[str, Any] = {}
        snapshot: dict[str, Any] = {}
        stage = "verify_result_page"
        while time.monotonic() < transition_deadline:
            raw_page = _probe_page(driver)
            if raw_page.get("securityPage"):
                report.update(
                    status="blocked_security_page",
                    target_ready_state=str(raw_page.get("readyState") or ""),
                )
                _write_report(report)
                return 78
            transition = driver._exec_js(
                build_zhilian_search_transition_script(QUERY, CITY)
            )
            if transition.get("readyState") == "complete":
                snapshot = driver._exec_js(build_zhilian_snapshot_script(limit=5))
                route_ok = _is_search_route(transition.get("url"))
                query_ok = (
                    " ".join(str(transition.get("observedKeyword") or "").split()).casefold()
                    == " ".join(QUERY.split()).casefold()
                )
                city_ok = bool(transition.get("titleCityMatch"))
                candidate_ready = int(snapshot.get("candidateCount") or 0) > 0
                surface_ready = int(snapshot.get("jobSurfaceCount") or 0) > 0
                no_results_ready = bool(snapshot.get("noResults"))
                if (
                    route_ok
                    and query_ok
                    and city_ok
                    and (candidate_ready or surface_ready or no_results_ready)
                ):
                    break
            if (
                not result_reload_attempted
                and time.monotonic() >= result_reload_deadline
            ):
                driver.cdp.send("Page.reload", {"ignoreCache": True})
                result_reload_attempted = True
            time.sleep(POLL_SECONDS)

        safe_transition = _safe_transition(transition)
        report["transition"] = safe_transition
        evidence = set(safe_transition["search_page_evidence"])
        candidate_count = int(snapshot.get("candidateCount") or 0)
        job_surface_count = int(snapshot.get("jobSurfaceCount") or 0)
        collectable_surface_count = int(
            snapshot.get("collectableSurfaceCount") or candidate_count
        )
        no_results = bool(snapshot.get("noResults"))
        report.update(
            candidate_count=candidate_count,
            collectable_surface_count=collectable_surface_count,
            dom_job_surface_count=job_surface_count,
            no_results=no_results,
            result_reload_attempted=result_reload_attempted,
        )
        route_complete = bool(
            _is_search_route(transition.get("url"))
            and safe_transition["ready_state"] == "complete"
            and safe_transition["observed_keyword_matches"]
            and safe_transition["title_city_match"]
        )
        list_signal = bool(
            (candidate_count > 0 and (job_surface_count > 0 or "job_action" in evidence))
            or no_results
        )
        explicit_login_wall = bool(
            transition.get("loginRequired") or snapshot.get("loginRequired")
        )
        if route_complete and list_signal:
            stage = "parse_result_snapshot"
            parsed_jobs = parse_zhilian_snapshot_jobs(
                snapshot,
                city_name=CITY,
                limit=5,
            )
            page_exhausted = _query_page_exhausted(snapshot, current_page=1)
            bound_driver = BoundResultPageDriver(driver)
            stage = "run_one_page_collector"
            collected = ZhilianReadOnlyCollector(
                driver=bound_driver,
                login_verification={
                    "valid": True,
                    "source": "recent_login_check",
                    "platform": "zhilian",
                    "round_id": "isolated-public-gate",
                    "browser_session_id": "ci-xvfb",
                    "age_seconds": 0,
                },
            ).collect(
                query=QUERY,
                limit=20,
                wait_seconds=0,
                page=1,
                pages=1,
                page_delay=0,
            )
            termination_reason = str(
                collected.snapshot.get("terminationReason") or ""
            )
            collection_budget_satisfied = zhilian_candidate_collection_completed(
                termination_reason
            )
            report.update(
                requested_pages=1,
                page_two_attempted=bound_driver.pagination_attempts > 0,
                collector_ok=bool(collected.ok),
                collector_candidate_count=len(collected.jobs),
                snapshot_parser_candidate_count=len(parsed_jobs),
                first_page_exhausted=page_exhausted,
                collection_budget_satisfied=collection_budget_satisfied,
                termination_reason=termination_reason,
                reviewable_parser_candidate_count=sum(
                    is_reviewable_zhilian_job(job) for job in parsed_jobs
                ),
                reviewable_collector_candidate_count=sum(
                    is_reviewable_zhilian_job(job) for job in collected.jobs
                ),
            )
            stage = "live_cross_city_switch"
            city_switch_gate = _run_live_city_switch_gate(driver)
            report["live_cross_city_switch_gate"] = city_switch_gate
            if not city_switch_gate.get("ok"):
                report["status"] = "failed_live_cross_city_switch"
                _write_report(report)
                return 1
            collection_boundary = _evaluate_one_page_collection_boundary(
                explicit_login_wall=explicit_login_wall,
                parsed_candidate_count=len(parsed_jobs),
                collector_ok=bool(collected.ok),
                collector_candidate_count=len(collected.jobs),
                page_two_attempted=bound_driver.pagination_attempts > 0,
                collection_budget_satisfied=collection_budget_satisfied,
                all_parser_candidates_reviewable=bool(parsed_jobs)
                and all(is_reviewable_zhilian_job(job) for job in parsed_jobs),
                all_collector_candidates_reviewable=bool(collected.jobs)
                and all(is_reviewable_zhilian_job(job) for job in collected.jobs),
            )
            if collection_boundary["status"] == "passed_route_only_login_wall":
                report.update(collection_boundary)
                _write_report(report)
                return 0
            if not collection_boundary["ok"]:
                report.update(collection_boundary)
                _write_report(report)
                return 1
            stage = "public_detail_reviewability"
            detail_gate = _run_public_detail_reviewability_gate(driver, parsed_jobs)
            report["public_detail_reviewability_gate"] = detail_gate
            if not detail_gate.get("ok"):
                report["status"] = "failed_public_detail_reviewability"
                _write_report(report)
                return 1
            stage = "document_title_fallback_fixture"
            title_fallback_gate = _run_document_title_fallback_gate(driver)
            report["document_title_fallback_gate"] = title_fallback_gate
            if not title_fallback_gate.get("ok"):
                report["status"] = "failed_document_title_fallback"
                _write_report(report)
                return 1
            stage = "generic_link_reviewability_fixture"
            reviewability_gate = _run_generic_link_reviewability_gate(driver)
            report["generic_link_reviewability_gate"] = reviewability_gate
            if not reviewability_gate.get("ok"):
                report["status"] = "failed_reviewability_boundary"
                _write_report(report)
                return 1
            stage = "cross_city_fallback_fixture"
            fallback_gate = _run_cross_city_fallback_gate(driver)
            report["cross_city_fallback_gate"] = fallback_gate
            if not fallback_gate.get("ok"):
                report["status"] = "failed_cross_city_fallback_boundary"
                _write_report(report)
                return 1
            report["status"] = "passed_full"
            _write_report(report)
            return 0
        if route_complete and explicit_login_wall:
            report.update(
                status="passed_route_only_login_wall",
                remaining_unverified="job_list_signal",
            )
            _write_report(report)
            return 0

        report["status"] = "failed_result_verification"
        _write_report(report)
        return 1
    except Exception as exc:
        report.update(
            status="failed_exception",
            error_type=type(exc).__name__,
            failure_stage=stage,
        )
        _write_report(report)
        return 1


if __name__ == "__main__":
    sys.exit(main())
