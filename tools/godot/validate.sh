#!/usr/bin/env bash
# Import gate + content gate. Env: SCENE_PATH, TARGET_NODE, TARGET_GLB, TARGET_ANIM.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
# shellcheck source=/dev/null
source "$ROOT/tools/env.sh"
# shellcheck source=/dev/null
source "$ROOT/tools/godot/lib.sh"

if [[ $# -ne 1 ]]; then
  echo "usage: tools/godot/validate.sh <godot_dir>" >&2
  exit 2
fi
GODOT_DIR="$(godot_dir_abs "$1")"
LOGS="$(project_artifacts_logs "$GODOT_DIR")"
STAMP="$(date -u +%Y%m%dT%H%M%SZ)"
IMPORT_LOG="$LOGS/import_$STAMP.log"
CHECK_LOG="$LOGS/content_$STAMP.log"

stage_checks "$GODOT_DIR"
run_import_gate "$GODOT_DIR" "$IMPORT_LOG"

set +e
timeout 120 "$GODOT" --headless --path "$GODOT_DIR" \
  --script res://.pipeline/validate_project.gd 2>&1 | tee "$CHECK_LOG"
rc=${PIPESTATUS[0]}
set -e
echo "CONTENT_LOG=$CHECK_LOG"
exit "$rc"
