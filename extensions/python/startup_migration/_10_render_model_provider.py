from __future__ import annotations

import os
from pathlib import Path

from helpers.extension import Extension


class RenderModelProvider(Extension):
    def execute(self, **kwargs):
        plugin_dir = Path(__file__).resolve().parents[3]
        template = plugin_dir / "conf" / "model_providers.yaml.template"
        target = plugin_dir / "conf" / "model_providers.yaml"
        port = _resolve_web_ui_port()
        rendered = template.read_text(encoding="utf-8").replace("${WEB_UI_PORT}", str(port))
        if not target.exists() or target.read_text(encoding="utf-8") != rendered:
            target.write_text(rendered, encoding="utf-8")


def _resolve_web_ui_port() -> int:
    for name in ("WEB_UI_PORT", "PORT"):
        raw = os.environ.get(name, "")
        if raw.isdigit():
            return int(raw)
    try:
        from helpers import runtime

        getter = getattr(runtime, "get_web_ui_port", None)
        if callable(getter):
            return int(getter())
    except Exception:
        pass
    return 5000
