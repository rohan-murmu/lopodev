#!/usr/bin/env bash
# Copy reusable QA scripts into <godot_dir>/.pipeline (gitignored).
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
# shellcheck source=/dev/null
source "$ROOT/tools/env.sh"
# shellcheck source=/dev/null
source "$ROOT/tools/godot/lib.sh"

if [[ $# -ne 1 ]]; then
  echo "usage: tools/godot/stage_checks.sh <godot_dir>" >&2
  exit 2
fi
stage_checks "$1"
