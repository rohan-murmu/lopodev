#!/usr/bin/env bash
# Fast deterministic verification of the LopoDev toolkit.
# usage: tools/verify_lopodev.sh [--crystal <project_dir>] [--full]
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
source "$ROOT/tools/env.sh"

CRYSTAL=""
FULL=0
while [[ $# -gt 0 ]]; do
  case "$1" in
    --crystal) CRYSTAL="${2:?missing project dir}"; shift 2 ;;
    --full) FULL=1; shift ;;
    -h|--help) sed -n '2,3p' "$0"; exit 0 ;;
    *) echo "ERROR: unknown argument: $1" >&2; exit 2 ;;
  esac
done

fail=0
check() {
  local name="$1"; shift
  echo "== $name =="
  if "$@"; then
    echo "CHECK_$name=PASS"
  else
    echo "CHECK_$name=FAIL" >&2
    fail=$((fail + 1))
  fi
}

check unit_tests python3 -m unittest discover -s "$ROOT/tools/tests"
check whitespace git -C "$ROOT" diff --check
check sanitize python3 "$ROOT/tools/sanitize_local_paths.py" --check
check android "$ROOT/tools/godot/check_android.sh"
check knowledge python3 "$ROOT/tools/knowledge.py" validate
check spec_template python3 "$ROOT/tools/validate_spec.py" "$ROOT/templates/project.json" --no-file-checks
check world_template python3 "$ROOT/tools/world_plan.py" validate "$ROOT/templates/world_plan.json"
check asset_registry python3 "$ROOT/tools/asset_pipeline.py" providers
# LopoDev is not tied to one art style; only legacy aliases may name the old skill.
no_style_lock() {
  ! git -C "$ROOT" grep --untracked -n -i -E "low[- ]?poly" -- . ':!resources/knowledge/evidence' \
    | grep -v "pre-0.3 name"
}
check art_style_neutral no_style_lock
check formula python3 "$ROOT/tools/homebrew_formula.py" --check "$ROOT/Formula/lopodev.rb" --license MIT
check integrations "$ROOT/bin/lopodev" doctor --project "$ROOT" --no-live

if [[ ! -e "$ROOT/.opencode/agents/lopodev.md" ]]; then
  echo "INFO: installing generated OpenCode adapter for verification" >&2
  "$ROOT/bin/lopodev" install opencode --project "$ROOT" >/dev/null
fi

echo "== agents and commands =="
# OpenCode truncates piped debug output at ~64 KB; a file gets all of it.
config_file="$(mktemp)"
(cd "$ROOT" && opencode debug config >"$config_file" 2>/dev/null)
set +e
python3 - "$config_file" <<'PY'
import json
import sys
with open(sys.argv[1], encoding="utf-8") as handle:
    data = json.load(handle)
assert data.get("default_agent") == "lopodev", data.get("default_agent")
agents = data.get("agent") or {}
commands = data.get("command") or {}
expected_agents = {
    "lopodev", "game-design", "modeling", "animation", "level-design",
    "gameplay", "ui", "optimization", "qa-release",
}
expected_commands = {
    "lopodev", "init-game", "adopt-game", "character", "prop", "animate",
    "mechanic", "level", "mobile-ui", "diagnose", "optimize", "release",
}
missing_agents = expected_agents - set(agents)
missing_commands = expected_commands - set(commands)
assert not missing_agents, f"missing agents: {sorted(missing_agents)}"
assert not missing_commands, f"missing commands: {sorted(missing_commands)}"
print(f"AGENTS_OK={len(expected_agents)} COMMANDS_OK={len(expected_commands)}")
PY
config_rc=$?
rm -f "$config_file"
set -e
if [[ $config_rc -ne 0 ]]; then
  echo "CHECK_opencode=FAIL" >&2
  fail=$((fail + 1))
else
  echo "CHECK_opencode=PASS"
fi

if [[ -n "$CRYSTAL" ]]; then
  check crystal_state python3 "$ROOT/tools/pipeline_state.py" validate --project "$CRYSTAL"
  check crystal_events python3 "$ROOT/tools/lopodev_log.py" validate --project "$CRYSTAL" --allow-missing
  if [[ "$FULL" -eq 1 ]]; then
    GODOT_DIR="$CRYSTAL/godot"
    check content env TARGET_NODE=Drone TARGET_GLB=res://assets/models/sm_hover_drone.glb \
      "$ROOT/tools/godot/validate.sh" "$GODOT_DIR"
    check runtime env SMOKE_TEST=1 TARGET_NODE=Drone EXPECT_MOVEMENT=1 \
      MIN_MOVEMENT_M=1.0 FRAMES=180 "$ROOT/tools/godot/smoke.sh" "$GODOT_DIR"
    check gameplay "$GODOT" --headless --path "$GODOT_DIR" \
      --script res://tests/gameplay_test.gd
    check visual "$ROOT/tools/godot/screenshot.sh" "$GODOT_DIR" \
      "$CRYSTAL/artifacts/screenshots/verify_lopodev.png"
  fi
fi

if [[ "$fail" -eq 0 ]]; then
  echo "LOPODEV_VERIFY=PASS"
  exit 0
fi
echo "LOPODEV_VERIFY=FAIL failures=$fail" >&2
exit 1
