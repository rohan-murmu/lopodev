#!/usr/bin/env bash
# Report Android capability without claiming device or performance readiness.
# usage: tools/godot/check_android.sh
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
# shellcheck source=/dev/null
source "$ROOT/tools/env.sh"

fail=0
warn=0
report() { printf '%s=%s\n' "$1" "$2"; }
missing() { printf 'MISSING=%s\n' "$1"; fail=$((fail + 1)); }
optional_missing() { printf 'WARN_MISSING=%s\n' "$1"; warn=$((warn + 1)); }

printf 'ANDROID_CHECK_BEGIN=1\n'

GODOT_VERSION_TEXT=""
TPL_VERSION="4.6.1.stable"
if [[ -n "${GODOT:-}" && -x "$GODOT" ]]; then
  GODOT_VERSION_TEXT="$("$GODOT" --version 2>/dev/null | head -1)"
  parsed="${GODOT_VERSION_TEXT%%.official*}"
  if [[ "$parsed" =~ ^[0-9]+\.[0-9]+\.[0-9]+(\.[A-Za-z0-9]+)?$ ]]; then
    TPL_VERSION="$parsed"
  fi
  report GODOT "$GODOT"
  report GODOT_VERSION "$GODOT_VERSION_TEXT"
else
  missing "godot executable"
fi

TPL_DIR="$GODOT_TEMPLATES/$TPL_VERSION"
if [[ -d "$TPL_DIR" ]]; then
  report ANDROID_TEMPLATES_DIR "$TPL_DIR"
  for template in android_debug.apk android_release.apk; do
    if [[ -s "$TPL_DIR/$template" ]]; then
      report "TEMPLATE_${template//./_}" "$TPL_DIR/$template"
    else
      missing "export template $TPL_DIR/$template"
    fi
  done
  if [[ -s "$TPL_DIR/android_source.zip" ]]; then
    report TEMPLATE_android_source_zip "$TPL_DIR/android_source.zip"
  else
    optional_missing "android_source.zip (required only for Gradle/AAB export)"
  fi
else
  missing "export templates at $TPL_DIR"
fi

SDK="${ANDROID_HOME:-${ANDROID_SDK_ROOT:-$HOME/Android/Sdk}}"
if [[ -d "$SDK" ]]; then
  report ANDROID_SDK "$SDK"
else
  missing "Android SDK (set ANDROID_HOME or ANDROID_SDK_ROOT)"
fi

ADB="${SDK}/platform-tools/adb"
if [[ -x "$ADB" ]]; then
  report ADB "$ADB"
  devices="$("$ADB" devices 2>/dev/null | awk 'NR>1 && $2=="device" {count++} END {print count+0}')"
  report ADB_DEVICES "$devices"
  if [[ "$devices" -eq 0 ]]; then
    optional_missing "connected Android device/emulator (device gate NOT RUN)"
  fi
else
  optional_missing "adb at $ADB"
fi

BUILD_TOOLS="$(find "$SDK/build-tools" -maxdepth 1 -mindepth 1 -type d 2>/dev/null | sort -V | tail -1 || true)"
if [[ -n "$BUILD_TOOLS" && -x "$BUILD_TOOLS/apksigner" ]]; then
  report APKSIGNER "$BUILD_TOOLS/apksigner"
else
  missing "Android build-tools with apksigner"
fi

JAVA_BIN="${JAVA_HOME:+$JAVA_HOME/bin/java}"
if [[ -z "$JAVA_BIN" || ! -x "$JAVA_BIN" ]]; then
  JAVA_BIN="$(command -v java || true)"
fi
if [[ -n "$JAVA_BIN" && -x "$JAVA_BIN" ]]; then
  report JAVA "$JAVA_BIN"
  report JAVA_VERSION "$("$JAVA_BIN" -version 2>&1 | head -1)"
else
  missing "Java runtime"
fi

KEYSTORE="${ANDROID_DEBUG_KEYSTORE:-$HOME/.local/share/godot/keystores/debug.keystore}"
if [[ -f "$KEYSTORE" ]]; then
  report DEBUG_KEYSTORE "$KEYSTORE"
else
  optional_missing "debug keystore (Godot may create one on first debug export)"
fi

if [[ "$fail" -eq 0 ]]; then
  report ANDROID_EXPORT_READY 1
else
  report ANDROID_EXPORT_READY 0
fi
report ANDROID_CHECK_FAILURES "$fail"
report ANDROID_CHECK_WARNINGS "$warn"
printf 'ANDROID_CHECK_END=1\n'
[[ "$fail" -eq 0 ]]
