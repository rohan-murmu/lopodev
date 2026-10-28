---
name: asset-intelligence
description: Use to obtain the game's 3D assets, materials and characters - turn the asset list into requirements, discover openly licensed assets (local CC0 packs, Poly Haven, ambientCG), rank them, cache them, import them into Godot with collision wrappers, and generate credits. Prefer this over modeling from scratch.
license: MIT
---

# Asset Intelligence

Default asset strategy: **discover, select, adapt, assemble**. Model in Blender
only when the user asks for custom modeling or discovery has failed and a
procedural fallback would hurt the game. Deterministic code does the search,
license checks, downloads, hashing, scaling and collision; you decide intent
and review results.

## Required inputs

- `projects/<slug>/project.json` with an `assets` list. Each discovery entry:
  `id` (`sm_`/`mat_`), `class` (`static_prop`, `skeletal_character`,
  `animated_prop`, `modular_environment`, `procedural_element`, `material`,
  `hdri`), `role`, `terms`, optional `style`, `size_m` `[x,y,z]`,
  `animations` (actions: idle, walk, run, aim, shoot, reload, hit, death, jump,
  attack, interact), `collision`, `budget_triangles`, `mandatory`,
  `fallbacks` (`procedural:box|cylinder|sphere|capsule|rock|plane`,
  `requirement:<id>`, `asset:<catalog id>`), `providers`.
- Optional local packs the user downloaded (Kenney, Quaternius, KayKit, ...).

## Expected outputs

- `assets/requirements.json`, `assets/asset_manifest.json`, `assets/asset_map.json`
- `godot/assets/models/<id>.glb|<id>/` copies, `<id>.meta.json` provenance,
  `godot/assets/wrapped/<id>.tscn` (scale + collision), materials as `.tres`
- `CREDITS.md` and the generated block in `ASSET_LICENSES.md`
- `artifacts/asset_validation.json` with PASS / FAIL / NOT RUN per check

## Workflow

1. `lopodev assets providers` - see which sources are usable. Packs need
   `lopodev assets add-pack <zip|dir> --provider kenney --name <pack> --style stylized`.
   A pack without a license file is indexed as `unknown` and never auto-selected.
2. `lopodev assets requirements --project projects/<slug>` - fix every ERROR in
   `project.json`, not in the generated file. For a fresh game,
   `python3 tools/asset_requirements.py --prompt "<game prompt>"` prints a
   starting list to edit.
3. `lopodev assets search --project projects/<slug> [--requirement <id>]` -
   read the scores and reasons. Selection is metadata-based: when a provider
   has a thumbnail, look at it before approving; do not claim visual
   inspection you did not do.
4. `lopodev assets run --project projects/<slug>` (or `resolve`, `fetch`,
   `import`, `credits`, `validate` one at a time). Use `--offline` to use only
   packs and the cache.
5. Characters: prefer an asset whose own clips cover the required actions.
   The manifest's `animation_plan` lists own clips, clips borrowed from an
   identical skeleton, and `missing`. Retargeting between different skeletons
   is not automated: choose another character or animation set first; only
   then open a bounded Blender retarget task.
6. Review `rejected`, `needs_review`, `fidelity_reduced` and `provider_notes`
   in the manifest and report them.

## Change an existing asset (any Blender edit)

Reuse is the start, not the limit. To reshape, retexture, merge, rig or animate
a selected asset:

1. Add the target to `project.json`:
   `{"id": "sm_witch_well", "class": "static_prop", "source": "derived", "derive_from": "sm_water_well", "terms": ["well"]}`.
2. Inspect the source parts. The first line of a derive script can log
   `ctx.parts()`. With live mode on, `lopodev live start blender` shows it.
3. Write `projects/<slug>/blender/derive_<id>.py` with `edit(ctx)`. Any bpy is
   allowed; `tools/blender/lib_edit.py` has shortcuts. See
   `docs/examples/derive_witch_well.py`.
4. `lopodev assets derive --project P --from <source> --id <id> --script <file> [--with name=<id>]`.
   The window shows each step; the cached original is never changed.
5. Rig or animate with `lopodev assets rig --mode transfer|humanoid|parts|creature`
   (details in `docs/assets.md`).
6. Look at `artifacts/assets/<class>/<id>/before_*.png`, `after_*.png` and the
   `clip_*` frames before reporting. Check `rig_weights` and Godot
   `animation_playback` in `lopodev assets validate`.

## Validation

`lopodev assets validate --project projects/<slug>` must be `PASS`. Godot
import, mesh and animation playback checks run when Godot is available
(`godot_import`, `animation_playback`); otherwise they are `NOT RUN` and must
be reported as such. Then render the wrapped scene or run the world screenshot
for a visual check.

## Failure recovery

- Provider down: other sources are used automatically; `provider_notes` says so.
- `unmet`: add a pack, widen `terms`, add a `fallbacks` entry, or mark the
  requirement `mandatory: false` with the user's agreement. Never use an asset
  whose license is unknown, NC, ND or excluded by policy.
- `rejected_after_inspection`: the file disproved provider metadata (for
  example no skin). Run `resolve` again; the asset is excluded automatically.
- Scale flagged as centimeters: set `size_m` so the wrapper scales it.
- `.fbx`/`.obj`/`.blend`: needs a Blender conversion task (`blender-modeling`,
  processing mode) to produce glTF; the original stays in the cache.
- Import refuses to overwrite a file it did not write: rename the id or move
  the user's file; never delete user work.

## Handoff

Give `level-design` the `assets/asset_map.json` (world assembly uses it via
`--asset-map`), `gameplay` the character wrapper scenes and animation map, and
`qa-release` the validation report path.
