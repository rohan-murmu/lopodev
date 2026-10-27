---
description: Build or revise a Godot level from validated assets and verify content plus visual output.
agent: lopodev
---
Build the level described by `$ARGUMENTS`.

1. Confirm the level brief, asset list, spawn points, collision needs, camera,
   lighting, and acceptance criteria.
2. Reject unvalidated assets; do not substitute placeholder geometry.
3. Delegate to `level-design` with scene-only write access.
4. Run content validation and produce a screenshot; inspect it for blank output,
   scale, clipping, floating objects, and readable composition.
5. Record evidence and report known limitations.
