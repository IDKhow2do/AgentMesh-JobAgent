"""Local state helpers for the Codex-native fork.

Keeps recurring work cheap without caching time-sensitive application routing:
- cross-run job fingerprints and first/last-seen metadata
- Career-Profile-aware semantic decision cache
- code-enforced final-review authorization for recruiting-platform delivery
- a human-readable Markdown artifact for the user's final approval
"""
from __future__ import annotations

import hashlib
import json
from datetime import datetime
from pathlib import Path
from typing import Any

from jobagent.official import canonical_job_key

# Cache only semantic judgement that remains valid while the JD/profile are
# unchanged. Official URLs, ATS answers and preferred routing are intentionally
# re-resolved for the current application run because they can expire/change.
DECISION_FIELDS = (
    "decision",
    "score",
    "reasons",
    "risks",
    "greeting",
    "resume_variant",
    "platform_action",
)

# Bind everything the user sees that can materially influence execution.
_APPROVAL_FIELDS = (
    "canonical_job_key",
    "platform",
    "url",
    "company",
    "title",
    "name",
    "city",
    "decision",
    "score",
    "reasons",
    "risks",
    "greeting",
    "resume_variant",
    "preferred_channel",
    "platform_action",
    "screening_answers",
    "official_url",
    "official_match_confidence",
    "official_evidence",
)


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


def _read_json(path: Path, default: Any) -> Any:
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return default


