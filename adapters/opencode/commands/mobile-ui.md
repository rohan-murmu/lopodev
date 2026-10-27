---
description: Add responsive HUD, menus and touch controls, then verify layouts and Android export.
agent: lopodev
---
Implement the UI/mobile work described by `$ARGUMENTS`.

1. Run `tools/godot/check_android.sh` and report capability honestly.
2. Delegate HUD/menu/touch work to `ui`; require desktop and mobile-aspect
   screenshots and a safe-area check.
3. Run the gameplay regression to ensure UI did not take ownership of game state.
4. If Android is in scope, run `tools/godot/export_android.sh <godot_dir> --format apk`
   or `--format aab --release` and inspect the artifact and logs. Device launch
   remains `NOT RUN` unless a device or emulator exists and is inspected.
5. Never call desktop screenshots mobile evidence.
