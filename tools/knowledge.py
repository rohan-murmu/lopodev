#!/usr/bin/env python3
"""Persistent, inspectable engineering knowledge for LopoDev.

Three stores are searched in this order (see docs/knowledge.md):

  project  projects/<slug>/knowledge/   decisions and recipes for one game
  user     $LOPODEV_DATA/knowledge/     reusable across every game you build
  bundled  <toolkit>/resources/knowledge/  shipped with LopoDev, read-only

Each entry is one JSON file `entries/<id>.json`; larger code lives beside it
under `artifacts/<id>/` and is copied into a game with `apply`. Status moves
candidate -> verified only through `verify --run`, which executes the entry's
validation command and records the evidence. A user can mark a bundled entry
failed or deprecated through an overlay without editing toolkit files.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import integrations  # noqa: E402

SCHEMA_VERSION = 1
KINDS = {"recipe", "lesson", "decision"}
STATUSES = {"candidate", "verified", "deprecated", "failed"}
HIDDEN = {"deprecated", "failed"}
ID_RE = re.compile(r"^[a-z0-9][a-z0-9-]{2,63}$")
REQUIRED = ("id", "kind", "title", "topic", "tags", "problem", "approach", "status")
SECRET_PATTERNS = [
    re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----"),
    re.compile(r"\bAKIA[0-9A-Z]{16}\b"),
    re.compile(r"\bgh[pousr]_[A-Za-z0-9]{30,}\b"),
    re.compile(r"\bsk-[A-Za-z0-9_-]{20,}\b"),
    re.compile(r"(?i)\b(password|passwd|secret|api[_-]?key|token)\b\s*[:=]\s*['\"]?[^\s'\"$<{]{6,}"),
]
TOKEN_RE = re.compile(r"[a-z0-9]+")
WEIGHTS = {"title": 3.0, "tags": 3.0, "topic": 2.0, "problem": 1.0, "approach": 0.5}


class KnowledgeError(Exception):
    pass


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def toolkit_root() -> Path:
    configured = os.environ.get("LOPODEV_HOME")
    if configured:
        return Path(os.path.abspath(Path(configured).expanduser()))
    return Path(__file__).resolve().parent.parent


# ---------------------------------------------------------------- stores

def stores(project: Path | None) -> list[tuple[str, Path]]:
    found = []
    if project is not None:
        found.append(("project", project / "knowledge"))
    found.append(("user", integrations.data_dir() / "knowledge"))
    found.append(("bundled", toolkit_root() / "resources/knowledge"))
    return found


def overlay_path() -> Path:
    return integrations.data_dir() / "knowledge/overlay.json"


def read_overlay() -> dict:
    try:
        return json.loads(overlay_path().read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def write_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp")
    temporary.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    os.replace(temporary, path)


def load_entries(project: Path | None) -> list[dict]:
    """All entries, earlier stores shadowing later ones with the same id."""
    overlay = read_overlay()
    seen: dict[str, dict] = {}
    for store, base in stores(project):
        for path in sorted((base / "entries").glob("*.json")):
            try:
                entry = json.loads(path.read_text(encoding="utf-8"))
            except json.JSONDecodeError as exc:
                raise KnowledgeError(f"invalid JSON in {path}: {exc}") from exc
            if entry.get("id") in seen:
                continue
            entry["_store"] = store
            entry["_path"] = str(path)
            entry["_base"] = str(base)
            if store == "bundled" and entry.get("id") in overlay:
                entry["status"] = overlay[entry["id"]]["status"]
                entry["_overlay"] = overlay[entry["id"]]
            seen[entry["id"]] = entry
    return list(seen.values())


def find(project: Path | None, entry_id: str) -> dict:
    for entry in load_entries(project):
        if entry["id"] == entry_id:
            return entry
    raise KnowledgeError(f"no knowledge entry with id {entry_id!r}")


def public(entry: dict) -> dict:
    return {key: value for key, value in entry.items() if not key.startswith("_")}


# ---------------------------------------------------------------- validation

def scan_secrets(entry: dict) -> list[str]:
    text = json.dumps(public(entry))
    return [f"possible secret matching /{pattern.pattern[:40]}/"
            for pattern in SECRET_PATTERNS if pattern.search(text)]


def version_tuple(text: str) -> tuple[int, ...]:
    return tuple(int(part) for part in re.findall(r"\d+", text)[:3])


def version_matches(spec: str, version: str) -> bool:
    """`spec` is comma-separated constraints like ">=4.4,<4.7" or "4.6"."""
    actual = version_tuple(version)
    for constraint in filter(None, (c.strip() for c in spec.split(","))):
        match = re.fullmatch(r"(>=|<=|==|>|<)?\s*([\d.]+)", constraint)
        if not match:
            return False
        operator, wanted = match.group(1) or "==", version_tuple(match.group(2))
        current = actual[:len(wanted)] if operator == "==" else actual
        if operator == "==" and current != wanted:
            return False
        if operator == ">=" and current < wanted:
            return False
        if operator == ">" and current <= wanted:
            return False
        if operator == "<=" and current > wanted:
            return False
        if operator == "<" and current >= wanted:
            return False
    return True


def validate_entry(entry: dict, base: Path | None = None) -> list[str]:
    errors = []
    for field in REQUIRED:
        if field not in entry or entry[field] in ("", None, []):
            errors.append(f"missing {field}")
    if entry.get("schema_version") != SCHEMA_VERSION:
        errors.append(f"schema_version must be {SCHEMA_VERSION}")
    if not ID_RE.fullmatch(str(entry.get("id", ""))):
        errors.append("id must be 3-64 chars of lowercase letters, digits and hyphens")
    if entry.get("kind") not in KINDS:
        errors.append(f"kind must be one of {sorted(KINDS)}")
    if entry.get("status") not in STATUSES:
        errors.append(f"status must be one of {sorted(STATUSES)}")
    if entry.get("scope") not in {"global", "project"}:
        errors.append("scope must be global or project")
    if entry.get("scope") == "project" and not entry.get("project"):
        errors.append("project-scoped entries must name their project")
    if not isinstance(entry.get("tags"), list):
        errors.append("tags must be a list")
    engine = entry.get("engine")
    if engine is not None and not (isinstance(engine, dict) and engine.get("name")):
        errors.append("engine must be null or {name, versions}")
    if entry.get("status") == "verified":
        validation = entry.get("validation") or {}
        if validation.get("last_result") != "PASS" or not validation.get("evidence"):
            errors.append("verified entries need validation.last_result=PASS and evidence")
    for artifact in entry.get("artifacts", []):
        relative = Path(artifact.get("path", ""))
        if relative.is_absolute() or ".." in relative.parts or not artifact.get("path"):
            errors.append(f"artifact path must be relative inside the store: {artifact}")
        elif base is not None and not (base / relative).is_file():
            errors.append(f"artifact file missing: {relative}")
    errors.extend(scan_secrets(entry))
    return errors


# ---------------------------------------------------------------- search

def tokens(text: str) -> set[str]:
    return set(TOKEN_RE.findall(text.lower()))


def score(entry: dict, query: set[str]) -> float:
    total = 0.0
    for field, weight in WEIGHTS.items():
        value = entry.get(field, "")
        words = tokens(" ".join(value) if isinstance(value, list) else str(value))
        total += weight * len(query & words)
    if total == 0:
        return 0.0
    total += {"verified": 2.0, "candidate": 0.0}.get(entry.get("status"), -5.0)
    total += 1.0 if entry.get("_store") == "project" else 0.0
    return total


def compatible(entry: dict, engine: str | None, version: str | None, platform: str | None) -> bool:
    spec = entry.get("engine")
    if engine and spec and spec.get("name") != engine:
        return False
    if version and spec and spec.get("versions") and not version_matches(spec["versions"], version):
        return False
    platforms = entry.get("platforms") or []
    if platform and platforms and platform not in platforms and "any" not in platforms:
        return False
    return True


def search(project: Path | None, query: str, engine: str | None = None,
           version: str | None = None, platform: str | None = None,
           include_hidden: bool = False, limit: int = 5) -> list[tuple[float, dict]]:
    words = tokens(query)
    results = []
    for entry in load_entries(project):
        if not include_hidden and entry.get("status") in HIDDEN:
            continue
        if not include_hidden and not compatible(entry, engine, version, platform):
            continue
        value = score(entry, words)
        if value > 0:
            results.append((value, entry))
    results.sort(key=lambda item: (-item[0], item[1]["id"]))
    return results[:limit]


# ---------------------------------------------------------------- mutations

def writable_base(entry: dict) -> Path | None:
    return None if entry["_store"] == "bundled" else Path(entry["_base"])


def add_history(entry: dict, status: str, note: str) -> None:
    entry.setdefault("history", []).append({"ts": utc_now(), "status": status, "note": note})


def set_status(project: Path | None, entry_id: str, status: str, note: str) -> dict:
    entry = find(project, entry_id)
    if entry["_store"] == "bundled":
        overlay = read_overlay()
        overlay[entry_id] = {"status": status, "note": note, "ts": utc_now()}
        write_json(overlay_path(), overlay)
        entry["status"] = status
        return entry
    entry["status"] = status
    add_history(entry, status, note)
    write_json(Path(entry["_path"]), public(entry))
    return entry


def add(project: Path | None, source: Path, scope: str) -> dict:
    entry = json.loads(source.read_text(encoding="utf-8"))
    entry.setdefault("schema_version", SCHEMA_VERSION)
    entry["scope"] = scope
    if scope == "project":
        if project is None:
            raise KnowledgeError("--project is required for project-scoped entries")
        entry["project"] = project.name
    # New knowledge is never born verified: run `verify --run` to promote it.
    entry["status"] = "candidate"
    entry.setdefault("provenance", {}).setdefault("created_at", utc_now())
    add_history(entry, "candidate", f"added from {source.name}")
    base = project / "knowledge" if scope == "project" else integrations.data_dir() / "knowledge"
    artifacts_dir = source.parent
    copies = []
    for artifact in entry.get("artifacts", []):
        origin = artifacts_dir / artifact["path"]
        if not origin.is_file():
            raise KnowledgeError(f"artifact not found next to entry: {origin}")
        copies.append((origin, base / artifact["path"]))
    errors = validate_entry(entry)
    if errors:
        raise KnowledgeError("; ".join(errors))
    target = base / "entries" / f"{entry['id']}.json"
    if target.exists():
        raise KnowledgeError(f"entry already exists: {target} (edit it or pick another id)")
    for origin, destination in copies:
        if destination.exists() and destination.read_bytes() != origin.read_bytes():
            raise KnowledgeError(f"refusing to overwrite different artifact: {destination}")
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(origin, destination)
    write_json(target, entry)
    return entry


def verify(project: Path | None, entry_id: str, run: bool, workspace: Path,
           evidence_dir: Path | None = None, maintainer: bool = False) -> tuple[str, dict]:
    """Run the entry's validation. `maintainer` records results on bundled
    entries (toolkit checkout only), with evidence kept inside the store."""
    entry = find(project, entry_id)
    if maintainer and entry["_store"] == "bundled":
        entry["_store"] = "maintainer"
        evidence_dir = Path(entry["_base"]) / "evidence"
    validation = entry.get("validation") or {}
    command = validation.get("command")
    if not command:
        raise KnowledgeError(f"{entry_id} has no validation.command; it cannot be verified")
    if not run:
        return "NOT RUN", entry
    env = dict(os.environ, LOPODEV_KNOWLEDGE_BASE=entry["_base"],
               LOPODEV_HOME=str(toolkit_root()))
    result = subprocess.run(command, shell=True, cwd=workspace, text=True, capture_output=True,
                            timeout=int(validation.get("timeout", 600)), env=env, check=False)
    outcome = "PASS" if result.returncode == 0 else "FAIL"
    if evidence_dir is None and entry["_store"] == "project":
        evidence_dir = Path(entry["_base"]).parent / "artifacts/logs"
    log_dir = evidence_dir or integrations.data_dir() / "knowledge/evidence"
    log_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    log = log_dir / f"{entry_id}-{stamp}.log"
    text = (f"$ {command}\nexit={result.returncode}\n--- stdout\n{result.stdout}"
            f"\n--- stderr\n{result.stderr}")
    # Evidence is shared and may be committed: keep machine paths out of it.
    for private, placeholder in ((str(toolkit_root()), "$LOPODEV_HOME"),
                                 (str(Path(entry["_base"])), "$LOPODEV_KNOWLEDGE_BASE"),
                                 (str(Path.home()), "~")):
        text = text.replace(private, placeholder)
    log.write_text(text, encoding="utf-8")
    if entry["_store"] == "bundled":
        if outcome == "FAIL":
            set_status(project, entry_id, "failed", f"validation failed; see {log}")
        return outcome, entry
    recorded = str(log.relative_to(entry["_base"])) if log.is_relative_to(entry["_base"]) else str(log)
    validation.update({"last_result": outcome, "validated_at": utc_now(), "evidence": [recorded]})
    if engine_version := os.environ.get("LOPODEV_ENGINE_VERSION"):
        validation["engine_version"] = engine_version
    entry["validation"] = validation
    entry["status"] = "verified" if outcome == "PASS" else "failed"
    add_history(entry, entry["status"], f"verify --run exit={result.returncode}; {recorded}")
    write_json(Path(entry["_path"]), public(entry))
    return outcome, entry


def promote(project: Path, entry_id: str, note: str) -> dict:
    entry = find(project, entry_id)
    if entry["_store"] != "project":
        raise KnowledgeError(f"{entry_id} is not a project entry")
    if entry.get("status") != "verified":
        raise KnowledgeError(f"{entry_id} is {entry.get('status')}; run `verify --run` in this "
                             "project before promoting it")
    if not note.strip():
        raise KnowledgeError("--note must say what makes this reusable beyond the project")
    promoted = public(entry)
    promoted.update({"scope": "global", "status": "candidate"})
    promoted.pop("project", None)
    promoted.setdefault("provenance", {})["project"] = project.name
    add_history(promoted, "candidate", f"promoted from project {project.name}: {note}")
    base = integrations.data_dir() / "knowledge"
    target = base / "entries" / f"{entry_id}.json"
    if target.exists():
        raise KnowledgeError(f"global entry already exists: {target}")
    for artifact in entry.get("artifacts", []):
        source = Path(entry["_base"]) / artifact["path"]
        destination = base / artifact["path"]
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, destination)
    write_json(target, promoted)
    return promoted


def apply(project: Path, entry_id: str, godot_dir: Path, dry_run: bool) -> list[str]:
    """Copy an entry's artifacts into a game without overwriting anything."""
    entry = find(project, entry_id)
    if entry.get("status") in HIDDEN:
        raise KnowledgeError(f"{entry_id} is {entry['status']}; it must not be reused")
    messages = []
    planned = []
    for artifact in entry.get("artifacts", []):
        install_to = artifact.get("install_to")
        if not install_to:
            continue
        source = Path(entry["_base"]) / artifact["path"]
        destination = godot_dir / install_to
        if Path(install_to).is_absolute() or ".." in Path(install_to).parts:
            raise KnowledgeError(f"install_to escapes the Godot project: {install_to}")
        if destination.exists():
            if destination.read_bytes() == source.read_bytes():
                messages.append(f"UNCHANGED {destination}")
                continue
            raise KnowledgeError(f"refusing to overwrite existing file: {destination}")
        planned.append((source, destination))
    for source, destination in planned:
        if not dry_run:
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, destination)
        messages.append(f"{'WOULD_COPY' if dry_run else 'COPIED'} {destination}")
    if not dry_run:
        record = project / "knowledge/applied.json"
        try:
            applied = json.loads(record.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            applied = []
        applied.append({"id": entry_id, "status_at_apply": entry.get("status"),
                        "store": entry["_store"], "ts": utc_now(),
                        "files": [str(d) for _, d in planned],
                        "verified_in_project": False})
        record.parent.mkdir(parents=True, exist_ok=True)
        record.write_text(json.dumps(applied, indent=2) + "\n", encoding="utf-8")
    messages.append(f"NEXT integrate per `lopodev knowledge show {entry_id}` and run its "
                    "validation in this project; reuse is not verification")
    return messages


# ---------------------------------------------------------------- CLI

def describe(entry: dict, full: bool = False) -> str:
    engine = entry.get("engine") or {}
    lines = [f"{entry['id']} [{entry.get('status')}] ({entry['_store']}) {entry.get('title')}",
             f"  topic: {entry.get('topic')}  tags: {', '.join(entry.get('tags', []))}",
             f"  engine: {engine.get('name', 'any')} {engine.get('versions', '')}".rstrip()
             + f"  platforms: {', '.join(entry.get('platforms') or ['any'])}"]
    if entry.get("_overlay"):
        lines.append(f"  overlay: {entry['_overlay'].get('note')}")
    if not full:
        lines.append(f"  problem: {entry.get('problem')}")
        return "\n".join(lines)
    for field in ("problem", "approach", "expected_behavior"):
        if entry.get(field):
            lines.append(f"{field}: {entry[field]}")
    for field in ("prerequisites", "integration", "limitations"):
        if entry.get(field):
            lines.append(f"{field}:")
            lines.extend(f"  - {item}" for item in entry[field])
    for mode in entry.get("failure_modes", []):
        lines.append(f"failure: {mode.get('symptom')} -> {mode.get('cause')} -> {mode.get('fix')}")
    for artifact in entry.get("artifacts", []):
        lines.append(f"artifact: {Path(entry['_base']) / artifact['path']}"
                     + (f" -> <godot>/{artifact['install_to']}" if artifact.get("install_to") else ""))
    validation = entry.get("validation") or {}
    if validation:
        lines.append(f"validation: {validation.get('command')}")
        lines.append(f"  last: {validation.get('last_result', 'NOT RUN')} {validation.get('validated_at', '')}"
                     f" engine={validation.get('engine_version', '?')}")
        for item in validation.get("evidence", []):
            lines.append(f"  evidence: {item}")
    return "\n".join(lines)


def project_arg(value: str | None) -> Path | None:
    if not value:
        return None
    path = Path(value).expanduser().resolve()
    if not path.is_dir():
        raise KnowledgeError(f"project directory not found: {value}")
    return path


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="lopodev knowledge", description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--project", help="projects/<slug> to include project memory")
    # Accept --project after the subcommand too; agents put flags anywhere.
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--project", default=argparse.SUPPRESS, help=argparse.SUPPRESS)
    sub = parser.add_subparsers(dest="command", required=True)
    find_p = sub.add_parser("search", help="find reusable knowledge before implementing", parents=[common])
    find_p.add_argument("query", nargs="+")
    find_p.add_argument("--engine", default=None)
    find_p.add_argument("--engine-version", default=None)
    find_p.add_argument("--platform", default=None)
    find_p.add_argument("--all", action="store_true", help="include failed/deprecated/incompatible")
    find_p.add_argument("--limit", type=int, default=5)
    find_p.add_argument("--json", action="store_true")
    show_p = sub.add_parser("show", help="print one entry in full", parents=[common])
    show_p.add_argument("id")
    show_p.add_argument("--json", action="store_true")
    sub.add_parser("list", help="list every entry and its status", parents=[common])
    add_p = sub.add_parser("add", help="add a candidate entry from a JSON file", parents=[common])
    add_p.add_argument("file")
    add_p.add_argument("--scope", choices=("global", "project"), default="project")
    verify_p = sub.add_parser("verify", help="run an entry's validation and record evidence", parents=[common])
    verify_p.add_argument("id")
    verify_p.add_argument("--run", action="store_true", help="actually execute the validation")
    verify_p.add_argument("--workspace", default=".")
    verify_p.add_argument("--maintainer", action="store_true",
                          help="record results on bundled entries (toolkit checkout only)")
    for name, help_text in (("deprecate", "hide an outdated entry"),
                            ("fail", "mark an entry as failing so it is not reused")):
        mark = sub.add_parser(name, help=help_text, parents=[common])
        mark.add_argument("id")
        mark.add_argument("--reason", required=True)
    promote_p = sub.add_parser("promote", help="copy a project entry to global knowledge as candidate", parents=[common])
    promote_p.add_argument("id")
    promote_p.add_argument("--note", required=True)
    apply_p = sub.add_parser("apply", help="copy an entry's artifacts into a Godot project", parents=[common])
    apply_p.add_argument("id")
    apply_p.add_argument("--godot-dir", required=True)
    apply_p.add_argument("--dry-run", action="store_true")
    sub.add_parser("validate", help="validate every entry in every store", parents=[common])
    args = parser.parse_args(argv)
    try:
        project = project_arg(args.project)
        if args.command == "search":
            results = search(project, " ".join(args.query), args.engine, args.engine_version,
                             args.platform, args.all, args.limit)
            if args.json:
                print(json.dumps([{"score": s, **public(e), "store": e["_store"]} for s, e in results], indent=2))
            elif not results:
                print("NO_MATCH: nothing reusable found; implement, verify, then record it with "
                      "`lopodev knowledge add`")
            else:
                for _, entry in results:
                    print(describe(entry))
            return 0
        if args.command == "show":
            entry = find(project, args.id)
            print(json.dumps(public(entry), indent=2) if args.json else describe(entry, full=True))
            return 0
        if args.command == "list":
            for entry in sorted(load_entries(project), key=lambda e: e["id"]):
                print(f"{entry['id']:40} {entry.get('status'):10} {entry['_store']:8} {entry.get('title')}")
            return 0
        if args.command == "add":
            entry = add(project, Path(args.file), args.scope)
            print(f"ADDED {entry['id']} status=candidate scope={entry['scope']}")
            print(f"NEXT lopodev knowledge{' --project ' + args.project if args.project else ''} "
                  f"verify {entry['id']} --run")
            return 0
        if args.command == "verify":
            outcome, entry = verify(project, args.id, args.run, Path(args.workspace).resolve(),
                                    maintainer=args.maintainer)
            print(f"KNOWLEDGE_VERIFY {args.id}={outcome} status={entry.get('status')}")
            return 0 if outcome in ("PASS", "NOT RUN") else 1
        if args.command in ("deprecate", "fail"):
            status = "deprecated" if args.command == "deprecate" else "failed"
            set_status(project, args.id, status, args.reason)
            print(f"MARKED {args.id} status={status}")
            return 0
        if args.command == "promote":
            if project is None:
                raise KnowledgeError("--project is required")
            entry = promote(project, args.id, args.note)
            print(f"PROMOTED {entry['id']} to global knowledge as candidate")
            return 0
        if args.command == "apply":
            if project is None:
                raise KnowledgeError("--project is required so the reuse is recorded")
            for message in apply(project, args.id, Path(args.godot_dir).resolve(), args.dry_run):
                print(message)
            return 0
        if args.command == "validate":
            failures = 0
            for entry in load_entries(project):
                errors = validate_entry(public(entry), Path(entry["_base"]))
                for error in errors:
                    print(f"INVALID {entry['id']} ({entry['_store']}): {error}")
                failures += bool(errors)
            print(f"KNOWLEDGE_VALIDATE={'FAIL' if failures else 'PASS'} entries={len(load_entries(project))}")
            return 1 if failures else 0
    except (KnowledgeError, OSError, json.JSONDecodeError, subprocess.TimeoutExpired) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
