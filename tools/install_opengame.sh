#!/usr/bin/env bash
# Install OpenGame into an existing workspace without touching user files.
# usage: tools/install_opengame.sh [workspace] [--dry-run]
set -euo pipefail

TOOLKIT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
WORKSPACE="."
DRY_RUN=0
for arg in "$@"; do
  case "$arg" in
    --dry-run) DRY_RUN=1 ;;
    -h|--help) sed -n '2,3p' "$0"; exit 0 ;;
    *) WORKSPACE="$arg" ;;
  esac
done
WORKSPACE="$(realpath -m "$WORKSPACE")"
if [[ ! -d "$WORKSPACE" ]]; then
  echo "ERROR: workspace does not exist: $WORKSPACE" >&2
  exit 2
fi

warnings=0
created=0
skipped=0
link_one() {
  local source="$1" target="$2" label="$3"
  if [[ -e "$target" || -L "$target" ]]; then
    local current
    current="$(readlink -f "$target" 2>/dev/null || true)"
    if [[ "$current" == "$(readlink -f "$source")" ]]; then
      echo "ALREADY_LINKED=$target"
      skipped=$((skipped + 1))
    else
      echo "WARN_EXISTS=$target (left unchanged; merge manually if needed)" >&2
      warnings=$((warnings + 1))
    fi
    return
  fi
  echo "LINK=$target -> $source"
  [[ "$DRY_RUN" -eq 1 ]] || ln -s "$source" "$target"
  created=$((created + 1))
}

for pair in \
  "tools:tools" \
  "templates:templates" \
  "AGENTS.md:AGENTS.md" \
  ".gitignore:.gitignore" \
  ".opencode:.opencode"; do
  source="${pair%%:*}"
  target="${pair##*:}"
  link_one "$TOOLKIT/$source" "$WORKSPACE/$target" "$target"
done

PROJECTS="$WORKSPACE/projects"
if [[ -d "$PROJECTS" ]]; then
  echo "ALREADY_EXISTS=$PROJECTS"
else
  echo "MKDIR=$PROJECTS"
  [[ "$DRY_RUN" -eq 1 ]] || mkdir -p "$PROJECTS"
  created=$((created + 1))
fi

CONFIG="$WORKSPACE/opencode.json"
if [[ -e "$CONFIG" ]]; then
  if python3 - "$CONFIG" <<'PY' >/dev/null 2>&1
import json, sys
with open(sys.argv[1], encoding="utf-8") as handle:
    raise SystemExit(0 if json.load(handle).get("default_agent") == "opengame" else 1)
PY
  then
    echo "ALREADY_CONFIGURED=$CONFIG"
    skipped=$((skipped + 1))
  else
    echo "WARN_EXISTS=$CONFIG (not modified; default_agent is not opengame)" >&2
    warnings=$((warnings + 1))
  fi
else
  echo "WRITE=$CONFIG"
  if [[ "$DRY_RUN" -eq 0 ]]; then
    python3 - "$CONFIG" "$TOOLKIT" <<'PY'
import json
import sys
from pathlib import Path

path, toolkit = sys.argv[1], sys.argv[2]
config = {
    "$schema": "https://opencode.ai/config.json",
    "default_agent": "opengame",
    "mcp": {
        "blender": {
            "type": "local",
            "command": ["uvx", "mcp-for-blender"],
            "enabled": True,
            "environment": {
                "BLENDER_HOST": "localhost",
                "BLENDER_PORT": "9876",
                "DISABLE_TELEMETRY": "true",
            },
            "timeout": 60000,
        }
    },
}
Path(path).write_text(json.dumps(config, indent=2) + "\n", encoding="utf-8")
PY
  fi
  created=$((created + 1))
fi

echo "INSTALL_WORKSPACE=$WORKSPACE"
echo "INSTALL_DRY_RUN=$DRY_RUN"
echo "INSTALL_CREATED=$created"
echo "INSTALL_SKIPPED=$skipped"
echo "INSTALL_WARNINGS=$warnings"
echo "INSTALL_NEXT=OpenCode in this workspace; verify agents with: opencode agent list"
