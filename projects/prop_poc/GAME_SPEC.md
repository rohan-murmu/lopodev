# Prop Pipeline PoC - Game Specification

Status: in progress
Slug: `prop_poc`
Target: Linux x86_64, Godot 4.6.1 (`gl_compatibility`), Blender 5.2.2
First milestone: one Blender-generated prop visible and rotating in a Godot scene

## Purpose

This is a technical vertical slice, not a game. It proves that the pipeline can
generate a low-poly prop, export GLB, validate it independently, import it into
Godot, run a scene, render it, and build a Linux executable, with evidence at
each step.

## Scope

Must have:

- Procedural low-poly wooden crate authored in Blender with origin at ground.
- Editable `.blend`, binary GLB, and `.meta.json` sidecar.
- Independent GLB validation: header, meshes, materials, bounds, triangles.
- Godot main scene with camera, directional light, ground, HUD label, and the
  imported crate instance.
- Slow crate rotation so runtime tests can observe a state change.
- Headless content and runtime gates.
- Graphical screenshot from a real launch, inspected by a human/agent.
- Linux release build that runs headless for a bounded frame count.
- Animated gem asset proving armature + action export and Godot clip import.

Explicit non-goals:

- Player movement, input, combat, inventory, audio, UI flow.
- Level design beyond one presentation scene.
- Collision, navigation, or a win/lose loop.
- Third-party art or paid services.

## Controls

None. The crate rotates automatically for demonstration.

## Scene and flow

- Main scene: `res://scenes/Main.tscn`
- Start state: camera looks at the crate on a ground plane; HUD explains the PoC.
- Behavior: crate rotates around +Y at 0.6 rad/s.
- Exit: close the window. Automated visual checks quit after saving a screenshot.

## Assets

| ID | Kind | Source | Triangles | Animated | Notes |
|---|---|---|---|---|---|
| `sm_crate` | prop | procedural | 180 | no | 1.04 x 1.08 x 1.0 m, 2 materials |
| `sm_gem` | pickup | procedural | 20 | yes | 1 bone, `anim_spin`, 2.0 s loop |

All assets are generated in this repository. No third-party licenses apply.

## Milestones and tasks

| ID | Task | Skill | Verification | Status |
|---|---|---|---|---|
| T1 | Generate crate | blender-modeling | make_prop.py + .blend/.glb/meta exist | pending |
| T2 | Validate crate | blender-modeling | validate_asset.py | pending |
| T3 | Animated gem | blender-animation | validate_asset.py --require-animation | pending |
| T4 | Godot scene | game-world | validate.sh | pending |
| T5 | Runtime smoke | godot-gameplay | smoke.sh | pending |
| T6 | Visual gate | game-qa | screenshot.sh + inspection | pending |
| T7 | Build gate | game-qa | export_build.sh | pending |

## Acceptance criteria

| ID | Criterion | Gate | Evidence |
|---|---|---|---|
| A1 | Crate GLB passes structural, material, bounds, budget checks | asset | `artifacts/sm_crate.validate.json` |
| A2 | Main scene contains imported crate mesh with materials | content | `artifacts/qa_report.json` |
| A3 | 40 headless frames processed; rotation changes | runtime | `artifacts/qa_report.json` |
| A4 | Non-blank graphical screenshot inspected | visual | `artifacts/screenshots/main_scene.png` |
| A5 | Godot imports `anim_spin` AnimationPlayer clip | content | `artifacts/sm_gem.animation.json` |
| A6 | Linux build runs headless with exit 0 | build | `artifacts/qa_report.json` |

## Assumptions and open questions

- The imported GLB scene root can be instanced directly in the `.tscn`; confirmed
  by the content gate.
- `gl_compatibility` is sufficient for the visual gate; confirmed by the
  environment audit and screenshot.
- The pipeline owns generated files under `projects/prop_poc/`; manual changes to
  those files will be overwritten by regeneration.
