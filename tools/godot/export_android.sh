#!/usr/bin/env bash
# Build an Android APK and record evidence. Device launch is a separate gate.
# usage: tools/godot/export_android.sh <godot_dir> [--release] [--preset NAME] [--out FILE]
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
# shellcheck source=/dev/null
source "$ROOT/tools/env.sh"
# shellcheck source=/dev/null
source "$ROOT/tools/godot/lib.sh"

if [[ $# -lt 1 ]]; then
  echo "usage: tools/godot/export_android.sh <godot_dir> [--release] [--preset NAME] [--out FILE]" >&2
  exit 2
fi

GODOT_DIR="$(godot_dir_abs "$1")"; shift
RELEASE=0
PRESET="Android"
PROJECT_ROOT="$(dirname "$GODOT_DIR")"
OUT=""
while [[ $# -gt 0 ]]; do
  case "$1" in
    --release) RELEASE=1; shift ;;
    --preset) PRESET="${2:?missing preset}"; shift 2 ;;
    --out) OUT="${2:?missing output path}"; shift 2 ;;
    -h|--help) sed -n '2,4p' "$0"; exit 0 ;;
    *) echo "ERROR: unknown argument: $1" >&2; exit 2 ;;
  esac
done
if [[ -z "$OUT" ]]; then
  if [[ "$RELEASE" -eq 1 ]]; then
    OUT="$PROJECT_ROOT/build/$(basename "$PROJECT_ROOT").apk"
  else
    OUT="$PROJECT_ROOT/build/$(basename "$PROJECT_ROOT")_debug.apk"
  fi
fi
OUT="$(realpath -m "$OUT")"
mkdir -p "$(dirname "$OUT")"
LOGS="$(project_artifacts_logs "$GODOT_DIR")"
STAMP="$(date -u +%Y%m%dT%H%M%SZ)"
MODE="debug"; [[ "$RELEASE" -eq 1 ]] && MODE="release"
IMPORT_LOG="$LOGS/android_import_$STAMP.log"
EXPORT_LOG="$LOGS/android_export_${MODE}_$STAMP.log"

if [[ ! -f "$GODOT_DIR/project.godot" ]]; then
  echo "ERROR: not a Godot project: $GODOT_DIR" >&2
  exit 2
fi
if [[ ! -f "$GODOT_DIR/export_presets.cfg" ]] || ! grep -q "^name=\"$PRESET\"" "$GODOT_DIR/export_presets.cfg"; then
  echo "ERROR: Android export preset '$PRESET' not found in $GODOT_DIR/export_presets.cfg" >&2
  exit 2
fi
if [[ "$RELEASE" -eq 1 ]]; then
  if ! grep -qE '^keystore/release=' "$GODOT_DIR/export_presets.cfg" && \
     [[ -z "${ANDROID_KEYSTORE_RELEASE_PATH:-}" ]]; then
    echo "ERROR: release signing is not configured." >&2
    echo "Set ANDROID_KEYSTORE_RELEASE_PATH (and user/password env vars) or add" >&2
    echo "keystore/release to the Android preset. Do not use the debug key for release." >&2
    exit 2
  fi
fi
if ! grep -qE '^textures/vram_compression/import_etc2_astc=true' "$GODOT_DIR/project.godot"; then
  echo "ERROR: Android export requires [rendering] textures/vram_compression/import_etc2_astc=true" >&2
  echo "Fix project.godot, re-import, then retry. This one setting caused the initial probe failure." >&2
  exit 2
fi

"$ROOT/tools/godot/check_android.sh" >"$LOGS/android_capability_$STAMP.log" 2>&1 || {
  echo "ANDROID_EXPORT_GATE=FAIL capability check failed; see $LOGS/android_capability_$STAMP.log" >&2
  tail -n 30 "$LOGS/android_capability_$STAMP.log" >&2 || true
  exit 1
}
grep -q '^ANDROID_EXPORT_READY=1' "$LOGS/android_capability_$STAMP.log" || {
  echo "ANDROID_EXPORT_GATE=FAIL Android toolchain unavailable" >&2
  cat "$LOGS/android_capability_$STAMP.log" >&2
  exit 1
}

SDK="${ANDROID_HOME:-${ANDROID_SDK_ROOT:-$HOME/Android/Sdk}}"
JAVA_BIN="${JAVA_HOME:+$JAVA_HOME/bin/java}"
if [[ -z "$JAVA_BIN" || ! -x "$JAVA_BIN" ]]; then
  JAVA_BIN="$(command -v java)"
fi
JAVA_REAL="$(readlink -f "$JAVA_BIN")"
JAVA_HOME_DETECTED="$(dirname "$(dirname "$JAVA_REAL")")"
KEYSTORE="${ANDROID_DEBUG_KEYSTORE:-$HOME/.local/share/godot/keystores/debug.keystore}"
TMP_CFG="$(mktemp -d /tmp/opengame_android_cfg.XXXXXX)"
trap 'rm -rf "$TMP_CFG"' EXIT
mkdir -p "$TMP_CFG/godot"
cat >"$TMP_CFG/godot/editor_settings-4.6.tres" <<EOF
[gd_resource type="EditorSettings" format=3]

[resource]
export/android/android_sdk_path = "$SDK"
export/android/java_sdk_path = "$JAVA_HOME_DETECTED"
export/android/debug_keystore = "$KEYSTORE"
export/android/debug_keystore_pass = "android"
EOF

run_import_gate "$GODOT_DIR" "$IMPORT_LOG"

set +e
XDG_CONFIG_HOME="$TMP_CFG" timeout 600 "$GODOT" --headless --path "$GODOT_DIR" \
  --export-$MODE "$PRESET" "$OUT" >"$EXPORT_LOG" 2>&1
export_rc=$?
set -e
if [[ $export_rc -ne 0 ]]; then
  echo "ANDROID_EXPORT_GATE=FAIL mode=$MODE exit=$export_rc log=$EXPORT_LOG" >&2
  tail -n 60 "$EXPORT_LOG" >&2 || true
  exit "$export_rc"
fi
if [[ ! -s "$OUT" ]]; then
  echo "ANDROID_EXPORT_GATE=FAIL APK missing or empty: $OUT" >&2
  exit 1
fi
BYTES="$(stat -c %s "$OUT")"
if [[ "$BYTES" -lt 1000000 ]]; then
  echo "ANDROID_EXPORT_GATE=FAIL APK implausibly small: $BYTES bytes" >&2
  exit 1
fi
if ! unzip -l "$OUT" AndroidManifest.xml >/dev/null 2>&1; then
  echo "ANDROID_EXPORT_GATE=FAIL APK has no AndroidManifest.xml: $OUT" >&2
  exit 1
fi

echo "ANDROID_EXPORT_GATE=PASS mode=$MODE apk=$OUT bytes=$BYTES log=$EXPORT_LOG capability_log=$LOGS/android_capability_$STAMP.log"
echo "DEVICE_GATE=NOT_RUN launch and inspect the APK on a real device or emulator"
