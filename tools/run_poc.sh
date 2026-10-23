#!/usr/bin/env bash
# Re-run the complete crate PoC and record real evidence.
# Usage: tools/run_poc.sh [--regenerate]
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
# shellcheck source=/dev/null
source "$ROOT/tools/env.sh"

REGENERATE=0
if [[ "${1:-}" == "--regenerate" ]]; then
  REGENERATE=1
elif [[ $# -gt 0 ]]; then
  echo "usage: tools/run_poc.sh [--regenerate]" >&2
  exit 2
fi

PROJECT="$ROOT/projects/prop_poc"
GODOT_DIR="$PROJECT/godot"
ART="$PROJECT/artifacts"
LOGS="$ART/logs"
REPORT="$ART/qa_report.json"
STAMP="$(date -u +%Y%m%dT%H%M%SZ)"
CRATE_GLB="$GODOT_DIR/assets/models/sm_crate.glb"
GEM_GLB="$GODOT_DIR/assets/models/sm_gem.glb"
BUILD="$PROJECT/build/prop_poc.x86_64"

if [[ -z "${GODOT:-}" || ! -x "$GODOT" ]]; then
  echo "ERROR: Godot executable not found" >&2
  exit 127
fi
if [[ -z "${BLENDER:-}" || ! -x "$BLENDER" ]]; then
  echo "ERROR: Blender executable not found" >&2
  exit 127
fi
if [[ ! -f "$PROJECT/project.json" ]]; then
  echo "ERROR: missing $PROJECT/project.json" >&2
  exit 2
fi

mkdir -p "$LOGS" "$ART/screenshots" "$ART/previews" "$PROJECT/build"
python3 "$ROOT/tools/evidence.py" reset --report "$REPORT"

run_gate() {
  local gate="$1"
  shift
  local command
  command="$(printf '%q ' "$@")"
  local log="$LOGS/poc_${gate}_${STAMP}.log"
  set +e
  "$@" >"$log" 2>&1
  local rc=$?
  set -e
  local status="PASS"
  if [[ $rc -ne 0 ]]; then
    status="FAIL"
  fi
  python3 "$ROOT/tools/evidence.py" record \
    --report "$REPORT" \
    --gate "$gate" \
    --status "$status" \
    --command "$command" \
    --evidence "$log" \
    --details "exit=$rc" >/dev/null
  echo "POC_GATE=${gate} status=${status} log=${log}"
  if [[ $rc -ne 0 ]]; then
    tail -n 40 "$log" >&2 || true
    echo "POC_RESULT=FAIL gate=${gate} report=${REPORT}" >&2
    exit "$rc"
  fi
}

if [[ $REGENERATE -eq 1 ]]; then
  run_gate generation "$ROOT/tools/blender/run.sh" make_prop.py \
    --kind crate --out-dir "$PROJECT" --name sm_crate
  run_gate generation_anim "$ROOT/tools/blender/run.sh" make_animated_prop.py \
    --kind gem --out-dir "$PROJECT" --name sm_gem
fi

if [[ ! -s "$CRATE_GLB" || ! -s "$GEM_GLB" ]]; then
  echo "ERROR: missing generated GLBs; rerun with --regenerate" >&2
  exit 2
fi

run_gate asset python3 "$ROOT/tools/blender/validate_asset.py" "$CRATE_GLB" \
  --min-triangles 50 --max-triangles 2000 --require-material \
  --require-ground-origin --report "$ART/sm_crate.validate.json"
run_gate asset_anim python3 "$ROOT/tools/blender/validate_asset.py" "$GEM_GLB" \
  --require-animation --expect-animation anim_spin --require-skin \
  --require-material --require-ground-origin \
  --report "$ART/sm_gem.animation.json"

run_gate preview_crate "$ROOT/tools/blender/run.sh" render_preview.py \
  --blend "$PROJECT/blender/sm_crate.blend" \
  --out "$ART/previews/sm_crate.png" --width 640 --height 480
run_gate preview_anim "$ROOT/tools/blender/run.sh" render_preview.py \
  --blend "$PROJECT/blender/sm_gem.blend" \
  --out "$ART/previews/sm_gem.png" --frames 0,12,24,36,48 \
  --width 480 --height 360

run_gate content env \
  TARGET_NODE=Prop_Crate \
  TARGET_GLB=res://assets/models/sm_crate.glb \
  "$ROOT/tools/godot/validate.sh" "$GODOT_DIR"

run_gate runtime env \
  TARGET_NODE=Prop_Crate EXPECT_ROTATION=1 FRAMES=40 \
  "$ROOT/tools/godot/smoke.sh" "$GODOT_DIR"

run_gate visual "$ROOT/tools/godot/screenshot.sh" "$GODOT_DIR" \
  "$ART/screenshots/main_scene.png"

run_gate build "$ROOT/tools/godot/export_build.sh" "$GODOT_DIR" Linux "$BUILD"

python3 "$ROOT/tools/evidence.py" show --report "$REPORT"
echo "POC_RESULT=PASS report=${REPORT} screenshot=${ART}/screenshots/main_scene.png build=${BUILD}"
