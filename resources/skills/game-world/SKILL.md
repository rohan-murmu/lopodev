---
name: game-world
description: Use after assets pass validation to build Godot 3D scenes and levels - importing GLB assets as instances, placing props, lighting, cameras, collision, spawn points, and verifying the scene loads and renders.
license: MIT
---

# Game World

**Procedural by default.** Write intent as `docs/world_plan.json`, let
`lopodev world generate` place everything deterministically from the seed, and
`lopodev world validate --map` check it. Plan keys: `bounds`, `seed`, `terrain`
(`noise` heightfield, `max_walkable_slope_deg`, `flatten` zones), `spawns`,
`enemy_spawns` + `enemy_radius`, `objectives`, `landmarks`, `paths`,
`exclusions` (circles/boxes), `blockers`, `scatter` rules (`asset` = requirement
id, `count`, `radius`, `min_spacing`, `distribution: poisson`, `cluster`,
`max_slope_deg`, `collision`), `sightlines`, `combat_zones`
(`max_cover_ratio`), `budgets`. Assemble with
`python3 tools/godot/world_to_tscn.py <resolved.json> --godot-dir <dir> --out scenes/World.tscn --asset-map projects/<slug>/assets/asset_map.json`
(ground or heightfield collision, sun, environment, NavigationRegion3D) and
prove paths with
`godot --headless --path <dir> --script res://.pipeline/nav_check.gd -- res://scenes/World.tscn`
after copying `tools/godot/checks/nav_check.gd` to `<dir>/.pipeline/`. If
validation fails, change parameters and regenerate; do not hand-move scatter.

Assemble validated Blender assets into a runnable Godot scene. This skill owns
the scene tree, transforms, lighting, camera, environment, collision, and spawn
layout. It does not write gameplay systems beyond minimal scene setup.

## Required inputs

- `project.json` / `GAME_SPEC.md` with the level brief and `main_scene`.
- Validated `sm_<noun>.glb` + `.meta.json` files and their triangle reports.
- A scene tree map: root type, expected node names, spawn points, camera intent,
  lighting/mood, collision requirements.
- Target Godot project:
  `projects/<slug>/godot/project.godot`.

## Expected outputs

- `godot/scenes/<PascalCase>.tscn` with:
  - imported GLB instances via `ext_resource type="PackedScene"`;
  - a `Camera3D` with a deliberate transform;
  - lighting and an environment/background;
  - static collision for walkable/blocking geometry where required;
  - named spawn/marker nodes (`Spawn_01`, `PlayerStart`, ...);
  - no runtime-only gameplay logic beyond a thin scene script.
- Scene node map in `projects/<slug>/docs/scene_<name>.md`.
- Import/content/visual evidence paths in `artifacts/`.

## Workflow

1. Read the level brief and confirm asset paths and budgets from the spec.
2. Confirm the GLB files exist and are validated. If not, stop and return to
   `blender-modeling`/`blender-animation`.
3. Create the Godot project only if absent. Never overwrite an existing
   `project.godot` without inspecting it.
4. Run the import gate:
   ```bash
   source tools/env.sh
   "$GODOT" --headless --path projects/<slug>/godot --import
   ```
   Review the log for `ERROR:` or `SCRIPT ERROR:`. Asset import warnings caused
   by the project must be fixed now.
5. Author the scene incrementally. Reference the GLB as a PackedScene:
   ```text
   [ext_resource type="PackedScene" path="res://assets/models/sm_crate.glb" id="1"]
   [node name="Prop_Crate" parent="." instance=ExtResource("1")]
   ```
   Keep transforms in meters and rotations in radians/degrees consistently.
6. Add camera, key light, fill/ambient, ground, and background. Verify framing
   with a graphical screenshot, not by guessing coordinates.
7. Add collision. Static level geometry gets `StaticBody3D` + matching
   `CollisionShape3D`. Character controllers are added by `godot-gameplay`.
8. Validate scene content:
   ```bash
   TARGET_NODE=Prop_Crate TARGET_GLB=res://assets/models/sm_crate.glb \
     tools/godot/validate.sh projects/<slug>/godot
   ```
9. Capture and inspect a screenshot:
   ```bash
   tools/godot/screenshot.sh projects/<slug>/godot \
     projects/<slug>/artifacts/main_scene.png
   ```
   The screenshot must show the actual assets, not a blank/one-color frame.
10. Record scene paths, transforms, camera parameters, and evidence for
    `godot-gameplay` and `game-qa`.

## World plan first

Never scatter props directly into a scene. Plan, resolve, validate, then assemble:

1. Copy `templates/world_plan.json` to `projects/<slug>/docs/world_plan.json` and
   fill bounds, spawns, objectives, landmarks (with `asset` when solid), paths,
   authored obstacles, `blockers` (walls/water) and scatter rules. Use clusters
   for vegetation, `region` to keep rocks on slopes or edges, `avoid` to keep
   paths, spawns and objectives clear, and budgets for instances and repetition.
2. `lopodev world generate docs/world_plan.json --out docs/world_plan.resolved.json`
   (deterministic from `seed`; change the seed, not the code, to vary layouts).
3. `lopodev world validate docs/world_plan.resolved.json --report artifacts/world_plan.report.json --map`
   must PASS: inside bounds, no collidable overlaps, spawn and path clearance,
   every objective reachable, budgets, complete scatter. Read the ASCII map.
4. `python3 tools/godot/world_to_tscn.py docs/world_plan.resolved.json --godot-dir godot --out scenes/World.tscn`
   instances GLBs and creates `Markers/Spawn_*`, `Markers/Objective_*` for gameplay.
   Missing assets fail; generate them first instead of using placeholders.
5. In Godot, verify vertical placement (no floating/sunken props), collision
   shapes on `static` props, and a screenshot from the player's spawn.

Distinguish `collision`: `static` (blocks movement), `destructible`, `none`
(decor such as grass). Interactables belong in `objectives` or landmarks with
`interactive: true` so reachability covers them.

## Validation procedures

- Import gate: headless import exit 0 with no project-caused errors.
- Content gate: main scene instantiates; target GLB-derived node exists; mesh
  surfaces > 0; materials > 0; AABB size > 0.
- Placement gate: each asset's world transform is finite and within the level
  bounds; origin-at-ground props sit at the intended height.
- Visual gate: screenshot inspected; asset silhouette/color visible; not blank.
- Collision gate: walkable surface and blocking objects have collision shapes
  (verified by runtime movement tests in `godot-gameplay` when applicable).

## Failure recovery

- **GLB import fails** - validate the GLB outside Godot; re-export from Blender.
  Check the import log for unsupported extensions.
- **Scene instantiates but node is empty** - verify the GLB was imported before
  scene load and that the ext_resource path is exact (`res://...glb`).
- **Asset is tiny/huge** - check units and transform application in Blender; fix
  the source rather than adding compensating scale.
- **Black or blank screenshot** - add lights/environment, point the camera at
  the asset, verify non-headless launch. A screenshot that exists but is blank
  is a FAIL.
- **Missing collision** - add collision shapes explicitly; glTF meshes do not
  create collision automatically.
- **Import log errors are environmental** - classify them (renderer/locale) and
  record the warning; do not mark a project error as a pass.

## Handoff

Deliver scene paths, node map, expected target node names, camera/light setup,
collision status, and screenshot evidence. Then `godot-gameplay` attaches
mechanics.
