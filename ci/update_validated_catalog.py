#!/usr/bin/env python3
from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from pathlib import Path
from typing import Any

import httpx


CATALOG_URL = "https://integrate.api.nvidia.com/v1/models"
CHAT_URL = "https://integrate.api.nvidia.com/v1/chat/completions"
ENV_VAR = "NVIDIA_BUILD_FREE_API_KEY"
OUTPUT = Path("catalog/validated_models.json")
ARTIFACTS = Path("artifacts")
FAILURE_STREAK_LIMIT = 3
PROBE_ATTEMPTS = 3
RETRY_HTTP_STATUSES = {429, 500, 502, 503, 504}
RETRY_REASONS = {"no_tool_call", "request_failed", "timeout"}
FAILURE_REASON_PRIORITY = (
    "no_tool_call",
    "timeout",
    "request_failed",
)
EXPECTED_MODELS = (
    "deepseek-ai/deepseek-v4-flash",
    "minimaxai/minimax-m2.7",
)
EXCLUDE_SUBSTRINGS = (
    "embedding",
    "embed",
    "rerank",
    "retrieval",
    "guard",
    "safety",
    "audio",
    "speech",
    "image",
    "video",
    "vision-only",
)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true")
    parser.add_argument(
        "--concurrency",
        type=int,
        default=int(os.environ.get("NVIDIA_BUILD_FREE_CI_CONCURRENCY", "4")),
    )
    args = parser.parse_args()
    api_key = os.environ.get(ENV_VAR, "")
    if not api_key:
        print(f"Missing required GitHub Actions secret {ENV_VAR} for NVIDIA catalog CI.", file=sys.stderr)
        return 2

    previous = load_catalog(OUTPUT)
    result = asyncio.run(build_catalog(api_key, max(1, args.concurrency), previous, freeze_retained_streaks=args.check))
    rendered = json.dumps(result["catalog"], indent=2, sort_keys=True) + "\n"
    previous_rendered = OUTPUT.read_text(encoding="utf-8") if OUTPUT.exists() else ""
    ARTIFACTS.mkdir(exist_ok=True)
    if args.check:
        (ARTIFACTS / "nvidia-catalog-candidate.json").write_text(rendered, encoding="utf-8")
    else:
        OUTPUT.parent.mkdir(parents=True, exist_ok=True)
        OUTPUT.write_text(rendered, encoding="utf-8")
    (ARTIFACTS / "nvidia-catalog-validation.json").write_text(
        json.dumps(result["report"], indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(result["report"], indent=2, sort_keys=True))

    failed = result["report"]["expected_model_failures"]
    if failed:
        print(f"Expected live models missing from catalog: {json.dumps(failed, sort_keys=True)}", file=sys.stderr)
        return 1
    if args.check and previous_rendered != rendered:
        print(
            "catalog/validated_models.json differs from the current live probe; "
            "scheduled refresh will update it if the drift persists.",
            file=sys.stderr,
        )
    return 0


def load_catalog(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    return payload if isinstance(payload, dict) else {}


async def build_catalog(
    api_key: str,
    concurrency: int,
    previous: dict[str, Any] | None = None,
    *,
    freeze_retained_streaks: bool = False,
) -> dict[str, Any]:
    previous = previous or {}
    async with httpx.AsyncClient(timeout=45) as client:
        response = await client.get(CATALOG_URL, headers={"Authorization": f"Bearer {api_key}"})
        if response.status_code != 200:
            raise SystemExit(f"NVIDIA catalog returned HTTP {response.status_code}")
        live_ids = extract_model_ids(response.json())
        candidates = [model_id for model_id in live_ids if not obviously_non_chat_model(model_id)]
        sem = asyncio.Semaphore(concurrency)

        async def probe_one(model_id: str) -> tuple[str, bool, str]:
            async with sem:
                return await probe_model(client, api_key, model_id)

        results = await asyncio.gather(*(probe_one(model_id) for model_id in candidates))
    return merge_probe_results(live_ids, results, previous, freeze_retained_streaks=freeze_retained_streaks)


def merge_probe_results(
    live_ids: list[str],
    probe_results: list[tuple[str, bool, str]],
    previous: dict[str, Any],
    *,
    freeze_retained_streaks: bool = False,
) -> dict[str, Any]:
    live = set(live_ids)
    candidate_ids = {model_id for model_id in live if not obviously_non_chat_model(model_id)}
    non_chat = live - candidate_ids
    previous_models = string_set(previous.get("models"))
    previous_streaks = int_map(previous.get("failure_streaks"))
    previous_rejected_models = dict_map(previous.get("rejected_models"))
    result_by_id = {model_id: (ok, reason) for model_id, ok, reason in probe_results}

    models: set[str] = set()
    failure_streaks: dict[str, int] = {}
    rejected_models: dict[str, dict[str, Any]] = {}
    retained_models: dict[str, dict[str, Any]] = {}
    removed_models: dict[str, dict[str, Any]] = {}
    rejected_reasons: dict[str, int] = {"obvious_non_chat": len(non_chat)}

    for model_id in sorted(previous_models - live):
        removed_models[model_id] = rejection("not_in_live_catalog", True)

    for model_id in sorted(non_chat):
        previously_validated = model_id in previous_models
        entry = rejection("obvious_non_chat", previously_validated)
        rejected_models[model_id] = entry | {"final_status": "removed" if previously_validated else "rejected"}
        if previously_validated:
            removed_models[model_id] = entry

    for model_id in sorted(candidate_ids):
        ok, reason = result_by_id.get(model_id, (False, "not_probed"))
        if ok:
            models.add(model_id)
            continue

        rejected_reasons[reason] = rejected_reasons.get(reason, 0) + 1
        previously_validated = model_id in previous_models
        streak = previous_streaks.get(model_id, 0) + 1 if previously_validated else 0
        status = "rejected"
        if previously_validated and streak < FAILURE_STREAK_LIMIT:
            models.add(model_id)
            failure_streaks[model_id] = streak
            retained_models[model_id] = rejection(reason, True, streak) | {"remove_after_failures": FAILURE_STREAK_LIMIT}
            status = "retained"
        elif previously_validated:
            removed_models[model_id] = rejection(reason, True, streak)
            status = "removed"

        rejected_models[model_id] = rejection(reason, previously_validated, streak if previously_validated else None) | {"final_status": status}

    catalog_failure_streaks = failure_streaks
    catalog_rejected_source = rejected_models
    if freeze_retained_streaks:
        catalog_failure_streaks, catalog_rejected_source = frozen_retained_catalog_state(
            failure_streaks,
            rejected_models,
            previous_streaks,
            previous_rejected_models,
        )
    catalog_rejected_models = stable_catalog_rejected_models(catalog_rejected_source, previous_rejected_models, previous_models)
    last_rejection_reasons = {
        model_id: reason
        for model_id, entry in catalog_rejected_models.items()
        if isinstance(reason := entry.get("reason"), str)
    }
    catalog = {
        "accepted_models": sorted(models),
        "catalog_url": CATALOG_URL,
        "failure_streaks": dict(sorted(catalog_failure_streaks.items())),
        "last_rejection_reasons": dict(sorted(last_rejection_reasons.items())),
        "models": sorted(models),
        "provider_id": "nvidia_build_free",
        "rejected_models": catalog_rejected_models,
        "validation": "models are included only after a successful chat/completions tool-call probe",
    }
    expected_failures = {
        model_id: rejection_reason(model_id, rejected_models, removed_models)
        for model_id in EXPECTED_MODELS
        if model_id in live and model_id not in models
    }
    report = {
        "provider_id": "nvidia_build_free",
        "catalog_url": CATALOG_URL,
        "live_count": len(live),
        "candidate_count": len(candidate_ids),
        "presented_model_count": len(models),
        "validated_count": len(models),
        "rejected_reasons": dict(sorted(rejected_reasons.items())),
        "rejected_models": dict(sorted(rejected_models.items())),
        "retained_models": dict(sorted(retained_models.items())),
        "removed_models": dict(sorted(removed_models.items())),
        "expected_models": list(EXPECTED_MODELS),
        "expected_model_failures": expected_failures,
        "models": sorted(models),
        "validated_models": sorted(models),
    }
    return {"catalog": catalog, "report": report}


def stable_catalog_rejected_models(
    current: dict[str, dict[str, Any]],
    previous: dict[str, dict[str, Any]],
    previous_models: set[str],
) -> dict[str, dict[str, Any]]:
    stable = {}
    for model_id, entry in current.items():
        previous_entry = previous.get(model_id)
        if (
            model_id not in previous_models
            and entry.get("final_status") == "rejected"
            and previous_entry
            and previous_entry.get("final_status") in {"rejected", "removed"}
        ):
            stable[model_id] = previous_entry
        else:
            stable[model_id] = entry
    return dict(sorted(stable.items()))


def frozen_retained_catalog_state(
    failure_streaks: dict[str, int],
    rejected_models: dict[str, dict[str, Any]],
    previous_streaks: dict[str, int],
    previous_rejected_models: dict[str, dict[str, Any]],
) -> tuple[dict[str, int], dict[str, dict[str, Any]]]:
    catalog_failure_streaks: dict[str, int] = {}
    catalog_rejected_models = dict(rejected_models)
    for model_id in failure_streaks:
        previous_streak = previous_streaks.get(model_id, 0)
        previous_entry = previous_rejected_models.get(model_id)
        if previous_streak > 0:
            catalog_failure_streaks[model_id] = previous_streak
            if previous_entry and previous_entry.get("final_status") == "retained":
                catalog_rejected_models[model_id] = previous_entry
        else:
            catalog_rejected_models.pop(model_id, None)
    return catalog_failure_streaks, catalog_rejected_models


def rejection(reason: str, previously_validated: bool, failure_streak: int | None = None) -> dict[str, Any]:
    entry: dict[str, Any] = {"failure_mode": reason, "reason": reason, "previously_validated": previously_validated}
    if failure_streak is not None:
        entry["failure_streak"] = failure_streak
    return entry


def rejection_reason(
    model_id: str,
    rejected_models: dict[str, dict[str, Any]],
    removed_models: dict[str, dict[str, Any]],
) -> str:
    entry = rejected_models.get(model_id) or removed_models.get(model_id)
    reason = entry.get("reason") if isinstance(entry, dict) else None
    return reason if isinstance(reason, str) else "missing_without_reason"


def string_set(value: Any) -> set[str]:
    return {item for item in value if isinstance(item, str)} if isinstance(value, list) else set()


def int_map(value: Any) -> dict[str, int]:
    if not isinstance(value, dict):
        return {}
    result = {}
    for key, item in value.items():
        if isinstance(key, str) and isinstance(item, int) and item > 0:
            result[key] = item
    return result


def dict_map(value: Any) -> dict[str, dict[str, Any]]:
    if not isinstance(value, dict):
        return {}
    return {
        key: item
        for key, item in value.items()
        if isinstance(key, str) and isinstance(item, dict)
    }

def extract_model_ids(payload: dict[str, Any]) -> list[str]:
    data = payload.get("data", [])
    return sorted({item["id"] for item in data if isinstance(item, dict) and isinstance(item.get("id"), str)}) if isinstance(data, list) else []


def obviously_non_chat_model(model_id: str) -> bool:
    return any(part in model_id.lower() for part in EXCLUDE_SUBSTRINGS)


def probe_payload(model_id: str) -> dict[str, Any]:
    return {
        "model": model_id,
        "messages": [{"role": "user", "content": "Call the tool named agent_zero_probe with ok=true."}],
        "tools": [
            {
                "type": "function",
                "function": {
                    "name": "agent_zero_probe",
                    "description": "Probe whether the model can emit a valid tool call.",
                    "parameters": {"type": "object", "properties": {"ok": {"type": "boolean"}}, "required": ["ok"]},
                },
            }
        ],
        "tool_choice": "auto",
        "temperature": 0,
        "max_tokens": 128,
    }


async def probe_model(client: httpx.AsyncClient, api_key: str, model_id: str) -> tuple[str, bool, str]:
    reasons = []
    for attempt in range(PROBE_ATTEMPTS):
        ok, reason = await probe_once(client, api_key, model_id)
        reasons.append(reason)
        if ok or not retry_probe(reason) or attempt == PROBE_ATTEMPTS - 1:
            return model_id, ok, choose_failure_reason(reasons) if not ok else reason
        await asyncio.sleep(1)
    return model_id, False, choose_failure_reason(reasons)


async def probe_once(client: httpx.AsyncClient, api_key: str, model_id: str) -> tuple[bool, str]:
    try:
        response = await client.post(
            CHAT_URL,
            headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
            json=probe_payload(model_id),
        )
        if response.status_code != 200:
            return False, f"http_{response.status_code}"
        passed = passed_tool_call_probe(response.json())
        return passed, "ok" if passed else "no_tool_call"
    except httpx.TimeoutException:
        return False, "timeout"
    except Exception:
        return False, "request_failed"


def retry_probe(reason: str) -> bool:
    if reason in RETRY_REASONS:
        return True
    if not reason.startswith("http_"):
        return False
    try:
        return int(reason.removeprefix("http_")) in RETRY_HTTP_STATUSES
    except ValueError:
        return False


def choose_failure_reason(reasons: list[str]) -> str:
    for prefix in ("http_400", "http_404", "http_410", "http_422"):
        if prefix in reasons:
            return prefix
    for reason in FAILURE_REASON_PRIORITY:
        if reason in reasons:
            return reason
    return reasons[-1] if reasons else "request_failed"


def passed_tool_call_probe(payload: dict[str, Any]) -> bool:
    choices = payload.get("choices")
    if not isinstance(choices, list) or not choices:
        return False
    message = choices[0].get("message") if isinstance(choices[0], dict) else None
    calls = message.get("tool_calls") if isinstance(message, dict) else None
    return isinstance(calls, list) and any(
        isinstance(call, dict)
        and isinstance(call.get("function"), dict)
        and call["function"].get("name") == "agent_zero_probe"
        for call in calls
    )


if __name__ == "__main__":
    raise SystemExit(main())
