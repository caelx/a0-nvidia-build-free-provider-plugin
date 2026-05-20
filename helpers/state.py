from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any


FAILED_RETRY_SECONDS = 6 * 60 * 60
FULL_SCAN_SECONDS = 24 * 60 * 60
WORKER_STALE_SECONDS = 2 * 60 * 60


def default_state() -> dict[str, Any]:
    return {
        "allowed": {},
        "failed": {},
        "worker": {
            "running": False,
            "last_scan_started_at": None,
            "last_scan_finished_at": None,
        },
    }


def state_path() -> Path:
    return Path(__file__).resolve().parents[1] / "state" / "tool_call_allow_cache.json"


def load_state(path: Path | None = None) -> dict[str, Any]:
    path = path or state_path()
    try:
        state = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return default_state()
    if not isinstance(state, dict):
        return default_state()
    state.setdefault("allowed", {})
    state.setdefault("failed", {})
    state.setdefault("worker", {})
    state["worker"].setdefault("running", False)
    state["worker"].setdefault("last_scan_started_at", None)
    state["worker"].setdefault("last_scan_finished_at", None)
    return state


def save_state(state: dict[str, Any], path: Path | None = None) -> None:
    path = path or state_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(state, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    tmp.replace(path)


def retry_ready(entry: dict[str, Any], now: float | None = None) -> bool:
    now = now or time.time()
    next_retry_at = entry.get("next_retry_at")
    if not isinstance(next_retry_at, (int, float)):
        return True
    return next_retry_at <= now


def should_start_worker(state: dict[str, Any], live_ids: list[str], now: float | None = None) -> bool:
    now = now or time.time()
    worker = state.get("worker", {})
    if worker.get("running") and not worker_running_is_stale(worker, now):
        return False
    allowed = state.get("allowed", {})
    failed = state.get("failed", {})
    for model_id in live_ids:
        if model_id not in allowed and model_id not in failed:
            return True
        failed_entry = failed.get(model_id)
        if isinstance(failed_entry, dict) and retry_ready(failed_entry, now):
            return True
    finished = state.get("worker", {}).get("last_scan_finished_at")
    return not isinstance(finished, (int, float)) or finished + FULL_SCAN_SECONDS <= now


def worker_running_is_stale(worker: dict[str, Any], now: float | None = None) -> bool:
    now = now or time.time()
    started = worker.get("last_scan_started_at")
    return not isinstance(started, (int, float)) or started + WORKER_STALE_SECONDS <= now


def mark_allowed(state: dict[str, Any], model_id: str, now: float | None = None) -> None:
    now = now or time.time()
    state.setdefault("allowed", {})[model_id] = {"passed_at": now}
    state.setdefault("failed", {}).pop(model_id, None)


def mark_failed(state: dict[str, Any], model_id: str, reason: str, now: float | None = None) -> None:
    now = now or time.time()
    state.setdefault("failed", {})[model_id] = {
        "reason": reason,
        "last_failed_at": now,
        "next_retry_at": now + FAILED_RETRY_SECONDS,
    }


def worker_started(state: dict[str, Any], now: float | None = None) -> None:
    now = now or time.time()
    worker = state.setdefault("worker", {})
    worker["running"] = True
    worker["last_scan_started_at"] = now


def worker_finished(state: dict[str, Any], now: float | None = None) -> None:
    now = now or time.time()
    worker = state.setdefault("worker", {})
    worker["running"] = False
    worker["last_scan_finished_at"] = now
