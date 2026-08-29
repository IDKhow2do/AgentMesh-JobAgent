"""Official-careers routing helpers for the Codex-native workflow.

This module does not scrape the public web by itself. Codex discovers and verifies
an official career/ATS URL, writes that evidence into review.json, and this module
provides deterministic dedupe, routing, ATS detection, queue state, and concurrency
limits.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Any
from urllib.parse import urlparse
import json

DEFAULT_MAX_OPEN_TABS = 4
DEFAULT_MAX_FORM_TABS = 2
DEFAULT_MAX_SUBMITS = 1
OFFICIAL_CONFIDENCE_THRESHOLD = 0.80

ATS_HOST_HINTS = {
    "greenhouse": ("greenhouse.io", "boards.greenhouse.io"),
    "lever": ("lever.co", "jobs.lever.co"),
    "ashby": ("ashbyhq.com", "jobs.ashbyhq.com"),
    "workday": ("myworkdayjobs.com", "workday.com"),
    "smartrecruiters": ("smartrecruiters.com",),
    "icims": ("icims.com",),
    "jobvite": ("jobvite.com",),
    "oracle": ("oraclecloud.com", "taleo.net"),
    "sap": ("successfactors.com",),
    "moka": ("mokahr.com", "moka.com"),
    "beisen": ("beisen.com",),
}


def _norm(value: Any) -> str:
    text = str(value or "").lower().strip()
    text = re.sub(r"\s+", "", text)
    text = re.sub(r"[（()）【】\[\]·•,，。._\-/\\]", "", text)
    return text


def canonical_job_key(job: dict[str, Any]) -> str:
    seed = "|".join([
        _norm(job.get("company")),
        _norm(job.get("title") or job.get("name")),
        _norm(job.get("city") or job.get("area")),
    ])
    return hashlib.sha256(seed.encode("utf-8")).hexdigest()[:20]


def detect_ats(url: str | None) -> str:
    host = (urlparse(str(url or "")).hostname or "").lower()
    for name, hints in ATS_HOST_HINTS.items():
        if any(hint in host for hint in hints):
            return name
    return "generic_official"


def official_verified(job: dict[str, Any], threshold: float = OFFICIAL_CONFIDENCE_THRESHOLD) -> bool:
    url = str(job.get("official_url") or "").strip()
    if not url.startswith(("https://", "http://")):
        return False
    try:
        confidence = float(job.get("official_match_confidence", 0))
    except (TypeError, ValueError):
        confidence = 0
    evidence = job.get("official_evidence")
    return confidence >= threshold and bool(evidence)


def merge_cross_channel_jobs(jobs: list[dict[str, Any]]) -> list[dict[str, Any]]:
    grouped: dict[str, dict[str, Any]] = {}
    for raw in jobs:
        if not isinstance(raw, dict):
            continue
        key = canonical_job_key(raw)
        existing = grouped.get(key)
        source = {
            "platform": raw.get("platform"),
            "url": raw.get("url"),
            "id": raw.get("id"),
        }
        if existing is None:
            existing = dict(raw)
            existing["canonical_job_key"] = key
            existing["sources"] = [source]
            grouped[key] = existing
        else:
            existing.setdefault("sources", []).append(source)
            for field in ("jd", "salary", "experience", "degree", "skills"):
                if not existing.get(field) and raw.get(field):
                    existing[field] = raw[field]
            if official_verified(raw) and not official_verified(existing):
                for field in ("official_url", "official_match_confidence", "official_evidence"):
                    existing[field] = raw.get(field)
    return list(grouped.values())


@dataclass(frozen=True)
class BrowserLimits:
    max_open_tabs: int = DEFAULT_MAX_OPEN_TABS
    max_form_tabs: int = DEFAULT_MAX_FORM_TABS
    max_submits: int = DEFAULT_MAX_SUBMITS

    def __post_init__(self) -> None:
        if self.max_open_tabs < 1:
            raise ValueError("max_open_tabs must be >= 1")
        if self.max_form_tabs < 1 or self.max_form_tabs > self.max_open_tabs:
            raise ValueError("max_form_tabs must be between 1 and max_open_tabs")
        if self.max_submits != 1:
            raise ValueError("official submission must remain serial: max_submits=1")


@dataclass
class OfficialQueueItem:
    canonical_job_key: str
    company: str
    title: str
    city: str
    official_url: str | None
    ats: str
    preferred_channel: str
    fallback_platform: str | None
    fallback_url: str | None
    status: str = "queued"
    last_error: str | None = None
    submitted_via: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def build_official_queue(jobs: list[dict[str, Any]], threshold: float = OFFICIAL_CONFIDENCE_THRESHOLD) -> dict[str, Any]:
    merged = merge_cross_channel_jobs(jobs)
    items: list[dict[str, Any]] = []
    for job in merged:
        if str(job.get("decision") or "").lower() not in {"selected", "review"}:
            continue
        official = official_verified(job, threshold)
        fallback_platform = str(job.get("platform") or "") or None
        item = OfficialQueueItem(
            canonical_job_key=str(job["canonical_job_key"]),
            company=str(job.get("company") or ""),
            title=str(job.get("title") or job.get("name") or ""),
            city=str(job.get("city") or job.get("area") or ""),
            official_url=str(job.get("official_url") or "") or None,
            ats=detect_ats(job.get("official_url")) if official else "none",
            preferred_channel="official" if official else "platform",
            fallback_platform=fallback_platform,
            fallback_url=str(job.get("url") or "") or None,
        )
        items.append(item.to_dict())
    return {
        "schema": "jobagent-official-queue-v1",
        "policy": {
            "official_first": True,
            "official_confidence_threshold": threshold,
            "cross_channel_submit_once": True,
            "browser_limits": asdict(BrowserLimits()),
            "submit_is_serial": True,
        },
        "items": items,
    }


def claim_items(queue: dict[str, Any], kind: str = "form") -> list[dict[str, Any]]:
    limits = BrowserLimits(**queue.get("policy", {}).get("browser_limits", {}))
    cap = limits.max_form_tabs if kind == "form" else limits.max_open_tabs
    active = [item for item in queue.get("items", []) if item.get("status") in {"claimed", "filling", "submitting"}]
    available = max(0, cap - len(active))
    claimed: list[dict[str, Any]] = []
    for item in queue.get("items", []):
        if available <= 0:
            break
        if item.get("status") != "queued":
            continue
        item["status"] = "claimed"
        claimed.append(item)
        available -= 1
    return claimed


def update_item(queue: dict[str, Any], key: str, status: str, *, error: str | None = None, submitted_via: str | None = None) -> dict[str, Any]:
    allowed = {"queued", "claimed", "filling", "human_required", "ready_to_submit", "submitting", "submitted", "failed", "skipped", "fallback_platform"}
    if status not in allowed:
        raise ValueError(f"unsupported queue status: {status}")
    if status == "submitting":
        active_submit = [item for item in queue.get("items", []) if item.get("status") == "submitting" and item.get("canonical_job_key") != key]
        if active_submit:
            raise ValueError("submit concurrency is 1; another job is already submitting")
    for item in queue.get("items", []):
        if item.get("canonical_job_key") == key:
            item["status"] = status
            item["last_error"] = error
            if submitted_via:
                item["submitted_via"] = submitted_via
            return item
    raise KeyError(key)


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
