from __future__ import annotations

import importlib
import os
from pathlib import Path


def render_model_provider_config(plugin_dir: Path | None = None) -> bool:
    root = plugin_dir or Path(__file__).resolve().parents[1]
    template = root / "conf" / "model_providers.yaml.template"
    target = root / "conf" / "model_providers.yaml"
    rendered = template.read_text(encoding="utf-8").replace("${WEB_UI_PORT}", str(resolve_web_ui_port()))
    if target.exists() and target.read_text(encoding="utf-8") == rendered:
        return False
    target.write_text(rendered, encoding="utf-8")
    return True


def resolve_web_ui_port() -> int:
    for name in ("WEB_UI_PORT", "PORT"):
        raw = os.environ.get(name, "")
        if raw.isdigit():
            return int(raw)
    try:
        runtime = importlib.import_module("helpers.runtime")
        getter = getattr(runtime, "get_web_ui_port", None)
        if callable(getter):
            return int(getter())
    except Exception:
        pass
    return 80
