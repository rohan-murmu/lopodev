#!/usr/bin/env python3
"""Persistent approval-gated state for the automated game development pipeline.

The state file lives inside a game project and records the current gate, human
approvals and rejections, tasks, assets, tests, issues, and recovery notes. It is
plain JSON so a new agent session can resume without conversation history.
"""

from __future__ import annotations

import argparse
import contextlib
import json
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

SCHEMA_VERSION = 1
STATE_FILENAME = "pipeline_state.json"
SLUG_RE = re.compile(r"^[a-z][a-z0-9_]*$")

GATES = [
    ("A", "Requirements and game plan"),
    ("B", "Character and asset previews"),
    ("C", "Animation previews"),
    ("D", "First playable prototype"),
    ("E", "Integrated gameplay and QA"),
    ("F", "Final release candidate"),
]
GATE_IDS = [gate_id for gate_id, _ in GATES]
GATE_NAMES = dict(GATES)
VALID_GATE_STATUS = {"pending", "proposed", "approved", "rejected"}
# Canonical LopoDev task states. ``pending`` and ``complete`` are retained as
# legacy aliases so projects created by the first draft keep validating.
TASK_STATUSES = {
    "planned", "in_progress", "blocked", "needs_approval", "verified", "failed",
}
LEGACY_TASK_STATUSES = {"pending", "complete"}
VALID_TASK_STATUS = TASK_STATUSES | LEGACY_TASK_STATUSES
TASK_STATUS_ALIASES = {"pending": "planned", "complete": "verified"}
VALID_ASSET_STATUS = {"pending", "validated", "rejected"}
VALID_TEST_STATUS = {"PASS", "FAIL", "NOT RUN"}
VALID_ISSUE_STATUS = {"open", "resolved"}


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def project_path(project: str) -> Path:
    return Path(project).expanduser().resolve()


def state_path(project: str) -> Path:
    return project_path(project) / STATE_FILENAME


@contextlib.contextmanager
def state_lock(project: str | Path):
    """Serialize state read/modify/write operations across CLI and MCP processes."""
    directory = Path(project).expanduser().resolve()
    directory.mkdir(parents=True, exist_ok=True)
    lock_path = directory / ".pipeline_state.lock"
    with lock_path.open("a+b") as lock_file:
        if os.name == "nt":
            import msvcrt
            lock_file.seek(0)
            if lock_file.read(1) == b"":
                lock_file.write(b"0")
                lock_file.flush()
            lock_file.seek(0)
            msvcrt.locking(lock_file.fileno(), msvcrt.LK_LOCK, 1)
            try:
                yield
            finally:
                lock_file.seek(0)
                msvcrt.locking(lock_file.fileno(), msvcrt.LK_UNLCK, 1)
        else:
            import fcntl
            fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX)
            try:
                yield
            finally:
                fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)


def gate_index(gate: str) -> int:
    return GATE_IDS.index(gate)


def previous_gates(gate: str) -> list[str]:
    return GATE_IDS[:gate_index(gate)]


def next_gate(gate: str) -> str:
    index = gate_index(gate) + 1
    return GATE_IDS[index] if index < len(GATE_IDS) else "complete"


def new_state(slug: str, title: str, workspace: str, project_dir: str) -> dict:
    now = utc_now()
    return {
        "schema_version": SCHEMA_VERSION,
        "slug": slug,
        "title": title,
        "workspace": workspace,
        "project_dir": project_dir,
        "created_at_utc": now,
        "updated_at_utc": now,
        "current_gate": "A",
        "gates": {
            gate_id: {
                "name": name,
                "status": "pending",
                "revision": 0,
                "proposed_at_utc": None,
                "approved_at_utc": None,
                "rejected_at_utc": None,
                "reopened_at_utc": None,
                "user_statement": "",
                "reason": "",
                "skip_reason": "",
                "note": "",
                "evidence": [],
            }
            for gate_id, name in GATES
        },
        "tasks": [],
        "assets": [],
        "tests": [],
        "approvals": [],
        "rejections": [],
        "reopenings": [],
        "issues": [],
        "recovery": {
            "next_step": "Run game-planner, write GAME_SPEC.md and project.json, then propose gate A.",
            "last_command": "",
            "notes": [],
        },
    }


