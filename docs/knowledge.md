# Persistent engineering knowledge

LopoDev keeps what it learns in plain JSON files, so a solution found while
building one game (a multitouch joystick, an Android export fix, a navigation
pattern) is found, adapted and re-validated in the next game instead of being
re-invented. Nothing depends on a model provider, a database or a running
service: any agent that can run a command or call the LopoDev MCP server can use it.

## Scopes and stores

| Scope | Location | Holds | Survives |
|---|---|---|---|
| Project memory | `projects/<slug>/knowledge/` | decisions and recipes for one game; `applied.json` reuse log | the project |
| User knowledge | `$LOPODEV_DATA/knowledge/` (default `~/.local/share/lopodev/knowledge/`) | reusable recipes you verified or promoted | sessions, games, upgrades, uninstall |
| Bundled | `<toolkit>/resources/knowledge/` | recipes shipped and verified with LopoDev | read-only; overlays can mark them failed |
| Task/session state | `projects/<slug>/pipeline_state.json`, `artifacts/events.jsonl` | gates, tasks, tests, issues, next safe step | the project |

Search order is project, then user, then bundled; an id found earlier shadows
later stores. Project entries are never visible from another project.

## Entry format (schema_version 1)

One file per entry: `entries/<id>.json`. Substantial code lives beside it in
`artifacts/<id>/` and is referenced, not pasted.

```json
{
  "schema_version": 1,
  "id": "godot-screen-router",
  "kind": "recipe",                     // recipe | lesson | decision
  "scope": "global",                    // global | project (+ "project": "<slug>")
  "title": "Screen router: menus, overlays, pause, restart and back navigation",
  "topic": "ui/navigation",
  "tags": ["pause", "android-back", "restart"],
  "engine": {"name": "godot", "versions": ">=4.2,<4.7"},   // or null
  "platforms": ["any"],
  "problem": "What breaks without this.",
  "approach": "The verified technique, in a few sentences.",
  "prerequisites": ["project settings or assets it needs"],
  "integration": ["step-by-step adoption in a new game"],
  "expected_behavior": "What a correct integration does.",
  "artifacts": [{"path": "artifacts/godot-screen-router/screen_router.gd",
                 "install_to": "scripts/core/screen_router.gd"}],
  "limitations": ["what was not proven"],
  "failure_modes": [{"symptom": "...", "cause": "...", "fix": "..."}],
  "validation": {"command": "...", "last_result": "PASS", "validated_at": "...",
                 "engine_version": "4.6.1", "evidence": ["evidence/<log>"]},
  "status": "verified",                 // candidate | verified | deprecated | failed
  "provenance": {"source": "...", "created_at": "...", "project": "<origin>"},
  "history": [{"ts": "...", "status": "verified", "note": "verify --run exit=0"}]
}
```

`lopodev knowledge validate` checks every store: required fields, id format,
version constraints, artifact paths (relative, present), verified entries carry
PASS evidence, and no secrets (private keys, tokens, `password=` values).

## Status rules

- `add` always creates a `candidate`, whatever the draft says.
- Only `verify --run` changes status: it executes `validation.command` (with
  `$LOPODEV_KNOWLEDGE_BASE` and `$LOPODEV_HOME` set), stores the log as evidence
  (paths redacted), and records `verified` on exit 0 or `failed` otherwise.
- `promote` copies a **verified** project entry to user knowledge as a new
  `candidate`; it must be verified again outside its original project.
- `fail` / `deprecate` hide an entry from search. On bundled entries this is an
  overlay in `$LOPODEV_DATA/knowledge/overlay.json`; toolkit files are not edited.
- `apply` refuses failed/deprecated entries and never overwrites a file. It logs
  the reuse in `projects/<slug>/knowledge/applied.json` with
  `verified_in_project: false`: reuse is not verification.

## Daily use

```bash
# Before implementing (engine/platform filters drop incompatible entries)
lopodev knowledge search touch joystick look --project projects/my_game --engine-version 4.6.1 --platform android
lopodev knowledge show godot-mobile-touch-controls
lopodev knowledge apply godot-mobile-touch-controls --project projects/my_game --godot-dir projects/my_game/godot

# After a verified milestone
lopodev knowledge add draft.json --project projects/my_game          # candidate
lopodev knowledge verify pinch-zoom-camera --run --project projects/my_game
lopodev knowledge promote pinch-zoom-camera --project projects/my_game --note "camera-agnostic"
lopodev knowledge verify pinch-zoom-camera --run                     # re-verify globally

# Maintenance
lopodev knowledge list
lopodev knowledge fail godot-screen-router --reason "breaks on 4.7: <log>"
lopodev knowledge validate
```

`lopodev context --project projects/<slug> [--task T3]` assembles a bounded
(about 6 KB) brief for one task: dependency status, verify command, skills,
enabled MCP tools, the top matching knowledge, open issues and recent failures.
Agents start from it instead of re-reading the whole project.

MCP clients get the same through `lopodev_task_brief`,
`lopodev_knowledge_search` and `lopodev_knowledge_show` (`lopodev install mcp`).

## Bundled entries

| id | Kind | Verified by |
|---|---|---|
| `godot-mobile-touch-controls` | recipe | headless Godot 4.6.1 multitouch test (`resources/knowledge/checks/test_mobile_touch.gd`) |
| `godot-screen-router` | recipe | headless navigation test (`test_screen_router.gd`) |
| `godot-safe-area` | recipe | headless safe-area mapping test (`test_safe_area.gd`) |
| `godot-headless-touch-testing` | lesson | same touch test |

Maintainers re-verify them in a checkout with
`LOPODEV_ENGINE_VERSION=4.6.1 lopodev knowledge verify <id> --run --maintainer`,
which writes the redacted log to `resources/knowledge/evidence/`. None of them
has been run on a physical device; their `limitations` say so.

## What not to store

Secrets, keystores, credentials, personal data, chat transcripts and reasoning
dumps. Store the decision, the command, the evidence path and the limitation.
Game-specific choices (this game's input map, level layout) belong in project
memory, not in global recipes.

## Why no vector database

Entries are few, short and tagged; token-overlap search with engine/platform
filters and status ranking finds them reliably and is fully inspectable. Add
semantic retrieval only if the store grows to where keyword search measurably
misses relevant entries.
