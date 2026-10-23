# OpenGame Repository Audit

Date: 2026-10-23
Audit baseline commit: `f2c259f` (`docs: record environment audit and implementation plan`)
Repository: `/media/rohan/D5/MyProjects/automated-game-dev-agent`

## Executive summary

The first draft has a working deterministic spine: project scaffolding, spec
validation, procedural Blender assets, Godot import/content/runtime/visual/build
wrappers, approval-gated state, and a passing external crystal-arena regression.
Its main gap was orchestration: one global custom agent, no project-local
agents, no slash commands, no structured event log, no project adoption path,
and no Android wrapper.

This audit records what was observed before the second-draft changes. Later
implementation is tracked separately in `docs/opengame-architecture.md`.

## Evidence

| Check | Command | Result |
|---|---|---|
| Git state | `git status --short --branch` | `main`, clean at audit start |
| History | `git log --oneline -5` | `f2c259f`, `b2fee97 feat: first draft` |
| OpenCode | `opencode --version` | `1.18.35` |
| Unit tests | `python3 -m unittest discover -s tools/tests -v` | 11 tests passed (pre-change) |
| Crystal content | `TARGET_NODE=Drone TARGET_GLB=res://assets/models/sm_hover_drone.glb tools/godot/validate.sh ...` | PASS |
| Crystal runtime | `SMOKE_TEST=1 TARGET_NODE=Drone EXPECT_MOVEMENT=1 MIN_MOVEMENT_M=1.0 FRAMES=180 tools/godot/smoke.sh ...` | PASS |
| Crystal gameplay | `"$GODOT" --headless --path ... --script res://tests/gameplay_test.gd` | PASS |
| Crystal state | `python3 tools/pipeline_state.py validate --project ...` | PASS |
| Android export | isolated export to `/tmp/opencode/android_probe/probe.apk` | PASS, 27,497,874 bytes |
| Android device | `adb devices` | none; daemon connection refused |
| Blender MCP | `get_addon_status` | addon not running; connection failed |

Crystal baseline logs are under `/tmp/opencode/crystal_*_baseline.log`.
Crystal release tar SHA-256:
`5dff9566a79eeaccd227fc368732b998805f0fcedcbea0da77ac3f01d0da8633`.
Crystal binary SHA-256:
`334409f5d7068e459de30da6a93cab390fc9399d90b33f1762821a8423824b4`.

## Repository inventory

- `tools/`: deterministic Python and Bash helpers.
- `templates/`: project spec and JSON templates.
- `.opencode/skills/`: six domain skills.
- `docs/`: first-draft environment audit and implementation notes.
- `projects/prop_poc/`: Blender prop and Godot scene proof.
- `projects/terminal_tower/`: second proof-of-concept project.
- `AGENTS.md`: first-draft single-agent operating rules.
- `.mcp.json`: codemap MCP entry.
- No `opencode.json`, project agents, or project commands at audit start.

## OpenCode configuration findings

- OpenCode `1.18.35` is installed.
- The only custom agent was global:
  `~/.config/opencode/agents/automated-game-dev-agent.md`, mode `primary`.
- The global agent had embedded domain procedures and broad edit/bash access,
  but was not discoverable as a project team and had no specialist delegation.
- Project skills were discoverable but not routed by a dedicated orchestrator.
- MCP configuration was split between global OpenCode config and `.mcp.json`.
- The native `task` tool supports delegation to project subagents. Project-local
  agent files under `.opencode/agents/` are the correct extension point.

## Crystal regression fixture

The working crystal-arena game is outside the repository:

```text
/media/rohan/D5/MyProjects/crystal_test/
  AGENTS.md -> repository AGENTS.md
  .gitignore -> repository .gitignore
  templates -> repository templates
  tools -> repository tools
  projects/crystal_test/
```

This fixture exercises the real pipeline end to end. Its source and binaries
must not be copied into Git. Regression checks after tooling changes must
include content, runtime, gameplay, visual, and state validation.

The fixture's state uses legacy task status `complete`. Backward compatibility
is mandatory: new validation may not break existing projects.

## Blender and Godot

- Blender: `5.2.2 LTS`.
- Godot: `4.6.1.stable.official.14d19694e`.
- Godot binary: `.tools/godot/Godot_v4.6.1-stable_linux.x86_64`.
- Export templates: `~/.local/share/godot/export_templates/4.6.1.stable`.
- Linux release export and bounded exported-binary run work.
- Blender MCP is configured but cannot be used until the Blender addon/server is
  running. Procedural CLI generation remains the reliable fallback.

## Android findings

A real debug export was produced during the audit. Two details are critical:

1. The Android preset and SDK/JDK paths must be supplied. The wrapper uses an
   isolated `XDG_CONFIG_HOME`, not a developer's global editor settings.
2. `[rendering] textures/vram_compression/import_etc2_astc=true` is required in
   `project.godot`. Without it the export fails during texture validation even
   when the SDK and templates are correct.

Host facts:

- SDK: `/home/rohan/Android/Sdk`
- JDK: `/usr/lib/jvm/java-17-openjdk-amd64` (`17.0.20`)
- Debug keystore: `~/.local/share/godot/keystores/debug.keystore`
- No connected device; `adb` daemon could not be reached.
- iOS was not tested and is not a supported claim.

## Gaps found

1. No project-local `opengame` primary agent or specialist team.
2. No slash-command workflows.
3. No structured JSONL event log for delegation, errors, and gate decisions.
4. No task dependencies, readiness selection, or evidence requirement in state.
5. No safe adoption path for an existing Godot project.
6. No Android capability/export wrapper.
7. No QA report schema that rejects unevidenced `PASS` results.
8. No blank-image check in the screenshot wrapper.
9. Bootstrap did not install `.opencode`, a default agent config, an Android
   preset, or a main scene, so a new project could not run immediately.
10. First-draft docs and templates still describe a single-agent pipeline.

## Risks

- Duplicating domain logic inside eight oversized agent prompts.
- Letting a specialist approve a human gate.
- Running visual or playability claims from headless checks.
- Breaking the external crystal fixture through state/tool changes.
- Letting Android export success imply device or performance readiness.
- Committing APKs, keystores, generated output, or external fixture binaries.
- Writing a parallel orchestration framework instead of using native OpenCode.

## Recommended priorities

1. Preserve the crystal fixture and prove backward compatibility after every
   state/tool change.
2. Add project-local agents with narrow scopes and explicit evidence contracts.
3. Add commands for initialization, adoption, asset, gameplay, UI, QA, and
   optimization workflows.
4. Add task dependencies/readiness and structured event logging.
5. Add Android and QA report wrappers.
6. Update bootstrap, docs, and templates only after the wrappers are tested.
