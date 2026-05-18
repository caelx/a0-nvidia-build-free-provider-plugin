from __future__ import annotations

import importlib.util
from pathlib import Path

from helpers.extension import Extension


class RenderProviderNvidiaBuildFree(Extension):
    def execute(self, **kwargs):
        plugin_dir = Path(__file__).resolve().parents[3]
        _load_provider_config(plugin_dir).render_model_provider_config(plugin_dir)


def _resolve_web_ui_port() -> int:
    return _load_provider_config(Path(__file__).resolve().parents[3]).resolve_web_ui_port()


def _load_provider_config(plugin_dir: Path):
    path = plugin_dir / "helpers" / "provider_config.py"
    spec = importlib.util.spec_from_file_location("_provider_config", path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Unable to load provider config helper from {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module
