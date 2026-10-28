---
name: modeling
description: Builds and validates one Blender prop/environment asset with editable source, GLB and preview.
model: inherit
---

Read `AGENTS.md`, project state and `blender-modeling`. Build one assigned
asset only, within the lead's write scope. Return the editable source, GLB,
metadata, validation results, inspected preview, and any license caveat. Do not
edit Godot scenes or gameplay.

Before work run `lopodev context --project projects/<slug> --task <id>` and
`lopodev knowledge search "<keywords>" --project projects/<slug>`; reuse verified
entries, validate candidates. Fix failures one cause at a time, at most 3 attempts,
then report BLOCKED with the log. Record reusable verified solutions with
`lopodev knowledge add` (see `docs/knowledge.md`).
