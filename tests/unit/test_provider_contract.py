from __future__ import annotations
import asyncio, importlib, importlib.util, json, sys, types
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2]
PLUGIN_NAME="provider_nvidia_build_free"
PROVIDER_ID="nvidia_build_free"
ENV_VAR="NVIDIA_BUILD_FREE_API_KEY"
HAS_API=True
MIGRATION_FILE=ROOT/"extensions"/"python"/"startup_migration"/"_10_render_provider_nvidia_build_free.py"
EXPECTED_ENDPOINT=f"http://127.0.0.1:80/api/plugins/{PLUGIN_NAME}/models"
TEMPLATE_ENDPOINT=f"http://127.0.0.1:${{WEB_UI_PORT}}/api/plugins/{PLUGIN_NAME}/models"
def install_package_alias() -> None:
    sys.path.insert(0, str(ROOT))
    usr=sys.modules.setdefault("usr", types.ModuleType("usr")); usr.__path__=[]
    plugins=sys.modules.setdefault("usr.plugins", types.ModuleType("usr.plugins")); plugins.__path__=[]
    provider=sys.modules.setdefault(f"usr.plugins.{PLUGIN_NAME}", types.ModuleType(f"usr.plugins.{PLUGIN_NAME}")); provider.__path__=[str(ROOT)]
def test_root_plugin_metadata_is_installable():
    assert (ROOT/"plugin.yaml").is_file(); assert (ROOT/"conf"/"model_providers.yaml").is_file(); assert (ROOT/"conf"/"model_providers.yaml.template").is_file(); assert (ROOT/"webui"/"config.html").is_file()
    assert f"name: {PLUGIN_NAME}" in (ROOT/"plugin.yaml").read_text(encoding="utf-8")
    model_config=(ROOT/"conf"/"model_providers.yaml").read_text(encoding="utf-8")
    template_config=(ROOT/"conf"/"model_providers.yaml.template").read_text(encoding="utf-8")
    assert PROVIDER_ID + ":" in model_config
    assert EXPECTED_ENDPOINT in model_config
    assert "127.0.0.1:5000" not in model_config
    assert TEMPLATE_ENDPOINT in template_config
    assert MIGRATION_FILE.is_file()
    assert not (ROOT/"extensions"/"python"/"startup_migration"/"_10_render_model_provider.py").exists()
def test_model_provider_port_resolution(monkeypatch):
    install_extension_stub()
    migration=load_migration()
    monkeypatch.delenv("WEB_UI_PORT", raising=False); monkeypatch.delenv("PORT", raising=False)
    assert migration._resolve_web_ui_port() == 80
    monkeypatch.setenv("WEB_UI_PORT", "8080")
    assert migration._resolve_web_ui_port() == 8080
    monkeypatch.setenv("WEB_UI_PORT", "invalid"); monkeypatch.setenv("PORT", "9000")
    assert migration._resolve_web_ui_port() == 9000
    monkeypatch.delenv("WEB_UI_PORT", raising=False); monkeypatch.delenv("PORT", raising=False)
    runtime=types.ModuleType("helpers.runtime"); runtime.get_web_ui_port=lambda: 7000
    sys.modules["helpers"].runtime=runtime; sys.modules["helpers.runtime"]=runtime
    assert migration._resolve_web_ui_port() == 7000
def install_extension_stub() -> None:
    helpers=sys.modules.setdefault("helpers", types.ModuleType("helpers")); helpers.__path__=[]
    extension=types.ModuleType("helpers.extension")
    class Extension:
        def __init__(self, agent=None, **kwargs):
            self.agent=agent
    extension.Extension=Extension
    helpers.extension=extension; sys.modules["helpers.extension"]=extension
def load_migration():
    spec=importlib.util.spec_from_file_location("provider_port_migration", MIGRATION_FILE)
    assert spec and spec.loader
    module=importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module
def load_catalog_refresh():
    spec=importlib.util.spec_from_file_location("update_validated_catalog", ROOT/"ci"/"update_validated_catalog.py")
    assert spec and spec.loader
    module=importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module
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
def test_nvidia_catalog_retains_previous_model_until_failure_limit():
    refresh=load_catalog_refresh()
    previous={"models":["model/a"],"failure_streaks":{}}
    result=refresh.merge_probe_results(["model/a"], [("model/a", False, "timeout")], previous)
    assert result["catalog"]["models"] == ["model/a"]
    assert result["catalog"]["accepted_models"] == ["model/a"]
    assert result["catalog"]["failure_streaks"] == {"model/a": 1}
    assert result["catalog"]["last_rejection_reasons"]["model/a"] == "timeout"
    assert result["catalog"]["rejected_models"]["model/a"]["failure_mode"] == "timeout"
    assert result["report"]["retained_models"]["model/a"]["failure_streak"] == 1
    assert result["report"]["rejected_models"]["model/a"]["final_status"] == "retained"
