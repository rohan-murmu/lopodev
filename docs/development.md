# Development notes

- Shared rules and project contracts: `AGENTS.md`, `templates/`, and
  `projects/<slug>/{GAME_SPEC.md,project.json,pipeline_state.json}`.
- Canonical skills live in `resources/skills/`. Every adapter source lives
  under `adapters/<platform>/` and mirrors its install path. `.opencode/`,
  `.kilo/`, `.cursor/`, and `.agents/skills/` are generated install targets and
  are gitignored. Run `./bin/lopodev install opencode --project .` after cloning
  to use OpenCode in this repository.
- `tools/` contains deterministic implementations, not an agent runtime.
- `tools/mcp_server.py` uses the optional official Python MCP SDK; standard
  tests cover its project-scoped business logic without needing a running model.
- `tools/godot/android_export.py` is the single APK/AAB implementation. The shell
  wrapper, `lopodev android-export`, and MCP tool delegate to it. Add new Android
  validation there, not in a platform adapter or duplicate script.
- `tools/homebrew_formula.py` renders formula code only from explicit release
  metadata. It does not create releases, tags, credentials or checksums.
- `tools/sanitize_local_paths.py --check` checks tracked text for machine-local
  absolute paths before publication; `--apply` replaces them with
  `<LOCAL_PATH>` in recorded text evidence.

Run local tests with:

```sh
python3 -m unittest discover -s tools/tests -v
tools/verify_lopodev.sh
```

When changing state behavior, preserve the JSON schema unless migration is
necessary. State CLI commands serialize access using a per-project lock file;
state writes use a temp file and atomic replacement. Do not manually remove a
lock while an agent is active.
