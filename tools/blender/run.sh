#!/usr/bin/env bash
# Run a Blender Python script headlessly with the pinned Blender.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
# shellcheck source=/dev/null
source "$ROOT/tools/env.sh"

if [[ $# -lt 1 ]]; then
  echo "usage: tools/blender/run.sh <script.py> [args...]" >&2
  exit 2
fi
if [[ -z "$BLENDER" || ! -x "$BLENDER" ]]; then
  echo "ERROR: Blender not found. Set BLENDER or install Blender." >&2
  exit 127
fi

script="$1"
shift
if [[ "$script" != /* ]]; then
  if [[ -f "$ROOT/tools/blender/$script" ]]; then
    script="$ROOT/tools/blender/$script"
  elif [[ -f "$ROOT/$script" ]]; then
    script="$ROOT/$script"
  fi
fi
if [[ ! -f "$script" ]]; then
  echo "ERROR: script not found: $script" >&2
  exit 2
fi

exec "$BLENDER" -b --factory-startup --python "$script" -- "$@"
