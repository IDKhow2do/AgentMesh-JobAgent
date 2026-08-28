from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from jobagent.infra.account_state import current_account_ref
from jobagent.infra.state import APP_DIR

WORKBENCH_ANNOUNCEMENT_ID = "jobagent_workbench_launch_202608"
WORKBENCH_URL = "https://agentmesh360.com/workbench/"
_SCHEMA_VERSION = 1


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _state_path(root: Path) -> Path:
    return root / "state" / "product_announcements.json"


def _read_state(path: Path) -> dict[str, Any] | None:
    if not path.exists():
        return {}
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return value if isinstance(value, dict) else None


def _write_state(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    temporary.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    temporary.replace(path)


def _announcement_payload() -> dict[str, Any]:
    return {
        "schema": "agentmesh360.product_announcement.v1",
        "id": WORKBENCH_ANNOUNCEMENT_ID,
        "kind": "product_launch",
        "product": "jobagent",
        "title": "Job Agent web workbench is now available",
        "message": (
            "Open the Job Agent web workbench for your resume profile, tailored "
            "interview practice, application tracking, offer comparison, and "
            "negotiation practice."
        ),
        "action": {
            "label": "Open the workbench",
            "url": WORKBENCH_URL,
        },
        "delivery": "once_per_account",
        "blocking": False,
        "requires_user_action": False,
    }


def _mark_delivered(*, app_dir: Path | None = None) -> bool:
    root = Path(app_dir) if app_dir is not None else APP_DIR
    account_ref = current_account_ref(app_dir=root)
    if not account_ref:
        return False
    path = _state_path(root)
    state = _read_state(path)
    if state is None:
        return False
    recorded_ref = str(state.get("account_ref") or "")
    if recorded_ref and recorded_ref != account_ref:
        return False
    delivered = state.get("delivered") or {}
    if not isinstance(delivered, dict):
        return False
    if delivered.get(WORKBENCH_ANNOUNCEMENT_ID):
        return False
    delivered[WORKBENCH_ANNOUNCEMENT_ID] = {"delivered_at": _utc_now()}
    try:
        _write_state(
            path,
            {
                "schema_version": _SCHEMA_VERSION,
                "account_ref": account_ref,
                "delivered": delivered,
            },
        )
    except OSError:
        return False
    return True


def claim_workbench_launch_announcement(
    *, app_dir: Path | None = None
) -> dict[str, Any] | None:
    if not _mark_delivered(app_dir=app_dir):
        return None
    return _announcement_payload()


def mark_workbench_launch_announced(*, app_dir: Path | None = None) -> bool:
    return _mark_delivered(app_dir=app_dir)
