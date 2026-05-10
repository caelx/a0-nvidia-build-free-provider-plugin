#!/usr/bin/env bash
set -euo pipefail
root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
image="${AGENT_ZERO_IMAGE:-agent0ai/agent-zero:latest}"
repo="${PROVIDER_PLUGIN_REPO:-file:///plugin-src}"
plugin_name="provider_nvidia_build_free"
provider_id="nvidia_build_free"
mkdir -p "$root/artifacts"
docker run --rm --shm-size=2g -e PROVIDER_PLUGIN_REPO="$repo" -v "$root:/plugin-src:ro" -v "$root/artifacts:/artifacts" "$image" bash -lc '
  set -euo pipefail
  . /ins/setup_venv.sh local
  cd /a0
  python -c "import json,sys; sys.path.insert(0, '''/git/agent-zero'''); from plugins._plugin_installer.helpers.install import install_from_git; from helpers import plugins; repo='''$repo'''; plugin_name='''$plugin_name'''; existing=plugins.find_plugin_dir(plugin_name); result={"success": True, "path": existing, "already_installed": True} if existing else install_from_git(repo, plugin_name=plugin_name); print(json.dumps(result, indent=2, sort_keys=True)); raise SystemExit(0 if result.get('''success''') else 1)"
  plugin_dir="$(python -c "import sys; sys.path.insert(0, '''/git/agent-zero'''); from helpers import plugins; print(plugins.find_plugin_dir('''$plugin_name''') or '''''')")"
  test -n "$plugin_dir"
  cd "$plugin_dir"
  test -f plugin.yaml
  test -f conf/model_providers.yaml
  test -f webui/config.html
  grep -q "name: $plugin_name" plugin.yaml
  grep -q "$provider_id:" conf/model_providers.yaml
  python ci/run_installed_smoke.py > /artifacts/installed-smoke.json
'
