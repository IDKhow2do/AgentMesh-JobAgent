"""CLI for the official Careers / ATS application queue."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from jobagent.official import (
    authorize_final_review,
    build_official_queue,
    claim_items,
    queue_digest,
    read_json,
    review_is_valid,
    update_item,
    write_json,
)


def dump(value) -> None:
    print(json.dumps(value, ensure_ascii=False, indent=2))


def _official_items(queue):
    return [item for item in queue.get("items", []) if item.get("preferred_channel") == "official"]


def cmd_prepare(args) -> int:
    payload = read_json(Path(args.input))
    jobs = payload.get("jobs", []) if isinstance(payload, dict) else payload
    queue = build_official_queue(jobs, args.threshold)
    out = Path(args.out) if args.out else Path(args.input).with_name("official-queue.json")
    write_json(out, queue)
    official_count = len(_official_items(queue))
    fallback_count = len(queue.get("items", [])) - official_count
    dump(
        {
            "ok": True,
            "queue": str(out),
            "total": len(queue.get("items", [])),
            "official_count": official_count,
            "platform_fallback_count": fallback_count,
            "policy": queue["policy"],
            "review_digest": queue["review_digest"],
            "next": (
                "Prepare claimed official forms, then include the resulting materials in FINAL_REVIEW.md. Do not submit yet."
                if official_count
                else "No verified official route is queued; use the reviewed recruiting-platform fallback plan."
            ),
        }
    )
    return 0


def cmd_claim(args) -> int:
    path = Path(args.queue)
    queue = read_json(path)
    claimed = claim_items(queue, args.kind)
    write_json(path, queue)
    dump(
        {
            "ok": True,
            "claimed": claimed,
            "count": len(claimed),
            "final_review_valid": review_is_valid(queue),
            "next": "Open only these claimed official URLs. Close/release finished tabs before claiming more." if claimed else "No official queue slot is currently available/needed.",
        }
    )
    return 0


def cmd_review(args) -> int:
    path = Path(args.queue)
    queue = read_json(path)
    official_items = _official_items(queue)
    if not args.approve:
        dump(
            {
                "ok": False,
                "error": "explicit_approval_required",
                "digest": queue_digest(queue),
                "official_items": official_items,
                "next": "Show the consolidated FINAL_REVIEW.md to the user. This command is not a substitute for user approval.",
            }
        )
        return 2
    if not official_items:
        dump(
            {
                "ok": True,
                "authorization": None,
                "official_count": 0,
                "message": "No verified official application is present, so no official-submit authorization is needed.",
            }
        )
        return 0
    try:
        authorization = authorize_final_review(queue, args.key or None)
    except ValueError as exc:
        dump({"ok": False, "error": str(exc), "official_items": official_items})
        return 2
    write_json(path, queue)
    dump(
        {
            "ok": True,
            "authorization": authorization,
            "official_count": len(authorization.get("approved_keys", [])),
            "next": "The approved materials are frozen by digest. Filling may continue; final Submit actions remain serial. Material changes require a new user review.",
        }
    )
    return 0


def cmd_update(args) -> int:
    path = Path(args.queue)
    queue = read_json(path)
    try:
        item = update_item(queue, args.key, args.status, error=args.error, submitted_via=args.submitted_via)
    except (ValueError, KeyError) as exc:
        dump({"ok": False, "error": str(exc), "final_review_valid": review_is_valid(queue)})
        return 2
    write_json(path, queue)
    dump({"ok": True, "item": item, "final_review_valid": review_is_valid(queue)})
    return 0


def cmd_status(args) -> int:
    queue = read_json(Path(args.queue))
    counts = {}
    for item in queue.get("items", []):
        status = item.get("status", "unknown")
        counts[status] = counts.get(status, 0) + 1
    dump(
        {
            "ok": True,
            "policy": queue.get("policy", {}),
            "counts": counts,
            "official_count": len(_official_items(queue)),
            "final_review_valid": review_is_valid(queue),
            "review_authorization": queue.get("review_authorization"),
            "items": queue.get("items", []) if args.details else None,
        }
    )
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="jobagent-official",
        description="Official-first Careers/ATS queue with bounded tabs and a mandatory final review gate",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    prepare = sub.add_parser("prepare", help="Build the official/fallback queue from a reviewed job list")
    prepare.add_argument("--input", required=True)
    prepare.add_argument("--out")
    prepare.add_argument("--threshold", type=float, default=0.80)
    prepare.set_defaults(func=cmd_prepare)

    claim = sub.add_parser("claim", help="Claim only the bounded number of official browser/form slots")
    claim.add_argument("--queue", required=True)
    claim.add_argument("--kind", choices=["browser", "form"], default="form")
    claim.set_defaults(func=cmd_claim)

    review = sub.add_parser("review", help="Persist explicit user approval of the exact official application materials")
    review.add_argument("--queue", required=True)
    review.add_argument("--approve", action="store_true")
    review.add_argument("--key", action="append", help="Approve only these canonical official-job keys; omit to approve all official jobs")
    review.set_defaults(func=cmd_review)

    update = sub.add_parser("update", help="Advance one queue item through its application state")
    update.add_argument("--queue", required=True)
    update.add_argument("--key", required=True)
    update.add_argument("--status", required=True)
    update.add_argument("--error")
    update.add_argument("--submitted-via")
    update.set_defaults(func=cmd_update)

    status = sub.add_parser("status", help="Show queue counts and final-review validity")
    status.add_argument("--queue", required=True)
    status.add_argument("--details", action="store_true")
    status.set_defaults(func=cmd_status)
    return parser


def main() -> None:
    args = build_parser().parse_args()
    try:
        code = int(args.func(args))
    except KeyboardInterrupt:
        code = 130
    except Exception as exc:
        dump({"ok": False, "error": type(exc).__name__, "message": str(exc)})
        code = 2
    raise SystemExit(code)


if __name__ == "__main__":
    main()
