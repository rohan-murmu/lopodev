#!/usr/bin/env bash
# Runtime gate: process real frames and assert observable state.
# Env: SCENE_PATH, TARGET_NODE, TARGET_ANIM, FRAMES, EXPECT_ROTATION,
#      EXPECT_MOVEMENT, EXPECT_ANIM_PLAYING.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
# shellcheck source=/dev/null
source "$ROOT/tools/env.sh"
# shellcheck source=/dev/null
source "$ROOT/tools/godot/lib.sh"

if [[ $# -ne 1 ]]; then
  echo "usage: tools/godot/smoke.sh <godot_dir>" >&2
  exit 2
fi
GODOT_DIR="$(godot_dir_abs "$1")"
LOGS="$(project_artifacts_logs "$GODOT_DIR")"
STAMP="$(date -u +%Y%m%dT%H%M%SZ)"
IMPORT_LOG="$LOGS/import_smoke_$STAMP.log"
SMOKE_LOG="$LOGS/runtime_$STAMP.log"

stage_checks "$GODOT_DIR"
run_import_gate "$GODOT_DIR" "$IMPORT_LOG"

set +e
timeout 120 "$GODOT" --headless --path "$GODOT_DIR" \
  --script res://.pipeline/runtime_smoke.gd 2>&1 | tee "$SMOKE_LOG"
rc=${PIPESTATUS[0]}
set -e
if grep -nE '(^| )ERROR:|SCRIPT ERROR:' "$SMOKE_LOG" >/dev/null 2>&1; then
  echo "RUNTIME_GATE=FAIL engine errors in $SMOKE_LOG" >&2
  grep -nE '(^| )ERROR:|SCRIPT ERROR:' "$SMOKE_LOG" >&2 || true
  exit 1
fi
echo "RUNTIME_LOG=$SMOKE_LOG"
exit "$rc"
