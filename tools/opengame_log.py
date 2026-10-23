#!/usr/bin/env python3
"""Append and inspect structured OpenGame events as JSON Lines.

The log is intentionally lightweight and local: one JSON object per line under
``projects/<slug>/artifacts/events.jsonl`` by default. Events are evidence for
retrospectives, not a replacement for pipeline_state.json.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

SECRET_KEY_RE = re.compile(
    r"(token|secret|password|passwd|api[_-]?key|authorization|credential|private[_-]?key)",
    re.IGNORECASE,
)
MAX_VALUE_CHARS = 2000
EVENT_FIELDS = {
    "event", "agent", "gate", "task", "status", "command", "evidence",
    "message", "data",
}


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def default_log(project: str) -> Path:
    return Path(project).expanduser().resolve() / "artifacts" / "events.jsonl"


def resolve_log(args: argparse.Namespace) -> Path:
    if args.log:
        return Path(args.log).expanduser().resolve()
    if args.project:
        return default_log(args.project)
    raise ValueError("provide --log or --project")


def sanitize(value, key: str = ""):
    if SECRET_KEY_RE.search(key):
        return "<redacted>"
    if isinstance(value, dict):
        return {str(k): sanitize(v, str(k)) for k, v in value.items()}
    if isinstance(value, list):
        return [sanitize(item, key) for item in value]
    if isinstance(value, str) and len(value) > MAX_VALUE_CHARS:
        return value[:MAX_VALUE_CHARS] + f"... <truncated {len(value) - MAX_VALUE_CHARS} chars>"
    return value


def parse_data(values: list[str], json_data: str | None) -> dict:
    data: dict = {}
    if json_data:
        parsed = json.loads(json_data)
        if not isinstance(parsed, dict):
            raise ValueError("--json-data must be a JSON object")
        data.update(parsed)
    for item in values:
        if "=" not in item:
            raise ValueError(f"--data expects key=value, got: {item!r}")
        key, value = item.split("=", 1)
        if not key.strip():
            raise ValueError("--data key must be non-empty")
        data[key.strip()] = value
    return data


def cmd_append(args: argparse.Namespace) -> int:
    path = resolve_log(args)
    event = {"ts_utc": utc_now(), "event": args.event}
    for field in ("agent", "gate", "task", "status", "command", "evidence", "message"):
        value = getattr(args, field, None)
        if value not in (None, ""):
            event[field] = value
    data = parse_data(args.data or [], args.json_data)
    if data:
        event["data"] = sanitize(data)
    event = sanitize(event)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(event, ensure_ascii=False, sort_keys=True) + "\n")
    print(f"EVENT_APPENDED={args.event} log={path}")
    return 0


def read_events(path: Path) -> list[dict]:
    if not path.is_file():
        raise FileNotFoundError(f"event log not found: {path}")
    events = []
    with path.open(encoding="utf-8") as handle:
        for number, line in enumerate(handle, 1):
            text = line.strip()
            if not text:
                continue
            try:
                value = json.loads(text)
            except json.JSONDecodeError as exc:
                raise ValueError(f"{path}:{number}: invalid JSON: {exc}") from exc
            if not isinstance(value, dict):
                raise ValueError(f"{path}:{number}: event must be a JSON object")
            events.append(value)
    return events


def cmd_tail(args: argparse.Namespace) -> int:
    path = resolve_log(args)
    events = read_events(path)
    for event in events[-args.limit:]:
        print(json.dumps(event, ensure_ascii=False, sort_keys=True))
    return 0


def cmd_summary(args: argparse.Namespace) -> int:
    path = resolve_log(args)
    events = read_events(path)
    counts = Counter(event.get("event", "unknown") for event in events)
    statuses = Counter(event.get("status", "") for event in events if event.get("status"))
    agents = Counter(event.get("agent", "") for event in events if event.get("agent"))
    print(f"EVENT_LOG={path} events={len(events)}")
    for name, count in counts.most_common():
        print(f"EVENT {name} {count}")
    for name, count in statuses.most_common():
        print(f"STATUS {name} {count}")
    for name, count in agents.most_common():
        print(f"AGENT {name} {count}")
    if events:
        print(f"FIRST={events[0].get('ts_utc', '?')} LAST={events[-1].get('ts_utc', '?')}")
    return 0


def cmd_validate(args: argparse.Namespace) -> int:
    path = resolve_log(args)
    if not path.is_file() and args.allow_missing:
        print(f"EVENT_LOG_CHECK=PASS events=0 note=missing path={path}")
        return 0
    try:
        events = read_events(path)
    except (OSError, ValueError) as exc:
        print(f"EVENT_LOG_CHECK=FAIL {exc}", file=sys.stderr)
        return 1
    errors = []
    for number, event in enumerate(events, 1):
        if not event.get("ts_utc"):
            errors.append(f"line {number}: missing ts_utc")
        if not event.get("event"):
            errors.append(f"line {number}: missing event")
        unknown = set(event) - {"ts_utc"} - EVENT_FIELDS
        if unknown:
            errors.append(f"line {number}: unknown fields {sorted(unknown)}")
    print(f"EVENT_LOG_CHECK={'PASS' if not errors else 'FAIL'} events={len(events)}")
    for error in errors:
        print(f"ERROR: {error}")
    return 0 if not errors else 1


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    append = sub.add_parser("append", help="append one structured event")
    append.add_argument("--log", type=Path)
    append.add_argument("--project", help="write to <project>/artifacts/events.jsonl")
    append.add_argument("--event", required=True,
                        help="task_start, task_complete, delegation, tool_call, "
                             "error, approval, rejection, validation, issue")
    append.add_argument("--agent")
    append.add_argument("--gate")
    append.add_argument("--task")
    append.add_argument("--status")
    append.add_argument("--command")
    append.add_argument("--evidence")
    append.add_argument("--message")
    append.add_argument("--data", action="append", default=[])
    append.add_argument("--json-data")
    append.set_defaults(func=cmd_append)

    tail = sub.add_parser("tail", help="print the newest events")
    tail.add_argument("--log", type=Path)
    tail.add_argument("--project")
    tail.add_argument("--limit", type=int, default=20)
    tail.set_defaults(func=cmd_tail)

    summary = sub.add_parser("summary", help="count events, statuses and agents")
    summary.add_argument("--log", type=Path)
    summary.add_argument("--project")
    summary.set_defaults(func=cmd_summary)

    validate = sub.add_parser("validate", help="validate every JSONL line")
    validate.add_argument("--log", type=Path)
    validate.add_argument("--project")
    validate.add_argument("--allow-missing", action="store_true",
                          help="treat an absent log as empty (legacy projects)")
    validate.set_defaults(func=cmd_validate)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return args.func(args)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
