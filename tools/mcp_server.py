#!/usr/bin/env python3
"""Optional, project-scoped MCP tools for LoopDev. Requires `pip install 'mcp>=2,<3'`."""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))
sys.path.insert(0, str(ROOT / "tools/godot"))

import android_export  # noqa: E402
import lopodev_log  # noqa: E402
import pipeline_state  # noqa: E402
import validate_spec  # noqa: E402

SLUG_RE = re.compile(r"^[a-z][a-z0-9_]*$")


def project_path(workspace: Path, slug: str) -> Path:
    if not SLUG_RE.fullmatch(slug):
        raise ValueError("slug must be lowercase snake_case")
    base = (workspace / "projects").resolve()
    project = (base / slug).resolve()
    if project.parent != base:
        raise ValueError("project path escapes configured workspace")
    if not project.is_dir():
        raise FileNotFoundError(f"project directory not found: projects/{slug}")
    return project


def status(workspace: Path, slug: str) -> dict:
    project = project_path(workspace, slug)
    data = pipeline_state.load_state(str(project))
    return {
        "slug": slug,
        "title": data.get("title"),
        "current_gate": data.get("current_gate"),
        "gates": {key: value.get("status") for key, value in data.get("gates", {}).items()},
        "tasks": {"total": len(data.get("tasks", [])),
                  "verified": sum(t.get("status") in {"verified", "complete"} for t in data.get("tasks", [])),
                  "blocked": sum(t.get("status") == "blocked" for t in data.get("tasks", []))},
        "next_step": data.get("recovery", {}).get("next_step", ""),
    }


def next_task(workspace: Path, slug: str) -> dict:
    project = project_path(workspace, slug)
    data = pipeline_state.load_state(str(project))
    tasks = data.get("tasks", [])
    by_id = {task.get("id"): task for task in tasks}
    for task in tasks:
        if task.get("status") in {"blocked", "failed", "verified", "complete", "needs_approval"}:
            continue
        gate_id = task.get("gate")
        if gate_id in data.get("gates", {}) and data["gates"][gate_id].get("status") != "approved":
            continue
        dependencies = task.get("depends_on", [])
        if all(by_id.get(dep, {}).get("status") in {"verified", "complete"} for dep in dependencies):
            return {"ready": True, "id": task.get("id"), "title": task.get("title"),
                    "owner": task.get("owner"), "depends_on": dependencies,
                    "verification": task.get("verify", "")}
    return {"ready": False, "message": "No dependency-ready task. Check gate approvals, blocked work, and project task sync."}


def validate_project(workspace: Path, slug: str) -> dict:
    project = project_path(workspace, slug)
    spec_file = project / "project.json"
    errors: list[str] = []
    try:
        spec = json.loads(spec_file.read_text(encoding="utf-8"))
        errors.extend(validate_spec.validate(spec, project))
    except (OSError, json.JSONDecodeError) as exc:
        errors.append(f"project.json: {exc}")
    try:
        errors.extend(f"pipeline_state: {error}" for error in pipeline_state.validate_state(
            pipeline_state.load_state(str(project))))
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        errors.append(f"pipeline_state: {exc}")
    return {"slug": slug, "status": "PASS" if not errors else "FAIL", "errors": errors}


def context(workspace: Path, slug: str) -> dict:
    project = project_path(workspace, slug)
    summary = status(workspace, slug)
    excerpts = {}
    for filename, cap in (("GAME_SPEC.md", 12000), ("ASSET_LICENSES.md", 4000)):
        path = project / filename
        if path.is_file():
            with path.open(encoding="utf-8") as handle:
                excerpts[filename] = handle.read(cap)
    contract_path = ROOT / "AGENTS.md"
    if contract_path.is_file():
        with contract_path.open(encoding="utf-8") as handle:
            contract = handle.read(12000)
    else:
        contract = ""
    return {"project": summary, "documents": excerpts,
            "workflow_contract": contract}


def checkpoint(workspace: Path, slug: str, note: str) -> dict:
    if not note.strip() or len(note) > 2000:
        raise ValueError("note must contain 1..2000 characters")
    project = project_path(workspace, slug)
    state_path = project / pipeline_state.STATE_FILENAME
    with pipeline_state.state_lock(project):
        data = pipeline_state.load_state(str(project))
        notes = data.setdefault("recovery", {}).setdefault("notes", [])
        notes.append({"at_utc": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
                      "note": note.strip()})
        data["recovery"]["notes"] = notes[-50:]
        data["recovery"]["next_step"] = note.strip()
        pipeline_state.save_state(str(project), data)
    lopodev_log.append_event(str(project), event="checkpoint", message=note.strip())
    return {"slug": slug, "checkpoint": "saved", "state": str(state_path)}


