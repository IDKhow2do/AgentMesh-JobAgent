"""Codex-native local job-search workflow.

The interactive Codex session is the reasoning layer. This CLI supplies local
collection, incremental state, safe review artifacts and deterministic delivery.
No AgentMesh cloud or third-party LLM API is required.
"""
from __future__ import annotations

import argparse
import json
from datetime import datetime
from pathlib import Path
from typing import Any

from jobagent.drivers.boss import create_driver
from jobagent.local_state import (
    annotate_job_history,
    authorize_platform_review,
    authorized_selected_jobs,
    compact_job,
    hydrate_decision_cache,
    platform_review_is_valid,
    profile_digest,
    render_final_review,
    save_decision_cache,
)
from jobagent.official import merge_cross_channel_jobs
from jobagent.platforms.discovery import CollectionError, collect_from_search_plan

PLATFORMS = ("boss", "liepin", "zhilian", "51job")
DEFAULT_STATE_DIR = Path(".jobagent-local")
DEFAULT_CAREER_DIR = Path("career/private")


def _json_dump(payload: Any) -> str:
    return json.dumps(payload, ensure_ascii=False, indent=2)


def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(_json_dump(payload) + "\n", encoding="utf-8")
    tmp.replace(path)


def _read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _make_plan(platform: str, cities: list[str], keywords: list[str], page_limit: int, candidate_limit: int) -> dict[str, Any]:
    queries = [
        {"city": city, "keyword": keyword, "page_limit": page_limit}
        for city in cities
        for keyword in keywords
    ]
    return {
        "platform": platform,
        "candidate_limit": min(max(candidate_limit, 1), 100),
        "queries": queries,
        "source": "codex-local",
    }


def _discover_one(platform: str, cities: list[str], keywords: list[str], page_limit: int, candidate_limit: int, wait_seconds: int, page_delay: float) -> dict[str, Any]:
    plan = _make_plan(platform, cities, keywords, page_limit, candidate_limit)
    jobs = collect_from_search_plan(plan, wait_seconds=wait_seconds, page_delay=page_delay)
    for job in jobs:
        job.setdefault("platform", platform)
    return {"ok": True, "mode": "local_only", "platform": platform, "plan": plan, "count": len(jobs), "jobs": jobs}


def _profile_status(career_dir: Path) -> dict[str, Any]:
    expected = {
        "resume": any(career_dir.glob("*.pdf")) or (career_dir / "resumes").exists(),
        "profile": (career_dir / "MASTER_PROFILE.md").exists() or (career_dir / "PROFILE.md").exists(),
        "targets": (career_dir / "TARGETS.md").exists(),
        "filters": (career_dir / "FILTERS.md").exists(),
        "projects": (career_dir / "PROJECTS.md").exists(),
        "answers": (career_dir / "ANSWERS.json").exists(),
    }
    core_ready = bool(expected["resume"] and expected["profile"] and expected["targets"] and expected["filters"])
    return {
        "career_dir": str(career_dir),
        "core_ready": core_ready,
        "files": expected,
        "next": (
            "Career profile is ready for job review."
            if core_ready
            else "Codex should run conversational Career Onboarding: read the resume first, then ask only for missing facts/preferences."
        ),
    }


def cmd_doctor(args: argparse.Namespace) -> int:
    state_dir = Path(args.state_dir)
    payload = {
        "ok": True,
        "mode": "local_only",
        "cloud_required": False,
        "llm_api_required": False,
        "host_agent": "Codex",
        "platforms": list(PLATFORMS),
        "state_dir": str(state_dir),
        "profile": _profile_status(Path(args.career_dir)),
        "performance": {
            "cross_platform_dedupe": True,
            "cross_run_job_index": str(state_dir / "job-index.json"),
            "profile_aware_decision_cache": str(state_dir / "decision-cache.json"),
            "compact_review_index": True,
        },
        "safety": {
            "platform_send_requires_final_review_digest": True,
            "official_submit_requires_final_review_digest": True,
            "browser_tabs": 4,
            "form_tabs": 2,
            "submit_concurrency": 1,
        },
        "next": "Complete Career Onboarding if needed, then run `jobagent-local round ...`.",
    }
    print(_json_dump(payload))
    return 0


