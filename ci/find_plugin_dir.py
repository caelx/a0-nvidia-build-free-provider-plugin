#!/usr/bin/env python3
from __future__ import annotations

import sys

PLUGIN_NAME = "provider_nvidia_build_free"


def main() -> int:
    sys.path.insert(0, "/git/agent-zero")
    from helpers import plugins

    path = plugins.find_plugin_dir(PLUGIN_NAME) or ""
    print(path)
    return 0 if path else 1


if __name__ == "__main__":
    raise SystemExit(main())
