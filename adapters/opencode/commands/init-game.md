---
description: Bootstrap a new LopoDev project and produce a measurable Gate A plan.
agent: lopodev
---
Create a new project for: `$ARGUMENTS`.

1. Choose a lowercase snake_case slug and title. If the user did not provide
   enough information, state assumptions instead of asking about reversible
   details.
2. Run
   `python3 tools/bootstrap_project.py --workspace . --slug <slug> --title "<title>"`.
3. Run `python3 tools/validate_spec.py projects/<slug>/project.json` and
   `python3 tools/pipeline_state.py validate --project projects/<slug>`.
4. Delegate to `game-design` with the full brief protocol. Require a complete
   `GAME_SPEC.md`, mobile budget if relevant, ordered tasks, assets, measurable
   acceptance criteria, and risks.
5. Independently validate the spec and state. Then present Gate A for explicit
   human approval. Do not start modeling before approval.
