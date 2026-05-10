#!/usr/bin/env python3
from __future__ import annotations

import json
import os
import sys

PLUGIN_NAME = "provider_nvidia_build_free"


def main() -> int:
    repo = os.environ.get("PROVIDER_PLUGIN_REPO", "file:///plugin-src")
    sys.path.insert(0, "/git/agent-zero")
    from plugins._plugin_installer.helpers.install import install_from_git
    from helpers import plugins

    existing = plugins.find_plugin_dir(PLUGIN_NAME)
    if existing:
        print(json.dumps({"success": True, "already_installed": True, "path": existing}, indent=2, sort_keys=True))
        return 0
    result = install_from_git(repo, plugin_name=PLUGIN_NAME)
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0 if result.get("success") else 1


if __name__ == "__main__":
    raise SystemExit(main())
