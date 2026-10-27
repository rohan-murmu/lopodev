# Repository dependency map

This is a source-level map of the current implementation. The workflow remains
Markdown-first; deterministic Python/Bash helpers own validation and state.

```text
Agent platform
  OpenCode: opencode.json -> .opencode/agents, commands, skills -> native task tool
  Kilo:     .kilo/agents (installed adapter) + .agents/skills -> Kilo runtime
  Cursor:   .cursor/rules + .cursor/agents + .agents/skills -> Cursor Agent
  MCP:      tools/mcp_server.py -> pipeline_state, validate_spec, lopodev_log,
                                  tools/godot/android_export.py

Shared workflow contract
  AGENTS.md + templates/GAME_SPEC.md + templates/project.json
  projects/<slug>/GAME_SPEC.md + project.json + pipeline_state.json
  artifacts/events.jsonl + artifacts/qa_report.json

Work tools
  tools/blender/* -> Blender CLI -> .blend/GLB/meta/previews -> Godot
  tools/godot/*   -> Godot CLI -> import/content/runtime/visual/export evidence
  tools/godot/android_export.py -> shared APK/AAB core -> shell wrapper, CLI, MCP
```

## Ownership and boundaries

| Component | Reusable logic | Platform coupling |
|---|---|---|
| `AGENTS.md`, project specs, templates | Naming, safety, gates, acceptance contracts | None; shared instructions and state source of truth |
| `.opencode/skills/` | Domain procedures; shared Agent Skill-style Markdown | OpenCode discovery path; several procedures name LopoDev tools |
| `.opencode/agents/` | Lead/specialist roles and return contracts | OpenCode frontmatter, native `task` delegation and permissions |
| `.opencode/commands/` | Repeatable workflows | OpenCode slash-command format and `$ARGUMENTS` |
| `tools/pipeline_state.py` | Gates, task dependencies, durable state, validation | No agent runtime dependency |
| `tools/lopodev_log.py`, `qa_report.py`, `validate_spec.py` | Evidence, schema and spec validation | No agent runtime dependency |
| `tools/blender/`, `tools/godot/` | Deterministic production and QA operations | External Blender/Godot executables; Blender MCP is optional |
| `adapters/` | Native platform entry instructions | Kilo/Cursor-specific formats; Kilo and Cursor delegate via their own Task support |
| `tools/mcp_server.py` | Safe project-scoped status/context/validation/checkpoint and Android export operations | Official Python MCP SDK optional dependency; not a general agent orchestrator |
| `tools/godot/android_export.py` | Android preset/signing/capability/import/artifact/signature validation and export | Godot, Android SDK/JDK, `apksigner`/`jarsigner`; Gradle template for AAB |
| `bin/loopdev`, `tools/loopdev_cli.py` | Install adapter files, diagnose tools, report package update path | Python 3; Homebrew formula must package resources |

## Preservation and cleanup findings

- Keep `tools/evidence.py` and `tools/run_poc.sh`: the tracked PoC runner uses
  this earlier evidence ledger and remains a reproducible vertical-slice check.
- Keep `tools/verify_lopodev.sh`: documented regression runner; it checks native
  OpenCode discovery and can run Crystal fixture gates.
- Keep `projects/prop_poc/artifacts/`: tracked outputs substantiate the PoC and
  are not caches. Developer-local absolute paths in historical logs/reports are
  replaced by `<LOCAL_PATH>`; `.godot/`, `build/`, and Python caches are generated/ignored.
- `.opencode/package.json` is not needed by the current Markdown-native agent
  definitions, but its contents declare the OpenCode plugin SDK; it is retained
  because package-managed plugin extensions may depend on it. It is not used by
  the current OpenCode workflows.
- `.mcp.json` is Codemap setup, not LoopDev workflow logic; its command uses
  `PATH` and workspace-relative root. Existing `.claude/settings.local.json` is
  user-local and untracked; installers do not modify it.
- `docs/lopodev-audit.md` and `docs/implementation-plan.md` capture historical
  decisions. They are not runtime inputs, but deleting them would remove audit
  context, so they remain.

The configured Git remote and verified GitHub repository are
`https://github.com/rohan-murmu/lopodev`; the repository currently has no tags or
releases. Historical PoC logs retain test outcomes with machine paths redacted.
The repository therefore cannot truthfully claim an already-published Homebrew
release. See
[`installation.md`](installation.md) for the metadata-gated formula workflow.
