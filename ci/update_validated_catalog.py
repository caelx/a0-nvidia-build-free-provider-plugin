#!/usr/bin/env python3
from __future__ import annotations
import argparse, asyncio, json, os, sys
from pathlib import Path
from typing import Any
import httpx
CATALOG_URL="https://integrate.api.nvidia.com/v1/models"; CHAT_URL="https://integrate.api.nvidia.com/v1/chat/completions"; ENV_VAR="NVIDIA_BUILD_FREE_API_KEY"; OUTPUT=Path("catalog/validated_models.json"); ARTIFACTS=Path("artifacts")
EXCLUDE_SUBSTRINGS=("embedding","embed","rerank","retrieval","guard","safety","audio","speech","image","video","vision-only")
def main() -> int:
    parser=argparse.ArgumentParser(); parser.add_argument("--check", action="store_true"); parser.add_argument("--concurrency", type=int, default=int(os.environ.get("NVIDIA_BUILD_FREE_CI_CONCURRENCY","4"))); args=parser.parse_args(); api_key=os.environ.get(ENV_VAR,"")
    if not api_key: print(f"Missing required GitHub Actions secret {ENV_VAR} for NVIDIA catalog CI.", file=sys.stderr); return 2
    result=asyncio.run(build_catalog(api_key, max(1,args.concurrency))); rendered=json.dumps(result["catalog"], indent=2, sort_keys=True)+"\n"; previous=OUTPUT.read_text(encoding="utf-8") if OUTPUT.exists() else ""
    OUTPUT.parent.mkdir(parents=True, exist_ok=True); OUTPUT.write_text(rendered, encoding="utf-8"); ARTIFACTS.mkdir(exist_ok=True); (ARTIFACTS/"nvidia-catalog-validation.json").write_text(json.dumps(result["report"], indent=2, sort_keys=True)+"\n", encoding="utf-8"); print(json.dumps(result["report"], indent=2, sort_keys=True))
    if args.check and previous != rendered: print("catalog/validated_models.json is stale; run ci/update_validated_catalog.py and commit the result.", file=sys.stderr); return 1
    return 0
async def build_catalog(api_key: str, concurrency: int) -> dict[str, Any]:
    async with httpx.AsyncClient(timeout=45) as client:
        response=await client.get(CATALOG_URL, headers={"Authorization": f"Bearer {api_key}"})
        if response.status_code != 200: raise SystemExit(f"NVIDIA catalog returned HTTP {response.status_code}")
        live_ids=extract_model_ids(response.json()); candidates=[model_id for model_id in live_ids if not obviously_non_chat_model(model_id)]; sem=asyncio.Semaphore(concurrency)
        async def probe_one(model_id: str) -> tuple[str,bool,str]:
            async with sem: return await probe_model(client, api_key, model_id)
        results=await asyncio.gather(*(probe_one(model_id) for model_id in candidates))
    models=sorted(model_id for model_id, ok, _reason in results if ok); rejected={"obvious_non_chat": len(live_ids)-len(candidates)}
    for _model_id, ok, reason in results:
        if not ok: rejected[reason]=rejected.get(reason,0)+1
    return {"catalog":{"catalog_url":CATALOG_URL,"models":models,"provider_id":"nvidia_build_free","validation":"models are included only after a successful chat/completions tool-call probe"},"report":{"provider_id":"nvidia_build_free","catalog_url":CATALOG_URL,"live_count":len(live_ids),"candidate_count":len(candidates),"presented_model_count":len(models),"validated_count":len(models),"rejected_reasons":rejected,"models":models,"validated_models":models}}
def extract_model_ids(payload: dict[str, Any]) -> list[str]:
    data=payload.get("data", []); return sorted({item["id"] for item in data if isinstance(item, dict) and isinstance(item.get("id"), str)}) if isinstance(data, list) else []
def obviously_non_chat_model(model_id: str) -> bool: return any(part in model_id.lower() for part in EXCLUDE_SUBSTRINGS)
def probe_payload(model_id: str) -> dict[str, Any]: return {"model":model_id,"messages":[{"role":"user","content":"Call the tool named agent_zero_probe with ok=true."}],"tools":[{"type":"function","function":{"name":"agent_zero_probe","description":"Probe whether the model can emit a valid tool call.","parameters":{"type":"object","properties":{"ok":{"type":"boolean"}},"required":["ok"]}}}],"tool_choice":"auto","temperature":0,"max_tokens":128}
async def probe_model(client: httpx.AsyncClient, api_key: str, model_id: str) -> tuple[str,bool,str]:
    try:
        response=await client.post(CHAT_URL, headers={"Authorization": f"Bearer {api_key}","Content-Type":"application/json"}, json=probe_payload(model_id))
        if response.status_code != 200: return model_id, False, f"http_{response.status_code}"
        passed=passed_tool_call_probe(response.json()); return model_id, passed, "ok" if passed else "no_tool_call"
    except httpx.TimeoutException: return model_id, False, "timeout"
    except Exception: return model_id, False, "request_failed"
def passed_tool_call_probe(payload: dict[str, Any]) -> bool:
    choices=payload.get("choices")
    if not isinstance(choices, list) or not choices: return False
    message=choices[0].get("message") if isinstance(choices[0], dict) else None; calls=message.get("tool_calls") if isinstance(message, dict) else None
    return isinstance(calls, list) and any(isinstance(call, dict) and isinstance(call.get("function"), dict) and call["function"].get("name") == "agent_zero_probe" for call in calls)
if __name__ == "__main__": raise SystemExit(main())
