#!/usr/bin/env python3
from __future__ import annotations
import json, os, sys
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen
ENV_VAR="NVIDIA_BUILD_FREE_API_KEY"
CATALOG_URL="https://integrate.api.nvidia.com/v1/models"
CATALOG_KIND="openai"
PROVIDER_ID="nvidia_build_free"
PARAMS={}
def main() -> int:
    api_key=os.environ.get(ENV_VAR,"")
    if not api_key:
        print(f"Missing required GitHub Actions secret {ENV_VAR} for {PROVIDER_ID} live CI.", file=sys.stderr); return 2
    url=CATALOG_URL + (("?" + urlencode(PARAMS)) if PARAMS else "")
    req=Request(url, headers={"Authorization": f"Bearer {api_key}", "User-Agent": "agent-zero-provider-plugin-ci"})
    try:
        with urlopen(req, timeout=30) as response: payload=json.loads(response.read().decode("utf-8"))
    except HTTPError as exc:
        print(f"{PROVIDER_ID} live catalog returned HTTP {exc.code}", file=sys.stderr); return 1
    except (OSError, URLError, json.JSONDecodeError) as exc:
        print(f"{PROVIDER_ID} live catalog request failed: {exc}", file=sys.stderr); return 1
    ids=extract_model_ids(payload)
    if not ids:
        print(f"{PROVIDER_ID} live catalog returned no recognizable models", file=sys.stderr); return 1
    print(json.dumps({"provider_id": PROVIDER_ID, "model_count": len(ids), "sample": ids[:10]}, indent=2)); return 0
def extract_model_ids(payload: object) -> list[str]:
    if not isinstance(payload, dict): return []
    if CATALOG_KIND == "ollama": return sorted({item.get("name") for item in payload.get("models", []) if isinstance(item, dict) and isinstance(item.get("name"), str)})
    return sorted({item.get("id") for item in payload.get("data", []) if isinstance(item, dict) and isinstance(item.get("id"), str)})
if __name__ == "__main__": raise SystemExit(main())