def load_state(project: str) -> dict:
    path = state_path(project)
    if not path.is_file():
        raise FileNotFoundError(
            f"state file not found: {path}; run bootstrap_project.py or 'init' first"
        )
    with path.open(encoding="utf-8") as handle:
        data = json.load(handle)
    if data.get("schema_version") != SCHEMA_VERSION:
        raise ValueError(
            f"unsupported state schema_version: {data.get('schema_version')!r}"
        )
    return data


def save_state(project: str, data: dict) -> None:
    path = state_path(project)
    path.parent.mkdir(parents=True, exist_ok=True)
    data["updated_at_utc"] = utc_now()
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n",
                         encoding="utf-8")
    os.replace(temporary, path)


def add_evidence(target: list, values: list[str] | None) -> None:
    for value in values or []:
        if value and value not in target:
            target.append(value)


def require_user_statement(value: str | None, action: str) -> str:
    text = (value or "").strip()
    if not text:
        raise ValueError(
            f"{action} requires --user-statement with the user's actual approval "
            "or rejection words; a tool call or command is not human approval"
        )
    return text


def require_reason(value: str | None, action: str) -> str:
    text = (value or "").strip()
    if not text:
        raise ValueError(f"{action} requires --reason")
    return text


def cmd_init(args: argparse.Namespace) -> int:
    project = project_path(args.project)
    path = project / STATE_FILENAME
    if path.exists():
        print(f"ERROR: state already exists, refusing to overwrite: {path}",
              file=sys.stderr)
        return 2
    if not SLUG_RE.match(args.slug):
        print("ERROR: slug must be lowercase snake_case starting with a letter",
              file=sys.stderr)
        return 2
    if not args.title.strip():
        print("ERROR: title must be non-empty", file=sys.stderr)
        return 2
    project.mkdir(parents=True, exist_ok=True)
    if args.workspace:
        workspace = str(Path(args.workspace).expanduser().resolve())
    elif project.parent.name == "projects":
        workspace = str(project.parent.parent)
    else:
        workspace = str(project)
    data = new_state(args.slug, args.title.strip(), workspace, str(project))
    save_state(str(project), data)
    print(f"STATE_INITIALIZED={path}")
    print(f"CURRENT_GATE=A")
    return 0


def cmd_show(args: argparse.Namespace) -> int:
    data = load_state(args.project)
    if args.json:
        print(json.dumps(data, indent=2, ensure_ascii=False))
        return 0
    print(f"project={data.get('project_dir')} slug={data.get('slug')}")
    print(f"current_gate={data.get('current_gate')} updated={data.get('updated_at_utc')}")
    for gate_id, name in GATES:
        gate = data["gates"][gate_id]
        marker = "*" if data.get("current_gate") == gate_id else " "
        print(f"{marker} {gate_id} {gate['status']:9s} rev={gate['revision']:<2d} {name}")
        if gate.get("user_statement"):
            print(f"    user: {gate['user_statement']}")
    print(f"tasks={len(data.get('tasks', []))} assets={len(data.get('assets', []))} "
          f"tests={len(data.get('tests', []))} issues={len(data.get('issues', []))}")
    print(f"next_step={data.get('recovery', {}).get('next_step', '')}")
    return 0


def cmd_propose(args: argparse.Namespace) -> int:
    data = load_state(args.project)
    gate = data["gates"][args.gate]
    if gate["status"] == "approved":
        print("ERROR: gate is already approved; use 'reopen' with the user's "
              "statement before proposing a revision", file=sys.stderr)
        return 2
    for previous in previous_gates(args.gate):
        if data["gates"][previous]["status"] != "approved":
            print(f"ERROR: gate {args.gate} cannot be proposed before gate "
                  f"{previous} is approved", file=sys.stderr)
            return 2
    gate["status"] = "proposed"
    gate["proposed_at_utc"] = utc_now()
    gate["rejected_at_utc"] = None
    gate["revision"] += 1
    gate["note"] = (args.note or "").strip()
    gate["skip_reason"] = (args.skip_reason or "").strip()
    add_evidence(gate["evidence"], args.evidence)
    data["current_gate"] = args.gate
    save_state(args.project, data)
    print(f"GATE_PROPOSED={args.gate} revision={gate['revision']}")
    print(f"evidence={len(gate['evidence'])}")
    return 0