def cmd_profile(args: argparse.Namespace) -> int:
    print(_json_dump({"ok": True, **_profile_status(Path(args.career_dir))}))
    return 0


def cmd_discover(args: argparse.Namespace) -> int:
    try:
        result = _discover_one(args.platform, args.city, args.keyword, args.pages, args.limit, args.wait_seconds, args.page_delay)
    except CollectionError as exc:
        result = {
            "ok": False,
            "mode": "local_only",
            "platform": args.platform,
            "error": exc.code,
            "message": exc.message,
            "user_prompt": exc.user_prompt,
            "details": exc.details or {},
        }
    out = Path(args.out) if args.out else Path(args.state_dir) / "latest" / f"{args.platform}.json"
    _write_json(out, result)
    result["output"] = str(out)
    print(_json_dump(result))
    return 0 if result.get("ok") else 2


def cmd_round(args: argparse.Namespace) -> int:
    state_dir = Path(args.state_dir)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    run_dir = state_dir / "runs" / stamp
    requested = args.platform or list(PLATFORMS)
    summary: list[dict[str, Any]] = []
    collected_jobs: list[dict[str, Any]] = []

    for platform in requested:
        try:
            result = _discover_one(platform, args.city, args.keyword, args.pages, args.limit, args.wait_seconds, args.page_delay)
        except Exception as exc:  # one site must not kill the other sites
            if isinstance(exc, CollectionError):
                result = {
                    "ok": False,
                    "mode": "local_only",
                    "platform": platform,
                    "error": exc.code,
                    "message": exc.message,
                    "user_prompt": exc.user_prompt,
                    "details": exc.details or {},
                }
            else:
                result = {"ok": False, "mode": "local_only", "platform": platform, "error": type(exc).__name__, "message": str(exc)}
        _write_json(run_dir / f"{platform}.json", result)
        jobs = list(result.get("jobs") or []) if result.get("ok") else []
        collected_jobs.extend(jobs)
        summary.append({"platform": platform, "ok": bool(result.get("ok")), "count": len(jobs), "error": result.get("error")})

    raw_count = len(collected_jobs)
    merged_jobs = merge_cross_channel_jobs(collected_jobs)
    history_stats = annotate_job_history(merged_jobs, state_dir / "job-index.json")
    current_profile_digest = profile_digest(Path(args.career_dir))
    cached_decisions = hydrate_decision_cache(merged_jobs, state_dir / "decision-cache.json", current_profile_digest)
    needs_review = sum(
        1
        for job in merged_jobs
        if not job.get("decision_cached") or (job.get("history") or {}).get("is_changed")
    )

    review = {
        "schema": "jobagent-local-review-v2",
        "created_at": datetime.now().isoformat(timespec="seconds"),
        "mode": "local_only",
        "profile_digest": current_profile_digest,
        "final_review_authorization": None,
        "instructions": {
            "host_agent": "Codex",
            "decision_values": ["selected", "review", "rejected"],
            "review_strategy": "Read review-index.json first. Reuse decision_cached jobs unless there is a reason to reconsider them. Deep-read full JD only for new, changed, uncertain, or promising jobs.",
            "rule": "Apply local FILTERS before scoring. Never invent resume/JD facts. Add decision, score, reasons, risks, greeting, resume_variant, preferred_channel and screening_answers where relevant.",
            "delivery": "Real platform delivery requires a matching final-review authorization created by `jobagent-local review --approve`; --send alone is insufficient.",
        },
        "jobs": merged_jobs,
    }
    review_file = run_dir / "review.json"
    compact_file = run_dir / "review-index.json"
    _write_json(review_file, review)
    _write_json(compact_file, {
        "schema": "jobagent-local-review-index-v1",
        "created_at": review["created_at"],
        "total": len(merged_jobs),
        "needs_review": needs_review,
        "cached_decisions": cached_decisions,
        "jobs": [compact_job(job) for job in merged_jobs],
    })

    payload = {
        "ok": any(item["ok"] for item in summary),
        "mode": "local_only",
        "run_dir": str(run_dir),
        "platforms": summary,
        "raw_jobs": raw_count,
        "canonical_jobs": len(merged_jobs),
        "duplicates_removed": max(0, raw_count - len(merged_jobs)),
        "history": history_stats,
        "cached_decisions": cached_decisions,
        "needs_review": needs_review,
        "review_index": str(compact_file),
        "review_file": str(review_file),
        "next": "Codex: read review-index.json first, deep-review only needed jobs in review.json, then run `jobagent-local summary --input <review.json>` before asking the user for final approval.",
    }
    _write_json(run_dir / "summary.json", payload)
    print(_json_dump(payload))
    return 0 if payload["ok"] else 2


