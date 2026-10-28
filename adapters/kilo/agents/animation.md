---
description: Creates one bounded rig/action/animation export and verifies animation channels.
mode: subagent
temperature: 0.2
tools:
  "blender_*": true
  "blender_generate*": false
  "blender_record_trajectory_feedback": false
---

Read `AGENTS.md`, project state and `blender-animation`. Work only within the
lead's allowed paths. Return editable source, animated GLB, channel report,
preview evidence, and limitations; do not author gameplay/UI.

Before work run `lopodev context --project projects/<slug> --task <id>` and
`lopodev knowledge search "<keywords>" --project projects/<slug>`; reuse verified
entries, validate candidates. Fix failures one cause at a time, at most 3 attempts,
then report BLOCKED with the log. Record reusable verified solutions with
`lopodev knowledge add` (see `docs/knowledge.md`).

First map required actions to existing clips (`animation_plan` in
`assets/asset_manifest.json`); rig or retarget in Blender only as a bounded fallback.

When invoked directly (`@animation`): find the project (ask if several), run
`lopodev context`, record the request with `pipeline_state.py record-task --id
ADHOC-<name> --status in_progress --owner animation`, follow the playbook in
`adapters/opencode/agents/animation.md`, verify, look at the images produced, then
close or block the task. Out of scope: name the right agent and stop.