def _write_json_atomic(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    tmp.replace(path)


def _stable_hash(value: Any) -> str:
    encoded = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def job_fingerprint(job: dict[str, Any]) -> str:
    """Fingerprint source job content, excluding transient enrichment/state."""
    material = {
        "canonical_job_key": job.get("canonical_job_key") or canonical_job_key(job),
        "salary": job.get("salary"),
        "experience": job.get("experience"),
        "degree": job.get("degree"),
        "skills": job.get("skills"),
        "jd": job.get("jd"),
    }
    return _stable_hash(material)


def profile_digest(career_dir: Path) -> str:
    """Invalidate cached decisions when career facts/preferences/resumes change."""
    text_names = (
        "MASTER_PROFILE.md",
        "PROFILE.md",
        "TARGETS.md",
        "FILTERS.md",
        "PROJECTS.md",
        "STORIES.md",
        "ANSWERS.json",
    )
    material: list[tuple[str, str]] = []
    for name in text_names:
        path = career_dir / name
        if path.exists() and path.is_file():
            try:
                material.append((name, path.read_text(encoding="utf-8")))
            except OSError:
                material.append((name, "<unreadable>"))

    resume_files: list[Path] = []
    if career_dir.exists():
        for pattern in ("*.pdf", "*.docx"):
            resume_files.extend(career_dir.glob(pattern))
            resumes_dir = career_dir / "resumes"
            if resumes_dir.exists():
                resume_files.extend(resumes_dir.rglob(pattern))
    for path in sorted(set(resume_files), key=lambda item: str(item)):
        try:
            digest = hashlib.sha256(path.read_bytes()).hexdigest()
        except OSError:
            digest = "<unreadable>"
        try:
            relative = str(path.relative_to(career_dir))
        except ValueError:
            relative = str(path)
        material.append((f"resume:{relative}", digest))
    return _stable_hash(material)


def annotate_job_history(jobs: list[dict[str, Any]], index_path: Path) -> dict[str, int]:
    index = _read_json(index_path, {"schema": "jobagent-local-index-v1", "jobs": {}})
    records = index.setdefault("jobs", {})
    now = _now()
    stats = {"new": 0, "changed": 0, "seen": 0}
    for job in jobs:
        key = str(job.get("canonical_job_key") or canonical_job_key(job))
        job["canonical_job_key"] = key
        fingerprint = job_fingerprint(job)
        previous = records.get(key)
        if previous is None:
            first_seen, seen_count, is_new, is_changed = now, 1, True, False
            stats["new"] += 1
        else:
            first_seen = str(previous.get("first_seen") or now)
            seen_count = int(previous.get("seen_count") or 0) + 1
            is_new = False
            is_changed = str(previous.get("fingerprint") or "") != fingerprint
            stats["changed" if is_changed else "seen"] += 1
        job["history"] = {
            "first_seen": first_seen,
            "last_seen": now,
            "seen_count": seen_count,
            "is_new": is_new,
            "is_changed": is_changed,
        }
        records[key] = {
            "first_seen": first_seen,
            "last_seen": now,
            "seen_count": seen_count,
            "fingerprint": fingerprint,
            "company": job.get("company"),
            "title": job.get("title") or job.get("name"),
            "city": job.get("city") or job.get("area"),
        }
    index["updated_at"] = now
    _write_json_atomic(index_path, index)
    return stats


def hydrate_decision_cache(jobs: list[dict[str, Any]], cache_path: Path, current_profile_digest: str) -> int:
    cache = _read_json(cache_path, {"schema": "jobagent-local-decision-cache-v1", "jobs": {}})
    entries = cache.get("jobs", {}) if isinstance(cache, dict) else {}
    restored = 0
    for job in jobs:
        key = str(job.get("canonical_job_key") or canonical_job_key(job))
        job["canonical_job_key"] = key
        entry = entries.get(key)
        if not isinstance(entry, dict):
            continue
        if entry.get("profile_digest") != current_profile_digest:
            continue
        if entry.get("job_fingerprint") != job_fingerprint(job):
            continue
        decision = entry.get("decision")
        if not isinstance(decision, dict):
            continue
        for field in DECISION_FIELDS:
            if field in decision:
                job[field] = decision[field]
        job["decision_cached"] = True
        job["official_revalidation_required"] = str(job.get("decision") or "").lower() in {"selected", "review"}
        restored += 1
    return restored


def save_decision_cache(jobs: list[dict[str, Any]], cache_path: Path, current_profile_digest: str) -> int:
    cache = _read_json(cache_path, {"schema": "jobagent-local-decision-cache-v1", "jobs": {}})
    entries = cache.setdefault("jobs", {})
    saved = 0
    for job in jobs:
        if str(job.get("decision") or "").lower() not in {"selected", "review", "rejected"}:
            continue
        key = str(job.get("canonical_job_key") or canonical_job_key(job))
        decision = {field: job.get(field) for field in DECISION_FIELDS if field in job}
        entries[key] = {
            "profile_digest": current_profile_digest,
            "job_fingerprint": job_fingerprint(job),
            "decision": decision,
            "updated_at": _now(),
        }
        saved += 1
    cache["updated_at"] = _now()
    _write_json_atomic(cache_path, cache)
    return saved


def compact_job(job: dict[str, Any]) -> dict[str, Any]:
    jd = str(job.get("jd") or "").strip().replace("\n", " ")
    return {
        "canonical_job_key": job.get("canonical_job_key") or canonical_job_key(job),
        "platform": job.get("platform"),
        "company": job.get("company"),
        "title": job.get("title") or job.get("name"),
        "city": job.get("city") or job.get("area"),
        "salary": job.get("salary"),
        "experience": job.get("experience"),
        "degree": job.get("degree"),
        "skills": job.get("skills"),
        "history": job.get("history"),
        "decision_cached": bool(job.get("decision_cached")),
        "official_revalidation_required": bool(job.get("official_revalidation_required")),
        "decision": job.get("decision"),
        "score": job.get("score"),
        "url": job.get("url"),
        "jd_preview": jd[:360] + ("…" if len(jd) > 360 else ""),
    }


def _selected_jobs(payload: Any) -> list[dict[str, Any]]:
    jobs = payload.get("jobs", []) if isinstance(payload, dict) else payload
    if not isinstance(jobs, list):
        return []
    return [job for job in jobs if isinstance(job, dict) and str(job.get("decision") or "").lower() == "selected"]


def platform_review_digest(payload: Any, approved_keys: list[str]) -> str:
    approved = set(approved_keys)
    rows = []
    for job in _selected_jobs(payload):
        key = str(job.get("canonical_job_key") or canonical_job_key(job))
        if key not in approved:
            continue
        row = {field: job.get(field) for field in _APPROVAL_FIELDS}
        row["canonical_job_key"] = key
        rows.append(row)
    rows.sort(key=lambda item: str(item.get("canonical_job_key") or ""))
    return _stable_hash(rows)


def authorize_platform_review(payload: dict[str, Any], approved_keys: list[str] | None = None) -> dict[str, Any]:
    selected = _selected_jobs(payload)
    current_keys = [str(job.get("canonical_job_key") or canonical_job_key(job)) for job in selected]
    allowed = set(current_keys)
    keys = list(dict.fromkeys(approved_keys if approved_keys is not None else current_keys))
    unknown = [key for key in keys if key not in allowed]
    if unknown:
        raise ValueError(f"approved keys are not selected jobs: {', '.join(unknown)}")
    if not keys:
        raise ValueError("there are no selected platform jobs to approve")
    authorization = {"approved": True, "approved_at": _now(), "approved_keys": sorted(keys)}
    authorization["digest"] = platform_review_digest(payload, authorization["approved_keys"])
    payload["final_review_authorization"] = authorization
    return authorization


def platform_review_is_valid(payload: Any) -> bool:
    if not isinstance(payload, dict):
        return False
    authorization = payload.get("final_review_authorization")
    if not isinstance(authorization, dict) or not authorization.get("approved"):
        return False
    keys = authorization.get("approved_keys")
    if not isinstance(keys, list) or not keys:
        return False
    return authorization.get("digest") == platform_review_digest(payload, [str(key) for key in keys])


def authorized_selected_jobs(payload: dict[str, Any]) -> list[dict[str, Any]]:
    if not platform_review_is_valid(payload):
        raise ValueError("final_user_review_required: selected platform jobs are not covered by a valid final-review authorization")
    keys = set(str(key) for key in payload["final_review_authorization"]["approved_keys"])
    return [job for job in _selected_jobs(payload) if str(job.get("canonical_job_key") or canonical_job_key(job)) in keys]


def render_final_review(payload: Any) -> str:
    jobs = _selected_jobs(payload)
    jobs.sort(key=lambda job: float(job.get("score") or 0), reverse=True)
    lines = [
        "# 最终投递评审",
        "",
        "> 这是最终审批清单。未经你的明确批准，不得发送简历、官网 Submit 或招聘方招呼语。",
        "",
        f"共 **{len(jobs)}** 个拟投递岗位。",
        "",
        "| # | 公司 | 岗位 | 城市 | 匹配 | 渠道 | 简历版本 | 主要风险 |",
        "|---:|---|---|---|---:|---|---|---|",
    ]
    for index, job in enumerate(jobs, start=1):
        risks = job.get("risks") or []
        risk_text = "；".join(str(item) for item in risks[:2]) if isinstance(risks, list) else str(risks)
        channel = job.get("preferred_channel") or ("官网" if job.get("official_url") else job.get("platform") or "待定")
        lines.append(
            f"| {index} | {job.get('company') or '-'} | {job.get('title') or job.get('name') or '-'} | "
            f"{job.get('city') or job.get('area') or '-'} | {job.get('score') if job.get('score') is not None else '-'} | "
            f"{channel} | {job.get('resume_variant') or '默认'} | {risk_text or '-'} |"
        )
    lines.extend(["", "## 逐项详情", ""])
    for index, job in enumerate(jobs, start=1):
        key = str(job.get("canonical_job_key") or canonical_job_key(job))
        lines.append(f"### {index}. {job.get('company') or '-'} · {job.get('title') or job.get('name') or '-'}")
        lines.append(f"- Key: `{key}`")
        lines.append(f"- 渠道: {job.get('preferred_channel') or ('official' if job.get('official_url') else job.get('platform') or '待定')}")
        if job.get("official_url"):
            lines.append(f"- 官网/ATS: {job.get('official_url')}")
        if job.get("url"):
            lines.append(f"- 招聘平台: {job.get('platform') or '-'} · {job.get('url')}")
        if job.get("platform_action"):
            lines.append(f"- 招聘平台附加动作: {job.get('platform_action')}")
        lines.append(f"- 简历: {job.get('resume_variant') or '默认版本'}")
        reasons = job.get("reasons") or []
        risks = job.get("risks") or []
        if reasons:
            lines.append("- 推荐理由: " + "；".join(str(item) for item in reasons))
        if risks:
            lines.append("- 风险: " + "；".join(str(item) for item in risks))
        if job.get("greeting"):
            lines.append(f"- 招呼语: {job.get('greeting')}")
        answers = job.get("screening_answers")
        if isinstance(answers, dict) and answers:
            lines.append("- 官网关键问题:")
            for question, answer in answers.items():
                lines.append(f"  - {question}: {answer}")
        lines.append("")
    lines.extend(
        [
            "## 你的决定",
            "",
            "你可以：**全部同意**、指出要排除的编号/岗位，或要求修改渠道、简历、招呼语和筛选题答案。",
            "任何方案变更都必须重新生成本页并再次审批。",
            "",
        ]
    )
    return "\n".join(lines)
