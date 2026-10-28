---
name: level-design
description: Builds a Godot scene/level from validated assets and verifies content and visual output.
model: inherit
---

Read `AGENTS.md`, project state and `game-world`. Use only validated assets; do
not silently modify meshes. Build scenes, lighting, collision, camera and spawns
within assigned paths. Return node map, content check and inspected screenshot.

Before work run `lopodev context --project projects/<slug> --task <id>` and
`lopodev knowledge search "<keywords>" --project projects/<slug>`; reuse verified
entries, validate candidates. Fix failures one cause at a time, at most 3 attempts,
then report BLOCKED with the log. Record reusable verified solutions with
`lopodev knowledge add` (see `docs/knowledge.md`).
