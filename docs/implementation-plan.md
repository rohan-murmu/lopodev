> **Superseded for LopoDev.** This document records the first-draft
> single-agent milestone plan. See `docs/lopodev-architecture.md` for the
> current agent team, commands, state, and verification plan.

# Implementation Plan

## Goal

A reusable, zero-cost pipeline in which an agent can specify, generate, validate,
integrate, run, test, and build 3D games with Blender, Godot, and
OpenCode. This first deliverable establishes the audit, skills, agent contract,
reusable tools, and one complete vertical slice. It does not attempt a full game.

## Architecture

```text
game request
    |
    v
[game-planner] --> project spec + ordered tasks + acceptance criteria
    |
    v
[blender-modeling] --> .blend + GLB + asset report
[blender-animation] --> rigged/animated .blend + GLB + animation report
    |
    v
[game-world] --> Godot scenes/levels, imported GLB instances, lighting
[godot-gameplay] --> GDScript systems, input, signals, animation wiring
    |
    v
[game-qa] --> import check, content check, runtime smoke, screenshot,
              export, exported-build smoke, evidence report
    |
    v
playable project + build + known limitations
```

Skills live in `resources/skills/<name>/SKILL.md` and are linked into each platform's discovery path. Shared contracts live in
`AGENTS.md`. Executable helpers live in `tools/` and never depend on a model
call. Global agent registration and resume behavior are documented in
`docs/agent-orchestration.md`.

## Naming and layout contract

```text
projects/<game_slug>/
  project.json                  # spec, status, tool versions, evidence paths
  GAME_SPEC.md                  # human-readable scope and acceptance criteria
  ASSET_LICENSES.md             # required if non-generated assets are used
  blender/                      # editable .blend sources
  godot/
    project.godot
    assets/models/sm_<asset>.glb
    assets/models/sm_<asset>.meta.json
    scenes/*.tscn
    scripts/*.gd
    .pipeline/                  # gitignored staged QA scripts
  artifacts/                    # test JSON, logs, screenshots
  build/                        # gitignored export output
  docs/                         # per-game notes, report
```

- Files: `snake_case`. Blender objects / Godot mesh assets: `sm_<noun>`,
  materials `mat_<noun>`, rigs `rig_<noun>`, animations `anim_<verb>`,
  scenes `PascalCase.tscn`, scripts `snake_case.gd`.
- Units: 1 Blender unit = 1 Godot meter. Generated props are authored with
  origin at ground contact and +Z up in Blender; glTF export uses +Y up.
- Original budget (superseded by `resources/budgets.json`): props 50-2,000 triangles; characters 500-6,000; one material
  per asset unless a documented reason exists.

## Milestones and acceptance criteria

### M0 - Audit and checkpoint (complete when checked)

- [ ] `docs/environment-audit.md` records actual versions, paths, verified
      commands, and missing dependencies.
- [ ] Empty repository preserved; Git initialized with a checkpoint commit.
- [ ] `.tools/` (Godot binary) and Godot caches/builds are gitignored.

### M1 - Skills and agent contract

- [ ] Skills exist at `resources/skills/{game-planner,blender-modeling,
      blender-animation,game-world,godot-gameplay,mobile-game,
      lopodev-workflow,game-qa}/SKILL.md`.
- [ ] Each has valid YAML frontmatter (`name` equals folder, non-empty
      description), required inputs, outputs, numbered workflow, validation
      commands, and failure recovery.
- [ ] Root `AGENTS.md` defines cooperation, naming, test gates, safety, Git
      checkpoints, and the completion report format.

### M2 - Blender tooling

- [ ] `tools/blender/make_prop.py` generates at least `crate`, `barrel`, and
      `rock`, saves an editable `.blend`, exports GLB, and writes a metadata
      sidecar.
- [ ] `tools/blender/make_animated_prop.py` generates a rigged pickup with a
      looping action, saves `.blend`, exports GLB with animation.
- [ ] `tools/blender/validate_asset.py` independently parses GLB, checks magic,
      version, JSON/BIN chunks, mesh/material presence, bounds, triangle budget,
      and (optionally) animation channels. Exit code is non-zero on failure.
- [ ] `tools/blender/api_report.py` prints actual Blender/Python/glTF operator
      capabilities for compatibility audits.

### M3 - Godot tooling

- [ ] `tools/godot/validate_project.gd` loads the main scene, verifies the GLB
      source exists, instantiates the scene, checks the target node and mesh
      surfaces/AABB, and optionally checks an AnimationPlayer clip.
- [ ] `tools/godot/runtime_smoke.gd` runs the scene for real frames and asserts
      runtime behavior (nodes present, rotation changes when expected).
- [ ] `tools/godot/stage_checks.sh` stages QA scripts into the project without
      modifying authored files.
- [ ] `tools/godot/export_build.sh` runs import + Linux release export and
      verifies the executable exists and is non-trivial in size.

### M4 - End-to-end PoC

- [ ] Generate one crate in Blender; save `.blend`; export GLB.
- [ ] Validate the GLB independently: valid header, >0 meshes, >0 triangles,
      materials, finite bounds within budget.
- [ ] Import GLB into a Godot 4.6 project and instance it in `main.tscn` with
      camera, light, and ground.
- [ ] Headless project validation passes and prints a JSON report.
- [ ] Headless runtime smoke passes after processing frames.
- [ ] Graphical launch on `DISPLAY=:0` writes a non-blank screenshot; the
      screenshot is inspected, not merely assumed.
- [ ] Linux release build is produced; the exported executable passes a headless
      smoke run.
- [ ] `projects/prop_poc/artifacts/` contains logs/reports, and
      `projects/prop_poc/docs/poc-report.md` lists actual evidence and limits.

## Verification commands

```bash
tools/check_env.sh
tools/run_poc.sh
```

`tools/run_poc.sh` is idempotent for generated assets: it rewrites only files it
owns under `projects/prop_poc/`. It does not delete user-authored files.

## Risks and mitigations

| Risk | Mitigation |
|---|---|
| Godot not on `PATH` | Pinned `.tools/godot/...` resolved by `tools/env.sh`. |
| Blender 5.x API drift | Introspect operators with `api_report.py`; fail loudly, never assume success. |
| Headless checks pass but visuals are wrong | Mandatory graphical screenshot plus human/agent inspection. |
| Export template mismatch | Engine and templates pinned to the same 4.6.1 stable build. |
| Disk/GPU constraints | Platform budgets, compatibility renderer, small scenes. |
| Unbounded inference cost | Small milestones, deterministic scripts, no model calls inside tools. |
| Corrupting user work | Git checkpoints, no destructive deletes, generated files confined to owned paths. |

## Next milestones (not part of this deliverable)

1. Rigged humanoid with idle/walk/run/jump animation set.
2. Third-person controller and one playable level.
3. Interaction/system tests (pickup, health, win condition).
4. Blender-to-Godot material/texture pipeline (CC0 textures only).
5. CI-style `tools/qa_all.sh` across all projects.
