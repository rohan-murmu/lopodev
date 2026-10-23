# <Game Title> - Game Specification

Status: draft
Slug: `<game_slug>`
Target: Linux x86_64; Android validation when mobile is in scope; Godot 4.6.1, Blender 5.2.2
First milestone: `<one vertical slice>`

## Player fantasy and core loop

<One paragraph. What does the player do repeatedly, and why is it interesting?>

## Scope

Must have for the first playable slice:

- <mechanic or scene>
- <asset or system>

Explicit non-goals:

- <out of scope>

## Controls

| Action | Input | Result |
|---|---|---|
| Move | WASD | <result> |
| Camera | Mouse | <result> |
| Interact | E | <result> |

## Scene and flow

- Main scene: `res://scenes/<PascalCase>.tscn`
- Start state: <spawn, camera, objective>
- Win condition: <measurable>
- Lose/restart condition: <measurable>

## Assets

| ID | Kind | Source | Triangles | Animated | Notes |
|---|---|---|---|---|---|
| `sm_<noun>` | prop | procedural | <= 2000 | no | <brief> |

Licenses: procedurally generated assets are repo-owned. Any third-party asset
must be recorded in `ASSET_LICENSES.md` with source and attribution.

## Technical constraints

- Low-poly budgets and naming from `AGENTS.md`.
- Renderer: `gl_compatibility` (verified on this host).
- Mobile budget: <= 60,000 visible triangles, <= 80 draw calls, <= 2,048 px
  textures, 44x44 logical-pixel touch targets. These are starting limits, not
  measured device guarantees.
- Android export requires `textures/vram_compression/import_etc2_astc=true`.
- No paid services or mandatory paid APIs.
- One script per system; no monolithic game script.

## Milestones and tasks

| ID | Task | Skill | Verification | Status |
|---|---|---|---|---|
| T1 | <task> | modeling | <command> | planned |
| T2 | <task> | level-design | <command> | planned |

## Acceptance criteria

| ID | Criterion | Gate | Evidence |
|---|---|---|---|
| A1 | <measurable criterion> | asset | `<path>` |
| A2 | <measurable criterion> | content | `<path>` |
| A3 | <measurable criterion> | runtime | `<path>` |
| A4 | <visual evidence inspected> | visual | `<path>` |
| A5 | <Linux build runs> | build | `<path>` |
| A6 | <Android export and device state recorded honestly> | android | `<path>` |

## Assumptions and open questions

- <assumption recorded instead of asking>
