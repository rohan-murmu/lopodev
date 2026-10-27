# LoopDev (repository: LopoDev)

LoopDev is an agent-assisted workflow for building and validating playable 3D
games with Blender and Godot. Plans, skills, tools, evidence, and approval-gated
state are kept in files so work can resume across sessions.

OpenCode is the reference native integration, with a selectable lead agent,
specialists, slash commands, and native delegation. Kilo Code has a selectable
primary plus specialist subagents and shared skills. Cursor has project rules,
specialist subagents, and shared skills. Other compatible agents can call
optional project-scoped MCP tools. MCP does not automatically give an agent
LoopDev orchestration or native specialist delegation.

## Quick start

Requirements: Python 3.12+, Godot for runtime/build checks, and Blender for asset
authoring. OpenCode, Kilo, Cursor, and the MCP SDK are optional integrations.

```sh
./bin/loopdev --version
./bin/loopdev doctor
./bin/loopdev install opencode --project /path/to/workspace --dry-run
./bin/loopdev install opencode --project /path/to/workspace
```

Other project adapters: `loopdev install kilo`, `loopdev install cursor`, or
`loopdev install mcp`. Installers preserve existing paths, support `--dry-run`,
and do not modify user-level agent configuration. MCP setup writes a registration
example which you manually merge into the selected client's MCP settings. Remove
LoopDev-managed, unchanged files using `loopdev uninstall <target>`.

Existing OpenCode users can keep using `bin/lopodev`, `/init-game`, `/prop`, and
the other established OpenCode commands.

## Homebrew status

The canonical repository is confirmed as `https://github.com/rohan-murmu/lopodev`
and the local Git remote points there. No release tag/archive or repository
`LICENSE` exists yet. Establish the project's license and publish a versioned
archive before claiming public `brew tap` availability; the formula helper
computes the checksum from that exact archive. See
[`docs/installation.md`](docs/installation.md). A formula in this repository
alone is not a tap.

## Requirements

- OpenCode 1.18 or later for the reference native agent experience (optional).
- Python 3.12+.
- Blender 5.2 LTS for asset work (not required for an existing Godot project).
- Godot 4.6.1 with Linux export templates. Android work also needs the Android
  SDK, JDK 17, Android templates, and a debug keystore.
- Linux desktop with a display for the visual gate.

The repository pins Godot under `.tools/godot/`. See
`docs/environment-audit.md` and `docs/lopodev-audit.md` for this host's actual
audited capabilities.

## Android export

Check the host, then export a debug APK or a signed release AAB:

```bash
tools/godot/check_android.sh
tools/godot/export_android.sh projects/<slug>/godot
tools/godot/export_android.sh projects/<slug>/godot --release
tools/godot/export_android.sh projects/<slug>/godot --format aab --release
```

The same workflow is available as `loopdev android-export` and the optional
`loopdev_android_export` MCP tool. Release AAB export requires a release
keystore via `GODOT_ANDROID_KEYSTORE_RELEASE_PATH`,
`GODOT_ANDROID_KEYSTORE_RELEASE_USER`, and
`GODOT_ANDROID_KEYSTORE_RELEASE_PASSWORD`, plus Godot's Gradle Android template.
See [`docs/android-export.md`](docs/android-export.md) for signing, verification,
and the difference between export evidence and device evidence.

## Legacy LopoDev commands

```bash
bin/lopodev install-cli
lopodev version
```

This links `lopodev` into `~/.local/bin` without overwriting an existing
non-symlink. Use `lopodev install-cli /another/bin` to choose the directory.

The existing `lopodev` launcher remains for backwards compatibility. The new
multi-platform installer is `loopdev`.

## Legacy OpenCode workspace setup

```bash
tools/install_lopodev.sh /path/to/workspace
# or
lopodev install /path/to/workspace
```

This links `tools/`, `templates/`, `AGENTS.md`, `README.md`, `.gitignore`, and `.opencode/`,
creates `projects/`, and writes a project `opencode.json` with
`default_agent: lopodev`. Existing files are never overwritten. Restart
OpenCode in that workspace after installation.

## Quick start

```bash
# New game scaffold
lopodev new --slug sky_runner --title "Sky Runner"
lopodev open
```

The scaffold is intentionally a draft. Run `/init-game` or ask `lopodev` to plan
Gate A; it fills `project.json`, validates it, syncs tasks, and stops for your
approval. The first output is a measurable plan, not art.

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
| `lopodev` | Plan, route, verify, approval gates |
| `game-design` | Spec, tasks, scope, acceptance criteria |
| `modeling` | Blender props, GLB, metadata, previews |
| `animation` | Rigs, actions, animated GLB, channel report |
| `level-design` | Scenes, lighting, collision, spawns |
| `gameplay` | Player, camera, mechanics, runtime tests |
| `ui` | HUD, menus, touch controls, safe areas |
| `optimization` | Measured performance fixes |
| `qa-release` | Independent QA and release evidence |

OpenCode delegates through its native `task` tool. Kilo and Cursor delegate via
their own Task/subagent support; tasks stay bounded by shared scopes and evidence
contracts. MCP clients receive tools, not an implicit LoopDev orchestrator.

## Commands

| Command | Purpose |
|---|---|
| `/lopodev` | Resume status and next safe action |
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
python3 tools/lopodev_log.py summary --project projects/<slug>
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

- `docs/lopodev-audit.md` - audited capabilities, evidence, gaps, risks.
- `docs/lopodev-architecture.md` - agent architecture, state, gates, phases.
- `docs/agent-orchestration.md` - delegation and resume behavior.
- `docs/dependency-map.md` - source dependency map and cleanup findings.
- `docs/integrations.md` - OpenCode, Kilo, Cursor and MCP support levels.
- `docs/mcp.md` - optional project-scoped MCP server.
- `docs/android-export.md` - APK/AAB export, signing and verification limits.
- `docs/installation.md` - CLI, prerequisites and Homebrew release workflow.
- `docs/development.md` - maintenance/testing notes.
- `docs/troubleshooting.md` - common setup failures.
- `tools/sanitize_local_paths.py --check` - check tracked text/artifacts before publishing.
- `docs/environment-audit.md` - installed toolchain and verified commands.
- `AGENTS.md` - binding rules for every agent.

## Known limitations

- Android device, interaction, and performance checks are `NOT RUN` on this host
  until a device or emulator is connected and inspected. A signed AAB is not
  Play Console acceptance.
- iOS is not validated.
- Blender MCP requires the Blender addon/server to be running. Procedural CLI
  generation works without it.
- The visual gate requires a display and human/model inspection; it cannot be
  replaced by a headless screenshot.
