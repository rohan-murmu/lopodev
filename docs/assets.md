# Asset intelligence and procedural worlds

LopoDev's default is **discover, select, adapt, assemble**. The planner writes
what the game needs; deterministic tools find openly licensed assets, check
licenses, cache files, measure them, import them into Godot with collision,
and generate credits. Environments are generated from a seeded world plan.
Blender is optional processing.

```text
project.json assets ──► requirements.json ──► providers ──► ranking ──► asset_manifest.json
   (planner intent)       (normalized)         (search)     (hard filters + score)
                                                                   │
        CREDITS.md ◄── credits      catalog/cache ◄── fetch ◄──────┘
        ASSET_LICENSES.md            (originals by sha256, inspected)
                                                │
   world_plan.json ─► world generate ─► resolved plan          import ─► godot/assets/{models,wrapped,materials}
   (level intent)     (Poisson, terrain,   │                     │       + asset_map.json + Godot playback check
                       exclusions)          ▼                     ▼
                                     world validate ─► world_to_tscn ─► World.tscn ─► nav_check.gd
                                     (reachability,     (ground/terrain, light,      (bake + paths)
                                      enemy nav, LOS)    NavigationRegion3D)
```

## Commands

| Step | Command |
|---|---|
| Sources and status | `lopodev assets providers` |
| Add a downloaded pack | `lopodev assets add-pack <zip\|dir> --provider kenney --name <pack> [--style stylized] [--tag nature]` |
| Starting asset list from a prompt | `python3 tools/asset_requirements.py --prompt "<game prompt>" --style stylized` |
| Normalize requirements | `lopodev assets requirements --project projects/<slug>` |
| Rank candidates (no download) | `lopodev assets search --project projects/<slug> [--requirement <id>] [--offline]` |
| Everything | `lopodev assets run --project projects/<slug> [--offline] [--no-godot]` |
| Stages | `resolve`, `fetch`, `import`, `credits`, `validate [--strict]` |

The cache is per user: `$LOPODEV_DATA/assets/` (`~/.local/share/lopodev/assets`).

## Sources

| Provider | Interface | License | Automated |
|---|---|---|---|
| Kenney | packs you download (no API) | CC0, `License.txt` in each pack | no |
| Quaternius | packs you download (no API) | CC0, license file in each pack | no |
| KayKit | packs you download (itch.io) | CC0, license file in each pack | no |
| Poly Haven | official API `api.polyhaven.com` (identifying User-Agent required by its ToS) | CC0 | yes |
| ambientCG | official API `ambientcg.com/api/v2/full_json` | CC0 | yes (materials) |
| Poly Pizza | API needs a key; per-asset CC0/CC-BY | per asset | no adapter |
| OpenGameArt | no documented API; mixed licenses | per asset | no (manual pack with `--license`) |

Registry: `resources/asset_sources.json`. A new provider is an adapter class in
`tools/asset_sources.py` (`status`, `search`, `fetch`) plus a registry entry.
No scraping: a provider without a supported interface is registered as
`unavailable` with the reason.

When a pack is added, its own license file decides the license. No license
file means `unknown`; conflicting files mean `unknown`. Unknown assets are
never selected automatically. `--license` is for a license you verified
yourself, and it is refused if it contradicts the pack's own file.

## License policy

`license_policy` in the registry is a hard filter, applied before scoring:

- `allowed`: CC0-1.0
- `allowed_with_attribution`: CC-BY-3.0/4.0, OGA-BY-3.0 (credits generated)
- `review`: CC-BY-SA, GPL/LGPL, anything not listed (never auto-selected; listed under `needs_review`)
- `rejected`: NC, ND, proprietary, unknown

## Contracts

Three different documents, never conflated:

1. **Requirement** (`assets/requirements.json`, `lopodev.asset-requirements/1`)
   - what the game needs: `id`, `class`, `role`, `terms`, `style`, `size_m`,
   `formats`, `rig` (`none|optional|required`), `animations` (actions),
   `collision` (`none|box|sphere|capsule|cylinder|convex|trimesh`),
   `budget_triangles`, `texture_max_px`, `mandatory`, `fallbacks`,
   `providers`, `resolution` (`discover|generate|provided`).
2. **Asset record** (catalog) - what an asset provides: `asset_id`,
   `provider`, `provider_id`, `source_url`, `license` (`id`, `evidence`,
   `creator`, `attribution`), `format`, `local` (`path`, `sha256`),
   `original` (archive hash), `capabilities` (`triangles`, `size_m`,
   `skinned`, `joints` with parents, `animations`, `importable`,
   `verified_by`: `provider_metadata` or `inspection`), `inspection`,
   `history`.
3. **Validation report** (`artifacts/asset_validation.json`,
   `lopodev.asset-validation/1`) - what was verified, per requirement and
   check, as PASS / FAIL / NOT RUN.

