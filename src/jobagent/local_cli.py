"""Local-only Codex-native workflow for Job Agent.

This file is a local-only extension to the upstream AgentMesh Job Agent client.
It deliberately avoids AgentMesh cloud APIs: Codex (or another host agent)
creates search intent, reviews collected jobs, writes decisions/greetings, and
this CLI reuses the open-source browser collectors and delivery drivers.

Safety: real delivery requires an explicit ``--send`` flag. The default is a
dry-run so an agent cannot send applications merely by inspecting a file.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

from jobagent.drivers.boss import create_driver
from jobagent.platforms.discovery import CollectionError, collect_from_search_plan

PLATFORMS = ("boss", "liepin", "zhilian", "51job")
DEFAULT_STATE_DIR = Path(".jobagent-local")


def _json_dump(payload: Any) -> str:
    return json.dumps(payload, ensure_ascii=False, indent=2)


def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(_json_dump(payload) + "\n", encoding="utf-8")


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
    jobs = collect_from_search_plan(
        plan,
        wait_seconds=wait_seconds,
        page_delay=page_delay,
    )
    for job in jobs:
        job.setdefault("platform", platform)
    return {
        "ok": True,
        "mode": "local_only",
        "platform": platform,
        "plan": plan,
        "count": len(jobs),
        "jobs": jobs,
    }


def cmd_doctor(args: argparse.Namespace) -> int:
    payload = {
        "ok": True,
        "mode": "local_only",
        "cloud_required": False,
        "llm_api_required": False,
        "host_agent": "Codex",
        "platforms": list(PLATFORMS),
        "state_dir": str(Path(args.state_dir)),
        "next": "Run `jobagent-local round --city <city> --keyword <keyword> ...` after logging into recruiting sites in the managed Chrome profile.",
    }
    print(_json_dump(payload))
    return 0


def cmd_discover(args: argparse.Namespace) -> int:
    try:
        result = _discover_one(
            args.platform,
            args.city,
            args.keyword,
            args.pages,
            args.limit,
            args.wait_seconds,
            args.page_delay,
        )
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
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    run_dir = Path(args.state_dir) / "runs" / stamp
    requested = args.platform or list(PLATFORMS)
    summary: list[dict[str, Any]] = []
    merged_jobs: list[dict[str, Any]] = []

    for platform in requested:
        try:
            result = _discover_one(
                platform,
                args.city,
                args.keyword,
                args.pages,
                args.limit,
                args.wait_seconds,
                args.page_delay,
            )
        except Exception as exc:  # isolate platforms: one failure must not kill the round
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
                result = {
                    "ok": False,
                    "mode": "local_only",
                    "platform": platform,
                    "error": type(exc).__name__,
                    "message": str(exc),
                }
        _write_json(run_dir / f"{platform}.json", result)
        jobs = list(result.get("jobs") or []) if result.get("ok") else []
        merged_jobs.extend(jobs)
        summary.append({
            "platform": platform,
            "ok": bool(result.get("ok")),
            "count": len(jobs),
            "error": result.get("error"),
        })

    review = {
        "schema": "jobagent-local-review-v1",
        "created_at": datetime.now().isoformat(timespec="seconds"),
        "mode": "local_only",
        "instructions": {
            "host_agent": "Codex",
            "decision_values": ["selected", "review", "rejected"],
            "rule": "Codex should read the user's local career profile, score each job, add decision/score/reasons/risks and a greeting when useful. Never invent missing JD facts.",
            "delivery": "Only jobs with decision=selected are eligible. Real delivery still requires `jobagent-local apply --input <review.json> --send`.",
        },
        "jobs": merged_jobs,
    }
    _write_json(run_dir / "review.json", review)
    payload = {
        "ok": any(item["ok"] for item in summary),
        "mode": "local_only",
        "run_dir": str(run_dir),
        "platforms": summary,
        "total_jobs": len(merged_jobs),
        "review_file": str(run_dir / "review.json"),
        "next": "Codex: review review.json using career/private files, write decisions and greetings back to it, show the user the selected list, and only call apply --send after explicit user approval.",
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

    attempts = sender.send_batch(
        jobs,
        limit=limit,
        dry_run=dry_run,
        stop_on_failure=True,
    )
    return [_attempt_to_dict(item) for item in attempts]


def cmd_apply(args: argparse.Namespace) -> int:
    source = Path(args.input)
    payload = _read_json(source)
    jobs = _selected_jobs(payload)
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
        "selected_count": len(jobs),
        "results": results,
        "safety": "Real applications were sent only if --send was explicitly provided." if args.send else "No real applications were sent. Re-run with --send only after explicit user approval.",
    }
    _write_json(out, result)
    result["output"] = str(out)
    print(_json_dump(result))
    return 0 if result["ok"] else 2


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="jobagent-local", description="Codex-native local-only job search workflow; no AgentMesh cloud/API key required.")
    parser.add_argument("--state-dir", default=str(DEFAULT_STATE_DIR))
    sub = parser.add_subparsers(dest="command", required=True)

    doctor = sub.add_parser("doctor", help="Show local-only mode requirements")
    doctor.set_defaults(func=cmd_doctor)

    discover = sub.add_parser("discover", help="Collect jobs from one recruiting platform using a local SearchPlan")
    discover.add_argument("--platform", choices=PLATFORMS, required=True)
    discover.add_argument("--city", action="append", required=True)
    discover.add_argument("--keyword", action="append", required=True)
    discover.add_argument("--pages", type=int, default=1)
    discover.add_argument("--limit", type=int, default=100)
    discover.add_argument("--wait-seconds", type=int, default=6)
    discover.add_argument("--page-delay", type=float, default=2.0)
    discover.add_argument("--out")
    discover.set_defaults(func=cmd_discover)

    round_cmd = sub.add_parser("round", help="Collect from Boss, Liepin, Zhilian and 51Job in one isolated local round")
    round_cmd.add_argument("--platform", action="append", choices=PLATFORMS)
    round_cmd.add_argument("--city", action="append", required=True)
    round_cmd.add_argument("--keyword", action="append", required=True)
    round_cmd.add_argument("--pages", type=int, default=1)
    round_cmd.add_argument("--limit", type=int, default=100)
    round_cmd.add_argument("--wait-seconds", type=int, default=6)
    round_cmd.add_argument("--page-delay", type=float, default=2.0)
    round_cmd.set_defaults(func=cmd_round)

    apply_cmd = sub.add_parser("apply", help="Dry-run or deliver Codex-reviewed selected jobs")
    apply_cmd.add_argument("--input", required=True, help="review.json containing Codex decisions")
    apply_cmd.add_argument("--limit", type=int, default=20)
    apply_cmd.add_argument("--send", action="store_true", help="Actually send/apply. Omit for safe dry-run.")
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
