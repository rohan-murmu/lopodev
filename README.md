# LopoDev (repository: LopoDev)

LopoDev is an agent-assisted workflow for building and validating playable 3D
games with Blender and Godot. Plans, skills, tools, evidence, and approval-gated
state are kept in files so work can resume across sessions.

OpenCode is the reference native integration, with a selectable lead agent,
specialists, slash commands, and native delegation. Kilo Code has a selectable
primary plus specialist subagents and shared skills. Cursor has project rules,
specialist subagents, and shared skills. Other compatible agents can call
optional project-scoped MCP tools. MCP does not automatically give an agent
LopoDev orchestration or native specialist delegation.

## Install

Homebrew (macOS/Linux). The formula lives in this repository, so tap it by URL.
Until the first tagged release is published, install the development head:

```sh
brew tap rohan-murmu/lopodev https://github.com/rohan-murmu/lopodev
brew install --HEAD rohan-murmu/lopodev/lopodev     # after a release: brew install lopodev
```

From a checkout:

```sh
git clone https://github.com/rohan-murmu/lopodev && cd lopodev
bin/lopodev install-cli            # symlinks ~/.local/bin/lopodev
```

## First run

```sh
lopodev setup                                   # once per user: pinned MCP servers + skills
lopodev new --workspace ~/games --slug sky_runner --title "Sky Runner"
lopodev doctor --project ~/games                # live: skill discovery + MCP connectivity
cd ~/games && lopodev open                      # OpenCode with the lopodev lead agent
```

`lopodev setup` installs, into `~/.local/share/lopodev` only (no global Python
or Node changes), pinned and checksum-verified:

