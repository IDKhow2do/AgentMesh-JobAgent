"""Official Careers / ATS routing helpers for the Codex-native workflow.

Codex discovers and verifies official career URLs. This module stays
deterministic: cross-channel dedupe, ATS classification, browser queue limits,
fallback sources, and a user-owned final-review authorization digest.
"""
from __future__ import annotations

import hashlib
import json
import re
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

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
    return re.sub(r"[（()）【】\[\]·•,，。._\-/\\]", "", text)


def canonical_job_key(job: dict[str, Any]) -> str:
    seed = "|".join(
        [
            _norm(job.get("company")),
            _norm(job.get("title") or job.get("name")),
            _norm(job.get("city") or job.get("area")),
        ]
    )
    return hashlib.sha256(seed.encode("utf-8")).hexdigest()[:20]


def detect_ats(url: str | None) -> str:
    host = (urlparse(str(url or "")).hostname or "").lower()
    for name, hints in ATS_HOST_HINTS.items():
        if any(hint in host for hint in hints):
            return name
    return "generic_official"


def official_verified(job: dict[str, Any], threshold: float = OFFICIAL_CONFIDENCE_THRESHOLD) -> bool:
    url = str(job.get("official_url") or "").strip()
    try:
        confidence = float(job.get("official_match_confidence", 0))
    except (TypeError, ValueError):
        confidence = 0
    return url.startswith(("https://", "http://")) and confidence >= threshold and bool(job.get("official_evidence"))


def merge_cross_channel_jobs(jobs: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Conservatively merge exact normalized company/title/city duplicates."""
    grouped: dict[str, dict[str, Any]] = {}
    for raw in jobs:
        if not isinstance(raw, dict):
            continue
        key = canonical_job_key(raw)
        source = {
            "platform": raw.get("platform"),
            "url": raw.get("url"),
            "id": raw.get("id"),
        }
        existing = grouped.get(key)
        if existing is None:
            existing = dict(raw)
            existing["canonical_job_key"] = key
            existing["sources"] = [source]
            grouped[key] = existing
            continue

        if source not in existing.setdefault("sources", []):
            existing["sources"].append(source)
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
    sources: list[dict[str, Any]]
    score: Any = None
    risks: Any = None
    resume_variant: Any = None
    screening_answers: Any = None
    platform_action: Any = None
    status: str = "queued"
    last_error: str | None = None
    submitted_via: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


_REVIEW_FIELDS = (
    "canonical_job_key",
    "company",
    "title",
    "city",
    "official_url",
    "ats",
    "preferred_channel",
    "fallback_platform",
    "fallback_url",
    "sources",
    "score",
    "risks",
    "resume_variant",
    "screening_answers",
    "platform_action",
)


def queue_digest(queue: dict[str, Any]) -> str:
    material = [
        {field: item.get(field) for field in _REVIEW_FIELDS}
        for item in queue.get("items", [])
        if item.get("status") not in {"skipped", "submitted"}
    ]
    material.sort(key=lambda item: str(item.get("canonical_job_key") or ""))
    encoded = json.dumps(material, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def build_official_queue(jobs: list[dict[str, Any]], threshold: float = OFFICIAL_CONFIDENCE_THRESHOLD) -> dict[str, Any]:
    items: list[dict[str, Any]] = []
    for job in merge_cross_channel_jobs(jobs):
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
            sources=list(job.get("sources") or []),
            score=job.get("score"),
            risks=job.get("risks"),
            resume_variant=job.get("resume_variant"),
            screening_answers=job.get("screening_answers"),
            platform_action=job.get("platform_action"),
        )
        items.append(item.to_dict())

    queue = {
        "schema": "jobagent-official-queue-v3",
        "policy": {
            "official_first": True,
            "official_confidence_threshold": threshold,
            "cross_channel_submit_once": True,
            "browser_limits": asdict(BrowserLimits()),
            "submit_is_serial": True,
            "final_user_review_required": True,
        },
        "review_authorization": None,
        "items": items,
    }
    queue["review_digest"] = queue_digest(queue)
    return queue


def authorize_final_review(queue: dict[str, Any], approved_keys: list[str] | None = None) -> dict[str, Any]:
    eligible = [
        str(item.get("canonical_job_key"))
        for item in queue.get("items", [])
        if item.get("status") not in {"skipped", "submitted"}
    ]
    allowed = set(eligible)
    approved = set(approved_keys or eligible)
    unknown = sorted(approved - allowed)
    if unknown:
        raise ValueError(f"approved keys are not eligible queue items: {', '.join(unknown)}")

    for item in queue.get("items", []):
        if item.get("status") in {"submitted", "skipped"}:
            continue
        if item.get("canonical_job_key") not in approved:
            item["status"] = "skipped"
            item["last_error"] = "excluded_by_user_final_review"

    digest = queue_digest(queue)
    queue["review_digest"] = digest
    queue["review_authorization"] = {
        "approved": True,
        "approved_at": datetime.now().isoformat(timespec="seconds"),
        "digest": digest,
        "approved_keys": sorted(approved),
    }
    return queue["review_authorization"]


def review_is_valid(queue: dict[str, Any]) -> bool:
    authorization = queue.get("review_authorization") or {}
    return bool(authorization.get("approved") and authorization.get("digest") == queue_digest(queue))


def claim_items(queue: dict[str, Any], kind: str = "form") -> list[dict[str, Any]]:
    limits = BrowserLimits(**queue.get("policy", {}).get("browser_limits", {}))
    cap = limits.max_form_tabs if kind == "form" else limits.max_open_tabs
    active = [
        item
        for item in queue.get("items", [])
        if item.get("status") in {"claimed", "filling", "submitting"}
    ]
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


def update_item(
    queue: dict[str, Any],
    key: str,
    status: str,
    *,
    error: str | None = None,
    submitted_via: str | None = None,
) -> dict[str, Any]:
    allowed = {
        "queued",
        "claimed",
        "filling",
        "human_required",
        "ready_to_submit",
        "submitting",
        "submitted",
        "failed",
        "skipped",
        "fallback_platform",
    }
    if status not in allowed:
        raise ValueError(f"unsupported queue status: {status}")
    if status in {"submitting", "submitted"} and not review_is_valid(queue):
        raise ValueError("final_user_review_required: queue or approved materials changed, or final review has not been explicitly approved")
    if status == "submitting" and any(
        item.get("status") == "submitting" and item.get("canonical_job_key") != key
        for item in queue.get("items", [])
    ):
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
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    tmp.replace(path)
