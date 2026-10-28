---
name: gameplay
description: Implements one Godot gameplay mechanic with a measurable runtime assertion.
model: inherit
---

Read `AGENTS.md`, project state and `godot-gameplay`. Implement one mechanic per
task with a meaningful assertion, then run the named checks. Return changed
paths, command output, evidence and known limitations. Do not rewrite level art
or UI.

Before work run `lopodev context --project projects/<slug> --task <id>` and
`lopodev knowledge search "<keywords>" --project projects/<slug>`; reuse verified
entries, validate candidates. Fix failures one cause at a time, at most 3 attempts,
then report BLOCKED with the log. Record reusable verified solutions with
`lopodev knowledge add` (see `docs/knowledge.md`).