def _selected_jobs(payload: Any) -> list[dict[str, Any]]:
    jobs = payload.get("jobs", []) if isinstance(payload, dict) else payload
    if not isinstance(jobs, list):
        raise ValueError("Input must be a list of jobs or an object containing a jobs list")
    selected = []
    for job in jobs:
        if not isinstance(job, dict):
            continue
        decision = str(job.get("decision") or job.get("recommendation") or "").lower()
        if decision == "selected" or job.get("selected") is True:
            selected.append(job)
    return selected


def cmd_summary(args: argparse.Namespace) -> int:
    source = Path(args.input)
    payload = _read_json(source)
    markdown = render_final_review(payload)
    out = Path(args.out) if args.out else source.with_name("FINAL_REVIEW.md")
    out.write_text(markdown + "\n", encoding="utf-8")
    selected = _selected_jobs(payload)
    print(_json_dump({
        "ok": True,
        "selected_count": len(selected),
        "final_review": str(out),
        "authorized": platform_review_is_valid(payload),
        "next": "Show the entire FINAL_REVIEW.md to the user. Do not submit anything until the user explicitly approves this plan.",
    }))
    return 0


def cmd_review(args: argparse.Namespace) -> int:
    source = Path(args.input)
    payload = _read_json(source)
    selected = _selected_jobs(payload)
    summary_path = Path(args.summary_out) if args.summary_out else source.with_name("FINAL_REVIEW.md")
    summary_path.write_text(render_final_review(payload) + "\n", encoding="utf-8")

    if not args.approve:
        print(_json_dump({
            "ok": False,
            "error": "explicit_approval_required",
            "selected_count": len(selected),
            "final_review": str(summary_path),
            "next": "Present FINAL_REVIEW.md to the user. Only rerun with --approve after an explicit final decision.",
        }))
        return 2

    try:
        authorization = authorize_platform_review(payload, args.key or None)
    except ValueError as exc:
        print(_json_dump({"ok": False, "error": str(exc)}))
        return 2
    _write_json(source, payload)
    saved = save_decision_cache(
        list(payload.get("jobs") or []),
        Path(args.state_dir) / "decision-cache.json",
        profile_digest(Path(args.career_dir)),
    )
    print(_json_dump({
        "ok": True,
        "authorization": authorization,
        "cached_decisions_saved": saved,
        "final_review": str(summary_path),
        "next": "The exact approved platform plan is authorized. Run a dry-run, then --send only for this unchanged approved snapshot.",
    }))
    return 0


def _attempt_to_dict(attempt: Any) -> dict[str, Any]:
    return {
        "job_url": getattr(attempt, "job_url", ""),
        "message": getattr(attempt, "message", ""),
        "delivered": bool(getattr(attempt, "delivered", False)),
        "error": getattr(attempt, "error", ""),
        "steps": getattr(attempt, "steps", []),
    }


