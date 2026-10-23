# Agent Orchestration

## Global registration

The reusable agent is installed globally at:

```text
~/.config/opencode/agents/automated-game-dev-agent.md
```

The project skills are registered globally through `~/.config/opencode/opencode.json`:

```json
{
  "skills": {
    "paths": [
      "/media/rohan/D5/MyProjects/automated-game-dev-agent/.opencode/skills"
    ]
  }
}
```

This is additive: it does not replace any existing global skill path or MCP
server. The agent runs as a primary OpenCode agent with the following
permissions:

- edits: allowed;
- bash: allowed, except `rm *`, `git reset *`, `git clean *`, and `git push *`
  require approval, and `sudo *` is denied;
- `question`: allowed so approval gates can be presented;
- external directories: the toolkit root is allowed, everything else asks.

Restart OpenCode after changing the agent or config so the TUI reloads them.

## Approval gates

| Gate | Name | Artifact handed to the human |
|---|---|---|
| A | Requirements and game plan | `GAME_SPEC.md`, `project.json`, tasks, assets, acceptance criteria, risks |
| B | Character and asset previews | `.blend`, validated `.glb`, `.meta.json`, validator JSON, rendered previews |
| C | Animation previews | animated `.glb`, channel report, frame strip, Godot import and runtime animation evidence |
| D | First playable | one core loop, controls, scene, runtime smoke, real screenshot |
| E | Integrated gameplay and QA | all mechanics, cumulative technical gates, QA report, known limitations |
| F | Release candidate | final export, acceptance table, known limitations, final report |

A gate is skipped only when it has no real work, and the skip still needs
explicit human approval.

## Persistent state

Each project owns `pipeline_state.json`:

```text
projects/<slug>/pipeline_state.json
```

It records:

- current gate and per-gate status (`pending`, `proposed`, `approved`, `rejected`),
- approval and rejection history with the human's statement,
- tasks, assets, tests, issues, and the next safe recovery step.

The source of truth on resume is the state file, not conversation history.

```bash
python3 tools/pipeline_state.py show --project projects/<slug>
python3 tools/pipeline_state.py propose --project projects/<slug> --gate A --evidence "<paths>" --note "<change>"
python3 tools/pipeline_state.py approve --project projects/<slug> --gate A --user-statement "<approval>"
python3 tools/pipeline_state.py reject --project projects/<slug> --gate A --reason "<reason>" --user-statement "<reply>"
python3 tools/pipeline_state.py record-test --project projects/<slug> --gate A --name "<check>" --status PASS --command "<command>" --evidence "<path>"
python3 tools/pipeline_state.py validate --project projects/<slug>
```

`approve` refuses an empty statement. A successful command, a generated plan,
or file existence is never treated as approval.

## Workspace bootstrap

```bash
python3 tools/bootstrap_project.py \
  --workspace "$PWD" \
  --slug my_game \
  --title "My Game"
```

The script creates `projects/my_game/` and links `tools/`, `templates/`,
`AGENTS.md`, and `.gitignore` back to the toolkit. It refuses to overwrite an
existing project. It writes `project.json`, `GAME_SPEC.md`,
`ASSET_LICENSES.md`, `pipeline_state.json`, and a minimal Godot project. Run
toolkit commands from the workspace root; the `tools/` link is at the workspace
root, not inside each project.

The planner then fills the spec and task list. Gate A is proposed only after
`tools/validate_spec.py` passes or its remaining failures are explicitly
recorded.

## Resume protocol

1. Read `pipeline_state.json`.
2. Show the current gate, approvals, open issues, and next safe step.
3. Continue only the approved milestone.
4. If state is missing but a project exists, ask before creating or adopting
   state.
5. Never re-run approved work merely because a new session started.

## Validation performed

```bash
opencode debug agent automated-game-dev-agent
opencode debug skill
python3 tools/bootstrap_project.py --workspace <temp> --slug test_game --title "Test Game"
python3 tools/pipeline_state.py validate --project <temp>/projects/test_game
```

Results:

- Agent loads as `primary`, with `question` and `skill` tools enabled.
- Skill discovery returns 14 skills, including all six game-pipeline skills.
- Bootstrap creates the expected files, symlinks, and `current_gate=A`.
- `tools/check_env.sh` returns `ENV_CHECK=PASS` from both the toolkit root and a
  linked workspace; `env.sh` resolves the real toolkit root through symlinks.
- State validation returns `STATE_CHECK=PASS`.
- Blender MCP responds to `get_scene_info`.
- `tools/run_poc.sh` returns `POC_RESULT=PASS` with all eight gates PASS.

## Known limitations

- Humanoid character rigging and animation are not yet tested. Only one-bone
  prop animation has passed Blender export, Godot import, runtime state, and
  preview inspection.
- The existing `projects/prop_poc` is a legacy PoC without a
  `pipeline_state.json`; it has not been retrofitted with recorded approvals.
- OpenCode must be restarted before the global agent appears in the TUI.
- The agent's global path is machine-specific; moving the toolkit requires
  updating the agent prompt and `skills.paths`.
