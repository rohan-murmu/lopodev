# Agent Orchestration

## Native OpenCode structure

LopoDev uses project-local OpenCode agents. There is no custom runtime.

```text
adapters/opencode/agents/     # source: primary + 8 specialists
adapters/opencode/commands/   # source: slash workflows
resources/skills/             # source: reusable procedures

.opencode/                    # generated, gitignored
  agents -> adapters/opencode/agents
  commands -> adapters/opencode/commands
  skills/<name> -> resources/skills/<name>
```

`opencode.json` sets `default_agent: lopodev`. `lopodev install opencode` (also
invoked by `bootstrap_project.py`) creates the generated `.opencode/` links, so
agents and commands are discovered without copying files.

Verify discovery:

```bash
opencode agent list
opencode debug agent lopodev
opencode debug config
```

The legacy global `lopodev` may remain on the machine; LopoDev
does not depend on it and does not overwrite it.

## Delegation

The lead calls the native `task` tool with the exact specialist name. Every
brief contains:

1. Project slug and one-sentence objective.
2. Upstream files to read.
3. Allowed and forbidden write paths.
4. Acceptance commands and thresholds.
5. Required evidence paths and event/state updates.
6. Stop conditions: invalid upstream artifact, license gap, ambiguous scope,
   failed prerequisite gate, or writes outside scope.

Specialists return changed paths, commands/results, evidence, and limitations.
The lead inspects the evidence and records the task; a specialist's claim is not
accepted without inspection.

## Approval gates

| Gate | Human approves |
|---|---|
| A | Spec, tasks, asset list, measurable acceptance, scope, risks |
| B | Editable sources, validated GLBs, metadata, inspected previews |
| C | Animated GLB, channel report, rendered frames, Godot import |
| D | One complete core loop, controls, runtime smoke, real screenshot |
| E | All mechanics, cumulative QA evidence, known limitations |
| F | Final export, acceptance table, limitations, final report |

A gate with no real work still requires a recorded reason and explicit approval.
A passing command, generated plan, or file is never approval.

## Persistent state

`projects/<slug>/pipeline_state.json` is the resume source of truth. It records
the current gate, proposal/approval/rejection history with the human's exact
statement, tasks with dependencies and evidence, assets, tests, issues, and the
next safe step.

```bash
python3 tools/pipeline_state.py show --project projects/<slug>
python3 tools/pipeline_state.py next-task --project projects/<slug>
python3 tools/pipeline_state.py record-task --project projects/<slug> --task-id T2 \
  --status verified --owner gameplay --acceptance "player moves" \
  --verification "smoke PASS" --evidence projects/<slug>/artifacts/qa_report.json
python3 tools/pipeline_state.py propose --project projects/<slug> --gate A \
  --evidence "<paths>" --note "<change>"
python3 tools/pipeline_state.py approve --project projects/<slug> --gate A \
  --user-statement "<exact human approval>"
python3 tools/pipeline_state.py validate --project projects/<slug>
```

A task cannot be `verified` without evidence or verification text, or while a
matching gate test is `FAIL`. Legacy `pending`/`complete` statuses remain valid
for existing projects.

## Event log

`projects/<slug>/artifacts/events.jsonl` records task starts/completions,
delegations, errors, validations, approvals, and rejections.

```bash
python3 tools/lopodev_log.py append --project projects/<slug> \
  --event delegation --agent modeling --task T3 --status started \
  --message "prop brief accepted"
python3 tools/lopodev_log.py tail --project projects/<slug> --limit 20
python3 tools/lopodev_log.py summary --project projects/<slug>
python3 tools/lopodev_log.py validate --project projects/<slug>
```

Secret-like keys and embedded credential assignments are redacted; long values
are truncated. The log is evidence
for recovery and retrospectives, not a replacement for `pipeline_state.json`.

## Resume protocol

1. Read `AGENTS.md` and `project.json`.
2. Show state, next task, and recent events.
3. Identify the current gate and its approval status.
4. Continue only the approved milestone.
5. If state is missing but a project exists, ask before creating or adopting it.
6. Never re-run approved work only because a new session started.