def _deliver_platform(platform: str, jobs: list[dict[str, Any]], *, send: bool, limit: int) -> list[dict[str, Any]]:
    dry_run = not send
    if platform == "boss":
        from jobagent.platforms.boss import execute_boss_greeting_flow
        driver = create_driver(platform="boss")
        attempts = []
        for job in jobs[:limit]:
            url = str(job.get("url") or "")
            message = str(job.get("greeting") or job.get("message") or "").strip()
            if not url:
                attempts.append({"job_url": url, "delivered": False, "error": "missing_job_url", "steps": []})
                continue
            if not message:
                attempts.append({"job_url": url, "delivered": False, "error": "missing_greeting", "steps": []})
                continue
            if dry_run:
                attempts.append({"job_url": url, "message": message, "delivered": False, "error": "dry_run", "steps": [{"step": "plan_boss_greeting", "ok": True}]})
            else:
                attempts.append(_attempt_to_dict(execute_boss_greeting_flow(driver, url, message)))
        return attempts

    if platform == "liepin":
        from jobagent.platforms.liepin import LiepinApplySender
        sender = LiepinApplySender()
    elif platform == "zhilian":
        from jobagent.platforms.zhilian import ZhilianApplySender
        sender = ZhilianApplySender()
    elif platform == "51job":
        from jobagent.platforms.job51 import Job51ApplySender
        sender = Job51ApplySender()
    else:
        raise ValueError(f"Unsupported platform: {platform}")
    attempts = sender.send_batch(jobs, limit=limit, dry_run=dry_run, stop_on_failure=True)
    return [_attempt_to_dict(item) for item in attempts]