| Integration | Pin | Used by |
|---|---|---|
| [MCP for Blender](https://github.com/ahujasid/mcp-for-blender) | `mcp-for-blender==2.2.4` (isolated venv) + Blender addon | modeling, animation, level-design |
| [Godot MCP](https://github.com/Coding-Solo/godot-mcp) | `@coding-solo/godot-mcp@0.1.1` (isolated npm prefix) | gameplay, ui, level-design, qa-release, optimization |
| [Code Map](https://github.com/JordanCoin/codemap) | `codemap` 4.6.0 (`brew`/`go`; an existing install is kept) | lead, gameplay, ui, qa-release, optimization, level-design |
| [blender-skills](https://github.com/EL4CTEO/blender-skills), [godot-skills](https://github.com/vl4dt/godot-skills), [blender-LPM-skill](https://github.com/ozanzeng/blender-LPM-skill), [blender-agent-skills](https://github.com/oh-ashen-one/blender-agent-skills) | commit + SHA-256 in `resources/integrations.json`; curated subset (31 skills) | per-agent skill lists |

`lopodev install opencode` runs `setup` first (skip with `--no-integrations` or
`LOPODEV_NO_INTEGRATIONS=1`), links skills, and merges MCP servers, per-agent
tool access and the approval policy into `opencode.json` key by key: your own
keys are preserved, the original is backed up to `.lopodev/backups/`, and
`lopodev uninstall opencode` removes only keys LopoDev wrote and you did not
edit. Running OpenCode sessions keep their old tools until you restart them;
LopoDev never restarts them. `lopodev doctor` proves activation by asking
OpenCode which skills it discovers and which MCP servers connect;
`lopodev doctor --probe` additionally makes one real read-only tool call per server.

Other adapters: `lopodev install kilo`, `lopodev install cursor`,
`lopodev install mcp` (prints a registration for any MCP client).

## Approval mode

```sh
lopodev approval            # show (default: auto)
lopodev approval manual     # ask before every edit and non-read-only command
lopodev approval auto
```

`auto` lets agents edit and run ordinary commands. In both modes destructive,
publishing and credential commands (`rm -rf`, `git push`, `git reset --hard`,
`gh release`, signing tools, `curl | sh`, ...) still ask, and recording a human
gate decision (`pipeline_state.py approve|reject|reopen`) always prompts: tool
approval is never gate approval. Mode changes are logged to `.lopodev/events.jsonl`.

## Knowledge that carries across games

```sh
lopodev knowledge search touch joystick look --engine-version 4.6.1 --platform android
lopodev knowledge apply godot-mobile-touch-controls --project projects/my_game --godot-dir projects/my_game/godot
lopodev context --project projects/my_game --task T3   # bounded brief for one task
```

Recipes are versioned JSON with artifacts, compatibility, failure modes and
validation evidence; only `verify --run` makes one `verified`. Shipped recipes
(multitouch controls, screen router, safe area) are verified by headless Godot
4.6.1 tests. See [`docs/knowledge.md`](docs/knowledge.md).

## Start a game: the Game Brief

The best first prompt is a filled Game Brief: title, pitch, genre, art style,
theme, story, core loop, win/lose, platform, controls, world, characters,
assets (including edits such as "water well -> witch well"), screens and
scope. Blank fields are fine; LopoDev fills them from genre defaults and lists
every guess as an assumption for you to approve at Gate A.

```sh
lopodev brief template > GAME_BRIEF.md        # fill it in
lopodev brief check GAME_BRIEF.md             # missing essentials, contradictions
lopodev new --workspace . --slug hex_hollow --title "Hex Hollow" --brief GAME_BRIEF.md
```

In OpenCode, `/new-game <brief or idea>` does the same. Examples:
[`docs/examples/brief_witch_village.md`](docs/examples/brief_witch_village.md),
[`docs/examples/brief_jungle_shooter.md`](docs/examples/brief_jungle_shooter.md);
details in [`docs/game-brief.md`](docs/game-brief.md).

## Assets: discover, don't model

LopoDev gets assets the way a small studio does: it reuses openly licensed
models, characters with ready-made animations, and materials, and assembles
environments procedurally. Blender is kept for bounded processing (conversion,
pivots, cleanup, decimation) and for custom models you ask for.

```sh
lopodev assets providers                                  # sources and status
lopodev assets add-pack ~/Downloads/kenney_nature-kit.zip --provider kenney --name nature-kit --style stylized
lopodev assets run --project projects/<slug>              # requirements -> select -> cache -> Godot -> credits -> validate
```

Sources: CC0 packs you download (Kenney, Quaternius, KayKit) and the official
Poly Haven and ambientCG APIs. Licenses are a hard filter (unknown, NC and ND
are never used; CC-BY needs attribution and lands in `CREDITS.md`). Characters
are ranked by rig and animation coverage, and `lopodev assets import` plays
every required clip in headless Godot. See [`docs/assets.md`](docs/assets.md).

## Change, rig and animate any asset

Downloaded assets are a starting point, not a limit. Blender can do anything
to them: reshape, retexture, merge with other assets, rig and animate. The
original stays untouched, and the result keeps the source's license and gets
before/after images:

```sh
lopodev assets derive --project P --from sm_water_well --id sm_witch_well --script derive_witch_well.py --live
lopodev assets rig --project P --from sm_villager_src --id sm_villager --mode humanoid --clip idle --clip walk
lopodev assets rig --project P --from sm_witch_well --id sm_witch_well_anim --mode parts --clip "bucket_bob:Bucket:bob_z:-0.4:1.5"
```

With live mode (default when a display exists), Blender and Godot open on
screen while LopoDev works and close when done; only windows LopoDev opened
are ever closed ([`docs/live.md`](docs/live.md)). `lopodev android-test` runs
the finished game on an Android emulator: install, launch, crash check,
screenshots, tap.

## Worlds, screens and controls

New specs (`design_version: 2`) must define the core loop, touch controls per
genre, screens and the navigation graph; `tools/validate_spec.py` rejects
unreachable screens, dead ends, dead buttons, missing pause or retry, shared
touch zones, tiny buttons, and an orientation that differs from `project.godot`.
Worlds are planned, resolved and validated before assembly:

```sh
lopodev world generate docs/world_plan.json --out docs/world_plan.resolved.json
lopodev world validate docs/world_plan.resolved.json --map
python3 tools/godot/world_to_tscn.py docs/world_plan.resolved.json --godot-dir godot \
  --out scenes/World.tscn --asset-map assets/asset_map.json
```

Plans support noise terrain with slope limits, Poisson-disk scatter, exclusion
zones, enemy spawns, sightlines and combat-zone cover limits. The scene gets
ground or heightfield collision, lighting and a NavigationRegion3D;
`tools/godot/checks/nav_check.gd` bakes it and proves enemies reach the player.

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
lopodev android-export projects/<slug>/godot --install-run   # + install/launch when a device is attached
```

New projects get an `Android` (APK) and an `Android AAB` (Gradle) preset;
`--format aab` picks the latter. Each export verifies size, zip structure,
signature, and for APKs the packaged manifest (package, versionCode, SDK levels,
launcher) against the preset, then writes a JSON report next to the logs.
Device launch, interaction and performance stay `NOT RUN` unless a device was
actually used.

The same workflow is available as `lopodev android-export` and the optional
`lopodev_android_export` MCP tool. Release AAB export requires a release
keystore via `GODOT_ANDROID_KEYSTORE_RELEASE_PATH`,
`GODOT_ANDROID_KEYSTORE_RELEASE_USER`, and
`GODOT_ANDROID_KEYSTORE_RELEASE_PASSWORD`, plus Godot's Gradle Android template.
See [`docs/android-export.md`](docs/android-export.md) for signing, verification,
and the difference between export evidence and device evidence.

## Repository layout

```text
resources/skills/          # canonical, platform-neutral Agent Skills
adapters/opencode/         # OpenCode agents and commands
adapters/kilo/agents/      # Kilo primary and specialist wrappers
adapters/cursor/rules|agents/
tools/ bin/ docs/ templates/
```

`Formula/lopodev.rb` is generated by `tools/homebrew_formula.py` (CI checks it),
`resources/integrations.json` pins third-party integrations, and
`resources/knowledge/` holds bundled recipes with their artifacts, checks and evidence.
`.opencode/`, `.kilo/`, `.cursor/`, and `.agents/skills/` are generated install
targets and are not edited by hand. `tools/install_lopodev.sh` is a deprecated
wrapper around `lopodev install opencode` and never overwrites existing files.
Restart the agent in that workspace after installation.

## Planning a game

```bash
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
contracts. MCP clients receive tools, not an implicit LopoDev orchestrator.

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
- `docs/knowledge.md` - knowledge scopes, schema, statuses and commands.
- `docs/assets.md` - asset sources, license policy, contracts, ranking, import, derive, rig, previews, worlds.
- `docs/live.md` - live mode: visible Blender/Godot/emulator and what gets closed.
- `docs/game-brief.md` - the structured first prompt.
- `docs/installation.md` - Homebrew, setup, upgrade, uninstall, release procedure.
- `CONTRIBUTING.md` - adding agents, skills, integrations and knowledge.
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
- Asset selection uses provider metadata and inspected geometry, not image
  understanding; thumbnails are recorded for a human or vision model to check.
  Poly Haven models are photoscans that often exceed mobile triangle budgets:
  use stylized CC0 packs for mobile games. Kenney, Quaternius and KayKit have no search
  API, so their packs are downloaded by hand. Poly Pizza (needs an API key)
  and OpenGameArt (no API, mixed licenses) have no adapter.
- Animation retargeting between different skeletons is detected and reported
  but not automated; LopoDev picks a character with a compatible clip set first.
- Blender MCP requires the Blender addon/server to be running. Procedural CLI
  generation works without it.
- The visual gate requires a display and human/model inspection; it cannot be
  replaced by a headless screenshot.
- Bundled knowledge recipes are verified with synthetic touch events in headless
  Godot, not on a phone.
- AAB manifests are not inspected (protobuf; `bundletool` is not bundled).
- Code Map's pin is not enforced on an existing user installation; `doctor`
  reports the installed version.
- Approval modes are rendered for OpenCode. Kilo and Cursor keep their own
  permission settings.
- The Homebrew tap is the formula in this repository; no release is published
  yet, so only `--HEAD` installs work until the first `v*` tag.
