#!/usr/bin/env python3
"""Record QA gate evidence in a JSON ledger. Never upgrades NOT RUN to a pass."""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

VALID_STATUS = {"PASS", "FAIL", "NOT RUN"}


def load(report_path: Path) -> dict:
    if report_path.exists():
        try:
            data = json.loads(report_path.read_text())
            if isinstance(data, dict):
                return data
        except json.JSONDecodeError:
            pass
    return {"gates": []}


def record(args: argparse.Namespace) -> int:
    if args.status not in VALID_STATUS:
        print(f"invalid status: {args.status}", file=sys.stderr)
        return 2
    report_path = args.report
    data = load(report_path)
    entry = {
        "gate": args.gate,
        "status": args.status,
        "command": args.command,
        "evidence": args.evidence,
        "details": args.details,
        "recorded_at_utc": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
    }
    data["gates"].append(entry)
    data["updated_at_utc"] = entry["recorded_at_utc"]
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(data, indent=2) + "\n")
    print(f"EVIDENCE_RECORDED gate={args.gate} status={args.status} report={report_path}")
    return 0


def show(args: argparse.Namespace) -> int:
    data = load(args.report)
    print(f"report={args.report} updated={data.get('updated_at_utc', 'never')}")
    for entry in data.get("gates", []):
        print(f"{entry.get('gate', '?'):12s} {entry.get('status', '?'):8s} "
              f"{entry.get('evidence', '')}")
    return 0


def reset(args: argparse.Namespace) -> int:
    report_path = args.report
    data = {
        "gates": [],
        "updated_at_utc": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
    }
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(data, indent=2) + "\n")
    print(f"EVIDENCE_RESET report={report_path}")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    rec = sub.add_parser("record")
    rec.add_argument("--report", type=Path, required=True)
    rec.add_argument("--gate", required=True)
    rec.add_argument("--status", required=True, choices=sorted(VALID_STATUS))
    rec.add_argument("--command", default="")
    rec.add_argument("--evidence", default="")
    rec.add_argument("--details", default="")
    rec.set_defaults(func=record)

    show_parser = sub.add_parser("show")
    show_parser.add_argument("--report", type=Path, required=True)
    show_parser.set_defaults(func=show)

    reset_parser = sub.add_parser("reset", help="start a new evidence report")
    reset_parser.add_argument("--report", type=Path, required=True)
    reset_parser.set_defaults(func=reset)

    args = parser.parse_args()
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
