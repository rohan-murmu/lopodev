---
name: lopodev-workflow
description: Use when orchestrating an LopoDev project end to end, resuming a project from pipeline state, delegating to LopoDev specialists, or enforcing approval gates and evidence-backed task completion.
license: MIT
---

# LopoDev Workflow

Use this as the operating loop for `lopodev`. The project state and files are
the source of truth, not the conversation.

## 1. Recover context

```bash
python3 tools/pipeline_state.py show --project projects/<slug>
python3 tools/pipeline_state.py next-task --project projects/<slug>
python3 tools/lopodev_log.py tail --project projects/<slug> --limit 10
```

Read `AGENTS.md`, `GAME_SPEC.md`, `project.json`, `ASSET_LICENSES.md`, the task's
dependency outputs, and the last QA report. If state is inconsistent, repair the
state before starting new production work.

## 2. Choose exactly one task

Pick the first task whose dependencies are `verified`, status is not `blocked`,
and gate prerequisite is approved. Mark it `in_progress`:

```bash
python3 tools/pipeline_state.py task-start --project projects/<slug> --task-id T3
python3 tools/lopodev_log.py append --project projects/<slug> --event task_start \
  --agent <agent> --task T3 --status started
```

If multiple projects match, ask the user. Do not guess.

## 3. Write a specialist brief

Every brief contains:

- Project slug and one-sentence objective.
- Required reading and exact upstream paths.
- Allowed write paths and forbidden paths.
- Acceptance command(s), measurable threshold, and expected evidence path.
- Stop conditions: missing/invalid input, license gap, ambiguous scope, need to
  modify outside allowed paths, or a failing prerequisite gate.
- Required event/state update.

Use the active platform's native specialist/subagent mechanism when one is
available. For OpenCode, delegate with its `task` tool and exact
`subagent_type` from the installed `.opencode/agents/` (source:
`adapters/opencode/agents/`). Other platforms use their own native
agent names and task syntax; never pass OpenCode-only fields to them. If the
active platform has no delegation, perform one task at a time or ask the user to
invoke a specialist workflow. Never simulate unsupported subagent APIs.
Do not ask a specialist to build a whole game.

## 4. Verify independently

Inspect the returned paths and run the named command yourself when practical.
Check exit code, log content, file size, image content, and expected node/asset
names. A specialist's statement is a claim until the evidence is examined.

Record:

```bash
python3 tools/pipeline_state.py record-task --project projects/<slug> --task-id T3 \
  --status verified --owner modeling --changed-file <path> \
  --acceptance "<criterion>" --verification "<command and result>" \
  --evidence projects/<slug>/artifacts/... 
python3 tools/pipeline_state.py record-test --project projects/<slug> --gate B \
  --name "<gate>" --status PASS --command "<command>" --evidence "<path>"
python3 tools/lopodev_log.py append --project projects/<slug> --event task_complete \
  --agent modeling --task T3 --status pass --evidence "<path>" --message "<result>"
```

`verified` requires evidence or verification text and no matching `FAIL` test.

## 5. Gate review

Gates:

| Gate | Evidence |
|---|---|
| A | Spec, tasks, assets, acceptance, scope, risks reviewed |
| B | Editable sources, validated GLBs, metadata, inspected previews |
| C | Animated GLB, channel report, rendered frames, Godot import |
| D | One complete loop, controls, runtime and real screenshot |
| E | All mechanics and QA gates, known limitations |
| F | Final export, acceptance table, limitations, report |

Propose with `pipeline_state.py propose`, present a compact evidence table, and
ask one explicit approval question. Do not run `approve` unless the human
explicitly approves in their own words. A skipped gate still needs approval and
a recorded reason.

## 6. Stop and report honestly

When blocked, stop the current task, mark it `blocked`, record the issue, and
state the smallest unblock action. Never turn `NOT RUN` into `PASS`.

Use the completion report:

```text
Status: COMPLETE | PARTIAL | BLOCKED
Deliverables: path -> measured content
Verification: gate -> command -> actual result -> evidence path
Acceptance criteria: criterion -> met/not met -> evidence
Known limitations: untested paths and environment warnings
Next safe step: one concrete action
```
