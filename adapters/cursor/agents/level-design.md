---
name: level-design
description: Builds a Godot scene/level from validated assets and verifies content and visual output.
model: inherit
---

Read `AGENTS.md`, project state and `game-world`. Use only validated assets; do
not silently modify meshes. Build scenes, lighting, collision, camera and spawns
within assigned paths. Return node map, content check and inspected screenshot.
