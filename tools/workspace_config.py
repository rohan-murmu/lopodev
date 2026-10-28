#!/usr/bin/env python3
"""Key-level ownership for JSON agent configs such as a workspace opencode.json.

LopoDev never rewrites a user's config wholesale. Each managed key is
addressed as "<top-level>" or "<top-level>.<child>" and recorded in the
installer manifest under `config_keys` with a hash of the value LopoDev wrote:

- absent key            -> written and recorded
- equal value           -> left alone
- recorded and unedited -> may be updated to the new desired value
- anything else         -> preserved and reported as a conflict

Uninstall removes only recorded keys whose value is still what LopoDev wrote.
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
from datetime import datetime, timezone
from pathlib import Path

MISSING = object()


def value_hash(value) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True).encode()).hexdigest()


def get_key(config: dict, key: str):
    head, _, child = key.partition(".")
    if not child:
        return config.get(head, MISSING)
    parent = config.get(head)
    return parent.get(child, MISSING) if isinstance(parent, dict) else MISSING


def set_key(config: dict, key: str, value) -> None:
    head, _, child = key.partition(".")
    if not child:
        config[head] = value
        return
    parent = config.setdefault(head, {})
    if not isinstance(parent, dict):
        raise ValueError(f"cannot set {key}: `{head}` is not an object")
    parent[child] = value


def delete_key(config: dict, key: str) -> None:
    head, _, child = key.partition(".")
    if not child:
        config.pop(head, None)
        return
    parent = config.get(head)
    if isinstance(parent, dict):
        parent.pop(child, None)
        if not parent:
            config.pop(head, None)


def load_config(path: Path) -> dict | None:
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"cannot safely inspect {path}: {exc}") from exc
    if not isinstance(data, dict):
        raise ValueError(f"{path} is not a JSON object")
    return data


def file_owned(path: Path, manifest: dict, relative: str) -> bool:
    """True when the whole file was written by LopoDev and is unedited."""
    entry = manifest.get("files", {}).get(relative)
    return bool(entry and entry.get("kind") == "file" and path.is_file()
                and hashlib.sha256(path.read_bytes()).hexdigest() == entry.get("sha256"))


def merge(workspace: Path, relative: str, desired: dict, manifest: dict, dry_run: bool,
          skeleton: dict | None = None, legacy: dict | None = None) -> list[str]:
    """Apply `desired` {key: value} to the JSON file, honoring ownership.

    `legacy` maps a key to values earlier LopoDev releases wrote without
    recording ownership; such values migrate as if LopoDev owned them.
    """
    legacy = legacy or {}
    path = workspace / relative
    config = load_config(path)
    created = config is None
    if created:
        config = json.loads(json.dumps(skeleton or {}))
    owned_file = not created and file_owned(path, manifest, relative)
    recorded = manifest.setdefault("config_keys", {}).setdefault(relative, {})
    messages: list[str] = []
    changed = False
    for key, value in desired.items():
        current = get_key(config, key)
        if current is not MISSING and current == value:
            messages.append(f"UNCHANGED {relative}:{key}")
            if created or owned_file:
                recorded[key] = value_hash(value)
            continue
        ours = (current is MISSING or owned_file or recorded.get(key) == value_hash(current)
                or current in legacy.get(key, []))
        if not ours:
            messages.append(f"PRESERVED {relative}:{key}; user value differs from LopoDev's "
                            "(edit it manually or remove it and rerun)")
            continue
        set_key(config, key, value)
        recorded[key] = value_hash(value)
        changed = True
        verb = "SET" if current is MISSING else "UPDATED"
        messages.append(f"{'WOULD_' + verb if dry_run else verb} {relative}:{key}")
    if not recorded:
        manifest["config_keys"].pop(relative, None)
    if changed and not dry_run:
        write(path, config, backup=not created and not owned_file, workspace=workspace)
        entry = manifest.get("files", {}).get(relative)
        if owned_file and entry:
            entry["sha256"] = hashlib.sha256(path.read_bytes()).hexdigest()
    if created and not dry_run and not changed:
        write(path, config, backup=False, workspace=workspace)
    return messages


def unmerge(workspace: Path, relative: str, manifest: dict, dry_run: bool,
            keys: set[str] | None = None) -> list[str]:
    """Remove recorded keys that still hold the value LopoDev wrote."""
    path = workspace / relative
    recorded = manifest.get("config_keys", {}).get(relative, {})
    config = load_config(path)
    messages: list[str] = []
    if config is None or not recorded:
        return messages
    changed = False
    for key in sorted(recorded):
        if keys is not None and key not in keys:
            continue
        current = get_key(config, key)
        if current is MISSING:
            recorded.pop(key)
            continue
        if value_hash(current) != recorded[key]:
            messages.append(f"PRESERVED {relative}:{key}; edited since LopoDev wrote it")
            continue
        messages.append(f"{'WOULD_REMOVE' if dry_run else 'REMOVED'} {relative}:{key}")
        if not dry_run:
            delete_key(config, key)
            recorded.pop(key)
            changed = True
    if changed:
        write(path, config, backup=True, workspace=workspace)
    if not recorded:
        manifest.get("config_keys", {}).pop(relative, None)
    return messages


def write(path: Path, config: dict, backup: bool, workspace: Path) -> None:
    if backup and path.exists():
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        target = workspace / ".lopodev/backups" / f"{path.name}.{stamp}"
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(path, target)
    temporary = path.with_name(f".{path.name}.tmp")
    temporary.write_text(json.dumps(config, indent=2) + "\n", encoding="utf-8")
    os.replace(temporary, path)
