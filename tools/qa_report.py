#!/usr/bin/env python3
"""Create and validate the evidence-backed QA report.

This is a reporting helper, not a test runner. It refuses to record a PASS or
FAIL without a command and evidence path, and a NOT RUN without a reason.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

STATUSES = {"PASS", "FAIL", "NOT RUN"}
SCHEMA_VERSION = 1


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def report_path(project: Path) -> Path:
    return project / "artifacts" / "qa_report.json"


def load_report(project: Path) -> dict:
    path = report_path(project)
    if not path.is_file():
        return {
            "schema_version": SCHEMA_VERSION,
            "slug": project.name,
            "created_at_utc": utc_now(),
            "updated_at_utc": utc_now(),
            "environment": {},
            "gates": [],
        }
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ValueError(f"invalid QA report JSON: {exc}") from exc
    if not isinstance(data, dict) or not isinstance(data.get("gates"), list):
        raise ValueError("QA report must be an object with a gates list")
    # First-draft reports used ``gate`` instead of ``name`` and had no slug or
    # schema version. Normalize in memory so a real historical report remains
    # readable and valid without rewriting its evidence.
    data.setdefault("schema_version", SCHEMA_VERSION)
    data.setdefault("slug", project.name)
    data.setdefault("environment", {})
    data.setdefault("created_at_utc", data.get("updated_at_utc", utc_now()))
    data.setdefault("updated_at_utc", data.get("created_at_utc", utc_now()))
    for gate in data["gates"]:
        if isinstance(gate, dict) and not gate.get("name") and gate.get("gate"):
            gate["name"] = gate["gate"]
    return data


def save_report(project: Path, data: dict) -> Path:
    data["updated_at_utc"] = utc_now()
    path = report_path(project)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    return path


def record_gate(data: dict, args: argparse.Namespace) -> None:
    status = args.status.upper()
    if status not in STATUSES:
        raise ValueError(f"status must be one of {sorted(STATUSES)}")
    if status in {"PASS", "FAIL"}:
        if not args.command.strip():
            raise ValueError(f"{status} requires --command")
        if not args.evidence.strip():
            raise ValueError(f"{status} requires --evidence")
    if status == "NOT RUN" and not (args.notes.strip() or args.reason.strip()):
        raise ValueError("NOT RUN requires --reason or --notes")
    record = {
        "name": args.name,
        "status": status,
        "command": args.command.strip(),
        "exit_code": args.exit_code,
        "evidence": args.evidence.strip(),
        "recorded_at_utc": utc_now(),
        "notes": args.notes.strip(),
        "reason": args.reason.strip(),
    }
    gates = [gate for gate in data["gates"] if gate.get("name") != args.name]
    gates.append(record)
    data["gates"] = gates
    if args.reset:
        data["gates"] = [record]


def validate_report(data: dict) -> list[str]:
    errors = []
    if data.get("schema_version") != SCHEMA_VERSION:
        errors.append("schema_version must be 1")
    if not data.get("slug"):
        errors.append("slug is missing")
    names = set()
    for index, gate in enumerate(data.get("gates", [])):
        name = gate.get("name")
        if not name:
            errors.append(f"gates[{index}] missing name")
        elif name in names:
            errors.append(f"duplicate gate name: {name}")
        names.add(name)
        status = gate.get("status")
        if status not in STATUSES:
            errors.append(f"gate {name!r} has invalid status: {status!r}")
        if status in {"PASS", "FAIL"}:
            if not gate.get("command"):
                errors.append(f"gate {name!r} is {status} without command")
            if not gate.get("evidence"):
                errors.append(f"gate {name!r} is {status} without evidence")
        if status == "NOT RUN" and not (gate.get("reason") or gate.get("notes")):
            errors.append(f"gate {name!r} is NOT RUN without a reason")
    return errors


def cmd_record(args: argparse.Namespace) -> int:
    project = Path(args.project).expanduser().resolve()
    if not project.is_dir():
        print(f"ERROR: project directory does not exist: {project}", file=sys.stderr)
        return 2
    try:
        data = load_report(project)
        record_gate(data, args)
    except ValueError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2
    if args.environment:
        for item in args.environment:
            if "=" not in item:
                print(f"ERROR: --environment expects key=value: {item}", file=sys.stderr)
                return 2
            key, value = item.split("=", 1)
            data["environment"][key] = value
    path = save_report(project, data)
    print(f"QA_GATE_RECORDED={args.name} status={args.status} report={path}")
    return 0


def cmd_show(args: argparse.Namespace) -> int:
    project = Path(args.project).expanduser().resolve()
    try:
        data = load_report(project)
    except ValueError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2
    counts: dict[str, int] = {}
    for gate in data.get("gates", []):
        status = gate.get("status", "?")
        counts[status] = counts.get(status, 0) + 1
        print(f"{gate.get('name', '?'):32s} {status:8s} {gate.get('evidence', '')}")
    print("QA_COUNTS=" + ",".join(f"{k}:{v}" for k, v in sorted(counts.items())))
    return 0


def cmd_validate(args: argparse.Namespace) -> int:
    project = Path(args.project).expanduser().resolve()
    try:
        data = load_report(project)
    except ValueError as exc:
        print(f"QA_REPORT_CHECK=FAIL {exc}", file=sys.stderr)
        return 1
    errors = validate_report(data)
    print(f"QA_REPORT_CHECK={'PASS' if not errors else 'FAIL'} "
          f"gates={len(data.get('gates', []))}")
    for error in errors:
        print(f"ERROR: {error}")
    return 0 if not errors else 1


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    record = sub.add_parser("record", help="record or replace one QA gate")
    record.add_argument("--project", required=True)
    record.add_argument("--name", required=True)
    record.add_argument("--status", required=True,
                        choices=["PASS", "FAIL", "NOT RUN", "pass", "fail", "not run"])
    record.add_argument("--command", default="")
    record.add_argument("--exit-code", type=int)
    record.add_argument("--evidence", default="")
    record.add_argument("--notes", default="")
    record.add_argument("--reason", default="")
    record.add_argument("--environment", action="append", default=[],
                        help="key=value environment fact, repeatable")
    record.add_argument("--reset", action="store_true",
                        help="discard previous gates and start a new report")
    record.set_defaults(func=cmd_record)
    show = sub.add_parser("show", help="print recorded gates")
    show.add_argument("--project", required=True)
    show.set_defaults(func=cmd_show)
    validate = sub.add_parser("validate", help="validate report structure and evidence")
    validate.add_argument("--project", required=True)
    validate.set_defaults(func=cmd_validate)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return args.func(args)
    except (OSError, ValueError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
