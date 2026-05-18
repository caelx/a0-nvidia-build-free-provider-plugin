from __future__ import annotations

import importlib.util
import json
import sys
import tomllib
import types
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
PLUGIN_NAME = "provider_nvidia_build_free"
PROVIDER_ID = "nvidia_build_free"


def load_execute():
    spec = importlib.util.spec_from_file_location("provider_execute", ROOT / "execute.py")
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_plugin_and_package_versions_match():
    plugin_version = _yaml_value(ROOT / "plugin.yaml", "version")
    pyproject = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    assert pyproject["project"]["version"] == plugin_version


def test_enabled_provider_requires_provider_manager_registration(monkeypatch):
    execute = load_execute()
    install_agent_zero_stubs(monkeypatch, toggle_state="enabled", provider_ids=set())
    payload = execute.status()
    payload["ok"] = execute.status_ok(payload)
    assert payload["installed"] is True
    assert payload["enabled"] is True
    assert payload["provider_config_present"] is True
    assert payload["provider_registered"] is False
    assert payload["ok"] is False


def test_disabled_provider_does_not_require_registration(monkeypatch):
    execute = load_execute()
    install_agent_zero_stubs(monkeypatch, toggle_state="disabled", provider_ids=set())
    payload = execute.status()
    payload["ok"] = execute.status_ok(payload)
    assert payload["enabled"] is False
    assert payload["provider_registered"] is False
    assert payload["ok"] is True


def test_enable_reloads_provider_manager(monkeypatch, capsys):
    execute = load_execute()
    reloads: list[str] = []
    install_agent_zero_stubs(
        monkeypatch,
        toggle_state="disabled",
        provider_ids={PROVIDER_ID},
        reloads=reloads,
    )
    assert execute.main(["enable", "--json"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["enabled"] is True
    assert payload["provider_registered"] is True
    assert payload["ok"] is True
    assert reloads == ["reload_providers"]


def test_setup_alias_renders_and_reports_status(monkeypatch, capsys):
    execute = load_execute()
    reloads: list[str] = []
    install_agent_zero_stubs(
        monkeypatch,
        toggle_state="enabled",
        provider_ids={PROVIDER_ID},
        reloads=reloads,
    )
    assert execute.main(["setup", "--noninteractive", "--json"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["command"] == "setup"
    assert payload["ok"] is True
    assert reloads == ["reload_providers"]


def test_provider_registration_accepts_value_field(monkeypatch):
    execute = load_execute()
    install_agent_zero_stubs(
        monkeypatch,
        toggle_state="enabled",
        provider_ids=set(),
        provider_entries=[{"value": PROVIDER_ID}],
    )
    payload = execute.status()
    assert payload["provider_registered"] is True


def test_status_json_is_structured_without_agent_zero_helpers(monkeypatch, capsys):
    execute = load_execute()
    for name in list(sys.modules):
        if name == "helpers" or name.startswith("helpers."):
            monkeypatch.delitem(sys.modules, name, raising=False)
    monkeypatch.setattr(sys, "path", [entry for entry in sys.path if "agent-zero" not in entry])

    assert execute.main(["status", "--json"]) == 1
    payload = json.loads(capsys.readouterr().out)
    assert payload["installed"] is False
    assert payload["toggle_state"] == "disabled"
    assert payload["provider_registered"] is False
    assert payload["ok"] is False


def test_disable_succeeds_for_missing_config(monkeypatch, capsys):
    execute = load_execute()
    reloads: list[str] = []
    install_agent_zero_stubs(
        monkeypatch,
        toggle_state="enabled",
        provider_ids=set(),
        reloads=reloads,
        plugin_dir="",
    )

    assert execute.main(["disable", "--json"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["installed"] is False
    assert payload["provider_config_present"] is True
    assert payload["ok"] is True


def test_uninstall_is_idempotent_without_agent_zero_helpers(monkeypatch, capsys):
    execute = load_execute()
    for name in list(sys.modules):
        if name == "helpers" or name.startswith("helpers."):
            monkeypatch.delitem(sys.modules, name, raising=False)
    monkeypatch.setattr(sys, "path", [entry for entry in sys.path if "agent-zero" not in entry])

    assert execute.main(["uninstall", "--json"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["installed"] is False
    assert payload["ok"] is True


def test_provider_config_renderer_uses_current_web_ui_port(monkeypatch, tmp_path):
    helper_path = ROOT / "helpers" / "provider_config.py"
    if not helper_path.is_file():
        return
    spec = importlib.util.spec_from_file_location("provider_config", helper_path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    conf = tmp_path / "conf"
    conf.mkdir()
    (conf / "model_providers.yaml.template").write_text(
        f"{PROVIDER_ID}:\n  endpoint_url: http://127.0.0.1:${{WEB_UI_PORT}}/models\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("WEB_UI_PORT", "8123")
    assert module.render_model_provider_config(tmp_path) is True
    assert "127.0.0.1:8123" in (conf / "model_providers.yaml").read_text(encoding="utf-8")
    assert module.render_model_provider_config(tmp_path) is False


def install_agent_zero_stubs(
    monkeypatch,
    *,
    toggle_state: str,
    provider_ids: set[str],
    reloads: list[str] | None = None,
    provider_entries: list[dict[str, str]] | None = None,
    plugin_dir: str | None = None,
) -> None:
    state = {"toggle": toggle_state}
    helpers = types.ModuleType("helpers")
    helpers.__path__ = []
    plugins = types.ModuleType("helpers.plugins")
    plugins.find_plugin_dir = lambda name: (str(ROOT) if plugin_dir is None else plugin_dir) if name == PLUGIN_NAME else ""
    plugins.get_toggle_state = lambda name: state["toggle"]

    def toggle_plugin(name: str, enabled: bool) -> None:
        assert name == PLUGIN_NAME
        state["toggle"] = "enabled" if enabled else "disabled"

    plugins.toggle_plugin = toggle_plugin
    providers = types.ModuleType("helpers.providers")

    class Manager:
        def get_raw_providers(self, kind: str):
            assert kind == "chat"
            if provider_entries is not None:
                return provider_entries
            return [{"id": provider_id} for provider_id in sorted(provider_ids)]

        def reload(self) -> None:
            if reloads is not None:
                reloads.append("reload")

    class ProviderManager:
        _manager = Manager()

        @classmethod
        def get_instance(cls):
            return cls._manager

    providers.ProviderManager = ProviderManager
    providers.reload_providers = lambda: reloads.append("reload_providers") if reloads is not None else None
    helpers.plugins = plugins
    helpers.providers = providers
    monkeypatch.setitem(sys.modules, "helpers", helpers)
    monkeypatch.setitem(sys.modules, "helpers.plugins", plugins)
    monkeypatch.setitem(sys.modules, "helpers.providers", providers)


def _yaml_value(path: Path, key: str) -> str:
    prefix = f"{key}:"
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.startswith(prefix):
            return line.split(":", 1)[1].strip().strip('"').strip("'")
    raise AssertionError(f"{key} not found in {path}")