The **manifest** (`assets/asset_manifest.json`, `lopodev.asset-manifest/1`)
links them: per requirement the `status` (`selected`, `fetched`, `imported`,
`fallback`, `unmet`, `generate`, `provided`, `rejected_after_inspection`),
the chosen asset with score, score parts and reasons, the snapshot license,
`animation_plan`, `alternatives`, `rejected` with reasons, `needs_review`,
`fidelity_reduced`, `import` (Godot paths, normalization, collision, Godot
check) and a `history` of every selection change. `owned_files` records hashes
of files LopoDev wrote into the Godot project; import never overwrites a file
it did not write.

## Ranking

Hard filters: license, kind (model/material/hdri), rig required but no skin,
more than twice the triangle budget, missing files. Survivors are scored
(weights in the registry):

| Part | Meaning |
|---|---|
| semantic | requirement terms in provider tags/categories (1.0), title tokens (0.6), synonyms (0.3) |
| style | overlap with the requested art style |
| technical | glb 1.0, gltf 0.9, zip 0.8, other formats 0.3 (need conversion) |
| rig | skinned when a rig is needed |
| animation | share of required actions mapped to clips |
| budget | triangles within budget |
| collision | measured size within 0.5x-2x of `size_m` |

Every selection stores its reasons and the alternatives. Selection uses
metadata and inspected geometry, not images. Thumbnails are recorded so a
human or a vision-capable model can check them.

A previous selection is kept on re-resolve (`--reselect` re-picks) unless it
became ineligible. The change is then recorded in `history`. After download,
the file is inspected and the hard filters run again. Provider metadata that
the file disproves (for example "rigged" but no skin) makes the asset
`rejected_after_inspection`, and it is excluded on the next resolve.

## Characters and animation

`animation_plan` per character:

- `own`: required action -> clip in the model (aliases: shoot ~ fire/attack,
  hit ~ hitreact/hurt, death ~ die, ...; plain clips win over compound ones).
- `external`: clips from other cached assets whose skeleton is `identical`
  (same normalized bone names and parents, `mixamorig:`/`DEF-` prefixes
  ignored) or `name_compatible` (>=70% names, >=90% parent agreement).
- `missing`: unresolved actions (validation FAIL).

`identical` is not proof: rest poses still need a playback check.
`name_compatible` needs a retarget, which is not automated. Validation reports
it as NOT RUN, and the resolver prefers a character that covers the actions
itself. `lopodev assets import` loads each wrapper in headless Godot and plays
every expected clip. A clip that moves no bone fails `animation_playback`.

## Godot import

For each selection: the original stays in the cache; the project gets
`godot/assets/models/<id>.glb` (or a glTF folder), `<id>.meta.json`
(provenance, normalization, collision), and `godot/assets/wrapped/<id>.tscn`:

- uniform scale toward `size_m` when the measured size is outside 0.8x-1.25x;
- a `StaticBody3D` with a box, sphere, cylinder or capsule sized from the
  measured bounds (convex/trimesh requests fall back to a box with a note);
- no static body for characters (gameplay owns the `CharacterBody3D` capsule);
- materials become `assets/materials/<id>.tres` from color/normal/roughness maps.

Procedural fallbacks (`procedural:box|cylinder|sphere|capsule|rock|plane`) produce a
wrapper with a primitive mesh and collision and are marked `fidelity_reduced`.

## Changing existing assets (derive)

Any downloaded (or generated) asset can be changed with the full power of
Blender. The cached original is never modified; the result is a new asset with
its own record, license and images.

```sh
lopodev assets derive --project P --from sm_water_well --id sm_witch_well \
    --script projects/<slug>/blender/derive_sm_witch_well.py [--with skull=sm_skull] [--live|--headless]
lopodev assets derive --project P --from sm_water_well --id sm_witch_well --from-blend edited.blend
```

- The script defines `edit(ctx)` and may use any Blender API (`ctx.bpy`). The
  helpers in `tools/blender/lib_edit.py` are shortcuts:
  - inspection: `parts`, `find`, `stats`;
  - materials: `recolor`, `set_material`/`material(emission=)`;
  - geometry: `add`, `place`, `remove`, `modifier`, `noise_displace`,
    `boolean`, `decimate`, `join`, `uv_unwrap`, `set_origin_ground`;
  - other assets: `extra(name)` for assets merged with `--with`.
  - Example: `docs/examples/derive_witch_well.py`.
- In live mode the edit runs in a visible Blender window, step by step.
- **Outputs:**
  - `projects/<slug>/blender/<id>.blend` (editable);
  - a GLB in the cache;
  - `artifacts/assets/<class>/<id>/before_*.png`, `after_*.png` and
    `clip_*` frames;
  - the provenance record (`provider: derived`, `derived_from` with source
    hashes, script, Blender version, operations log);
  - the normal Godot import (wrapper, collision, import and playback check).
- **License is inherited:** CC0 stays CC0; any CC-BY input makes the result
  CC-BY with "(modified)" attribution; ND, NC, share-alike and unknown sources
  are refused.
