from __future__ import annotations

import asyncio
import os
import threading
from typing import Any

import httpx

from usr.plugins.provider_nvidia_build_free.helpers import state as state_store


CHAT_URL = "https://integrate.api.nvidia.com/v1/chat/completions"
ENV_VAR = "NVIDIA_BUILD_FREE_API_KEY"
REQUEST_TIMEOUT_SECONDS = 45
SLEEP_BETWEEN_PROBES_SECONDS = 2
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

_worker_lock = threading.Lock()


def obviously_non_chat_model(model_id: str) -> bool:
    lower = model_id.lower()
    return any(substring in lower for substring in EXCLUDE_SUBSTRINGS)


def probe_payload(model_id: str) -> dict[str, Any]:
    return {
        "model": model_id,
        "messages": [
            {
                "role": "user",
                "content": "Call the tool named agent_zero_probe with ok=true.",
            }
        ],
        "tools": [
            {
                "type": "function",
                "function": {
                    "name": "agent_zero_probe",
                    "description": "Probe whether the model can emit a valid tool call.",
                    "parameters": {
                        "type": "object",
                        "properties": {"ok": {"type": "boolean"}},
                        "required": ["ok"],
                    },
                },
            }
        ],
        "tool_choice": "auto",
        "temperature": 0,
        "max_tokens": 128,
    }


def passed_tool_call_probe(payload: dict[str, Any]) -> bool:
    choices = payload.get("choices")
    if not isinstance(choices, list) or not choices:
        return False
    message = choices[0].get("message") if isinstance(choices[0], dict) else None
    if not isinstance(message, dict):
        return False
    tool_calls = message.get("tool_calls")
    if not isinstance(tool_calls, list):
        return False
    for tool_call in tool_calls:
        if not isinstance(tool_call, dict):
            continue
        function = tool_call.get("function")
        if isinstance(function, dict) and function.get("name") == "agent_zero_probe":
            return True
    return False


async def probe_model(api_key: str, model_id: str) -> tuple[bool, str]:
    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
    try:
        async with httpx.AsyncClient(timeout=REQUEST_TIMEOUT_SECONDS) as client:
            response = await client.post(CHAT_URL, headers=headers, json=probe_payload(model_id))
        if response.status_code != 200:
            return False, f"http_{response.status_code}"
        return (True, "ok") if passed_tool_call_probe(response.json()) else (False, "no_tool_call")
    except httpx.TimeoutException:
        return False, "timeout"
    except Exception:
        return False, "request_failed"


def start_background_worker(live_ids: list[str]) -> bool:
    if not _worker_lock.acquire(blocking=False):
        return False
    thread = threading.Thread(target=_worker_entrypoint, args=(list(live_ids),), daemon=True)
    thread.start()
    return True


def _worker_entrypoint(live_ids: list[str]) -> None:
    try:
        asyncio.run(_run_worker(live_ids))
    finally:
        _worker_lock.release()


async def _run_worker(live_ids: list[str]) -> None:
    cache = state_store.load_state()
    state_store.worker_started(cache)
    state_store.save_state(cache)
    api_key = os.environ.get(ENV_VAR, "")
    try:
        if api_key:
            await _probe_work(cache, api_key, live_ids)
    finally:
        state_store.worker_finished(cache)
        state_store.save_state(cache)


async def _probe_work(cache: dict[str, Any], api_key: str, live_ids: list[str]) -> None:
    for model_id in live_ids:
        if model_id in cache.get("allowed", {}):
            continue
        failed_entry = cache.get("failed", {}).get(model_id)
        if isinstance(failed_entry, dict) and not state_store.retry_ready(failed_entry):
            continue
        passed, reason = await probe_model(api_key, model_id)
        if passed:
            state_store.mark_allowed(cache, model_id)
        else:
            state_store.mark_failed(cache, model_id, reason)
        state_store.save_state(cache)
        await asyncio.sleep(SLEEP_BETWEEN_PROBES_SECONDS)
