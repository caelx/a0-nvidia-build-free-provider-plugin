#!/usr/bin/env python3
from __future__ import annotations
import asyncio, importlib, json, subprocess, sys
from pathlib import Path
PLUGIN_NAME="provider_nvidia_build_free"
PROVIDER_ID="nvidia_build_free"
EXPECTED_ENDPOINT=f"http://127.0.0.1:80/api/plugins/{PLUGIN_NAME}/models"
HAS_API=True
def main() -> int:
    result={"plugin_name":PLUGIN_NAME,"provider_id":PROVIDER_ID,"plugin_yaml":Path("plugin.yaml").is_file(),"model_config":Path("conf/model_providers.yaml").read_text(encoding="utf-8"),"webui_config":Path("webui/config.html").is_file()}
    assert result["plugin_yaml"]
    assert PROVIDER_ID + ":" in result["model_config"]
    assert EXPECTED_ENDPOINT in result["model_config"]
    assert "127.0.0.1:5000" not in result["model_config"]
    assert result["webui_config"]
    execute_status=json.loads(subprocess.check_output([sys.executable,"execute.py","status","--json"], text=True))
    assert execute_status["ok"] is True, execute_status
    assert execute_status["provider_config_present"] is True
    assert execute_status["provider_registered"] is True
    result["execute_status"]=execute_status
    if HAS_API:
        sys.path.insert(0,"/git/agent-zero")
        payload=asyncio.run(importlib.import_module(f"usr.plugins.{PLUGIN_NAME}.api.models").Models(None, None).process({}, None))
        assert isinstance(payload.get("data"), list)
        assert isinstance(payload.get("meta"), dict)
        result["api_meta"]=payload["meta"]
    print(json.dumps(result, indent=2, sort_keys=True)); return 0
if __name__ == "__main__": raise SystemExit(main())