def test_nvidia_catalog_removes_after_failure_limit():
    refresh=load_catalog_refresh()
    previous={"models":["model/a"],"failure_streaks":{"model/a":2}}
    result=refresh.merge_probe_results(["model/a"], [("model/a", False, "no_tool_call")], previous)
    assert result["catalog"]["models"] == []
    assert result["catalog"]["accepted_models"] == []
    assert result["catalog"]["failure_streaks"] == {}
    assert result["report"]["removed_models"]["model/a"]["failure_streak"] == 3
    assert result["report"]["rejected_models"]["model/a"]["final_status"] == "removed"
def test_nvidia_catalog_clears_failure_streak_on_pass():
    refresh=load_catalog_refresh()
    previous={"models":["model/a"],"failure_streaks":{"model/a":2},"last_rejection_reasons":{"model/a":"timeout"}}
    result=refresh.merge_probe_results(["model/a"], [("model/a", True, "ok")], previous)
    assert result["catalog"]["models"] == ["model/a"]
    assert result["catalog"]["failure_streaks"] == {}
    assert "model/a" not in result["catalog"]["last_rejection_reasons"]
def test_nvidia_catalog_removes_missing_live_model_immediately():
    refresh=load_catalog_refresh()
    result=refresh.merge_probe_results([], [], {"models":["model/a"],"failure_streaks":{"model/a":1}})
    assert result["catalog"]["models"] == []
    assert result["report"]["removed_models"]["model/a"]["reason"] == "not_in_live_catalog"
def test_nvidia_catalog_rejects_new_failed_model_with_reason():
    refresh=load_catalog_refresh()
    result=refresh.merge_probe_results(["model/a"], [("model/a", False, "http_422")], {"models":[]})
    assert result["catalog"]["models"] == []
    assert result["report"]["rejected_models"]["model/a"]["reason"] == "http_422"
    assert result["report"]["rejected_models"]["model/a"]["failure_mode"] == "http_422"
    assert result["report"]["rejected_models"]["model/a"]["previously_validated"] is False
def test_nvidia_catalog_reports_expected_model_failure_reason():
    refresh=load_catalog_refresh()
    model="deepseek-ai/deepseek-v4-flash"
    result=refresh.merge_probe_results([model], [(model, False, "no_tool_call")], {"models":[]})
    assert result["report"]["expected_model_failures"] == {model: "no_tool_call"}
def test_nvidia_probe_retry_policy():
    refresh=load_catalog_refresh()
    assert refresh.retry_probe("timeout") is True
    assert refresh.retry_probe("no_tool_call") is True
    assert refresh.retry_probe("http_500") is True
    assert refresh.retry_probe("http_404") is False
    assert refresh.retry_probe("http_422") is False
def test_nvidia_probe_chooses_stable_failure_reason():
    refresh=load_catalog_refresh()
    assert refresh.choose_failure_reason(["timeout","no_tool_call"]) == "no_tool_call"
    assert refresh.choose_failure_reason(["timeout","http_404"]) == "http_404"
    assert refresh.choose_failure_reason(["request_failed","timeout"]) == "timeout"
def test_nvidia_runtime_meta_exposes_failed_models(monkeypatch, tmp_path):
    install_package_alias()
    catalog=importlib.import_module("usr.plugins.provider_nvidia_build_free.helpers.catalog"); state=importlib.import_module("usr.plugins.provider_nvidia_build_free.helpers.state"); probe=importlib.import_module("usr.plugins.provider_nvidia_build_free.helpers.probe")
    state_path=tmp_path/"state.json"; checked_path=tmp_path/"validated.json"
    checked_path.write_text(json.dumps({"models":[]})+"\n", encoding="utf-8")
    cache=state.default_state(); state.mark_failed(cache,"model/a","timeout",now=100); state.save_state(cache,state_path)
    async def fake_fetch_catalog(): return ({"data":[{"id":"model/a"}]}, "ok")
    monkeypatch.setattr(state,"state_path",lambda: state_path); monkeypatch.setattr(catalog,"validated_catalog_path",lambda: checked_path); monkeypatch.setattr(catalog,"fetch_catalog",fake_fetch_catalog); monkeypatch.setattr(probe,"start_background_worker",lambda live_ids: False)
    response=asyncio.run(catalog.model_response())
    assert response["meta"]["failed_models"]["model/a"]["reason"] == "timeout"
    assert response["meta"]["failed_models"]["model/a"]["next_retry_at"] == 21700
