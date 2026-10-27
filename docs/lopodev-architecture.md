# LopoDev Architecture and Implementation Plan

Status: implemented in the working tree; deterministic and live routing checks pass
Date: 2026-10-23

## Goal

LopoDev is an OpenCode-native game-production toolkit. A lead agent plans,
routes bounded tasks to specialists, enforces human approval gates, and reports
only independently verified evidence. The repository stays a file-based toolkit;
it is not a separate agent runtime or web application.

## Non-goals

- No GUI, database, queue server, or custom agent loop.
- No mandatory paid API, hosted service, or model call from pipeline scripts.
- No replacement of Blender or Godot.
- No automatic gate approval.
- No promise of mobile readiness without device evidence.

## System layers

```text
User
  -> OpenCode primary agent: lopodev
     -> task tool
        -> 8 project-local specialist subagents
           -> shared skills (resources/skills)
              -> deterministic tools (tools/)
                 -> files: spec, state, logs, assets, scenes, QA evidence
```

The conversation is disposable; files are durable. `pipeline_state.json` owns
approval and task state. `artifacts/events.jsonl` records what happened.
`project.json` and `GAME_SPEC.md` own the product contract.

## Agent team

| Agent | Mode | Scope | Must not |
|---|---|---|---|
| `lopodev` | primary | Plan, route, verify, gate review | Approve on user's behalf; skip evidence |
| `game-design` | subagent | Spec, tasks, acceptance, scope | Build assets or mechanics |
| `modeling` | subagent | Blender props, GLB, previews | Edit scenes or gameplay |
| `animation` | subagent | Rig, actions, animated GLB | Author gameplay or UI |
| `level-design` | subagent | Scenes, lighting, collision, spawns | Change validated meshes silently |
| `gameplay` | subagent | Mechanics, input, runtime assertions | Rewrite level art or UI |
| `ui` | subagent | HUD, menus, touch, safe areas | Own game state |
| `optimization` | subagent | Measured performance fixes | Optimize without a number |
| `qa-release` | subagent | All verification gates and reports | Fix code during QA |

Every agent reads `AGENTS.md`, the project state, and upstream artifacts before
acting. Every task brief names write paths, acceptance, evidence, and stop
conditions.

## Commands

| Command | Outcome |
|---|---|
| `/lopodev` | Resume: gate, next task, last events |
| `/init-game` | Bootstrap and Gate A plan |
| `/adopt-game` | Adopt an existing Godot project without copying it |
| `/character` | Mesh then rig/animation through Gate C |
| `/prop` | One validated asset |
| `/animate` | One rig/clip milestone |
| `/mechanic` | One gameplay mechanic with assertion |
| `/level` | Scene/level with content and visual evidence |
| `/mobile-ui` | HUD/touch work plus Android export check |
| `/diagnose` | Minimal reproduction and root-cause repair |
| `/optimize` | Baseline, one cause, after measurement |
| `/release` | Full QA and Gate F package |

## Durable state

`projects/<slug>/pipeline_state.json`:

- Schema version, slug, title, workspace/project paths.
- Current gate and six gate records with proposal/approval/rejection history.
- Tasks with owner, skills, dependencies, acceptance, evidence, changed files,
  issues, status, and timestamp.
- Assets, tests, issues, rejections, and recovery next step.

Canonical task statuses: `planned`, `in_progress`, `blocked`, `needs_approval`,
`verified`, `failed`. Legacy `pending`/`complete` remain accepted. A `verified`
task requires evidence or verification text and is rejected while a matching
gate test is `FAIL`.

`projects/<slug>/artifacts/events.jsonl`:

- One JSON object per line with UTC timestamp and event name.
- Optional agent, gate, task, status, command, evidence, message, and data.
- Secret-like keys and embedded `key=value`/`Authorization:` credentials are
  redacted; values over 2,000 characters are truncated.
- `append`, `tail`, `summary`, and `validate` subcommands.

`projects/<slug>/artifacts/qa_report.json`:

- One record per gate with status `PASS`, `FAIL`, or `NOT RUN`.
- `PASS`/`FAIL` require command and evidence. `NOT RUN` requires a reason.
- Validated by `tools/qa_report.py validate`.

## Approval and test gates

Human gates A-F are separate from technical gates. The technical sequence is
generation, asset, import, content, runtime, visual, build, and Android. Each
result is `PASS`, `FAIL`, or `NOT RUN` with command and artifact path.

The visual gate requires a graphical launch, a PNG, an image statistics check,
and human/model inspection. The Android gate separates export from device,
interaction, and performance evidence.

## Implementation phases

| Phase | Work | Verification |
|---|---|---|
| 0 | Audit and baseline crystal checks | logs and hashes recorded |
| 1 | Project agents, config, commands | `opencode agent list`, `debug config` |
| 2 | State tasks/readiness and event log | unittest + crystal state validate |
| 3 | QA report and screenshot blank check | unittest + visual gate |
| 4 | Adoption and bootstrap | unittest + generated project inspection |
| 5 | Shared Android APK/AAB export core | capability check + APK/AAB probe |
| 6 | Remove/avoid legacy orchestration | no global mutation; docs migrated |
| 7 | Docs and templates | commands match behavior |
| 8 | Crystal end-to-end regression | content/runtime/gameplay/visual/build |
| 9 | Real second-draft game PoC | full A-F evidence, if time permits |

## Compatibility and migration

- The first-draft `tools/`, skills, and project structure remain valid.
- Existing projects with `pending`/`complete` tasks continue to validate.
- Crystal's Godot directory and binaries remain outside the repository.
- The global `lopodev` is not deleted or overwritten.
- New workspaces receive an `lopodev` default, local agents, Android preset and
  settings, and a minimal runnable scaffold clearly labeled as a scaffold.
- Adopted projects keep their original Godot directory; no game file is copied.

## Test matrix

| Area | Test |
|---|---|
| State gates | propose/approve/reject/reopen/order |
| State tasks | dependencies, cycles, verified evidence, FAIL block |
| Event log | JSONL validity, redaction, truncation |
| QA report | unevidenced PASS/NOT RUN rejected |
| Bootstrap | layout, links, config, scene, Android preset |
| Adoption | no source mutation, report/spec/state, validation |
| Crystal | content, runtime, gameplay, state, visual, build |
| Android | capability check, debug APK, release AAB, signatures |
| OpenCode | agent discovery, command discovery, default agent |
| Delegation | live specialist task and returned evidence |

## Risks and mitigations

| Risk | Mitigation |
|---|---|
| Agents become duplicated generalists | Narrow scopes, forbidden actions, evidence contracts |
| Generated plan mistaken for approval | Non-empty human statement required |
| Headless pass mistaken for playable | Separate visual gate with inspected PNG |
| Crystal regression | Re-run baseline after state/tool changes |
| Android overclaim | Separate export/device/perf results |
| Secret leakage | Redacting logger, no keystore/APK commits |
| Token burn | One bounded task, one specialist, no speculative loops |

## Definition of done

- All project tests pass.
- OpenCode discovers the primary agent, 8 specialists, and 12 commands.
- Crystal baseline still passes after tooling changes.
- A new workspace can bootstrap, plan, build one asset, render one scene, run a
  gameplay assertion, capture a screenshot, and export Linux.
- Android export is independently reproducible; device/perf remain explicitly
  `NOT RUN` when no device is present.
- Documentation describes the behavior that was actually verified.
