# Contributing to LopoDev

LopoDev succeeds when cheap models succeed with it, so every change should make
the workflow smaller, more explicit, or more verifiable. Read `AGENTS.md` and
`docs/lopodev-architecture.md` first.

## Ground rules

- One system per script; deterministic tools over prompt text.
- Every new behavior needs a test in `tools/tests/` (unittest, no network).
  Import `hermetic` first in tests that install or bootstrap. Tests that need
  Godot, Blender, brew or the MCP SDK must `skipUnless` the tool is present.
- Never hand-edit generated files: `Formula/lopodev.rb`
  (`tools/homebrew_formula.py`), `.opencode/`, `.kilo/`, `.cursor/`, `.agents/`.
- No machine paths in tracked files: `python3 tools/sanitize_local_paths.py --check`.
- Run `python3 -m unittest discover -s tools/tests` and `lopodev verify` before a PR.

## Adding or changing an agent

Agents live in `adapters/<platform>/agents/<name>.md`; OpenCode is the reference.

- Frontmatter must not set `permission.bash`, `permission.edit` or
  `permission.webfetch`: OpenCode appends agent rules after the workspace policy,
  so they would override the approval mode and its guards (a test enforces this).
- MCP access is per agent: list the agent under `agents` for each server in
  `resources/integrations.json`, then add `tools: {"<server>_*": true}` to the
  frontmatter (see `modeling.md` for the deny-after pattern).
- Keep the "Context, knowledge, skills and tools" section: context brief,
  knowledge search, named skills, enabled MCP tools, 3-attempt correction loop,
  knowledge capture.
- If the lead must delegate to it, add it to the lead's `permission.task` allowlist.
- Check the result in a scratch workspace with `opencode debug agent <name>`.

## Adding a LopoDev skill

Create `resources/skills/<name>/SKILL.md` with `name` equal to the directory.
Sections: required inputs, expected outputs, workflow, validation, failure
recovery, handoff. Add the name to `KNOWN_SKILLS` in `tools/validate_spec.py`
and to the agents that should load it. Keep it procedural and short.

## Adding or bumping a third-party integration

Edit `resources/integrations.json` only:

- Skill packs: `repo`, full `commit`, and the `sha256` of
  `https://codeload.github.com/<repo>/tar.gz/<commit>` (download it twice to
  confirm the archive is stable), the curated `skills` list and the `excluded`
  reasons. A vendored skill must not share a name with a LopoDev skill.
- MCP servers: exact `version`, `agents`, and `environment`. Never enable paid
  or telemetry tools; deny them in agent frontmatter.
- Verify: `lopodev setup`, a fresh workspace with `lopodev install opencode`,
  `lopodev doctor --project <ws> --probe`, and the unit tests.
- Record the upstream license; only MIT/Apache/BSD-style or explicitly permitted.

## Adding knowledge

See `docs/knowledge.md` for the schema. For bundled recipes:

1. Put code under `resources/knowledge/artifacts/<id>/` and a check under
   `resources/knowledge/checks/` that fails loudly and cannot pass vacuously
   (assert preconditions; Godot checks run through `tools/knowledge_godot_check.py`).
2. Write `resources/knowledge/entries/<id>.json` with `status: candidate`.
3. `LOPODEV_ENGINE_VERSION=<ver> lopodev knowledge verify <id> --run --maintainer`
   records evidence under `resources/knowledge/evidence/`.
4. `lopodev knowledge validate`, then commit entry, artifacts, check and evidence.

Document what was not proven (device, OS, engine versions) in `limitations`.

## Releases

See `docs/installation.md#release-procedure`.