def _platform_delivery_jobs(jobs: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    deliver: list[dict[str, Any]] = []
    skipped: list[dict[str, Any]] = []
    for job in jobs:
        preferred = str(job.get("preferred_channel") or "").lower()
        action = str(job.get("platform_action") or "").lower()
        platform = str(job.get("platform") or "")
        if preferred == "official":
            if platform == "boss" and action in {"message", "message_only", "followup"}:
                deliver.append(job)
            else:
                skipped.append({
                    "canonical_job_key": job.get("canonical_job_key"),
                    "company": job.get("company"),
                    "title": job.get("title") or job.get("name"),
                    "reason": "official_channel_preferred",
                })
            continue
        deliver.append(job)
    return deliver, skipped


def cmd_apply(args: argparse.Namespace) -> int:
    source = Path(args.input)
    payload = _read_json(source)
    if args.send:
        try:
            jobs = authorized_selected_jobs(payload)
        except ValueError as exc:
            print(_json_dump({
                "ok": False,
                "mode": "send_blocked",
                "error": str(exc),
                "next": "Regenerate FINAL_REVIEW.md and obtain explicit user approval with `jobagent-local review --approve`.",
            }))
            return 2
    else:
        jobs = _selected_jobs(payload)

    jobs, skipped = _platform_delivery_jobs(jobs)
    grouped: dict[str, list[dict[str, Any]]] = {platform: [] for platform in PLATFORMS}
    for job in jobs:
        platform = str(job.get("platform") or "")
        if platform in grouped:
            grouped[platform].append(job)

    results: dict[str, Any] = {}
    for platform, platform_jobs in grouped.items():
        if not platform_jobs:
            continue
        try:
            attempts = _deliver_platform(platform, platform_jobs, send=args.send, limit=args.limit)
            results[platform] = {
                "ok": all(item.get("delivered") or item.get("error") == "dry_run" for item in attempts),
                "attempts": attempts,
            }
        except Exception as exc:
            results[platform] = {"ok": False, "error": type(exc).__name__, "message": str(exc), "attempts": []}

    out = Path(args.out) if args.out else source.with_name(source.stem + (".sent.json" if args.send else ".dry-run.json"))
    result = {
        "ok": all(item.get("ok") for item in results.values()) if results else True,
        "mode": "send" if args.send else "dry_run",
        "approved": platform_review_is_valid(payload),
        "delivery_count": len(jobs),
        "skipped_for_official": skipped,
        "results": results,
        "safety": (
            "Real platform actions were restricted to the exact user-approved review snapshot."
            if args.send
            else "No real platform actions were sent. Dry-run does not require approval."
        ),
    }
    _write_json(out, result)
    result["output"] = str(out)
    print(_json_dump(result))
    return 0 if result["ok"] else 2


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="jobagent-local", description="Codex-native local job search; no AgentMesh cloud/API key required.")
    parser.add_argument("--state-dir", default=str(DEFAULT_STATE_DIR))
    parser.add_argument("--career-dir", default=str(DEFAULT_CAREER_DIR))
    sub = parser.add_subparsers(dest="command", required=True)

    doctor = sub.add_parser("doctor", help="Show local mode, privacy, cache and safety readiness")
    doctor.set_defaults(func=cmd_doctor)
    profile = sub.add_parser("profile", help="Show Career Onboarding completeness without exposing private content")
    profile.set_defaults(func=cmd_profile)

    discover = sub.add_parser("discover", help="Collect jobs from one recruiting platform")
    discover.add_argument("--platform", choices=PLATFORMS, required=True)
    discover.add_argument("--city", action="append", required=True)
    discover.add_argument("--keyword", action="append", required=True)
    discover.add_argument("--pages", type=int, default=1)
    discover.add_argument("--limit", type=int, default=100)
    discover.add_argument("--wait-seconds", type=int, default=6)
    discover.add_argument("--page-delay", type=float, default=2.0)
    discover.add_argument("--out")
    discover.set_defaults(func=cmd_discover)

    round_cmd = sub.add_parser("round", help="Collect all platforms, dedupe and prepare an incremental Codex review")
    round_cmd.add_argument("--platform", action="append", choices=PLATFORMS)
    round_cmd.add_argument("--city", action="append", required=True)
    round_cmd.add_argument("--keyword", action="append", required=True)
    round_cmd.add_argument("--pages", type=int, default=1)
    round_cmd.add_argument("--limit", type=int, default=100)
    round_cmd.add_argument("--wait-seconds", type=int, default=6)
    round_cmd.add_argument("--page-delay", type=float, default=2.0)
    round_cmd.set_defaults(func=cmd_round)

    summary = sub.add_parser("summary", help="Render one human-readable final review sheet")
    summary.add_argument("--input", required=True)
    summary.add_argument("--out")
    summary.set_defaults(func=cmd_summary)

    review = sub.add_parser("review", help="Render or explicitly authorize the final platform-delivery snapshot")
    review.add_argument("--input", required=True)
    review.add_argument("--approve", action="store_true")
    review.add_argument("--key", action="append", help="Approve only these canonical job keys; omit to approve all selected jobs")
    review.add_argument("--summary-out")
    review.set_defaults(func=cmd_review)

    apply_cmd = sub.add_parser("apply", help="Dry-run or deliver reviewed platform jobs")
    apply_cmd.add_argument("--input", required=True, help="review.json containing Codex decisions")
    apply_cmd.add_argument("--limit", type=int, default=20)
    apply_cmd.add_argument("--send", action="store_true", help="Real delivery; additionally requires a valid final-review authorization")
    apply_cmd.add_argument("--out")
    apply_cmd.set_defaults(func=cmd_apply)
    return parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
    try:
        code = int(args.func(args))
    except KeyboardInterrupt:
        code = 130
    except Exception as exc:
        print(_json_dump({"ok": False, "error": type(exc).__name__, "message": str(exc)}))
        code = 2
    raise SystemExit(code)


if __name__ == "__main__":
    main()
