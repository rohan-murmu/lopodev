#!/usr/bin/env bash
# Visual gate: launch graphically, render real frames, save and analyze a PNG.
# usage: tools/godot/screenshot.sh <godot_dir> <out.png>
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
# shellcheck source=/dev/null
source "$ROOT/tools/env.sh"
# shellcheck source=/dev/null
source "$ROOT/tools/godot/lib.sh"

if [[ $# -ne 2 ]]; then
  echo "usage: tools/godot/screenshot.sh <godot_dir> <out.png>" >&2
  exit 2
fi
if [[ -z "${DISPLAY:-}" ]]; then
  echo "ERROR: no DISPLAY; graphical visual gate cannot run" >&2
  exit 3
fi

GODOT_DIR="$(godot_dir_abs "$1")"
OUT="$(realpath -m "$2")"
mkdir -p "$(dirname "$OUT")"
LOGS="$(project_artifacts_logs "$GODOT_DIR")"
STAMP="$(date -u +%Y%m%dT%H%M%SZ)"
IMPORT_LOG="$LOGS/import_visual_$STAMP.log"
SHOT_LOG="$LOGS/screenshot_$STAMP.log"

stage_checks "$GODOT_DIR"
run_import_gate "$GODOT_DIR" "$IMPORT_LOG"

set +e
DISPLAY="$DISPLAY" SCREENSHOT_PATH="$OUT" \
  SCREENSHOT_FRAMES="${SCREENSHOT_FRAMES:-20}" \
  timeout 120 "$GODOT" --path "$GODOT_DIR" --resolution "${SCREENSHOT_RESOLUTION:-1280x720}" \
  --script res://.pipeline/screenshot.gd 2>&1 | tee "$SHOT_LOG"
rc=${PIPESTATUS[0]}
set -e

if [[ $rc -ne 0 || ! -s "$OUT" ]]; then
  echo "SCREENSHOT_GATE=FAIL out=$OUT log=$SHOT_LOG" >&2
  exit 1
fi
if command -v identify >/dev/null 2>&1; then
  identify "$OUT" | tee -a "$SHOT_LOG"
fi
echo "SCREENSHOT_GATE=PASS out=$OUT log=$SHOT_LOG"
