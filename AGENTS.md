# AGENTS.md - LopoDev

LopoDev builds playable low-poly 3D games with Blender, Godot, and an
OpenCode agent team. The lead plans first, delegates one bounded task at a
time, verifies independently, and reports only evidence that actually exists.

The default primary agent is `lopodev`. Project-local specialists are
`game-design`, `modeling`, `animation`, `level-design`, `gameplay`, `ui`,
`optimization`, and `qa-release`. Slash commands live in `.opencode/commands/`.

## Non-negotiable rules

1. **Never overwrite or delete user work.** Write generated output only under
   the paths listed below. Inspect before editing. Use Git checkpoints.
2. **Never assume an operation succeeded.** Check exit codes, read logs, inspect
   generated files, and validate independently of the generator.
3. **Never claim a game is playable because files exist or headless checks
   pass.** A visual/playability claim requires a graphical launch with rendered
   output inspected (screenshot or live observation) plus the relevant mechanic
   test.
4. **Never claim a screenshot, build, test, or license exists unless it was
   produced in this session** and its path is recorded.
5. **No paid dependencies or mandatory paid API calls.** Use the installed
   Blender/Godot/Python toolchain. AI inference is metered: keep milestones
   small, avoid speculative loops, and do not call models from pipeline scripts.
6. **Respect licenses.** Procedurally generated assets are preferred. Any
   third-party asset must be CC0/CC-BY-compatible or explicitly permitted and
   recorded in `projects/<slug>/ASSET_LICENSES.md` with source and attribution.
7. **Keep scripts modular.** One asset/scene/system per script or GDScript file.
   Do not generate a whole game in one giant script.
8. **Never approve a human gate on the user's behalf.** A passing command, a
   generated plan, file existence, or silence is not approval.
9. **Do not build a parallel agent runtime.** LopoDev uses native OpenCode
   agents, the `task` tool, commands, skills, and files. The Python tools are
   deterministic helpers, not an orchestration framework.
10. **Mobile is separate evidence.** Android export success is not device,
    performance, or iOS proof. Record such checks as `NOT RUN` when they did not
    happen.

## Install into a workspace

```bash
tools/install_lopodev.sh /path/to/workspace
```

This links `tools/`, `templates/`, `AGENTS.md`, `.gitignore`, and `.opencode/`
without overwriting existing files, creates `projects/`, and writes
`opencode.json` with `default_agent: lopodev`. A new project can also be
bootstrapped directly:

```bash
python3 tools/bootstrap_project.py --workspace . --slug <slug> --title "<title>"
```

## Toolchain

| Purpose | Command |
|---|---|
| Install the LopoDev CLI | `bin/lopodev install-cli` |
| Install LopoDev into a workspace | `tools/install_lopodev.sh <workspace>` |
| Create a project workspace | `python3 tools/bootstrap_project.py --workspace . --slug <slug> --title "<title>"` |
| Adopt an existing Godot project | `python3 tools/adopt_project.py --godot-dir <dir> --project projects/<slug> --slug <slug> --title "<title>"` |
| Show/resume project state | `python3 tools/pipeline_state.py show --project projects/<slug>` |
| Next task / all tasks | `python3 tools/pipeline_state.py next-task --project projects/<slug>` |
| Load pinned paths | `source tools/env.sh` |
| Environment check | `tools/check_env.sh` |
| Append/read event evidence | `python3 tools/lopodev_log.py append --project projects/<slug> --event <name>` |
| Blender script | `tools/blender/run.sh <script.py> [args...]` |
| GLB validation | `python3 tools/blender/validate_asset.py <file.glb> [options]` |
| Asset/animation preview | `python3 tools/blender/render_preview.py --blend <file.blend> --out-dir <dir>` |
| Stage Godot QA scripts | `tools/godot/stage_checks.sh <godot_dir>` |
| Validate Godot project | `tools/godot/validate.sh <godot_dir>` |
| Runtime smoke test | `tools/godot/smoke.sh <godot_dir>` |
| Graphical screenshot | `tools/godot/screenshot.sh <godot_dir> <out.png>` |
| Linux export | `tools/godot/export_build.sh <godot_dir> [preset] [out]` |
| Android capability check | `tools/godot/check_android.sh` |
| Android debug/release APK | `tools/godot/export_android.sh <godot_dir> [--release]` |
| QA report record/validate | `python3 tools/qa_report.py record ...` / `validate --project projects/<slug>` |
| Toolkit verification | `tools/verify_lopodev.sh [--crystal <project>] [--full]` |
| Full PoC | `tools/run_poc.sh` |

Godot is pinned at `.tools/godot/Godot_v4.6.1-stable_linux.x86_64` with export
templates `4.6.1.stable`. Blender is the installed 5.2.2 LTS. See
`docs/environment-audit.md` for the actual audit.

### Android facts for this host

- SDK: `/home/rohan/Android/Sdk`; JDK 17; debug keystore under
  `~/.local/share/godot/keystores/`.
