---
description: Adopt an existing Godot project safely, establish a baseline, and avoid rewriting working game files.
agent: lopodev
---
Adopt the existing Godot project at `$ARGUMENTS` (expected format:
`<godot_dir> <slug> "<title>"`).

1. Inspect `project.godot`, main scene, scenes, scripts, GLBs, and licenses.
   Do not modify the existing game directory.
2. Run `python3 tools/adopt_project.py --godot-dir <godot_dir> \
   --project projects/<slug> --slug <slug> --title "<title>"`.
3. Review `docs/ADOPTION_REPORT.md` and `GAME_SPEC.md`.
4. Delegate a read-only inventory to `level-design`, then a baseline QA run to
   `qa-release`. Record content/runtime/visual/build as PASS, FAIL, or NOT RUN.
5. Present Gate A for the adoption scope. Any change to existing gameplay needs
   explicit approval after the baseline.
