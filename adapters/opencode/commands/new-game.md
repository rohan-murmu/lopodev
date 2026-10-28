---
description: Start a game from a Game Brief (structured first prompt) - fill, check, scaffold, then plan Gate A.
agent: lopodev
---
Start a new game from this brief or idea: `$ARGUMENTS`.

1. If the text is not already a Game Brief (`Genre:`, `Core loop:` ... lines),
   show `lopodev brief template` and map the idea onto its fields yourself;
   leave unknown fields blank rather than inventing details.
2. Save it as `GAME_BRIEF.md` in the workspace and run
   `lopodev brief check GAME_BRIEF.md`. Ask the user only about `MISSING`
   required fields (genre, core loop, controls, platform, win) and real
   `CONTRADICTION` lines, in one message.
3. Choose a lowercase snake_case slug and create the project:
   `lopodev new --workspace . --slug <slug> --title "<title>" --brief GAME_BRIEF.md`.
4. Run `python3 tools/validate_spec.py projects/<slug>/project.json --no-file-checks`
   and `python3 tools/pipeline_state.py sync-spec --project projects/<slug> --spec projects/<slug>/project.json`.
5. Delegate to `game-design` to turn the scaffold into `GAME_SPEC.md`
   (story, loop, mechanics, screens, acceptance) and to review every entry in
   `assumptions`.
6. Present Gate A: the brief, the assumptions list, assets (including edits
   such as derived models), tasks and acceptance. Never approve it yourself.
