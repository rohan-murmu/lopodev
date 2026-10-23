# OpenGame

OpenGame builds playable low-poly 3D games with Blender, Godot 4.x, and native
OpenCode agents. The lead agent plans first, delegates one bounded task at a
time, verifies the evidence independently, and stops at explicit human approval
gates.

No paid runtime dependencies. No separate orchestration server. Just OpenCode
agents, skills, commands, deterministic tools, and files.

## Requirements

- OpenCode 1.18 or later.
- Python 3.12+.
- Blender 5.2 LTS for asset work (not required for an existing Godot project).
- Godot 4.6.1 with Linux export templates. Android work also needs the Android
  SDK, JDK 17, Android templates, and a debug keystore.
- Linux desktop with a display for the visual gate.

The repository pins Godot under `.tools/godot/`. See
`docs/environment-audit.md` and `docs/opengame-audit.md` for this host's actual
audited capabilities.

## Install into a workspace

```bash
tools/install_opengame.sh /path/to/workspace
```

This links `tools/`, `templates/`, `AGENTS.md`, `.gitignore`, and `.opencode/`,
creates `projects/`, and writes a project `opencode.json` with
`default_agent: opengame`. Existing files are never overwritten. Restart
OpenCode in that workspace after installation.

## Quick start

```bash
# New game
python3 tools/bootstrap_project.py --workspace . --slug sky_runner \
  --title "Sky Runner"
source tools/env.sh
python3 tools/validate_spec.py projects/sky_runner/project.json
python3 tools/pipeline_state.py sync-spec --project projects/sky_runner \
  --spec projects/sky_runner/project.json
python3 tools/pipeline_state.py validate --project projects/sky_runner
```

Then open OpenCode in the workspace and run `/init-game`, or ask `opengame` to
continue. The first output is a measurable Gate A plan, not art.

Adopt an existing Godot game without copying or editing it:

```bash
python3 tools/adopt_project.py \
  --godot-dir /path/to/existing/godot \
  --project projects/my_game \
  --slug my_game --title "My Game"
```

## Agent team

| Agent | Responsibility |
|---|---|
| `opengame` | Plan, route, verify, approval gates |
| `game-design` | Spec, tasks, scope, acceptance criteria |
| `modeling` | Blender props, GLB, metadata, previews |
| `animation` | Rigs, actions, animated GLB, channel report |
| `level-design` | Scenes, lighting, collision, spawns |
| `gameplay` | Player, camera, mechanics, runtime tests |
| `ui` | HUD, menus, touch controls, safe areas |
| `optimization` | Measured performance fixes |
| `qa-release` | Independent QA and release evidence |

The lead delegates through OpenCode's native `task` tool. A specialist gets a
bounded brief with allowed paths, acceptance commands, evidence requirements,
and stop conditions.

## Commands

| Command | Purpose |
|---|---|
| `/opengame` | Resume status and next safe action |
| `/init-game` | Bootstrap a project and plan Gate A |
| `/adopt-game` | Adopt an existing Godot project |
| `/character` | Character mesh and animation |
| `/prop` | One prop or environment asset |
| `/animate` | One rig/animation milestone |
| `/mechanic` | One gameplay mechanic with a test |
| `/level` | Scene/level assembly and visual check |
| `/mobile-ui` | HUD/touch work and Android export |
| `/diagnose` | Reproduce and fix a failing gate |
| `/optimize` | Measure, change one cause, measure again |
| `/release` | Full QA and release-candidate package |

## Evidence and gates

Human gates: **A** plan, **B** assets, **C** animation, **D** first playable,
**E** integrated QA, **F** release candidate. They are approved only by the
human, in their own words.

Technical gates are cumulative: generation, asset, import, content, runtime,
visual, build, and Android. Every result is `PASS`, `FAIL`, or `NOT RUN` with a
command and artifact path. A headless pass is not a playability claim. A desktop
pass is not mobile evidence.

```bash
python3 tools/pipeline_state.py show --project projects/<slug>
python3 tools/pipeline_state.py next-task --project projects/<slug>
python3 tools/qa_report.py validate --project projects/<slug>
python3 tools/opengame_log.py summary --project projects/<slug>
```

## Project layout

```text
projects/<slug>/
  GAME_SPEC.md
  project.json
  pipeline_state.json
  ASSET_LICENSES.md
  blender/
  godot/
  artifacts/logs/
  artifacts/screenshots/
  artifacts/events.jsonl
  artifacts/qa_report.json
  build/           # gitignored
```

## Documentation

- `docs/opengame-audit.md` - audited capabilities, evidence, gaps, risks.
- `docs/opengame-architecture.md` - agent architecture, state, gates, phases.
- `docs/agent-orchestration.md` - delegation and resume behavior.
- `docs/environment-audit.md` - installed toolchain and verified commands.
- `AGENTS.md` - binding rules for every agent.

## Known limitations

- Android device, interaction, and performance checks are `NOT RUN` on this host
  until a device or emulator is connected and inspected.
- iOS is not validated.
- Blender MCP requires the Blender addon/server to be running. Procedural CLI
  generation works without it.
- The visual gate requires a display and human/model inspection; it cannot be
  replaced by a headless screenshot.
