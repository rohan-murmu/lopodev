#!/usr/bin/env python3
"""Build a bounded, task-focused context brief for an agent session.

Small or cheap models do best with a short, authoritative brief instead of a
long conversation. This assembles, in priority order and within a character
budget:

  1. the task: objective, owner, dependencies, verify command, skills
  2. game facts that matter for it (genre, orientation, controls, screens)
  3. gate status and the recorded next safe step
  4. reusable knowledge matching the task (verified first)
  5. open issues and recent failures, so known dead ends are not repeated
  6. pointers to the authoritative files for anything not included

The brief contains references, not copies: agents read the named files when
they need more. Usage:

  lopodev context --project projects/<slug> [--task T3] [--max-chars 6000]
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import integrations  # noqa: E402
import knowledge  # noqa: E402
import lopodev_log  # noqa: E402
import pipeline_state  # noqa: E402

DONE = {"verified", "complete"}


def load_json(path: Path) -> dict:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def pick_task(state: dict, task_id: str | None) -> dict | None:
    tasks = state.get("tasks", [])
    if task_id:
        return next((task for task in tasks if task.get("id") == task_id), None)
    by_id = {task.get("id"): task for task in tasks}
    for status in ("in_progress", "planned", "pending", "failed"):
        for task in tasks:
            if task.get("status") != status:
                continue
            if all(by_id.get(dep, {}).get("status") in DONE for dep in task.get("depends_on", [])):
                return task
    return None


def section(title: str, lines: list[str]) -> str:
    body = "\n".join(line for line in lines if line)
    return f"## {title}\n{body}\n" if body else ""


def task_section(task: dict | None, spec: dict, state: dict) -> str:
    if task is None:
        return section("Task", ["No dependency-ready task. Check gate approvals and "
                                "`python3 tools/pipeline_state.py list-tasks --project <project>`."])
    by_id = {item.get("id"): item for item in state.get("tasks", [])}
    planned = next((item for item in spec.get("tasks", []) if item.get("id") == task.get("id")), {})
    deps = [f"{dep} ({by_id.get(dep, {}).get('status', 'missing')})" for dep in task.get("depends_on", [])]
    skills = task.get("skills") or planned.get("skills") or []
    owner = task.get("owner") or planned.get("owner", "")
    servers = [name for name, server in integrations.load_spec(knowledge.toolkit_root())["mcp_servers"].items()
               if owner in server.get("agents", [])]
    return section(f"Task {task.get('id')}: {task.get('title')}", [
        f"- status: {task.get('status')}  owner: {owner or 'unassigned'}",
        f"- depends on: {', '.join(deps) if deps else 'nothing'}",
        f"- verify: `{task.get('acceptance') or planned.get('verify') or 'not specified - define before coding'}`",
        f"- load skills: {', '.join(skills) if skills else 'see agent definition'}",
        f"- MCP tools available to {owner}: {', '.join(servers) if servers else 'none'}" if owner else "",
        f"- previous note: {task.get('note')}" if task.get("note") else "",
        f"- changed so far: {', '.join(task.get('changed_files', []))}" if task.get("changed_files") else "",
    ])


def game_section(spec: dict) -> str:
    mobile = spec.get("mobile") or {}
    controls = spec.get("controls") or {}
    screens = spec.get("screens") or []
    return section(f"Game: {spec.get('title', '?')}", [
        f"- {spec.get('summary', '')}",
        f"- genre: {spec.get('genre', '?')}  engine: godot {spec.get('engine', {}).get('version', '?')} "
        f"({spec.get('engine', {}).get('renderer', '?')})",
        f"- mobile: orientation={mobile.get('orientation', '?')} touch={mobile.get('touch_input', '?')} "
        f"budget={json.dumps(mobile.get('budget', {}))}" if mobile else "",
        f"- controls: {controls.get('scheme', '?')}: "
        + ", ".join(f"{c.get('id')}->{c.get('action')}" for c in controls.get("touch", []))
        if controls else "",
        f"- screens: {', '.join(s.get('id', '?') for s in screens)} (entry: "
        f"{(spec.get('navigation') or {}).get('entry', '?')})" if screens else "",
        f"- main scene: {spec.get('main_scene', '?')}  godot dir: {spec.get('godot_dir', '?')}",
    ])


def gate_section(state: dict) -> str:
    gates = state.get("gates", {})
    current = state.get("current_gate", "?")
    return section("Gates", [
        "- " + "  ".join(f"{gate}:{info.get('status')}" for gate, info in gates.items()),
        f"- current gate: {current}; work outside it needs the human's approval",
        f"- next safe step: {state.get('recovery', {}).get('next_step', '')}",
    ])


def knowledge_section(project: Path, task: dict | None, spec: dict) -> str:
    if task is None:
        return ""
    query = " ".join([task.get("title", ""), *task.get("skills", []), spec.get("genre", "")])
    version = spec.get("engine", {}).get("version")
    platform = "android" if (spec.get("platforms") or {}).get("mobile") == "android" else None
    try:
        results = knowledge.search(project, query, "godot" if version else None, version, platform, limit=3)
    except knowledge.KnowledgeError as exc:
        return section("Reusable knowledge", [f"- unavailable: {exc}"])
    lines = [f"- {entry['id']} [{entry.get('status')}] {entry.get('title')} "
             f"-> `lopodev knowledge show {entry['id']}`" for _, entry in results]
    if not lines:
        lines = ["- no match; after verifying your solution, record it with `lopodev knowledge add`"]
    else:
        lines.append("- candidate entries are unproven: validate them here before relying on them")
    return section("Reusable knowledge (check before implementing)", lines)


def history_section(project: Path, state: dict) -> str:
    lines = []
    for issue in state.get("issues", []):
        if issue.get("status") not in ("resolved", "closed"):
            lines.append(f"- open issue {issue.get('id')}: {issue.get('title') or issue.get('summary', '')}")
    failing = [test for test in state.get("tests", []) if test.get("status") == "FAIL"]
    for test in failing[-3:]:
        lines.append(f"- FAIL gate {test.get('gate')} {test.get('name')}: {test.get('evidence', '')}")
    events = lopodev_log.read_events(project / "artifacts/events.jsonl") \
        if (project / "artifacts/events.jsonl").is_file() else []
    for event in [e for e in events if e.get("status") in ("FAIL", "failed", "blocked")][-3:]:
        lines.append(f"- {event.get('ts', '')} {event.get('event')}: {event.get('message', '')}")
    return section("Known problems (do not repeat)", lines)


def build(project: Path, task_id: str | None = None, max_chars: int = 6000) -> str:
    spec = load_json(project / "project.json")
    state_error = ""
    state: dict = {}
    if (project / "pipeline_state.json").is_file():
        try:
            state = pipeline_state.load_state(str(project))
        except (ValueError, OSError, json.JSONDecodeError) as exc:
            state_error = (f"- pipeline_state.json is unreadable ({exc}); run "
                           f"`python3 tools/pipeline_state.py validate --project {project}` and repair it first")
    task = pick_task(state, task_id)
    parts = [
        f"# LopoDev context: {project.name}\n",
        task_section(task, spec, state),
        game_section(spec),
        section("Gates", [state_error]) if state_error else
        gate_section(state) if state else section("Gates", ["- no pipeline_state.json; run `lopodev new`"]),
        knowledge_section(project, task, spec),
        history_section(project, state),
        section("Authoritative files (read when needed)", [
            f"- {project / 'GAME_SPEC.md'}", f"- {project / 'project.json'}",
            f"- {project / 'pipeline_state.json'}", f"- {project / 'artifacts/events.jsonl'}",
            f"- {project / 'knowledge'}/ (project memory)"]),
    ]
    text = ""
    for part in parts:
        if len(text) + len(part) > max_chars:
            text += f"\n(truncated at {max_chars} chars; see authoritative files)\n"
            break
        text += part + "\n"
    return text.rstrip() + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="lopodev context", description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--project", required=True)
    parser.add_argument("--task")
    parser.add_argument("--max-chars", type=int, default=6000)
    args = parser.parse_args(argv)
    project = Path(args.project).resolve()
    if not project.is_dir():
        print(f"ERROR: project not found: {args.project}", file=sys.stderr)
        return 2
    print(build(project, args.task, args.max_chars), end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