def cmd_approve(args: argparse.Namespace) -> int:
    data = load_state(args.project)
    gate = data["gates"][args.gate]
    if gate["status"] != "proposed":
        print(f"ERROR: gate {args.gate} is {gate['status']}, not proposed",
              file=sys.stderr)
        return 2
    statement = require_user_statement(args.user_statement, "approval")
    now = utc_now()
    gate["status"] = "approved"
    gate["approved_at_utc"] = now
    gate["user_statement"] = statement
    add_evidence(gate["evidence"], args.evidence)
    data["approvals"].append({
        "gate": args.gate,
        "user_statement": statement,
        "approved_at_utc": now,
        "evidence": list(args.evidence or []),
    })
    data["current_gate"] = next_gate(args.gate)
    if data["current_gate"] == "complete":
        data["recovery"]["next_step"] = "All gates approved. Produce the final report."
    else:
        data["recovery"]["next_step"] = (
            f"Gate {data['current_gate']} ({GATE_NAMES[data['current_gate']]}) "
            "is next; do not start it until the user asks to continue."
        )
    save_state(args.project, data)
    print(f"GATE_APPROVED={args.gate} next={data['current_gate']}")
    return 0


def cmd_reject(args: argparse.Namespace) -> int:
    data = load_state(args.project)
    gate = data["gates"][args.gate]
    if gate["status"] != "proposed":
        print(f"ERROR: gate {args.gate} is {gate['status']}, not proposed",
              file=sys.stderr)
        return 2
    reason = require_reason(args.reason, "rejection")
    statement = require_user_statement(args.user_statement, "rejection")
    now = utc_now()
    gate["status"] = "rejected"
    gate["rejected_at_utc"] = now
    gate["user_statement"] = statement
    gate["reason"] = reason
    data["rejections"].append({
        "gate": args.gate,
        "reason": reason,
        "user_statement": statement,
        "rejected_at_utc": now,
    })
    data["current_gate"] = args.gate
    data["recovery"]["next_step"] = (
        f"Revise gate {args.gate}, preserve approved artifacts, then propose it again."
    )
    save_state(args.project, data)
    print(f"GATE_REJECTED={args.gate} revision={gate['revision']}")
    return 0


def cmd_reopen(args: argparse.Namespace) -> int:
    data = load_state(args.project)
    gate = data["gates"][args.gate]
    if gate["status"] != "approved":
        print(f"ERROR: gate {args.gate} is {gate['status']}, not approved",
              file=sys.stderr)
        return 2
    reason = require_reason(args.reason, "reopen")
    statement = require_user_statement(args.user_statement, "reopen")
    now = utc_now()
    gate["status"] = "pending"
    gate["reopened_at_utc"] = now
    gate["user_statement"] = statement
    gate["reason"] = reason
    data["reopenings"].append({
        "gate": args.gate,
        "reason": reason,
        "user_statement": statement,
        "reopened_at_utc": now,
    })
    data["current_gate"] = args.gate
    data["recovery"]["next_step"] = (
        f"Revise the approved work for gate {args.gate} without discarding artifacts "
        "the user did not authorize changing."
    )
    save_state(args.project, data)
    print(f"GATE_REOPENED={args.gate}")
    return 0


def _upsert(items: list[dict], key: str, value: str, payload: dict) -> dict:
    for item in items:
        if item.get(key) == value:
            item.update(payload)
            return item
    items.append(payload)
    return payload


