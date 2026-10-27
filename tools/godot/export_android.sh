#!/usr/bin/env bash
# Build an Android APK or AAB through the shared deterministic exporter.
# usage: tools/godot/export_android.sh <godot_dir> [--format apk|aab]
#        [--mode debug|release | --release] [--preset NAME] [--out FILE]
#        [--godot PATH] [--json] [--dry-run]
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"

if [[ $# -lt 1 ]]; then
  echo "usage: tools/godot/export_android.sh <godot_dir> [--format apk|aab] [--mode debug|release | --release] [--preset NAME] [--out FILE] [--godot PATH] [--json] [--dry-run]" >&2
  exit 2
fi
if [[ "$1" == "-h" || "$1" == "--help" ]]; then
  sed -n '2,5p' "$0"
  exit 0
fi

GODOT_DIR="$1"
shift
args=(--format apk --mode debug)
while [[ $# -gt 0 ]]; do
  case "$1" in
    --release) args+=(--mode release); shift ;;
    --debug) args+=(--mode debug); shift ;;
    --format) args+=(--format "${2:?missing format}"); shift 2 ;;
    --mode) args+=(--mode "${2:?missing mode}"); shift 2 ;;
    --preset) args+=(--preset "${2:?missing preset}"); shift 2 ;;
    --out) args+=(--out "${2:?missing output path}"); shift 2 ;;
    --godot) args+=(--godot "${2:?missing godot path}"); shift 2 ;;
    --json) args+=(--json); shift ;;
    --dry-run) args+=(--dry-run); shift ;;
    *)
      echo "ERROR: unknown argument: $1" >&2
      exit 2
      ;;
  esac
done

exec python3 "$ROOT/tools/godot/android_export.py" "$GODOT_DIR" "${args[@]}"
