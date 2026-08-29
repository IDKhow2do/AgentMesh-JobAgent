from __future__ import annotations

import argparse
import json
from pathlib import Path

from jobagent.official import build_official_queue, claim_items, read_json, update_item, write_json


def dump(value):
    print(json.dumps(value, ensure_ascii=False, indent=2))


def cmd_prepare(args):
    payload = read_json(Path(args.input))
    jobs = payload.get("jobs", []) if isinstance(payload, dict) else payload
    queue = build_official_queue(jobs, threshold=args.threshold)
    out = Path(args.out) if args.out else Path(args.input).with_name("official-queue.json")
    write_json(out, queue)
    dump({"ok": True, "queue": str(out), "count": len(queue["items"]), "policy": queue["policy"]})
    return 0


def cmd_claim(args):
    path = Path(args.queue)
    queue = read_json(path)
    claimed = claim_items(queue, kind=args.kind)
    write_json(path, queue)
    dump({"ok": True, "claimed": claimed, "count": len(claimed)})
    return 0


def cmd_update(args):
    path = Path(args.queue)
    queue = read_json(path)
    item = update_item(queue, args.key, args.status, error=args.error, submitted_via=args.submitted_via)
    write_json(path, queue)
    dump({"ok": True, "item": item})
    return 0


def cmd_status(args):
    queue = read_json(Path(args.queue))
    counts = {}
    for item in queue.get("items", []):
        counts[item.get("status", "unknown")] = counts.get(item.get("status", "unknown"), 0) + 1
    dump({"ok": True, "policy": queue.get("policy", {}), "counts": counts, "items": queue.get("items", []) if args.details else None})
    return 0


def build_parser():
    p = argparse.ArgumentParser(prog="jobagent-official", description="Official-careers-first queue for Codex browser execution")
    sub = p.add_subparsers(dest="command", required=True)
    prepare = sub.add_parser("prepare")
    prepare.add_argument("--input", required=True)
    prepare.add_argument("--out")
    prepare.add_argument("--threshold", type=float, default=0.80)
    prepare.set_defaults(func=cmd_prepare)
    claim = sub.add_parser("claim")
    claim.add_argument("--queue", required=True)
    claim.add_argument("--kind", choices=["browser", "form"], default="form")
    claim.set_defaults(func=cmd_claim)
    update = sub.add_parser("update")
    update.add_argument("--queue", required=True)
    update.add_argument("--key", required=True)
    update.add_argument("--status", required=True)
    update.add_argument("--error")
    update.add_argument("--submitted-via")
    update.set_defaults(func=cmd_update)
    status = sub.add_parser("status")
    status.add_argument("--queue", required=True)
    status.add_argument("--details", action="store_true")
    status.set_defaults(func=cmd_status)
    return p


def main():
    args = build_parser().parse_args()
    raise SystemExit(args.func(args))


if __name__ == "__main__":
    main()
