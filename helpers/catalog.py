from __future__ import annotations
import json, os, time
from pathlib import Path
from typing import Any
import httpx
from usr.plugins.provider_nvidia_build_free.helpers import probe
from usr.plugins.provider_nvidia_build_free.helpers import state as state_store
CATALOG_URL="https://integrate.api.nvidia.com/v1/models"; ENV_VAR="NVIDIA_BUILD_FREE_API_KEY"
async def fetch_catalog(timeout: float = 10.0) -> tuple[dict[str, Any] | None, str]:
    api_key=os.environ.get(ENV_VAR,"")
    if not api_key: return None,"missing_api_key"
    try:
        async with httpx.AsyncClient(timeout=timeout) as client: response=await client.get(CATALOG_URL, headers={"Authorization": f"Bearer {api_key}"})
        if response.status_code != 200: return None, f"http_{response.status_code}"
        return response.json(), "ok"
    except httpx.TimeoutException: return None,"timeout"
    except Exception: return None,"request_failed"
def validated_catalog_path() -> Path: return Path(__file__).resolve().parents[1]/"catalog"/"validated_models.json"
def checked_in_validated_ids(path: Path | None = None) -> list[str]:
    try: payload=json.loads((path or validated_catalog_path()).read_text(encoding="utf-8"))
    except Exception: return []
    models=payload.get("models") if isinstance(payload, dict) else None
    return sorted({model_id for model_id in models if isinstance(model_id, str)}) if isinstance(models, list) else []
def extract_model_ids(payload: dict[str, Any]) -> list[str]:
    data=payload.get("data", []); return sorted({item["id"] for item in data if isinstance(item, dict) and isinstance(item.get("id"), str)}) if isinstance(data, list) else []
async def model_response() -> dict[str, Any]:
    payload,status=await fetch_catalog(); live_ids=extract_model_ids(payload or {}); eligible=[model_id for model_id in live_ids if not probe.obviously_non_chat_model(model_id)]; excluded={"obvious_non_chat": len(live_ids)-len(eligible)}
    cache=state_store.load_state(); checked=set(checked_in_validated_ids()); allowed=set(cache.get("allowed", {})); validated=checked|allowed
    included=sorted(model_id for model_id in (eligible if status == "ok" else validated) if model_id in validated)
    now=time.time(); failed=cache.get("failed", {}); failed_backoff=[model_id for model_id in eligible if isinstance(failed.get(model_id), dict) and not state_store.retry_ready(failed[model_id], now)]; unprobed=[model_id for model_id in eligible if model_id not in validated and model_id not in failed]
    worker_started=False
    if status == "ok" and state_store.should_start_worker(cache, eligible, now): worker_started=probe.start_background_worker(eligible)
    return {"data":[{"id": model_id} for model_id in included],"meta":{"provider_id":"nvidia_build_free","required_env_var":ENV_VAR,"catalog_url":CATALOG_URL,"status":status,"included_count":len(included),"excluded_count":max(0,len(eligible)-len(included))+excluded["obvious_non_chat"],"excluded_reasons":excluded,"live_count":len(live_ids),"checked_in_validated_count":len(checked),"local_validated_count":len(allowed-checked),"allowed_cache_count":len(allowed),"unprobed_live_count":len(unprobed),"failed_backoff_count":len(failed_backoff),"worker_running":bool(cache.get("worker",{}).get("running")) or worker_started,"worker_started":worker_started,"last_scan_started_at":cache.get("worker",{}).get("last_scan_started_at"),"last_scan_finished_at":cache.get("worker",{}).get("last_scan_finished_at")}}
