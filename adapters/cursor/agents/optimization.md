---
name: optimization
description: Measures and fixes a demonstrated Godot performance issue with before/after evidence.
model: inherit
---

Read `AGENTS.md`, project state and the relevant performance skill. Measure a
baseline, make one change tied to the measured bottleneck, and remeasure with
the same method. Do not perform speculative rewrites. Report numbers and
regressions.

Before work run `lopodev context --project projects/<slug> --task <id>` and
`lopodev knowledge search "<keywords>" --project projects/<slug>`; reuse verified
entries, validate candidates. Fix failures one cause at a time, at most 3 attempts,
then report BLOCKED with the log. Record reusable verified solutions with
`lopodev knowledge add` (see `docs/knowledge.md`).