- **Reruns:** a rerun with the same source, script and LopoDev Blender scripts
  is a no-op. An existing `.blend` LopoDev did not write is never overwritten.
- **Declaring the asset:** add it to `project.json` as
  `{"id": "sm_witch_well", "source": "derived", "derive_from": "sm_water_well", ...}`.
  Until it is derived, validation reports a FAIL with the exact command (NOT
  RUN when it is optional).

## Rigging and animating existing models

```sh
lopodev assets rig --project P --from <id> --id <new id> --mode transfer --donor <rigged id>
lopodev assets rig --project P --from <id> --id <new id> --mode humanoid --clip idle --clip walk
lopodev assets rig --project P --from <id> --id <new id> --mode parts --clip "lid_open:Lid:rotate_x:-80:1.0"
lopodev assets rig --project P --from <id> --id <new id> --mode creature --chain "Tail=0,0.5,0.4:0,1.4,0.3:6"
```

| Mode | What it does | Best for |
|---|---|---|
| `transfer` | scales the model to a rigged donor, copies its skeleton and skin weights (Data Transfer), keeps the donor's clips | characters similar to a rigged pack character; reuses its whole animation set |
| `humanoid` | fits Rigify's basic human metarig (29 deform bones) to the mesh bounds, automatic weights, built-in clips (idle, walk, run, attack, hit, death) | humanoids with no donor |
| `parts` | pivots and animates named rigid parts (rotate, move, bob, scale) | props: doors, lids, buckets, cranks, roofs |
| `creature` | bone chains from given coordinates, automatic weights, sway clip | tails, tentacles, necks |

Rig mode writes `projects/<slug>/blender/rig_<id>.py`, a reproducible derive
script you can edit, and runs it through derive. Checks:

- every clip exported and playing in Godot (`animation_playback`);
- `rig_weights` (unweighted vertices, deform bones without influence);
- clip frames under `artifacts/assets/`.

Automatic weights often deform badly at elbows and knees, and the built-in
humanoid clips are simple. Look at the frames, and prefer `transfer` from a
good pack character.

## Asset image library

`lopodev assets previews --project P` (also part of `run`) writes
`artifacts/assets/<class>/<id>/` for every selected asset:

- `front.png`, `three_quarter.png`, `top.png` rendered from the actual file;
- `source_thumbnail.png` from the provider when it has one;
- before/after and clip frames for derived and rigged assets.

It also writes the gallery `artifacts/assets/index.md`. Renders are skipped
while the file's hash is unchanged (`--reselect` forces them).

## Procedural worlds

`tools/world_plan.py` adds to the existing plan format:

- `terrain`: `{"type": "noise", "amplitude", "scale", "octaves", "seed",
  "max_walkable_slope_deg", "flatten": [{"pos", "radius", "falloff"}]}`;
  placements get `y` from the heightfield;
- scatter `distribution: "poisson"` (blue noise), `max_slope_deg`, and
  per-rule rejection counts in `generation`;
- `exclusions` (circles `[x, z, r]` or boxes) for collidable scatter;
- `enemy_spawns` + `enemy_radius`, `sightlines`, `combat_zones`
  (`max_cover_ratio`, `min_cover_ratio`);
- spatial hashing for spacing and overlap queries.

`validate` adds `exclusions_clear`, `on_terrain`, `slope`, `enemy_navigation`,
`sightlines` and `combat_zones`, plus walkable-region metrics. When a check
fails, change the parameters and regenerate. Do not hand-move scatter.

`tools/godot/world_to_tscn.py` writes: `WorldEnvironment`, a sun,
`Ground` (box collision and plane, or `HeightMapShape3D` with a
runtime-built mesh from `scripts/world/heightfield_mesh.gd`, optional ground
material from the asset map), `Navigation` (`NavigationRegion3D` baking from the
`navigation_geometry` group with the enemy radius), `Props`, and `Markers`
(`Spawn_*`, `Enemy_*`, `Objective_*`, `Landmark_*`).

`tools/godot/checks/nav_check.gd` bakes the navmesh in headless Godot and
requires a complete path from every `Enemy_*` to the player spawn and from
the spawn to every `Objective_*`.

## Limitations

- Kenney, Quaternius and KayKit have no search API, so their packs are
  downloaded by hand. Poly Pizza and OpenGameArt have no adapter.
- Poly Haven models are photoscans, typically 10k-150k triangles. Mobile
  budgets reject many of them; desktop budgets accept more.
- Selection does not look at images. Visual fit is a human or vision-model
  check of the recorded thumbnails and of the rendered scene.
- Retargeting between different skeletons is detected, not performed. `rig
  --mode transfer` is the practical alternative: the model takes the donor's
  skeleton and clips.
- Preview renders use Workbench studio lighting. Colors read lighter than in
  the game, and emission is not shown as glow.
- Collision is primitive per asset. Exact convex/trimesh shapes need Godot
  import options.
- Navigation checks prove connectivity, not combat quality. Frame time is
  measured by the existing runtime and optimization gates, not here.