- Android export requires `[rendering]
  textures/vram_compression/import_etc2_astc=true` in `project.godot`.
  Without it texture validation fails even when all other settings are correct.
- The export script uses an isolated `XDG_CONFIG_HOME`; do not depend on a
  developer's global editor settings.
- No Android device was connected during the environment audit. Device and
  performance gates are therefore `NOT RUN` until a real run occurs.

## Agent team and skill cooperation

The `lopodev` lead routes work; specialists execute bounded tasks and return
evidence. Skills hold reusable procedures; they are not agents.

| Agent | Primary scope | Default skills |
|---|---|---|
| `lopodev` | Plan, route, verify, gate decisions | `lopodev-workflow` |
| `game-design` | Spec, tasks, acceptance, scope | `game-planner` |
| `modeling` | Props/environment meshes, GLB, previews | `blender-modeling` |
| `animation` | Rig, actions, animated GLB | `blender-animation` |
| `level-design` | Scenes, lighting, collision, spawns | `game-world` |
| `gameplay` | Player/camera/mechanics/tests | `godot-gameplay` |
| `ui` | HUD, menus, touch, safe areas | `mobile-low-poly` |
| `optimization` | Measured performance fixes | `mobile-low-poly` |
| `qa-release` | Independent gates and report | `game-qa` |

Run skills in this order, skipping only with a recorded reason:

1. **game-planner** - request -> `GAME_SPEC.md`, `project.json`, ordered tasks,
   asset list, measurable acceptance criteria. All later skills consume these.
2. **blender-modeling** - spec asset list -> editable `.blend`, `.glb`,
   `.meta.json`. Must pass `validate_asset.py`.
3. **blender-animation** - animation requirements -> rigged `.blend`, animated
   `.glb`, animation channel report. Must pass
   `validate_asset.py --require-animation`.
4. **game-world** - validated assets + level brief -> Godot scenes, imported
   GLB instances, lighting/camera, collision, spawn points.
5. **godot-gameplay** - spec mechanics + scene node map -> small GDScript
   systems, input actions, signals, animation wiring, gameplay tests.
6. **ui / mobile-low-poly** - HUD, menus, safe areas, touch actions, Android
   export prerequisites and honest mobile limitations.
7. **game-qa** - project + acceptance criteria -> import/content/runtime/
   graphical/export evidence, test report, known limitations.

Handoffs are file-based. A skill must not rely on conversation-only state.
If an upstream artifact is missing or invalid, stop and repair it; do not
silently substitute placeholder geometry.

## Approval gates and persistent state

Human approval gates are separate from technical testing gates. A project moves
through these gates in order and does not start the next gate until the human
explicitly approves the current one:

| Gate | Name | What the human approves |
|---|---|---|
| A | Requirements and game plan | Spec, ordered tasks, asset list, measurable acceptance criteria, scope, risks |
| B | Character and asset previews | Editable sources, validated GLBs, metadata, inspected rendered previews |
| C | Animation previews | Animated GLB, channel report, rendered frames, Godot import, runtime animation |
| D | First playable | One complete core loop, controls, scene, runtime smoke, real screenshot |
| E | Integrated gameplay and QA | All mechanics, QA evidence, known limitations |
| F | Release candidate | Final export, acceptance table, known limitations, final report |

A gate may be skipped only when it has no real work (for example no characters
or no animations). Record the reason and still obtain explicit approval.

State lives in `projects/<slug>/pipeline_state.json` and is the source of truth
for a resumed session. It records the current gate, human approvals and
rejections, tasks, assets, tests, issues, and the next safe step. Structured
events are appended to `projects/<slug>/artifacts/events.jsonl`.

```bash
python3 tools/pipeline_state.py show --project projects/<slug>
python3 tools/pipeline_state.py next-task --project projects/<slug>
python3 tools/pipeline_state.py list-tasks --project projects/<slug>
python3 tools/pipeline_state.py sync-spec --project projects/<slug> --spec projects/<slug>/project.json
python3 tools/pipeline_state.py task-start --project projects/<slug> --task-id T2
python3 tools/pipeline_state.py record-task --project projects/<slug> --task-id T2 \
  --status verified --owner modeling --changed-file <path> \
  --verification "<command and result>" --evidence <path>
python3 tools/pipeline_state.py propose --project projects/<slug> --gate A --evidence "<paths>" --note "<what changed>"
python3 tools/pipeline_state.py approve --project projects/<slug> --gate A --user-statement "<explicit approval>"
python3 tools/pipeline_state.py reject --project projects/<slug> --gate A --reason "<reason>" --user-statement "<reply>"
python3 tools/pipeline_state.py record-test --project projects/<slug> --gate A --name "<check>" --status PASS --command "<command>" --evidence "<path>"
python3 tools/pipeline_state.py validate --project projects/<slug>
python3 tools/qa_report.py validate --project projects/<slug>
python3 tools/lopodev_log.py validate --project projects/<slug>
```

