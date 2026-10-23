#!/usr/bin/env bash
# Fast deterministic verification of the OpenGame toolkit.
# usage: tools/verify_opengame.sh [--crystal <project_dir>] [--full]
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
check android "$ROOT/tools/godot/check_android.sh"

echo "== agents and commands =="
config="$(cd "$ROOT" && opencode debug config 2>/dev/null)"
set +e
python3 - "$config" <<'PY'
import json
import sys
data = json.loads(sys.argv[1])
assert data.get("default_agent") == "opengame", data.get("default_agent")
agents = data.get("agent") or {}
commands = data.get("command") or {}
expected_agents = {
    "opengame", "game-design", "modeling", "animation", "level-design",
    "gameplay", "ui", "optimization", "qa-release",
}
expected_commands = {
    "opengame", "init-game", "adopt-game", "character", "prop", "animate",
    "mechanic", "level", "mobile-ui", "diagnose", "optimize", "release",
}
missing_agents = expected_agents - set(agents)
missing_commands = expected_commands - set(commands)
assert not missing_agents, f"missing agents: {sorted(missing_agents)}"
assert not missing_commands, f"missing commands: {sorted(missing_commands)}"
print(f"AGENTS_OK={len(expected_agents)} COMMANDS_OK={len(expected_commands)}")
PY
config_rc=$?
set -e
if [[ $config_rc -ne 0 ]]; then
  echo "CHECK_opencode=FAIL" >&2
  fail=$((fail + 1))
else
  echo "CHECK_opencode=PASS"
fi

if [[ -n "$CRYSTAL" ]]; then
  check crystal_state python3 "$ROOT/tools/pipeline_state.py" validate --project "$CRYSTAL"
  check crystal_events python3 "$ROOT/tools/opengame_log.py" validate --project "$CRYSTAL" --allow-missing
  if [[ "$FULL" -eq 1 ]]; then
    GODOT_DIR="$CRYSTAL/godot"
    check content env TARGET_NODE=Drone TARGET_GLB=res://assets/models/sm_hover_drone.glb \
      "$ROOT/tools/godot/validate.sh" "$GODOT_DIR"
    check runtime env SMOKE_TEST=1 TARGET_NODE=Drone EXPECT_MOVEMENT=1 \
      MIN_MOVEMENT_M=1.0 FRAMES=180 "$ROOT/tools/godot/smoke.sh" "$GODOT_DIR"
    check gameplay "$GODOT" --headless --path "$GODOT_DIR" \
      --script res://tests/gameplay_test.gd
    check visual "$ROOT/tools/godot/screenshot.sh" "$GODOT_DIR" \
      "$CRYSTAL/artifacts/screenshots/verify_opengame.png"
  fi
fi

if [[ "$fail" -eq 0 ]]; then
  echo "OPENGAME_VERIFY=PASS"
  exit 0
fi
echo "OPENGAME_VERIFY=FAIL failures=$fail" >&2
exit 1
