from __future__ import annotations
import asyncio, importlib, json, sys, types
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2]
PLUGIN_NAME="provider_nvidia_build_free"
PROVIDER_ID="nvidia_build_free"
ENV_VAR="NVIDIA_BUILD_FREE_API_KEY"
HAS_API=True
def install_package_alias() -> None:
    sys.path.insert(0, str(ROOT))
    usr=sys.modules.setdefault("usr", types.ModuleType("usr")); usr.__path__=[]
    plugins=sys.modules.setdefault("usr.plugins", types.ModuleType("usr.plugins")); plugins.__path__=[]
    provider=sys.modules.setdefault(f"usr.plugins.{PLUGIN_NAME}", types.ModuleType(f"usr.plugins.{PLUGIN_NAME}")); provider.__path__=[str(ROOT)]
def test_root_plugin_metadata_is_installable():
    assert (ROOT/"plugin.yaml").is_file(); assert (ROOT/"conf"/"model_providers.yaml").is_file(); assert (ROOT/"webui"/"config.html").is_file()
    assert f"name: {PLUGIN_NAME}" in (ROOT/"plugin.yaml").read_text(encoding="utf-8")
    assert PROVIDER_ID + ":" in (ROOT/"conf"/"model_providers.yaml").read_text(encoding="utf-8")
def test_missing_api_key_returns_clear_status(monkeypatch):
    if not HAS_API: return
    install_package_alias(); monkeypatch.delenv(ENV_VAR, raising=False)
    payload,status=asyncio.run(importlib.import_module(f"usr.plugins.{PLUGIN_NAME}.helpers.catalog").fetch_catalog())
    assert payload is None; assert status == "missing_api_key"
def test_provider_specific_contracts(monkeypatch, tmp_path):
    install_package_alias()
    if PLUGIN_NAME == "provider_opencode_zen_free":
        m=importlib.import_module("usr.plugins.provider_opencode_zen_free.helpers.filter")
        assert m.filter_free_models(m.extract_model_ids({"data":[{"id":"big-pickle"},{"id":"custom-free"},{"id":"paid"}]})) == (["big-pickle","custom-free"], {"unknown_free_status":1})
    elif PLUGIN_NAME == "provider_openrouter_free":
        m=importlib.import_module("usr.plugins.provider_openrouter_free.helpers.filter")
        payload={"data":[{"id":"free","pricing":{"prompt":"0","completion":"0"},"supported_parameters":["tools"],"architecture":{"input_modalities":["text"],"output_modalities":["text"]},"expiration_date":None},{"id":"paid","pricing":{"prompt":"1","completion":"0"},"supported_parameters":["tools"],"architecture":{"input_modalities":["text"],"output_modalities":["text"]},"expiration_date":None}]}
        assert m.filter_models(payload) == (["free"], {"paid":1})
    elif PLUGIN_NAME == "provider_nvidia_build_free":
        catalog=importlib.import_module("usr.plugins.provider_nvidia_build_free.helpers.catalog"); state=importlib.import_module("usr.plugins.provider_nvidia_build_free.helpers.state"); probe=importlib.import_module("usr.plugins.provider_nvidia_build_free.helpers.probe")
        state_path=tmp_path/"state.json"; checked_path=tmp_path/"validated.json"
        checked_path.write_text(json.dumps({"models":["checked/live","checked/removed"]})+"\n", encoding="utf-8")
        cache=state.default_state(); state.mark_allowed(cache,"local/live",now=100); state.save_state(cache,state_path)
        async def fake_fetch_catalog(): return ({"data":[{"id":"checked/live"},{"id":"local/live"},{"id":"unvalidated/live"},{"id":"embedding-model"}]}, "ok")
        monkeypatch.setattr(state,"state_path",lambda: state_path); monkeypatch.setattr(catalog,"validated_catalog_path",lambda: checked_path); monkeypatch.setattr(catalog,"fetch_catalog",fake_fetch_catalog); monkeypatch.setattr(probe,"start_background_worker",lambda live_ids: False)
        response=asyncio.run(catalog.model_response())
        assert response["data"] == [{"id":"checked/live"},{"id":"local/live"}]
        assert response["meta"]["checked_in_validated_count"] == 2; assert response["meta"]["local_validated_count"] == 1
