---
name: blender-modeling
description: Use when a validated game spec requires low-poly 3D props or environment assets that must be generated in Blender, saved as editable .blend files, exported to GLB, and validated before Godot import.
license: MIT
---

# Blender Modeling

Generate deterministic, low-poly assets with Blender Python. Every asset leaves
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
4. Use flat-shaded, low-poly geometry. Keep one material unless the brief
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
