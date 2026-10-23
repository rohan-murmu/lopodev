#!/usr/bin/env python3
"""Persistent approval-gated state for the automated game development pipeline.

The state file lives inside a game project and records the current gate, human
approvals and rejections, tasks, assets, tests, issues, and recovery notes. It is
plain JSON so a new OpenCode session can resume without conversation history.
"""

from __future__ import annotations

import argparse
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
VALID_TASK_STATUS = {"pending", "in_progress", "complete", "blocked"}
VALID_ASSET_STATUS = {"pending", "validated", "rejected"}
VALID_TEST_STATUS = {"PASS", "FAIL", "NOT RUN"}
VALID_ISSUE_STATUS = {"open", "resolved"}


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def project_path(project: str) -> Path:
    return Path(project).expanduser().resolve()


def state_path(project: str) -> Path:
    return project_path(project) / STATE_FILENAME


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
    payload = {
        "id": args.id,
        "title": args.title or "",
        "status": args.status,
        "skills": list(args.skill or []),
        "depends_on": list(args.depends_on or []),
        "evidence": list(args.evidence or []),
        "note": (args.note or "").strip(),
        "updated_at_utc": utc_now(),
    }
    _upsert(data["tasks"], "id", args.id, payload)
    save_state(args.project, data)
    print(f"TASK_RECORDED={args.id} status={args.status}")
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
    for index, task in enumerate(data.get("tasks", [])):
        if task.get("status") not in VALID_TASK_STATUS:
            errors.append(f"tasks[{index}] invalid status: {task.get('status')!r}")
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
    task.add_argument("--title", default="")
    task.add_argument("--status", required=True)
    task.add_argument("--skill", action="append", default=[])
    task.add_argument("--depends-on", action="append", default=[])
    task.add_argument("--evidence", action="append", default=[])
    task.add_argument("--note", default="")
    task.set_defaults(func=cmd_record_task)

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
    recovery.add_argument("--next-step", required=True)
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
        return args.func(args)
    except (FileNotFoundError, ValueError, json.JSONDecodeError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