def cmd_record_task(args: argparse.Namespace) -> int:
    data = load_state(args.project)
    if args.status not in VALID_TASK_STATUS:
        print(f"ERROR: invalid task status: {args.status}", file=sys.stderr)
        return 2
    canonical = TASK_STATUS_ALIASES.get(args.status, args.status)
    if canonical == "verified":
        evidence = [value for value in (args.evidence or []) if value]
        if not evidence and not (args.verification or "").strip():
            print("ERROR: a verified task needs --evidence or --verification; "
                  "generating a file or running a tool is not verification",
                  file=sys.stderr)
            return 2
        failed = [t for t in data.get("tests", [])
                  if t.get("status") == "FAIL" and (not args.gate or t.get("gate") == args.gate)]
        if failed:
            print(f"ERROR: task {args.id} cannot be verified while gate "
                  f"{args.gate or '?'} has {len(failed)} FAIL test(s)", file=sys.stderr)
            return 2
    existing = next((item for item in data["tasks"] if item.get("id") == args.id), None)
    payload = dict(existing or {})
    payload["id"] = args.id
    if args.title is not None:
        payload["title"] = args.title
    payload["status"] = args.status
    if args.skill:
        payload["skills"] = list(args.skill)
    if args.depends_on is not None:
        payload["depends_on"] = list(args.depends_on)
    if args.evidence:
        current = list(payload.get("evidence", []))
        add_evidence(current, args.evidence)
        payload["evidence"] = current
    if args.owner is not None:
        payload["owner"] = args.owner
    if args.changed_file:
        current = list(payload.get("changed_files", []))
        add_evidence(current, args.changed_file)
        payload["changed_files"] = current
    if args.acceptance is not None:
        payload["acceptance"] = args.acceptance
    if args.verification is not None:
        payload["verification"] = args.verification
    if args.issue:
        current = list(payload.get("issues", []))
        add_evidence(current, args.issue)
        payload["issues"] = current
    if args.gate is not None:
        payload["gate"] = args.gate
    if args.note is not None:
        payload["note"] = args.note
    payload["updated_at_utc"] = utc_now()
    _upsert(data["tasks"], "id", args.id, payload)
    save_state(args.project, data)
    print(f"TASK_RECORDED={args.id} status={args.status}")
    if canonical != args.status:
        print(f"TASK_STATUS_ALIAS={args.status}->{canonical}")
    return 0


def _task_is_done(task: dict) -> bool:
    return TASK_STATUS_ALIASES.get(task.get("status"), task.get("status")) == "verified"


SKILL_OWNER = {
    "game-planner": "game-design",
    "blender-modeling": "modeling",
    "blender-animation": "animation",
    "game-world": "level-design",
    "godot-gameplay": "gameplay",
    "mobile-low-poly": "ui",
    "lopodev-workflow": "lopodev",
    "game-qa": "qa-release",
}


