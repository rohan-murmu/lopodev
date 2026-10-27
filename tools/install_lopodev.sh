#!/usr/bin/env bash
# Deprecated compatibility wrapper for `lopodev install opencode`.
# usage: tools/install_lopodev.sh [workspace] [--dry-run]
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
WORKSPACE="."
DRY_RUN=0
for arg in "$@"; do
  case "$arg" in
    --dry-run) DRY_RUN=1 ;;
    -h|--help) sed -n '2,3p' "$0"; exit 0 ;;
    *) WORKSPACE="$arg" ;;
  esac
done

echo "WARNING: tools/install_lopodev.sh is deprecated; use 'lopodev install opencode --project <workspace>'." >&2
args=(install opencode --project "$WORKSPACE")
if [[ "$DRY_RUN" -eq 1 ]]; then
  args+=(--dry-run)
fi
exec "$ROOT/bin/lopodev" "${args[@]}"
