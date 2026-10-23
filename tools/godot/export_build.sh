#!/usr/bin/env bash
# Build gate: import, export a Linux release, verify it, and run it headless.
# usage: tools/godot/export_build.sh <godot_dir> [preset] [out_binary]
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
# shellcheck source=/dev/null
source "$ROOT/tools/env.sh"
# shellcheck source=/dev/null
source "$ROOT/tools/godot/lib.sh"

if [[ $# -lt 1 || $# -gt 3 ]]; then
  echo "usage: tools/godot/export_build.sh <godot_dir> [preset] [out_binary]" >&2
  exit 2
fi

GODOT_DIR="$(godot_dir_abs "$1")"
PRESET="${2:-Linux}"
PROJECT_ROOT="$(dirname "$GODOT_DIR")"
if [[ $# -ge 3 ]]; then
  OUT="$(realpath -m "$3")"
else
  OUT="$PROJECT_ROOT/build/$(basename "$PROJECT_ROOT").x86_64"
fi
mkdir -p "$(dirname "$OUT")"
LOGS="$(project_artifacts_logs "$GODOT_DIR")"
STAMP="$(date -u +%Y%m%dT%H%M%SZ)"
IMPORT_LOG="$LOGS/import_build_$STAMP.log"
EXPORT_LOG="$LOGS/export_$STAMP.log"
RUN_LOG="$LOGS/exported_run_$STAMP.log"

if [[ ! -f "$GODOT_DIR/export_presets.cfg" ]]; then
  echo "ERROR: export_presets.cfg missing in $GODOT_DIR" >&2
  exit 2
fi
if ! grep -q "^name=\"$PRESET\"" "$GODOT_DIR/export_presets.cfg"; then
  echo "ERROR: export preset '$PRESET' not found" >&2
  exit 2
fi

run_import_gate "$GODOT_DIR" "$IMPORT_LOG"

set +e
timeout 300 "$GODOT" --headless --path "$GODOT_DIR" \
  --export-release "$PRESET" "$OUT" >"$EXPORT_LOG" 2>&1
export_rc=$?
set -e
if [[ $export_rc -ne 0 ]]; then
  echo "EXPORT_GATE=FAIL export exit=$export_rc log=$EXPORT_LOG" >&2
  tail -n 50 "$EXPORT_LOG" >&2 || true
  exit "$export_rc"
fi
if [[ ! -s "$OUT" ]]; then
  echo "EXPORT_GATE=FAIL binary missing or empty: $OUT" >&2
  exit 1
fi
BYTES="$(stat -c %s "$OUT")"
if [[ "$BYTES" -lt 5000000 ]]; then
  echo "EXPORT_GATE=FAIL binary implausibly small: $BYTES bytes" >&2
  exit 1
fi

set +e
timeout 90 "$OUT" --headless --quit-after 15 >"$RUN_LOG" 2>&1
run_rc=$?
set -e
if [[ $run_rc -ne 0 ]]; then
  echo "EXPORT_GATE=FAIL exported binary exit=$run_rc log=$RUN_LOG" >&2
  tail -n 50 "$RUN_LOG" >&2 || true
  exit "$run_rc"
fi

echo "EXPORT_GATE=PASS binary=$OUT bytes=$BYTES log=$EXPORT_LOG run_log=$RUN_LOG"
