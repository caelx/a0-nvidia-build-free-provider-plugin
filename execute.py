#!/usr/bin/env python3
from __future__ import annotations

import argparse
import importlib.util
import json
import sys
from contextlib import contextmanager
from pathlib import Path
from typing import Any


PLUGIN_NAME = "provider_nvidia_build_free"
PROVIDER_ID = "nvidia_build_free"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=f"{PLUGIN_NAME} lifecycle")
    parser.add_argument(
        "command",
        nargs="?",
        default="reconcile",
        choices=[
            "install",
            "setup",
            "repair",
            "update",
            "uninstall",
            "enable",
            "disable",
            "status",
            "reconcile",
            "run",
        ],
    )
    parser.add_argument("--json", action="store_true", dest="json_output")
    parser.add_argument("--noninteractive", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--skip-system-deps", action="store_true", help=argparse.SUPPRESS)
    args = parser.parse_args(argv)

    rendered = False
    if args.command in {"install", "setup", "repair", "update", "enable", "reconcile", "run"}:
        rendered = render_provider_config()
    if args.command == "enable":
        set_enabled(True)
    elif args.command in {"disable", "uninstall"}:
        set_enabled(False)
    if args.command != "status":
        reload_provider_cache()

    payload = status()
    payload["command"] = "reconcile" if args.command == "run" else args.command
    payload["provider_config_rendered"] = rendered
    payload["ok"] = status_ok(payload)
    print(json.dumps(payload, indent=2, sort_keys=True) if args.json_output else format_status(payload))
    return 0 if payload["ok"] else 1


def status() -> dict[str, Any]:
    root = Path(__file__).resolve().parent
    ensure_agent_zero_path(root)
    with without_local_helpers(root):
        from helpers import plugins

        plugin_dir = plugins.find_plugin_dir(PLUGIN_NAME) or ""
        toggle_state = plugins.get_toggle_state(PLUGIN_NAME) if plugin_dir else "disabled"
    provider_registered = provider_is_registered(root)
    provider_config_present = config_contains_provider(Path(plugin_dir) if plugin_dir else root)
    enabled = bool(plugin_dir) and toggle_state != "disabled"
    return {
        "plugin_name": PLUGIN_NAME,
        "provider_id": PROVIDER_ID,
        "installed": bool(plugin_dir),
        "plugin_dir": plugin_dir,
        "toggle_state": toggle_state,
        "enabled": enabled,
        "provider_config_present": provider_config_present,
        "provider_registered": provider_registered,
    }


def status_ok(payload: dict[str, Any]) -> bool:
    if not payload.get("installed"):
        return False
    if not payload.get("provider_config_present"):
        return False
    if payload.get("enabled") and not payload.get("provider_registered"):
        return False
    return True


def set_enabled(enabled: bool) -> None:
    root = Path(__file__).resolve().parent
    ensure_agent_zero_path(root)
    with without_local_helpers(root):
        from helpers import plugins

        plugins.toggle_plugin(PLUGIN_NAME, enabled)


def provider_is_registered(root: Path) -> bool:
    ensure_agent_zero_path(root)
    with without_local_helpers(root):
        from helpers.providers import ProviderManager

        provider_ids = {
            provider_id
            for provider in ProviderManager.get_instance().get_raw_providers("chat")
            for provider_id in (provider.get("id") or provider.get("value"),)
            if provider_id
        }
    return PROVIDER_ID in provider_ids


def reload_provider_cache() -> None:
    root = Path(__file__).resolve().parent
    ensure_agent_zero_path(root)
    with without_local_helpers(root):
        try:
            from helpers import providers

            reload_providers = getattr(providers, "reload_providers", None)
            if callable(reload_providers):
                reload_providers()
                return
            ProviderManager = providers.ProviderManager

            manager = ProviderManager.get_instance()
            for name in ("reload", "refresh", "load"):
                method = getattr(manager, name, None)
                if callable(method):
                    method()
                    return
            for name in ("_instance", "instance"):
                if hasattr(ProviderManager, name):
                    setattr(ProviderManager, name, None)
        except Exception:
            return


def render_provider_config() -> bool:
    helper = Path(__file__).resolve().parent / "helpers" / "provider_config.py"
    if not helper.is_file():
        return False
    spec = importlib.util.spec_from_file_location("_provider_config", helper)
    if spec is None or spec.loader is None:
        return False
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return bool(module.render_model_provider_config(Path(__file__).resolve().parent))


def config_contains_provider(plugin_dir: Path) -> bool:
    config = plugin_dir / "conf" / "model_providers.yaml"
    if not config.is_file():
        return False
    return f"{PROVIDER_ID}:" in config.read_text(encoding="utf-8")


def ensure_agent_zero_path(root: Path) -> None:
    for candidate in (root, *root.parents, Path("/a0")):
        if (candidate / "helpers" / "plugins.py").is_file():
            candidate_str = str(candidate)
            if candidate_str not in sys.path:
                sys.path.insert(0, candidate_str)
            return


@contextmanager
def without_local_helpers(root: Path):
    previous_path = list(sys.path)
    previous_helpers = {
        name: module
        for name, module in sys.modules.items()
        if name == "helpers" or name.startswith("helpers.")
    }
    for name, module in list(sys.modules.items()):
        if name != "helpers" and not name.startswith("helpers."):
            continue
        module_file_raw = getattr(module, "__file__", "") or ""
        if not module_file_raw:
            continue
        try:
            if Path(module_file_raw).resolve().is_relative_to(root):
                sys.modules.pop(name, None)
        except Exception:
            pass
    sys.path[:] = [entry for entry in sys.path if not _is_root_entry(entry, root)]
    try:
        yield
    finally:
        sys.path[:] = previous_path
        for name in list(sys.modules):
            if name == "helpers" or name.startswith("helpers."):
                sys.modules.pop(name, None)
        sys.modules.update(previous_helpers)


def _is_root_entry(entry: str, root: Path) -> bool:
    try:
        return Path(entry or ".").resolve() == root
    except Exception:
        return entry == str(root)


def format_status(payload: dict[str, Any]) -> str:
    return "\n".join(
        [
            f"{PLUGIN_NAME} lifecycle",
            f"Installed: {payload['installed']}",
            f"Toggle: {payload['toggle_state']}",
            f"Provider config: {payload['provider_config_present']}",
            f"Provider registered: {payload['provider_registered']}",
            f"OK: {payload['ok']}",
        ]
    )


if __name__ == "__main__":
    raise SystemExit(main())
