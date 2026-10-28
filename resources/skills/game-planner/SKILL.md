---
name: game-planner
description: Use FIRST for any new game or feature request to turn an idea into a measurable game specification, asset list, ordered tasks, and acceptance criteria before any Blender or Godot work starts.
license: MIT
---

# Game Planner

Convert an ambiguous game request into a small, testable delivery plan. This
skill never generates art or code; it produces the contracts that every later
skill consumes.

## Required inputs

- The user's request, ideally as a **Game Brief** (`templates/GAME_BRIEF.md`;
  `lopodev brief template`). If `projects/<slug>/docs/GAME_BRIEF.md` exists,
  `project.json` was scaffolded from it (`lopodev brief scaffold`): refine that
  draft instead of starting over, and resolve every entry in `assumptions`.
  For a free-text request, map it onto the brief fields first and record each
  guess in `assumptions`.
- Target platform (the brief's `Platform`; default android) and hard constraints.
- Existing repository state (`git status`, current `projects/`).
- Available toolchain facts from `docs/environment-audit.md`.
- If the project already exists, its `project.json`, `GAME_SPEC.md`, and prior
  evidence. Never discard existing scope silently.

## Expected outputs

```text
projects/<game_slug>/
  project.json          # machine-readable spec: assets, tasks, criteria
  GAME_SPEC.md          # human-readable scope, controls, loop, acceptance
  ASSET_LICENSES.md     # only when third-party assets are used
```

`project.json` must include:

- `slug`, `title`, `summary`, `status`, `genre`, `target_platform`;
- `engine` (`godot` + exact version), `blender` version;
- `main_scene` (`res://scenes/PascalCase.tscn`);
- `assets[]`: asset *requirements*, discovered by default. Each entry has
  `id`, `class` (`static_prop`, `skeletal_character`, `animated_prop`,
  `modular_environment`, `procedural_element`, `material`, `hdri`), `role`,
  `terms`, and when it matters `size_m`, `animations` (actions such as idle,
  walk, run, shoot, hit, death), `collision`, `budget_triangles`, `mandatory`,
  `fallbacks`. Use `"source": "procedural"` with `kind`/`license`/
  `budget_triangles`/`animated` only for assets that must be modeled in
  Blender. `python3 tools/asset_requirements.py --prompt "<prompt>"` prints a
  starting list; set `art_style` (any style: `stylized`, `realistic`, `toon`, ...) once for the game;
- `tasks[]`: `id`, `title`, `owner`, `skills[]`, `depends_on[]`, `verify`,
  `status` (`planned` for new work; legacy `pending` is accepted);
- `acceptance[]`: `id`, `criterion`, `gate`, `evidence`;
- `known_limitations[]`.

Use `templates/project.json` as the starting shape and
`templates/GAME_SPEC.md` for the document.

## Workflow

1. Inspect the repository and read `AGENTS.md`; do not overwrite an existing
   project. Create or resume `projects/<slug>/`.
2. Restate the request in one paragraph, then list explicit non-goals. A first
   milestone must produce one verifiable vertical slice, not a whole game.
3. Define the core loop, controls, camera, win/lose condition, and one playable
   scene. If the request is ambiguous, choose the smallest defensible scope and
   record the assumption.
4. Budget content: scene count, prop list, character list, animations, UI,
   sounds. Respect the platform budgets in `resources/budgets.json`.
5. Break delivery into ordered tasks. Each task must have one owner skill, a
   concrete command or check, and a dependency list. No task may be "make it
   fun" without a measurable check.
6. Define acceptance criteria that map to the test gates in `AGENTS.md`
   (generation, asset, import, content, runtime, visual, build). Include a
   graphical criterion for anything visual.
7. Write `project.json` and `GAME_SPEC.md`, then validate the JSON and sync the
   tasks/assets into durable state.
8. Select only the skills required for the first milestone. Record skipped
   skills and why in `GAME_SPEC.md`.

## Mobile game design (design_version 2)

New specs set `"design_version": 2` and must define, before any asset work:

- `core_loop`: one sentence the player repeats (act -> feedback -> reward -> next).
  One polished loop beats several shallow mechanics; cut features that do not
  serve it and list them under `known_limitations` as deferred.
- `mobile.orientation`: chosen from the game, not by habit (portrait for one-thumb
  puzzle/runner, landscape for twin-stick action/shooters/strategy).
- `controls`: `scheme` plus `touch` entries `{id, type, action, zone}`. Pick by genre:

  | Genre | Touch layout |
  |---|---|
  | Shooter / third-person action | joystick bottom-left, look-drag right half, fire/aim/reload buttons bottom-right |
  | Platformer | left/right dpad or joystick, jump + action buttons (>= 64 dp) |
  | Puzzle / match | tap and drag on the board; no joystick |
  | Strategy / builder | tap to select, drag to pan, pinch to zoom, contextual command panel |
  | Runner | swipe lanes/jump, tap to act |

  Continuous controls (joystick, look-drag, drag, pinch) need separate zones;
  buttons are >= 44 dp. Search `lopodev knowledge search touch <genre>` and name
  reused entries in `controls.knowledge`.
- `screens` (`menu|select|settings|gameplay|overlay|result|loading`, each with the
  `controls` it shows) and `navigation` (`entry`, `transitions` `{from, on, to}`,
  `to` may be `@back` or `@quit`). Start at a main menu unless the developer asked
  otherwise (then set `entry_reason`). Every visible control needs a transition
  or action; every gameplay screen needs a pause overlay; every result screen
  needs retry or menu. Use the `godot-screen-router` recipe.
- `world_plan`: path to `docs/world_plan.json` when the game has a 3D world
  (see the `game-world` skill and `templates/world_plan.json`).
- Acceptance criteria for controls (simultaneous move + look + action), the full
  navigation graph, pause/resume and restart, each with a runtime test.

`python3 tools/validate_spec.py` rejects unreachable screens, dead ends, dead
buttons, missing pause/retry, shared control zones, and tiny buttons.

## Validation

```bash
python3 tools/validate_spec.py projects/<slug>/project.json
python3 tools/pipeline_state.py sync-spec --project projects/<slug> \
  --spec projects/<slug>/project.json
python3 tools/pipeline_state.py validate --project projects/<slug>
```

Pass criteria:

- schema checks exit 0;
- every task has at least one `verify` command and a known skill owner;
- `main_scene` is a valid `res://...tscn` path;
- every asset is a valid requirement (`lopodev assets requirements`) or a
  Blender asset with a license/source and triangle budget;
- acceptance criteria name a gate and an evidence path;
- the first milestone has at least one runtime and one visual criterion when
  the deliverable is visual.

## Failure recovery

- **Invalid JSON** - fix the file and rerun `validate_spec.py`; do not bypass it.
- **Scope too large** - cut to one scene, one character/controller, and 1-3
  props; move the rest to a "later" section with no acceptance claims.
- **No measurable criterion** - replace adjectives with a command and a file
  path (for example "screenshot at `artifacts/poc.png` is non-blank and shows
  the crate").
- **Missing upstream decision** - ask the user one focused question, or record
  the smallest assumption in `GAME_SPEC.md` and proceed.
- **Existing project conflict** - stop, inspect `git diff`, and ask before
  changing user-authored scope.

## Handoff

Report the exact paths written and the ordered task list. The next skill is
`asset-intelligence` (discovery, licensing, import). `blender-modeling` follows
only for assets marked `"source": "procedural"` or for processing tasks the
asset stage requests. `game-world` can plan the world in parallel.