def project_godot_dir(workspace: Path, slug: str) -> Path:
    workspace = workspace.expanduser().resolve()
    project = project_path(workspace, slug)
    configured = f"projects/{slug}/godot"
    spec_file = project / "project.json"
    if spec_file.is_file():
        try:
            spec = json.loads(spec_file.read_text(encoding="utf-8"))
            configured = str(spec.get("godot_dir") or configured)
        except (OSError, json.JSONDecodeError) as exc:
            raise ValueError(f"project.json: {exc}") from exc
    candidate = Path(configured).expanduser()
    if not candidate.is_absolute():
        candidate = workspace / candidate
    candidate = candidate.resolve()
    if not candidate.is_relative_to(workspace):
        raise ValueError("godot_dir must stay inside the configured workspace")
    if not (candidate / "project.godot").is_file():
        raise FileNotFoundError(f"Godot project not found: {candidate}")
    return candidate


def android_export_project(workspace: Path, slug: str, export_format: str = "apk",
                           mode: str = "debug", preset: str = "Android",
                           output: str = "", godot: str = "",
                           check_capabilities: bool = True,
                           min_artifact_bytes: int = 1_000_000,
                           runner=subprocess.run) -> dict:
    workspace = workspace.expanduser().resolve()
    godot_dir = project_godot_dir(workspace, slug)
    if godot:
        executable = Path(godot).expanduser().resolve()
        allowed = (workspace.resolve(), ROOT.resolve())
        if not any(executable.is_relative_to(root) for root in allowed):
            raise ValueError("godot executable must stay inside the workspace or toolkit")
        if not executable.is_file() or not os.access(executable, os.X_OK):
            raise ValueError(f"godot executable is not runnable: {executable}")
        godot = str(executable)
    destination = output
    if output:
        candidate = Path(output).expanduser()
        if not candidate.is_absolute():
            candidate = godot_dir.parent / candidate
        candidate = candidate.resolve()
        if not candidate.is_relative_to(workspace):
            raise ValueError("output must stay inside the configured workspace")
        destination = str(candidate)
    result = android_export.export_project(
        str(godot_dir), export_format, mode, preset, destination or None,
        godot=godot or None, check_capabilities=check_capabilities,
        min_artifact_bytes=min_artifact_bytes, runner=runner)
    result["slug"] = slug
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", required=True, type=Path,
                        help="explicit workspace root; tools are scoped below projects/<slug>")
    args = parser.parse_args()
    workspace = args.root.expanduser().resolve()
    if not workspace.is_dir():
        parser.error(f"workspace root is not a directory: {workspace}")
    try:
        from mcp.server import MCPServer
        from mcp.shared.exceptions import MCPError
    except ImportError:
        print("LoopDev MCP requires the official Python MCP SDK. Install with: pip install 'mcp>=2,<3'",
              file=sys.stderr)
        return 2

    server = MCPServer(name="loopdev", version="0.2.0")

    @server.tool()
    def loopdev_status(slug: str) -> dict:
        """Read the status, gate approvals, task counts, and recovery step for one project."""
        try:
            return status(workspace, slug)
        except (ValueError, FileNotFoundError) as exc:
            raise MCPError(-32602, str(exc)) from exc

    @server.tool()
    def loopdev_next(slug: str) -> dict:
        """Return the first pending task whose dependencies are verified."""
        try:
            return next_task(workspace, slug)
        except (ValueError, FileNotFoundError) as exc:
            raise MCPError(-32602, str(exc)) from exc

    @server.tool()
    def loopdev_validate(slug: str) -> dict:
        """Validate the project's project.json spec and persistent pipeline state."""
        try:
            return validate_project(workspace, slug)
        except (ValueError, FileNotFoundError) as exc:
            raise MCPError(-32602, str(exc)) from exc

    @server.tool()
    def loopdev_context(slug: str) -> dict:
        """Return bounded project workflow status and excerpts from its spec/license record."""
        try:
            return context(workspace, slug)
        except (ValueError, FileNotFoundError) as exc:
            raise MCPError(-32602, str(exc)) from exc

    @server.tool()
    def loopdev_checkpoint(slug: str, note: str) -> dict:
        """Persist a short recovery checkpoint. Does not approve gates or run shell commands."""
        try:
            return checkpoint(workspace, slug, note)
        except (ValueError, FileNotFoundError) as exc:
            raise MCPError(-32602, str(exc)) from exc

    @server.tool()
    def loopdev_android_export(slug: str, format: str = "apk", mode: str = "debug",
                               preset: str = "Android", output: str = "",
                               godot: str = "") -> dict:
        """Export and verify a Godot Android APK or release AAB. Device/Play gates remain NOT RUN."""
        try:
            return android_export_project(workspace, slug, format, mode, preset,
                                          output, godot)
        except (ValueError, FileNotFoundError) as exc:
            raise MCPError(-32602, str(exc)) from exc
        except android_export.ExportError as exc:
            code = -32602 if exc.exit_code == 2 else -32603
            raise MCPError(code, str(exc)) from exc

    server.run(transport="stdio")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
