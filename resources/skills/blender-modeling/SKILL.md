---
name: blender-modeling
description: Use for bounded Blender asset processing (format conversion, pivot/origin fixes, cleanup, decimation, UV or material repair) requested by asset-intelligence, or for custom models the user explicitly asks for or that discovery could not supply. Saves editable .blend files, exports GLB, validates before Godot import.
license: MIT
---

# Blender Modeling

**Three modes, any art style:**

- **derive:** change an existing asset (`lopodev assets derive`, script with
  `edit(ctx)`, any bpy);
- **processing:** convert, fix pivots, decimate, repair UVs/materials (also a
  derive);
- **custom:** model from scratch when the user asks or nothing suitable
  exists (`"source": "custom"`).

**Role:** optional processing, not the default way to get assets. First run
`asset-intelligence` (`lopodev assets run`). Use this skill when a manifest
entry needs conversion or repair (input: the cached original path from
`assets/asset_manifest.json`; output: a new GLB under `godot/assets/models/`,
never an edit of the original), or when the user asked for a custom model or
discovery and procedural fallbacks failed.

Generate or modify deterministic assets with Blender Python, in the project's art style within the platform budget. Every asset leaves
this skill as an editable source plus a game-ready GLB and a machine-readable
report. No asset is considered done until an independent validator passes.

## Required inputs

- `projects/<slug>/project.json` and `GAME_SPEC.md` from `game-planner`.
- Asset brief per model: `id`, noun, purpose, dimensions in meters, palette,
  triangle budget, collision expectations, animation requirement (if any).
- Blender version and API facts from `docs/environment-audit.md`.
- Output paths following `AGENTS.md`:
  - source `projects/<slug>/blender/sm_<noun>.blend`
  - export `projects/<slug>/godot/assets/models/sm_<noun>.glb`
  - report `projects/<slug>/godot/assets/models/sm_<noun>.meta.json`
  - QA log `projects/<slug>/artifacts/logs/`

## Expected outputs

- Editable `.blend` with the final mesh, material(s), applied transforms, and
  origin at ground contact.
- Binary glTF `.glb` containing the mesh and material, exported with +Y up.
- `.meta.json` sidecar with bounds, triangle count, material list, source hash,
  generator command, and validation status.
- Validation JSON and console log in `artifacts/`.
- An optional preview render for visual inspection
  (`artifacts/previews/sm_<noun>.png`).

## Workflow

1. Read the asset brief and check budgets. Reject unclear dimensions before
   generating geometry.
2. Verify Blender API compatibility if the script or Blender version changed:
   ```bash
   tools/blender/run.sh api_report.py
   ```
   This prints the actual Blender/Python versions and glTF exporter properties.
3. Generate the asset with the reusable generator, one asset per invocation:
   ```bash
   tools/blender/run.sh make_prop.py \
     --kind crate \
     --out-dir projects/<slug> \
     --name sm_crate
   ```
   Supported starter kinds: `crate`, `barrel`, `rock`, `pillar`. Extend the
   generator in a new helper function rather than cloning the whole script.
4. Match the project's `art_style` and stay within the platform budget. Keep one material unless the brief
   requires more. Do not use paid add-ons or downloaded textures.
5. Confirm origin at ground contact (`min Z == 0` after generation), real-world
   scale, and applied rotation/scale.
6. Validate independently of the generator:
   ```bash
   python3 tools/blender/validate_asset.py \
     projects/<slug>/godot/assets/models/sm_<noun>.glb \
     --min-triangles 50 --max-triangles 2000 --require-material \
     --report projects/<slug>/artifacts/sm_<noun>.validate.json
   ```
7. For visual assets, render a preview from a fixed three-quarter camera and
   inspect it before claiming the look is acceptable. The render must use the
   actual Blender scene, not a placeholder.
8. Hand off the GLB path, meta path, triangle count, bounds, and validation
   result to `game-world`. If animation is required, hand off to
   `blender-animation` before level integration.

## Art quality: silhouette first, reference driven

A valid mesh is not an acceptable model. Work in passes and look at every pass:

1. **Brief**: from the spec or reference image, write down silhouette, proportions
   (real-world meters), 3-5 color palette, material zones and the 3 details that
   make the object recognizable (a cottage: roof tiles, timber frame, stone base,
   panelled door with hinges). Record these as visual acceptance criteria.
2. **Primary forms**: block the silhouette with correct proportions only. Render
   `--views front,right,top,three_quarter` and compare against the brief.
3. **Secondary forms**: bevels on visible edges, overhangs, insets, layered
   pieces (trim, frames, supports). Every triangle must change the silhouette or
   a material boundary; flat shading needs deliberate edge breaks.
4. **Tertiary detail and material**: palette materials (or one atlas), value
   contrast between zones, a little hue variation across repeats.
5. **Review**: render the views again with
   `python3 tools/blender/render_preview.py --blend <file> --out <png> --views front,right,top,three_quarter`
   and inspect them yourself. Fix proportion errors, floating parts, missing
   brief details and muddy palettes before exporting. With a reference image,
   load `concept-target-visual-gate` and keep a short mismatch ledger; never lower
   the target to declare success.

For a faceted/flat-shaded look (when `art_style` asks for it) load `blender-lpm-skill` (export through LopoDev's GLB
pipeline, not its FBX path). For modular kits keep a shared grid (1 m or 2 m),
pivots at ground contact, and consistent trim heights so pieces snap.
Live inspection through Blender MCP (`look`, `viewport_capture`) is welcome; the
saved generator script remains the source of truth.

## Validation procedures

- Generation gate: generator exit 0; `.blend`, `.glb`, `.meta.json` exist and
  are non-empty.
- Asset gate: `validate_asset.py` passes magic/version/chunks, mesh count,
  material presence, finite bounds, triangle budget, and file size.
- Naming gate: file base name starts with `sm_`; no spaces; lowercase snake_case.
- Unit gate: bounds match the brief within tolerance; origin at ground.
- Visual gate (when claimed): preview screenshot inspected and recorded.

## Failure recovery

- **Blender exits non-zero** - capture the full log to `artifacts/logs/`, run
  `tools/blender/api_report.py`, and check for renamed operators or properties.
  Fix the script; do not hand-edit the GLB.
- **Asset too many triangles** - dissolve coplanar faces, use flat primitives,
  or reduce bevel segments. Re-run the validator.
- **Material missing in GLB** - confirm the material is assigned to the mesh
  before export and that `export_materials='EXPORT'`; inspect the GLB JSON with
  `validate_asset.py --dump-json`.
- **Wrong scale/orientation** - fix the source `.blend` and re-export. Never
  compensate with a non-unit Godot import scale unless documented.
- **GLB validator fails** - reject the asset. Re-export from a clean scene with
  `bpy.ops.wm.read_factory_settings(use_empty=True)`.
- **No preview available** - state "VISUAL NOT VERIFIED"; do not claim the
  asset looks correct.

## Handoff

Deliver in this order: validated `.glb`, `.meta.json`, `.blend`, validation
report, optional preview, and a one-line summary with triangle count and bounds.
