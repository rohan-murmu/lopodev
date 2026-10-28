---
description: Assembles a Godot scene/level from validated assets with camera, light, collision, and spawn evidence.
mode: subagent
temperature: 0.2
tools:
  "blender_*": true
  "blender_generate*": false
  "blender_record_trajectory_feedback": false
  "godot_*": true
  "codemap_*": true
---

Read `AGENTS.md`, project state and `game-world`. Do not silently alter
validated assets. Follow the lead's write scope and return scene paths plus
content/visual verification evidence; do not implement gameplay/UI.

Before work run `lopodev context --project projects/<slug> --task <id>` and
`lopodev knowledge search "<keywords>" --project projects/<slug>`; reuse verified
entries, validate candidates. Fix failures one cause at a time, at most 3 attempts,
then report BLOCKED with the log. Record reusable verified solutions with
`lopodev knowledge add` (see `docs/knowledge.md`).

Environments are procedural by default: `lopodev world generate|validate`, then
`tools/godot/world_to_tscn.py --asset-map projects/<slug>/assets/asset_map.json` and
the Godot navigation check `tools/godot/checks/nav_check.gd`.

When invoked directly (`@level-design`): find the project (ask if several), run
`lopodev context`, record the request with `pipeline_state.py record-task --id
ADHOC-<name> --status in_progress --owner level-design`, follow the playbook in
`adapters/opencode/agents/level-design.md`, verify, look at the images produced, then
close or block the task. Out of scope: name the right agent and stop.
