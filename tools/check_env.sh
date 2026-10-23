#!/usr/bin/env bash
# Check the pinned toolchain. Exit 1 if a critical dependency is unavailable.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
# shellcheck source=/dev/null
source "$ROOT/tools/env.sh"

fail=0
note() { printf '%-22s %s\n' "$1" "$2"; }

if [[ -n "$BLENDER" && -x "$BLENDER" ]]; then
  note "blender" "$("$BLENDER" --version 2>/dev/null | head -n 1) ($BLENDER)"
else
  note "blender" "MISSING"; fail=1
fi

if [[ -n "$GODOT" && -x "$GODOT" ]]; then
  note "godot" "$("$GODOT" --version 2>/dev/null | head -n 1) ($GODOT)"
else
  note "godot" "MISSING"; fail=1
fi

note "python" "$("$PYTHON" --version 2>&1) ($(command -v "$PYTHON" || echo missing))"
note "git" "$(git --version)"
note "display" "${DISPLAY:-<none>}"

if find "$GODOT_TEMPLATES" -maxdepth 2 -name 'linux_release.x86_64' 2>/dev/null | grep -q .; then
  note "export templates" "linux_release.x86_64 present"
else
  note "export templates" "MISSING (needed for export gate)"; fail=1
fi

if command -v identify >/dev/null 2>&1; then
  note "imagemagick" "$(identify -version 2>/dev/null | head -n 1)"
else
  note "imagemagick" "MISSING (screenshot analysis unavailable)"
fi

if [[ $fail -eq 0 ]]; then
  echo "ENV_CHECK=PASS"
else
  echo "ENV_CHECK=FAIL"
fi
exit "$fail"
