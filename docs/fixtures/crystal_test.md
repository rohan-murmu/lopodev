# Crystal Arena Regression Fixture

The fixture is intentionally outside this repository:

```text
/media/rohan/D5/MyProjects/crystal_test/
```

It is a real, playable Godot game used to prove that toolkit changes do not
break existing projects. It is not a committed Git submodule and its binaries
must not be copied into this repository.

## Link layout

```text
crystal_test/AGENTS.md     -> repository AGENTS.md
crystal_test/.gitignore    -> repository .gitignore
crystal_test/templates     -> repository templates
crystal_test/tools         -> repository tools
crystal_test/projects/crystal_test/
```

## Recorded baseline

| Item | Value |
|---|---|
| Slug | `crystal_test` |
| Main scene | `res://scenes/CrystalArena.tscn` |
| Gate | `complete` |
| Assets | `sm_hover_drone`, `sm_crystal`, `sm_arena` |
| Binary bytes | 71,110,432 |
| Binary SHA-256 | `334409f5d7068e459de30da6a93cab390fc9399d90b33f1762821a8423824b4` |
| Release tar SHA-256 | `5dff9566a79eeaccd227fc368732b998805f0fcedcbea0da77ac3f01d0da8633` |

## Verification

```bash
tools/verify_opengame.sh \
  --crystal /media/rohan/D5/MyProjects/crystal_test/projects/crystal_test

tools/verify_opengame.sh \
  --crystal /media/rohan/D5/MyProjects/crystal_test/projects/crystal_test --full
```

The full run checks state, event-log compatibility, content, runtime movement,
gameplay assertions, and a graphical screenshot. The build gate is separate:

```bash
cd /media/rohan/D5/MyProjects/crystal_test
tools/godot/export_build.sh projects/crystal_test/godot Linux \
  projects/crystal_test/build/crystal_test.x86_64
```

Last verified: 2026-10-23. The rebuilt binary hash matched the baseline. The
screenshot at
`projects/crystal_test/artifacts/screenshots/verify_opengame.png` was inspected
and shows the drone, arena, three crystals, HUD, and controls.

## Rules

- Do not copy fixture source or binaries into this repository.
- Do not delete or rewrite fixture files.
- Re-run this regression after changing `tools/`, `templates/`, `AGENTS.md`, or
  state formats.
- If a legacy status/field changes, preserve backward compatibility or document
  a migration.
