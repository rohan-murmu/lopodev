---
name: godot-gameplay
description: Use when a Godot scene needs mechanics - player or camera control, input actions, signals, interaction, animation state wiring, and gameplay assertions that run both headless and in a graphical launch.
license: MIT
---

# Godot Gameplay

Implement small, testable GDScript systems on top of a verified scene. The goal
is observable mechanics, not just attached scripts.

## Required inputs

- `project.json` / `GAME_SPEC.md` mechanics and acceptance criteria.
- A scene that passes `game-world` validation, with a documented node map.
- Exact node paths/names, input actions, animation clip names, and state rules.
- Godot version facts (4.6.1) from `docs/environment-audit.md`.

## Expected outputs

- One responsibility per script under `godot/scripts/` (snake_case.gd).
- Input actions defined in `project.godot` (or an `.tres` resource) using
  descriptive names (`move_forward`, `interact`, `jump`).
- Signals for cross-system events; no hidden global state where a signal is
  appropriate.
- Animation wiring through `AnimationPlayer` / `AnimationTree` with explicit
  clip names.
- Runtime assertions callable via test environment variables, used by
  `tools/godot/runtime_smoke.gd`.
- Evidence in `artifacts/`: smoke JSON, log, and screenshot for visual behavior.

## Workflow

1. Read the mechanics and node map. List each mechanic as input -> state change
   -> observable result -> test.
2. Confirm the scene content gate passes before adding behavior.
3. Create one script per system. Use typed GDScript (`var speed: float = 4.0`),
   `@onready` node lookups, and `_physics_process` for movement.
4. Add input actions to `project.godot` and keep the mapping in version control.
5. Wire animations by clip name (`anim_idle`, `anim_walk`, ...). Verify the clip
   exists after import; never assume naming.
6. Implement a test hook controlled by an environment variable, for example:
   ```gdscript
   if OS.get_environment("SMOKE_TEST") == "1":
       await get_tree().process_frame
       # assert movement/rotation/animation state
       print("SMOKE_TEST=PASS")
       get_tree().quit(0)
   ```
   The test must fail loudly (exit 1) on assertion failure.
7. Run the headless runtime gate with real frames:
   ```bash
   TARGET_NODE=Player EXPECT_ROTATION=1 FRAMES=30 \
     tools/godot/smoke.sh projects/<slug>/godot
   ```
8. For visual mechanics, launch with `DISPLAY=:0`, exercise the mechanic, and
   capture a screenshot. A headless check alone cannot verify appearance or
   input feel.
9. Record what was tested, frame counts, and actual results.

## Validation procedures

- Parse gate: Godot loads all scripts with no `SCRIPT ERROR:`.
- Runtime gate: scene runs for N real frames; target node exists; expected
  rotation/position/animation state changes.
- Mechanic gate: each acceptance test maps to one assertion with a named result.
- Animation gate: required clip exists and is playing/advanced when required.
- Visual gate: graphical screenshot shows the result of the mechanic.
- Regression gate: rerun content and runtime checks after each change.

## Failure recovery

- **Parser error** - fix types/indentation first; run
  `godot --headless --path <project> --check-only --script <file>` where useful.
- **Node not found** - print the actual scene tree (`print_tree_pretty()`) from
  a test hook; fix paths instead of adding fragile searches.
- **Works headless but not graphically** - check renderer, camera, lighting, and
  viewport; headless uses a dummy renderer and proves logic only.
- **Animation not playing** - confirm `AnimationPlayer` is inside the tree, the
  clip name is exact, and the player is not stopped by another script.
- **Test hook never exits** - ensure the smoke env var is set in the same
  process, and that the hook runs after `_ready`/first frames, not before.
- **Flaky movement test** - assert direction/threshold over a fixed frame count,
  not an exact float position; use physics frames consistently.

## Handoff

Deliver script paths, input map, signals, node map, exact test commands, and
actual PASS/FAIL output to `game-qa`. Do not claim "playable" until the visual
gate and the relevant mechanic test both pass.
