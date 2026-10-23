#!/usr/bin/env bash
# Resolve pinned local tool paths. Source this file; do not execute it.

AGENT_ROOT="$(cd "$(dirname "$(readlink -f "${BASH_SOURCE[0]}")")/.." && pwd)"
export AGENT_ROOT

if [[ -z "${BLENDER:-}" ]]; then
  if command -v blender >/dev/null 2>&1; then
    BLENDER="$(command -v blender)"
  elif [[ -x /snap/bin/blender ]]; then
    BLENDER="/snap/bin/blender"
  else
    BLENDER=""
  fi
fi
export BLENDER

if [[ -z "${GODOT:-}" ]]; then
  for candidate in "$AGENT_ROOT"/.tools/godot/Godot_v*_linux.x86_64; do
    if [[ -x "$candidate" ]]; then
      GODOT="$candidate"
      break
    fi
  done
fi
if [[ -z "${GODOT:-}" ]] && command -v godot >/dev/null 2>&1; then
  GODOT="$(command -v godot)"
fi
GODOT="${GODOT:-}"
export GODOT

PYTHON="${PYTHON:-python3}"
export PYTHON

GODOT_TEMPLATES="${GODOT_TEMPLATES:-$HOME/.local/share/godot/export_templates}"
export GODOT_TEMPLATES