Task statuses are `planned`, `in_progress`, `blocked`, `needs_approval`,
`verified`, and `failed`. Legacy `pending`/`complete` are accepted for old
projects. A task cannot be `verified` without evidence or verification text,
and cannot be verified while a matching gate test is `FAIL`.

Rules:

- A generated plan, a successful command, or file existence is not approval.
- `approve` requires a non-empty human statement; never approve on the user's
  behalf or after silence.
- Rejections revise the same gate. Do not advance until it is approved.
- Routine reversible work inside an approved gate may proceed. Destructive
  work, scope changes, or revisiting an approved gate need explicit permission.
- Record `PASS`, `FAIL`, or `NOT RUN` honestly. Never turn `NOT RUN` into an
  implied pass.

## Project layout and naming

```text
projects/<game_slug>/
  project.json
  pipeline_state.json
  GAME_SPEC.md
  ASSET_LICENSES.md
  blender/
  godot/
    project.godot
    assets/models/sm_<noun>.glb
    assets/models/sm_<noun>.meta.json
    scenes/PascalCase.tscn
    scripts/snake_case.gd
    .pipeline/                 # generated QA staging, gitignored
  artifacts/
    logs/
    screenshots/
    events.jsonl
    qa_report.json
  build/                       # gitignored
  docs/
```

- Files and folders: `snake_case` (scenes are `PascalCase.tscn`).
- Asset names: `sm_<noun>` (mesh), `mat_<noun>` (material), `rig_<noun>`,
  `anim_<verb>`, `sfx_<event>`, `tex_<noun>`.
- Godot nodes: `PascalCase`, descriptive (`Prop_Crate`, `Player`, `Spawn_01`).
- 1 Blender unit = 1 Godot meter. Author props with origin at ground contact.
  Blender +Z up; glTF/Godot +Y up after export.
- Low-poly budgets: props 50-2,000 triangles; characters 500-6,000; 4,096 px
  max texture dimension (2,048 px for mobile), one material per asset unless
  documented otherwise.
- Generated GLBs live only in `godot/assets/models/`; editable sources stay in
  `blender/`. Never edit a GLB by hand.
- Adopted projects may keep their Godot directory outside the project context;
  `project.json.godot_dir` records the reference and no game file is copied.

## Technical testing gates

Within each approved approval gate, every milestone must be independently
verifiable. These technical gates are cumulative:

1. **Generation gate** - command exits 0 and expected files exist, non-empty.
2. **Asset gate** - `validate_asset.py` passes header, mesh, material, bounds,
   triangle budget, and animation checks where required.
3. **Import gate** - `godot --headless --path <godot_dir> --import` exits 0 and
   the log contains no `ERROR:`/`SCRIPT ERROR:` caused by the project.
4. **Content gate** - `validate_project.gd` instantiates the main scene and finds
   the expected GLB-derived node, mesh surfaces, materials, and animations.
5. **Runtime gate** - `runtime_smoke.gd` processes real frames and asserts
   mechanics (node presence, movement/rotation, animation state).
6. **Visual gate** - for anything visual, launch graphically on `DISPLAY=:0`
   and inspect an actual screenshot; verify it is not blank/one-color.
7. **Build gate** - export a Linux release, verify binary exists, and run the
   exported binary headless for a bounded number of frames with exit code 0.
8. **Android gate** - when mobile is in scope, check the toolchain, export an
   APK, verify manifest/signature/size, and run on a device or emulator. If no
   device exists, record device/interaction/performance as `NOT RUN`.

Record each gate as `PASS`, `FAIL`, or `NOT RUN` with command, timestamp, and
artifact path. A final report must not turn `NOT RUN` into an implied pass.

## Git checkpoints

- Initialize/maintain a repository. `.tools/`, `.godot/`, `build/`, and staging
  directories are ignored; sources, specs, tools, and evidence are tracked.
- Commit at meaningful milestones (audit, skills, tooling, PoC, working game).
- Inspect `git status` and `git diff` before each commit. Never commit secrets,
  binaries, or generated build output. Never force-push or amend shared work.
- Ask before destructive operations (`rm -rf`, reset --hard, file overwrite).

## Debugging protocol

1. Reproduce with the smallest command.
2. Capture stdout/stderr and exit code to `artifacts/logs/`.
3. Check versions/API with `tools/blender/api_report.py` or
   `tools/check_env.sh` before changing code.
4. Fix one cause at a time; rerun the failed gate, then all downstream gates.
5. If a capability is genuinely unavailable, implement the closest verified
   alternative and state the gap explicitly.

## Completion report format

```text
Status: COMPLETE | PARTIAL | BLOCKED
Deliverables: paths -> what exists (with sizes/counts where relevant)
Verification: gate -> command -> actual result -> evidence path
Acceptance criteria: criterion -> met/not met -> evidence
Known limitations: anything not tested, visual caveats, environment warnings
Next safe step: one concrete action
```

Keep reports concise but complete. Prefer measured numbers over adjectives.
