# Game Brief

A Game Brief is the recommended first prompt. A fixed set of fields gives the
planner everything a complete game needs on the first try: the planner turns
the brief into a spec instead of guessing or stopping to ask.

```sh
lopodev brief template > GAME_BRIEF.md
lopodev brief check GAME_BRIEF.md
lopodev new --workspace . --slug <slug> --title "<title>" --brief GAME_BRIEF.md
# or, for an existing draft project:
lopodev brief scaffold GAME_BRIEF.md --project projects/<slug>
```

In OpenCode: `/new-game <brief or idea>`.

## Format

`Key: value` lines. For a list, write the key and then `- item` lines, or put
the items on one line separated by commas. `#` headings and `<!-- comments -->`
are ignored. Key names are forgiving (`Setting`, `Theme/setting` and `Theme`
mean the same field).

| Section | Fields |
|---|---|
| Identity | Title, Pitch, **Genre**, References |
| Look | Art style (any), Theme/setting, Mood, Palette, Camera |
| Story | Premise, Protagonist, Goal, Antagonist, Ending, Tone |
| Play | **Core loop**, **Win**, Lose, Mechanics (must/should/could), Progression, Session length |
| Controls | **Platform**, Orientation, **Controls**, Actions |
| World | Levels/areas, World, World size (small/medium/large), Landmarks, Enemy placement |
| Characters | `- name (role, anim/anim/...)`; role is player, enemy, npc, boss or ally |
| Assets | Must-have assets, Asset edits (`- water well -> witch well with ...`), Custom models, Asset sources |
| Screens and audio | Screens (level select, shop/upgrades add screens), Music, SFX |
| Scope | V1 includes, V1 excludes, Performance target, Constraints |

Bold fields are required by `brief check`.

## What `check` catches

- Missing required fields.
- Contradictions:
  - first-person in portrait orientation;
  - a first-person genre with a top-down camera;
  - touch or tilt controls on a desktop-only platform;
  - keyboard-only controls on mobile;
  - a too-short core loop;
  - no lose condition (write `Lose: none` for relaxing games).

## What `scaffold` writes

- **`project.json`** (status stays `draft`):
  - genre, art style, camera, story, core loop, win/lose and mechanics;
  - platform, orientation and budget profile;
  - a touch or keyboard control plan from the `Controls`/`Actions` lines;
  - screens and navigation (menu, settings, credits, game, pause, victory,
    game over when there is a lose condition, plus level select and upgrades
    when asked);
  - asset requirements:
    - characters with their animations;
    - must-have props;
    - custom models (`source: custom`);
    - asset edits as a discovered source plus a `derived` target and a derive task;
    - theme/world suggestions;
  - ordered tasks with owners and verify commands;
  - acceptance criteria (including the emulator check for Android).
- **`assumptions`**: every blank field that was filled in, for Gate A review.
- **`docs/world_plan.json`**: terrain, spawn, goal, main path, Poisson scatter
  for vegetation and rocks, and enemy spawns when there are enemies.
- **`docs/GAME_BRIEF.md`**: the original brief.
- **`project.godot`**: the orientation to match.

The scaffold is a draft for `game-planner`; Gate A still needs your explicit
approval.
