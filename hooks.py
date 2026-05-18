from __future__ import annotations

import importlib.util
from pathlib import Path


def install(*args, **kwargs) -> bool:
    _load_provider_config().render_model_provider_config(Path(__file__).resolve().parent)
    return True


def pre_update(*args, **kwargs) -> bool:
    return install(**kwargs)


def _load_provider_config():
    path = Path(__file__).resolve().parent / "helpers" / "provider_config.py"
    spec = importlib.util.spec_from_file_location("_provider_config", path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Unable to load provider config helper from {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module