def cmd_sync_spec(args: argparse.Namespace) -> int:
    data = load_state(args.project)
    spec_path = Path(args.spec).expanduser().resolve()
    try:
        spec = json.loads(spec_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        print(f"ERROR: cannot read spec: {exc}", file=sys.stderr)
        return 2
    tasks = spec.get("tasks")
    assets = spec.get("assets")
    if not isinstance(tasks, list) or not tasks:
        print("ERROR: spec has no tasks to sync", file=sys.stderr)
        return 2
    existing_tasks = {task.get("id"): task for task in data.get("tasks", [])}
    existing_assets = {asset.get("id"): asset for asset in data.get("assets", [])}
    added_tasks = 0
    added_assets = 0
    seen_spec_tasks: set[str] = set()
    for task in tasks:
        task_id = task.get("id")
        if not task_id:
            print("ERROR: every spec task needs an id", file=sys.stderr)
            return 2
        if task_id in seen_spec_tasks:
            print(f"ERROR: duplicate task id in spec: {task_id}", file=sys.stderr)
            return 2
        seen_spec_tasks.add(task_id)
        if task_id in existing_tasks:
            continue
        skills = list(task.get("skills") or [])
        owner = task.get("owner") or (SKILL_OWNER.get(skills[0]) if skills else "")
        data["tasks"].append({
            "id": task_id,
            "title": task.get("title", ""),
            "status": "planned",
            "owner": owner,
            "skills": skills,
            "depends_on": list(task.get("depends_on") or []),
            "acceptance": task.get("verify", ""),
            "verification": "",
            "evidence": [],
            "changed_files": [],
            "issues": [],
            "gate": task.get("gate"),
            "note": "",
            "updated_at_utc": utc_now(),
        })
        added_tasks += 1
    for asset in assets or []:
        asset_id = asset.get("id")
        if not asset_id or asset_id in existing_assets:
            continue
        data["assets"].append({
            "id": asset_id,
            "path": "",
            "status": "pending",
            "triangles": 0,
            "animated": bool(asset.get("animated", False)),
            "evidence": [],
            "note": "planned from project.json",
            "updated_at_utc": utc_now(),
        })
        added_assets += 1
    errors = validate_state(data)
    if errors:
        print("ERROR: synced state would be invalid:", file=sys.stderr)
        for error in errors:
            print(f"  {error}", file=sys.stderr)
        return 2
    if args.dry_run:
        print(f"SYNC_DRY_RUN tasks={added_tasks} assets={added_assets}")
        return 0
    save_state(args.project, data)
    print(f"SYNCED_SPEC={spec_path} tasks_added={added_tasks} assets_added={added_assets}")
    return 0


def cmd_next_task(args: argparse.Namespace) -> int:
    data = load_state(args.project)
    tasks = data.get("tasks", [])
    by_id = {t.get("id"): t for t in tasks}
    ready = []
    blocked = []
    for task in tasks:
        if _task_is_done(task):
            continue
        status = TASK_STATUS_ALIASES.get(task.get("status"), task.get("status"))
        missing = [dep for dep in task.get("depends_on", [])
                   if dep not in by_id or not _task_is_done(by_id[dep])]
        if missing or status in {"blocked", "failed", "needs_approval"}:
            reason = ",".join(missing) if missing else f"status:{status}"
            blocked.append((task.get("id"), [reason]))
        else:
            ready.append(task)
    print(f"READY_TASKS={len(ready)} BLOCKED_TASKS={len(blocked)}")
    for task in ready:
        print(f"READY {task.get('id')} status={task.get('status')} "
              f"owner={task.get('owner', '')} title={task.get('title', '')}")
    for task_id, missing in blocked:
        print(f"BLOCKED {task_id} waiting_on={','.join(missing)}")
    return 0


def cmd_list_tasks(args: argparse.Namespace) -> int:
    data = load_state(args.project)
    counts: dict[str, int] = {}
    for task in data.get("tasks", []):
        status = task.get("status", "?")
        counts[status] = counts.get(status, 0) + 1
        print(f"{task.get('id', '?'):12s} {status:14s} "
              f"owner={task.get('owner', '-'):12s} deps="
              f"{','.join(task.get('depends_on', [])) or '-'} "
              f"{task.get('title', '')}")
    print("TASK_COUNTS=" + ",".join(f"{key}:{value}" for key, value in sorted(counts.items())))
    return 0


def cmd_record_asset(args: argparse.Namespace) -> int:
    data = load_state(args.project)
    if args.status not in VALID_ASSET_STATUS:
        print(f"ERROR: invalid asset status: {args.status}", file=sys.stderr)
        return 2
    payload = {
        "id": args.id,
        "path": args.path or "",
        "status": args.status,
        "triangles": args.triangles,
        "animated": args.animated,
        "evidence": list(args.evidence or []),
        "note": (args.note or "").strip(),
        "updated_at_utc": utc_now(),
    }
    _upsert(data["assets"], "id", args.id, payload)
    save_state(args.project, data)
    print(f"ASSET_RECORDED={args.id} status={args.status}")
    return 0


def cmd_record_test(args: argparse.Namespace) -> int:
    data = load_state(args.project)
    status = args.status.upper()
    if status not in VALID_TEST_STATUS:
        print(f"ERROR: invalid test status: {args.status}", file=sys.stderr)
        return 2
    data["tests"].append({
        "gate": args.gate,
        "name": args.name,
        "status": status,
        "command": args.command or "",
        "evidence": args.evidence or "",
        "details": (args.details or "").strip(),
        "recorded_at_utc": utc_now(),
    })
    save_state(args.project, data)
    print(f"TEST_RECORDED={args.name} gate={args.gate} status={status}")
    return 0


def cmd_record_issue(args: argparse.Namespace) -> int:
    data = load_state(args.project)
    if args.status not in VALID_ISSUE_STATUS:
        print(f"ERROR: invalid issue status: {args.status}", file=sys.stderr)
        return 2
    payload = {
        "id": args.id,
        "summary": args.summary or "",
        "status": args.status,
        "note": (args.note or "").strip(),
        "updated_at_utc": utc_now(),
    }
    _upsert(data["issues"], "id", args.id, payload)
    save_state(args.project, data)
    print(f"ISSUE_RECORDED={args.id} status={args.status}")
    return 0


def cmd_set_recovery(args: argparse.Namespace) -> int:
    data = load_state(args.project)
    data["recovery"]["next_step"] = args.next_step.strip()
    if args.last_command:
        data["recovery"]["last_command"] = args.last_command
    if args.note:
        data["recovery"]["notes"].append({
            "note": args.note.strip(),
            "recorded_at_utc": utc_now(),
        })
    save_state(args.project, data)
    print(f"RECOVERY_UPDATED={data['recovery']['next_step']}")
    return 0


def validate_state(data: dict) -> list[str]:
    errors: list[str] = []
    if data.get("schema_version") != SCHEMA_VERSION:
        errors.append("schema_version must be 1")
    if not isinstance(data.get("slug"), str) or not SLUG_RE.match(data.get("slug", "")):
        errors.append("slug must be lowercase snake_case")
    if not isinstance(data.get("title"), str) or not data.get("title", "").strip():
        errors.append("title must be non-empty")
    gates = data.get("gates")
    if not isinstance(gates, dict):
        return errors + ["gates must be an object"]
    for gate_id, _ in GATES:
        gate = gates.get(gate_id)
        if not isinstance(gate, dict):
            errors.append(f"missing gate: {gate_id}")
            continue
        status = gate.get("status")
        if status not in VALID_GATE_STATUS:
            errors.append(f"gate {gate_id} has invalid status: {status!r}")
        if status in {"proposed", "approved", "rejected"} and not gate.get("proposed_at_utc"):
            errors.append(f"gate {gate_id} is {status} without proposed_at_utc")
        if status == "approved":
            if not gate.get("approved_at_utc"):
                errors.append(f"gate {gate_id} approved without approved_at_utc")
            if not str(gate.get("user_statement", "")).strip():
                errors.append(f"gate {gate_id} approved without user_statement")
            for previous in previous_gates(gate_id):
                if gates.get(previous, {}).get("status") != "approved":
                    errors.append(
                        f"gate {gate_id} approved before gate {previous}"
                    )
        if status == "rejected":
            if not str(gate.get("reason", "")).strip():
                errors.append(f"gate {gate_id} rejected without reason")
            if not str(gate.get("user_statement", "")).strip():
                errors.append(f"gate {gate_id} rejected without user_statement")
    current = data.get("current_gate")
    if current not in GATE_IDS and current != "complete":
        errors.append(f"invalid current_gate: {current!r}")
    if current == "complete":
        for gate_id, _ in GATES:
            if gates.get(gate_id, {}).get("status") != "approved":
                errors.append("current_gate is complete but not all gates are approved")
                break
    task_id_list = [task.get("id") for task in data.get("tasks", [])
                    if isinstance(task, dict) and task.get("id")]
    if len(task_id_list) != len(set(task_id_list)):
        errors.append("task ids must be unique")
    task_ids = set(task_id_list)
    task_graph = {task.get("id"): list(task.get("depends_on", []))
                  for task in data.get("tasks", [])
                  if isinstance(task, dict) and task.get("id")
                  and isinstance(task.get("depends_on", []), list)}
    visiting: set[str] = set()
    visited: set[str] = set()

    def has_cycle(task_id: str) -> bool:
        if task_id in visiting:
            return True
        if task_id in visited:
            return False
        visiting.add(task_id)
        for dependency in task_graph.get(task_id, []):
            if dependency in task_graph and has_cycle(dependency):
                return True
        visiting.remove(task_id)
        visited.add(task_id)
        return False

    if any(has_cycle(task_id) for task_id in task_graph):
        errors.append("task dependencies contain a cycle")
    for index, task in enumerate(data.get("tasks", [])):
        if task.get("status") not in VALID_TASK_STATUS:
            errors.append(f"tasks[{index}] invalid status: {task.get('status')!r}")
        depends_on = task.get("depends_on", [])
        if not isinstance(depends_on, list):
            errors.append(f"tasks[{index}].depends_on must be a list")
            continue
        for dep in depends_on:
            if dep not in task_ids:
                errors.append(f"tasks[{index}] depends on unknown task: {dep!r}")
        if task.get("gate") is not None and task.get("gate") not in GATE_IDS:
            errors.append(f"tasks[{index}].gate is invalid: {task.get('gate')!r}")
        canonical = TASK_STATUS_ALIASES.get(task.get("status"), task.get("status"))
        if canonical == "verified":
            if not task.get("evidence") and not task.get("verification"):
                errors.append(f"tasks[{index}] is verified without evidence or verification")
    for index, asset in enumerate(data.get("assets", [])):
        if asset.get("status") not in VALID_ASSET_STATUS:
            errors.append(f"assets[{index}] invalid status: {asset.get('status')!r}")
    for index, test in enumerate(data.get("tests", [])):
        if test.get("status") not in VALID_TEST_STATUS:
            errors.append(f"tests[{index}] invalid status: {test.get('status')!r}")
    for index, issue in enumerate(data.get("issues", [])):
        if issue.get("status") not in VALID_ISSUE_STATUS:
            errors.append(f"issues[{index}] invalid status: {issue.get('status')!r}")
    return errors


def cmd_validate(args: argparse.Namespace) -> int:
    data = load_state(args.project)
    errors = validate_state(data)
    print(f"STATE_CHECK={'PASS' if not errors else 'FAIL'}")
    print(f"project={data.get('project_dir')} current_gate={data.get('current_gate')}")
    for error in errors:
        print(f"ERROR: {error}")
    return 0 if not errors else 1


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    init = sub.add_parser("init", help="create a new state file without overwriting")
    init.add_argument("--project", required=True)
    init.add_argument("--slug", required=True)
    init.add_argument("--title", required=True)
    init.add_argument("--workspace", default=None)
    init.set_defaults(func=cmd_init)

    show = sub.add_parser("show", help="show gate and work status")
    show.add_argument("--project", required=True)
    show.add_argument("--json", action="store_true")
    show.set_defaults(func=cmd_show)

    propose = sub.add_parser("propose", help="propose a gate for human approval")
    propose.add_argument("--project", required=True)
    propose.add_argument("--gate", required=True, choices=GATE_IDS)
    propose.add_argument("--evidence", action="append", default=[])
    propose.add_argument("--note", default="")
    propose.add_argument("--skip-reason", default="")
    propose.set_defaults(func=cmd_propose)

    approve = sub.add_parser("approve", help="record explicit human approval")
    approve.add_argument("--project", required=True)
    approve.add_argument("--gate", required=True, choices=GATE_IDS)
    approve.add_argument("--user-statement", required=True)
    approve.add_argument("--evidence", action="append", default=[])
    approve.set_defaults(func=cmd_approve)

    reject = sub.add_parser("reject", help="record explicit human rejection")
    reject.add_argument("--project", required=True)
    reject.add_argument("--gate", required=True, choices=GATE_IDS)
    reject.add_argument("--reason", required=True)
    reject.add_argument("--user-statement", required=True)
    reject.set_defaults(func=cmd_reject)

    reopen = sub.add_parser("reopen", help="reopen an approved gate with authorization")
    reopen.add_argument("--project", required=True)
    reopen.add_argument("--gate", required=True, choices=GATE_IDS)
    reopen.add_argument("--reason", required=True)
    reopen.add_argument("--user-statement", required=True)
    reopen.set_defaults(func=cmd_reopen)

    task = sub.add_parser("record-task", help="record or update a task")
    task.add_argument("--project", required=True)
    task.add_argument("--id", required=True)
    task.add_argument("--title", default=None)
    task.add_argument("--status", required=True,
                      choices=sorted(VALID_TASK_STATUS))
    task.add_argument("--owner", default=None,
                      help="agent responsible, e.g. gameplay or qa-release")
    task.add_argument("--skill", action="append", default=[])
    task.add_argument("--depends-on", action="append", default=None)
    task.add_argument("--changed-file", action="append", default=[])
    task.add_argument("--acceptance", default=None)
    task.add_argument("--verification", default=None)
    task.add_argument("--issue", action="append", default=[])
    task.add_argument("--gate", default=None, choices=GATE_IDS)
    task.add_argument("--evidence", action="append", default=[])
    task.add_argument("--note", default=None)
    task.set_defaults(func=cmd_record_task)

    sync = sub.add_parser("sync-spec", help="import new tasks/assets from project.json without overwriting state")
    sync.add_argument("--project", required=True)
    sync.add_argument("--spec", required=True)
    sync.add_argument("--dry-run", action="store_true")
    sync.set_defaults(func=cmd_sync_spec)

    next_task = sub.add_parser("next-task", help="show tasks whose dependencies are verified")
    next_task.add_argument("--project", required=True)
    next_task.set_defaults(func=cmd_next_task)

    list_tasks = sub.add_parser("list-tasks", help="list tasks and status counts")
    list_tasks.add_argument("--project", required=True)
    list_tasks.set_defaults(func=cmd_list_tasks)

    asset = sub.add_parser("record-asset", help="record or update an asset")
    asset.add_argument("--project", required=True)
    asset.add_argument("--id", required=True)
    asset.add_argument("--path", default="")
    asset.add_argument("--status", required=True)
    asset.add_argument("--triangles", type=int, default=None)
    asset.add_argument("--animated", action="store_true")
    asset.add_argument("--evidence", action="append", default=[])
    asset.add_argument("--note", default="")
    asset.set_defaults(func=cmd_record_asset)

    test = sub.add_parser("record-test", help="record a gate result")
    test.add_argument("--project", required=True)
    test.add_argument("--gate", required=True)
    test.add_argument("--name", required=True)
    test.add_argument("--status", required=True)
    test.add_argument("--command", default="")
    test.add_argument("--evidence", default="")
    test.add_argument("--details", default="")
    test.set_defaults(func=cmd_record_test)

    issue = sub.add_parser("record-issue", help="record or update an issue")
    issue.add_argument("--project", required=True)
    issue.add_argument("--id", required=True)
    issue.add_argument("--summary", default="")
    issue.add_argument("--status", required=True)
    issue.add_argument("--note", default="")
    issue.set_defaults(func=cmd_record_issue)

    recovery = sub.add_parser("set-recovery", help="set the next safe step")
    recovery.add_argument("--project", required=True)
    recovery.add_argument("--next-step", "--next", dest="next_step", required=True)
    recovery.add_argument("--last-command", default="")
    recovery.add_argument("--note", default="")
    recovery.set_defaults(func=cmd_set_recovery)

    validate = sub.add_parser("validate", help="validate the state file")
    validate.add_argument("--project", required=True)
    validate.set_defaults(func=cmd_validate)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        read_only = getattr(args, "command", None) in {
            "show", "next-task", "list-tasks", "validate",
        }
        if getattr(args, "project", None) and not read_only:
            # Serialize every read/modify/write operation across CLI and MCP.
            # Readers need no lock because saves replace the JSON atomically.
            with state_lock(args.project):
                return args.func(args)
        return args.func(args)
    except (FileNotFoundError, ValueError, json.JSONDecodeError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
