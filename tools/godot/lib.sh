#!/usr/bin/env bash
# Shared helpers for Godot gate wrappers. Source, do not execute.

godot_dir_abs() {
  realpath -m "$1"
}

stage_checks() {
  local godot_dir
  godot_dir="$(godot_dir_abs "$1")"
  if [[ ! -f "$godot_dir/project.godot" ]]; then
    echo "ERROR: not a Godot project (missing project.godot): $godot_dir" >&2
    return 2
  fi
  mkdir -p "$godot_dir/.pipeline"
  cp "$AGENT_ROOT"/tools/godot/checks/*.gd "$godot_dir/.pipeline/"
  echo "STAGED_CHECKS=$godot_dir/.pipeline"
}

project_artifacts_logs() {
  local godot_dir
  godot_dir="$(godot_dir_abs "$1")"
  local logs
  logs="$(dirname "$godot_dir")/artifacts/logs"
  mkdir -p "$logs"
  echo "$logs"
}

run_import_gate() {
  local godot_dir="$1"
  local log="$2"
  if [[ -z "${GODOT:-}" || ! -x "$GODOT" ]]; then
    echo "ERROR: Godot executable not found" >&2
    return 127
  fi
  timeout 120 "$GODOT" --headless --path "$godot_dir" --import >"$log" 2>&1
  local rc=$?
  if [[ $rc -ne 0 ]]; then
    echo "IMPORT_GATE=FAIL exit=$rc log=$log" >&2
    tail -n 40 "$log" >&2 || true
    return "$rc"
  fi
  local project_errors
  project_errors="$(grep -nE '(^| )ERROR:|SCRIPT ERROR:' "$log" || true)"
  if [[ -n "$project_errors" ]]; then
    echo "IMPORT_GATE=FAIL project-caused errors in $log" >&2
    echo "$project_errors" >&2
    return 1
  fi
  echo "IMPORT_GATE=PASS log=$log"
}
