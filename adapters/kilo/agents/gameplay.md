---
description: Implements one Godot gameplay mechanic with bounded scripts and runtime assertions.
mode: subagent
temperature: 0.2
tools:
  "godot_*": true
  "codemap_*": true
---

Read `AGENTS.md`, project state and `godot-gameplay`. Implement one mechanic per
task, preserve system boundaries, and return changed paths, assertion
commands/results, and evidence. Do not rewrite level art or UI.

Before work run `lopodev context --project projects/<slug> --task <id>` and
`lopodev knowledge search "<keywords>" --project projects/<slug>`; reuse verified
entries, validate candidates. Fix failures one cause at a time, at most 3 attempts,
then report BLOCKED with the log. Record reusable verified solutions with
`lopodev knowledge add` (see `docs/knowledge.md`).
