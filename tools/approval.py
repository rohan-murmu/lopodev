#!/usr/bin/env python3
"""Tool-permission approval modes for agent sessions in a LopoDev workspace.

`auto` (default) lets agents edit files and run ordinary commands without a
prompt. `manual` asks before every edit and every non-read-only command.
In both modes destructive, publishing, credential and human-gate commands
still require an explicit yes, and nothing here can approve a pipeline gate:
`pipeline_state.py approve|reject|reopen` always prompts, so a human sees the
recorded statement before it is written.

The mode lives in `.lopodev/config.json` and is rendered into the OpenCode
`permission` key (OpenCode evaluates rules in order; the last match wins).
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path

MODES = ("auto", "manual")
DEFAULT_MODE = "auto"

# Always prompt, in every mode. Order matters: these come after the catch-all.
GUARDED_COMMANDS = [
    "rm -rf *", "rm -fr *", "rm -r *", "rm -R *", "sudo *", "su *",
    "chmod -R *", "chown -R *", "dd *", "mkfs*", "shred *",
    "git push*", "git reset --hard*", "git clean*", "git checkout -- *",
    "git restore *", "git rebase*", "git commit --amend*", "git branch -D*",
    "git stash drop*", "git filter-branch*", "gh release*", "gh repo*", "gh pr merge*",
    "npm publish*", "twine upload*", "brew tap*", "brew uninstall*",
    "adb uninstall*", "*keytool*", "*apksigner sign*", "*jarsigner*",
    "curl * | *sh*", "wget * | *sh*",
    "*pipeline_state.py approve*", "*pipeline_state.py reject*", "*pipeline_state.py reopen*",
]

READ_ONLY_COMMANDS = [
    "ls*", "pwd", "cat *", "head *", "tail *", "wc *", "grep *", "rg *", "find *",
    "git status*", "git diff*", "git log*", "git show*",
    "lopodev doctor*", "lopodev version*", "lopodev knowledge search*",
    "lopodev knowledge show*", "lopodev context*",
    "python3 tools/pipeline_state.py show*", "python3 tools/pipeline_state.py next-task*",
    "python3 tools/pipeline_state.py list-tasks*", "python3 tools/pipeline_state.py validate*",
    "python3 tools/knowledge.py search*", "python3 tools/knowledge.py show*",
    "python3 tools/context_pack.py*", "python3 tools/lopodev_log.py tail*",
    "codemap*",
]


def policy(mode: str) -> dict:
    if mode not in MODES:
        raise ValueError(f"approval mode must be one of {', '.join(MODES)}")
    if mode == "auto":
        bash = {"*": "allow"}
        bash.update({pattern: "ask" for pattern in GUARDED_COMMANDS})
        return {"edit": "allow", "webfetch": "allow", "external_directory": "ask",
                "doom_loop": "ask", "bash": bash}
    bash = {"*": "ask"}
    bash.update({pattern: "allow" for pattern in READ_ONLY_COMMANDS})
    bash.update({pattern: "ask" for pattern in GUARDED_COMMANDS})
    return {"edit": "ask", "webfetch": "ask", "external_directory": "ask",
            "doom_loop": "ask", "bash": bash}


def config_path(workspace: Path) -> Path:
    return workspace / ".lopodev/config.json"


def read_config(workspace: Path) -> dict:
    try:
        data = json.loads(config_path(workspace).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def current_mode(workspace: Path) -> str:
    mode = read_config(workspace).get("approval_mode", DEFAULT_MODE)
    return mode if mode in MODES else DEFAULT_MODE


def record_mode(workspace: Path, mode: str, previous: str, source: str) -> None:
    config = read_config(workspace)
    config["approval_mode"] = mode
    path = config_path(workspace)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(config, indent=2) + "\n", encoding="utf-8")
    os.replace(temporary, path)
    event = {"ts": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
             "event": "approval_mode", "from": previous, "to": mode, "source": source}
    with (workspace / ".lopodev/events.jsonl").open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(event) + "\n")
