---
name: blender-animation
description: Use when a game spec requires a rigged or animated asset, including looping prop motion, armature setup, action authoring in Blender, GLB animation export, and verification that Godot imported the animation channels.
license: MIT
---

# Blender Animation

**Role:** fallback. Characters come from `asset-intelligence` with their own
clips when possible; the manifest's `animation_plan` lists the action -> clip
map, compatible external clips and `missing` actions, and `lopodev assets
import` proves playback in Godot. Use this skill only for a bounded rig,
retarget or clip task that resolution could not satisfy. Start with
`lopodev assets rig`:
- `--mode transfer --donor <rigged id>` (skeleton, weights and clips from a
  similar rigged asset);
- `--mode humanoid` (Rigify basic human metarig with automatic weights);
- `--mode parts` (rigid moving parts of props);
- `--mode creature` (bone chains).

Then refine in a derive script if the frames show problems. Matching bone names
do not prove a retarget works: verify rest pose, orientation, root motion and
playback in Godot.

Author a reusable armature and named actions in Blender, export animation in the
GLB, and prove the channels survive the Blender -> glTF -> Godot handoff.

## Required inputs

- Asset brief and animation requirements from `project.json` / `GAME_SPEC.md`:
  asset id, clip names (`anim_<verb>`), frame rate, loop behavior, root motion
  policy, and what the clip must look like.
- The validated static asset, or permission to generate the animated asset.
- Output paths:
  - source `projects/<slug>/blender/<asset_id>.blend`
  - export `projects/<slug>/godot/assets/models/<asset_id>.glb`
  - report `projects/<slug>/artifacts/<asset_id>.animation.json`
- `tools/blender/api_report.py` output for the installed Blender version.

## Expected outputs

- Editable `.blend` with an armature, mesh weights, and one or more named
  actions (`anim_<verb>`), not an unassigned action datablock.
- GLB with animation accessors, sampler input/output, and skin data when a rig
  is present.
- Animation validation report listing clip names, channel counts, duration, and
  whether loop endpoints match where required.
- Godot content-check result showing the imported `AnimationPlayer` and clip
  names.
- Optional rendered preview/GIF or frame strip from the actual scene.

## Rig and animation conventions

- 24 fps default; declare any other rate in the spec.
- One action per clip; action name starts with `anim_` (for example
  `anim_spin`, `anim_idle`, `anim_walk`).
- Props that only spin/bob use a single root bone (`root`) and rigid weights.
- Characters: root -> hips -> spine -> head chain plus limbs; keep bone roll
  consistent and document the rig in the project docs.
- Loops must have matching first/last poses for position and rotation channels.
- Scale keys only when required; prefer rotation/location.
- Do not bake root motion unless the gameplay spec explicitly requests it.

## Workflow

1. Read the animation requirements and confirm frame rate, loop, and duration.
2. Inspect the installed exporter API:
   ```bash
   tools/blender/run.sh api_report.py
   ```
   Confirm `export_animations`, `export_animation_mode`, and related defaults
   rather than assuming them.
3. Generate a starter animated prop or extend the rig helper:
   ```bash
   tools/blender/run.sh make_animated_prop.py \
     --kind gem --out-dir projects/<slug> --name sm_gem
   ```
4. Inspect the `.blend` action: it must be assigned to the armature (or stashed
   in an NLA strip that the exporter reads) and contain the expected keyframes.
5. Export GLB from the same script with animation enabled and sampling on for
   deterministic results. Never hand-edit the GLB.
6. Validate the GLB independently, including animation:
   ```bash
   python3 tools/blender/validate_asset.py \
     projects/<slug>/godot/assets/models/sm_gem.glb \
     --require-animation --require-material --max-triangles 2000 \
     --report projects/<slug>/artifacts/sm_gem.animation.json
   ```
7. Import the GLB in Godot and check the imported AnimationPlayer:
   ```bash
   tools/godot/validate.sh projects/<slug>/godot
   ```
   Set `TARGET_ANIM=anim_spin` (or the actual clip name) for the check.
8. Run a runtime smoke test proving the clip is present and plays, not only that
   it exists in the file.
9. For visual clips, launch graphically and inspect a screenshot or recorded
   frames. Headless success is not visual proof.

## Validation procedures

- Animation gate: validator sees `animations.length >= 1`, channels > 0, and
  expected clip names when `--expect-animation <name>` is supplied.
- Loop gate: first/last sampled values match within tolerance for required
  channels.
- Content gate: Godot `AnimationPlayer.has_animation("anim_<verb>")` is true.
- Runtime gate: clip plays and advances state across processed frames.
- Visual gate: screenshot/frames show the posed asset, inspected and recorded.

## Failure recovery

- **GLB has zero animations** - check the action is active/stashed, NLA settings,
  and exporter animation mode; re-export with `export_force_sampling=True`.
- **Animation exists but Godot reports none** - verify the clip name after
  import (`AnimationPlayer.get_animation_list()`), run the Godot import gate, and
  inspect the import log. Do not rename the GLB by hand.
- **Wrong pivot or axis** - fix armature orientation/export settings; remember
  glTF is +Y up while Blender is +Z up.
- **Loop pop** - add matching endpoint keys and re-validate the loop gate.
- **Missing skin/weights** - confirm the mesh has a vertex group for every
  deforming bone and an Armature modifier before export.
- **Preview cannot render** - mark visual verification as NOT RUN and state why.

## Handoff

Deliver the animated GLB, `.blend`, animation report, exact clip names, frame
rate, duration, loop status, and Godot AnimationPlayer evidence.
