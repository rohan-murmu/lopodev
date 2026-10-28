#!/usr/bin/env python3
"""LopoDev installation, diagnostics, and adapter setup CLI."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import shutil
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import approval  # noqa: E402
import integrations  # noqa: E402
import workspace_config  # noqa: E402


def toolkit_root() -> Path:
    configured = os.environ.get("LOPODEV_HOME")
    if configured:
        # Keep the configured spelling: Homebrew passes its stable opt/ path,
        # and resolving it would pin workspace links to a versioned Cellar dir
        # that disappears after `brew upgrade` + `brew cleanup`.
        return Path(os.path.abspath(Path(configured).expanduser()))
    return Path(__file__).resolve().parent.parent


def project_root(value: str | None) -> Path:
    return Path(value or os.getcwd()).expanduser().resolve()


def read_version(root: Path) -> str:
    try:
        version = (root / "VERSION").read_text(encoding="utf-8").strip()
    except OSError:
        version = "unknown"
    build = build_label(root)
    return f"{version} ({build})" if build else version


def build_label(root: Path) -> str:
    """Which build is running: the Homebrew formula version, else the checkout commit."""
    configured = os.environ.get("LOPODEV_BUILD", "").strip()
    if configured:
        return configured
    if not (root / ".git").exists():
        return ""
    try:
        result = subprocess.run(["git", "-C", str(root), "rev-parse", "--short", "HEAD"],
                                capture_output=True, text=True, timeout=5, check=False)
    except (OSError, subprocess.TimeoutExpired):
        return ""
    return f"git-{result.stdout.strip()}" if result.returncode == 0 and result.stdout.strip() else ""


def safe_destination(workspace: Path, destination: Path) -> Path:
    root = workspace.resolve()
    absolute = Path(os.path.abspath(destination))
    try:
        relative = absolute.relative_to(root)
    except ValueError:
        raise ValueError(f"destination escapes workspace: {destination}") from None
    parent = root
    for part in relative.parts[:-1]:
        parent = parent / part
        if parent.is_symlink() and not parent.resolve().is_relative_to(root):
            raise ValueError(f"destination parent symlink escapes workspace: {parent}")
    return absolute


def _install_file(src: Path, dst: Path, dry_run: bool) -> str:
    if dst.is_symlink():
        raise FileExistsError(f"refusing to write through an existing symlink: {dst}")
    if dst.exists():
        if dst.is_file() and dst.read_bytes() == src.read_bytes():
            return f"UNCHANGED {dst}"
        raise FileExistsError(f"refusing to overwrite existing user path: {dst}")
    if not dry_run:
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dst)
    return f"{'WOULD_WRITE' if dry_run else 'WROTE'} {dst}"


def same_existing_path(src: Path, dst: Path) -> bool:
    """True when the destination already is the source, as in the toolkit checkout."""
    try:
        return dst.exists() and not dst.is_symlink() and src.resolve() == dst.resolve()
    except OSError:
        return False


def _install_symlink(src: Path, dst: Path, dry_run: bool) -> str:
    if dst.exists() or dst.is_symlink():
        if dst.is_symlink() and dst.resolve() == src.resolve():
            return f"UNCHANGED {dst} -> {src}"
        if same_existing_path(src, dst):
            return f"ALREADY_PRESENT {dst}"
        raise FileExistsError(f"refusing to replace existing user path: {dst}")
    if not dry_run:
        dst.parent.mkdir(parents=True, exist_ok=True)
        dst.symlink_to(src, target_is_directory=src.is_dir())
    return f"{'WOULD_LINK' if dry_run else 'LINKED'} {dst} -> {src}"


def preflight_file(src: Path, dst: Path, workspace: Path) -> None:
    safe_destination(workspace, dst)
    if dst.is_symlink():
        raise FileExistsError(f"refusing to replace existing symlink: {dst}")
    if dst.exists() and (not dst.is_file() or dst.read_bytes() != src.read_bytes()):
        raise FileExistsError(f"refusing to overwrite existing user path: {dst}")


def preflight_symlink(src: Path, dst: Path, workspace: Path) -> None:
    safe_destination(workspace, dst)
    if same_existing_path(src, dst):
        return
    if dst.exists() or dst.is_symlink():
        if not dst.is_symlink() or dst.resolve() != src.resolve():
            raise FileExistsError(f"refusing to replace existing user path: {dst}")


def manifest_path(workspace: Path) -> Path:
    return workspace / ".lopodev/managed-files.json"


def load_manifest(workspace: Path) -> dict:
    path = manifest_path(workspace)
    safe_destination(workspace, path)
    if path.is_symlink():
        raise ValueError(f"refusing to use symlinked ownership manifest: {path}")
    if not path.exists():
        return {"schema_version": 1, "files": {}}
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict) or data.get("schema_version") != 1 or not isinstance(data.get("files"), dict):
        raise ValueError(f"invalid LopoDev installer manifest: {path}")
    return data


def record_created(workspace: Path, target: str, messages: list[str]) -> None:
    manifest = load_manifest(workspace)
    changed = False
    for message in messages:
        creates = message.startswith(("WROTE ", "LINKED "))
        shared_reference = message.startswith("UNCHANGED ") and " -> " in message
        preserved_contract = message.startswith("PRESERVED ") and "shared instructions" in message
        if not (creates or shared_reference or preserved_contract):
            continue
        path_text = message.split(" -> ", 1)[0].split(" ", 1)[1]
        path_text = path_text.split(";", 1)[0].strip()
        path = Path(os.path.abspath(path_text))
        try:
            relative = path.relative_to(workspace.resolve()).as_posix()
        except ValueError:
            raise ValueError(f"managed path escapes workspace: {path}") from None
        prior = manifest["files"].get(relative)
        if prior and (shared_reference or preserved_contract):
            owners = set(prior.get("owners", [prior.get("target")]))
            owners.add(target)
            prior["owners"] = sorted(owner for owner in owners if owner)
            changed = True
            continue
        if not creates:
            continue
        if path.is_symlink():
            entry = {"target": target, "owners": [target], "kind": "symlink",
                     "link_target": os.readlink(path)}
        elif path.is_file():
            entry = {"target": target, "owners": [target], "kind": "file",
                     "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}
        else:
            continue
        manifest["files"][relative] = entry
        changed = True
    if changed:
        path = manifest_path(workspace)
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_suffix(".tmp")
        temporary.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
        os.replace(temporary, path)


def managed_path_allowed(target: str, relative: str) -> bool:
    parts = Path(relative).parts
    shared_skills = len(parts) == 3 and parts[:2] == (".agents", "skills")
    if target == "opencode":
        return (relative in {"tools", "templates", "AGENTS.md", "opencode.json",
                             ".opencode/agents", ".opencode/commands"}
                or (len(parts) == 3 and parts[:2] == (".opencode", "skills"))
                or shared_skills)
    if target == "kilo":
        return (relative in {"AGENTS.md", "tools", "templates"}
                or (len(parts) == 3 and parts[:2] == (".kilo", "agents") and parts[2].endswith(".md"))
                or (len(parts) == 3 and parts[:2] == (".kilo", "skills"))
                or shared_skills)
    if target == "cursor":
        return (relative in {"AGENTS.md", "tools", "templates", ".cursor/rules/lopodev.mdc"}
                or (len(parts) == 3 and parts[:2] == (".cursor", "agents") and parts[2].endswith(".md"))
                or shared_skills)
    if target == "mcp":
        return relative == ".lopodev/mcp-server.json"
    return False


def prune_empty_dirs(workspace: Path, relative_dirs: tuple[str, ...]) -> None:
    for relative in relative_dirs:
        directory = workspace / relative
        try:
            directory.rmdir()
        except OSError:
            continue


def uninstall_target(workspace: Path, target: str, dry_run: bool) -> list[str]:
    path = manifest_path(workspace)
    safe_destination(workspace, path)
    if path.is_symlink():
        raise ValueError(f"refusing to use symlinked ownership manifest: {path}")
    if not path.is_file():
        return [f"NOT_INSTALLED {target}: no LopoDev ownership manifest at {path}"]
    manifest = load_manifest(workspace)
    messages: list[str] = []
    if target == "opencode":
        messages.extend(workspace_config.unmerge(workspace, "opencode.json", manifest, dry_run))
        config_file = workspace / "opencode.json"
        leftover = workspace_config.load_config(config_file)
        if (not dry_run and leftover is not None and set(leftover) <= {"$schema"}
                and "opencode.json" not in manifest["files"]):
            config_file.unlink()
            messages.append(f"REMOVED {config_file}")
    remaining = dict(manifest["files"])
    for relative, entry in list(manifest["files"].items()):
        if not managed_path_allowed(target, relative):
            messages.append(f"PRESERVED {relative}: path is outside {target}'s managed-path allowlist")
            continue
        owners = set(entry.get("owners", [entry.get("target")]))
        if target not in owners:
            continue
        if len(owners) > 1:
            owners.remove(target)
            entry["owners"] = sorted(owner for owner in owners if owner)
            messages.append(f"DETACHED {relative}: still used by {', '.join(entry['owners'])}")
            continue
        managed = workspace.resolve() / relative
        safe_destination(workspace, managed)
        if entry.get("kind") == "symlink":
            if not managed.is_symlink() or os.readlink(managed) != entry.get("link_target"):
                messages.append(f"PRESERVED {managed}: symlink no longer matches LopoDev manifest")
                continue
        elif entry.get("kind") == "file":
            if not managed.is_file() or hashlib.sha256(managed.read_bytes()).hexdigest() != entry.get("sha256"):
                messages.append(f"PRESERVED {managed}: contents changed since LopoDev installed it")
                continue
        else:
            messages.append(f"PRESERVED {managed}: unknown manifest entry type")
            continue
        messages.append(f"{'WOULD_REMOVE' if dry_run else 'REMOVED'} {managed}")
        if not dry_run:
            managed.unlink()
            remaining.pop(relative, None)
    if not dry_run:
        manifest["files"] = remaining
        if remaining or manifest.get("config_keys"):
            save_manifest(workspace, manifest)
        elif path.exists():
            path.unlink()
        prune_empty_dirs(workspace, (".opencode/skills", ".opencode", ".kilo/agents", ".kilo/skills", ".kilo",
                                     ".cursor/rules", ".cursor/agents", ".cursor",
                                     ".agents/skills", ".agents", ".lopodev"))
    return messages


def skill_sources(root: Path) -> list[Path]:
    """LopoDev's own skills plus vendored skills that `lopodev setup` installed."""
    own = [skill for skill in sorted((root / "resources/skills").iterdir())
           if skill.is_dir() and (skill / "SKILL.md").is_file()]
    names = {skill.name for skill in own}
    vendored_root = integrations.data_dir() / "skills"
    vendored = [vendored_root / name for name in integrations.vendored_skills(root)
                if name not in names and (vendored_root / name / "SKILL.md").is_file()]
    return own + vendored


def launcher_path(root: Path) -> str:
    """Stable launcher for MCP commands: the path the user invoked, not a Cellar path."""
    return os.environ.get("LOPODEV_LAUNCHER") or str(root / "bin/lopodev")


# Values earlier LopoDev releases wrote into opencode.json without recording
# ownership; reinstalling migrates them instead of reporting a conflict.
LEGACY_OPENCODE_VALUES = {
    "mcp.blender": [
        {"type": "local", "command": ["uvx", "mcp-for-blender"], "enabled": enabled,
         "environment": {"BLENDER_HOST": "localhost", "BLENDER_PORT": "9876",
                         "DISABLE_TELEMETRY": "true"}, "timeout": 60000}
        for enabled in (True, False)
    ],
}


def opencode_desired_config(root: Path, workspace: Path) -> dict:
    desired = {"default_agent": "lopodev", "instructions": ["AGENTS.md"],
               "permission": approval.policy(approval.current_mode(workspace))}
    try:
        existing = (workspace_config.load_config(workspace / "opencode.json") or {}).get("mcp", {})
    except ValueError:
        existing = {}
    for name, entry in integrations.opencode_mcp_block(root, launcher_path(root)).items():
        # Keep whichever lopodev launcher spelling the workspace already uses
        # (`lopodev` on PATH vs an absolute path); both run the same server.
        command = (existing.get(name) or {}).get("command") or []
        if (len(command) == 3 and command[1:] == ["mcp-run", name]
                and Path(command[0]).name == "lopodev"):
            entry = dict(entry, command=list(command))
        desired[f"mcp.{name}"] = entry
    for pattern, enabled in integrations.opencode_tool_defaults(root).items():
        desired[f"tools.{pattern}"] = enabled
    return desired


def configure_opencode(root: Path, workspace: Path, dry_run: bool) -> list[str]:
    manifest = load_manifest(workspace)
    messages = workspace_config.merge(
        workspace, "opencode.json", opencode_desired_config(root, workspace), manifest, dry_run,
        skeleton={"$schema": "https://opencode.ai/config.json"}, legacy=LEGACY_OPENCODE_VALUES)
    if not dry_run:
        save_manifest(workspace, manifest)
    return messages


def save_manifest(workspace: Path, manifest: dict) -> None:
    path = manifest_path(workspace)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    os.replace(temporary, path)


def install_opencode(root: Path, workspace: Path, dry_run: bool) -> list[str]:
    messages: list[str] = []
    opencode = workspace / ".opencode"
    if opencode.is_symlink():
        raise FileExistsError(
            f"refusing to replace legacy .opencode symlink; remove it and rerun: {opencode}")
    if opencode.exists() and not opencode.is_dir():
        raise FileExistsError(f"refusing to replace existing user path: {opencode}")
    components = {"agents": root / "adapters/opencode/agents",
                  "commands": root / "adapters/opencode/commands"}
    for destination in components.values():
        preflight_symlink(destination, opencode / destination.name, workspace)
    skills = skill_sources(root)
    for skill in skills:
        preflight_symlink(skill, opencode / "skills" / skill.name, workspace)
    workspace_config.load_config(workspace / "opencode.json")  # fail early on invalid JSON
    if not (workspace / "AGENTS.md").exists() and not (workspace / "AGENTS.md").is_symlink():
        preflight_file(root / "AGENTS.md", workspace / "AGENTS.md", workspace)
    for name in ("tools", "templates"):
        preflight_symlink(root / name, workspace / name, workspace)
    if not opencode.exists():
        if not dry_run:
            opencode.mkdir(parents=True)
        messages.append(f"{'WOULD_MKDIR' if dry_run else 'MKDIR'} {opencode}")
    for name, source in components.items():
        messages.append(_install_symlink(source, opencode / name, dry_run))
    skills_dir = opencode / "skills"
    if not skills_dir.exists():
        if not dry_run:
            skills_dir.mkdir(parents=True)
        messages.append(f"{'WOULD_MKDIR' if dry_run else 'MKDIR'} {skills_dir}")
    for skill in skills:
        messages.append(_install_symlink(skill, skills_dir / skill.name, dry_run))

    messages.extend(install_shared_contract(root, workspace, dry_run, include_skills=False))
    messages.extend(configure_opencode(root, workspace, dry_run))
    return messages


def install_kilo(root: Path, workspace: Path, dry_run: bool) -> list[str]:
    agents = sorted((root / "adapters/kilo/agents").glob("*.md"))
    skills = skill_sources(root)
    for agent in agents:
        preflight_file(agent, workspace / ".kilo/agents" / agent.name, workspace)
    for skill in skills:
        preflight_symlink(skill, workspace / ".kilo/skills" / skill.name, workspace)
    preflight_shared_contract(root, workspace)
    messages = [_install_file(agent, workspace / ".kilo/agents" / agent.name, dry_run)
                for agent in agents]
    messages.extend(_install_symlink(skill, workspace / ".kilo/skills" / skill.name, dry_run)
                    for skill in skills)
    messages.extend(install_shared_contract(root, workspace, dry_run))
    return messages


def install_shared_contract(root: Path, workspace: Path, dry_run: bool,
                            include_skills: bool = True) -> list[str]:
    messages = []
    agents_file = workspace / "AGENTS.md"
    if agents_file.exists() or agents_file.is_symlink():
        messages.append(f"PRESERVED {agents_file}; shared instructions were not replaced")
    else:
        messages.append(_install_file(root / "AGENTS.md", agents_file, dry_run))
    for name in ("tools", "templates"):
        messages.append(_install_symlink(root / name, workspace / name, dry_run))
    if include_skills:
        for skill in skill_sources(root):
            messages.append(_install_symlink(skill, workspace / ".agents/skills" / skill.name,
                                             dry_run))
    return messages


def preflight_shared_contract(root: Path, workspace: Path, include_skills: bool = True) -> None:
    agents_file = workspace / "AGENTS.md"
    if not agents_file.exists() and not agents_file.is_symlink():
        preflight_file(root / "AGENTS.md", agents_file, workspace)
    for name in ("tools", "templates"):
        preflight_symlink(root / name, workspace / name, workspace)
    if include_skills:
        for skill in skill_sources(root):
            preflight_symlink(skill, workspace / ".agents/skills" / skill.name, workspace)


def install_cursor(root: Path, workspace: Path, dry_run: bool) -> list[str]:
    rule = root / "adapters/cursor/rules/lopodev.mdc"
    agents = sorted((root / "adapters/cursor/agents").glob("*.md"))
    preflight_file(rule, workspace / ".cursor/rules/lopodev.mdc", workspace)
    for agent in agents:
        preflight_file(agent, workspace / ".cursor/agents" / agent.name, workspace)
    preflight_shared_contract(root, workspace)
    messages = [_install_file(rule, workspace / ".cursor/rules/lopodev.mdc", dry_run)]
    for agent in agents:
        messages.append(_install_file(agent, workspace / ".cursor/agents" / agent.name, dry_run))
    messages.extend(install_shared_contract(root, workspace, dry_run))
    return messages


def install_mcp(root: Path, workspace: Path, dry_run: bool,
                python_executable: str | None = None) -> list[str]:
    target = workspace / ".lopodev/mcp-server.json"
    safe_destination(workspace, target)
    python_executable = python_executable or sys.executable
    resolved_python = shutil.which(python_executable) or python_executable
    if not dry_run and (not Path(resolved_python).is_file() or not os.access(resolved_python, os.X_OK)):
        raise FileNotFoundError(f"MCP Python executable is not executable: {python_executable}")
    command = [resolved_python, str(root / "tools/mcp_server.py"), "--root", str(workspace)]
    payload = {"mcpServers": {"lopodev": {"command": command[0], "args": command[1:]}}}
    encoded = json.dumps(payload, indent=2) + "\n"
    if target.exists():
        if target.read_text(encoding="utf-8") == encoded:
            return [f"UNCHANGED {target}",
                    "MANUAL: merge this server entry into your agent's MCP configuration"]
        raise FileExistsError(f"refusing to overwrite existing user path: {target}")
    if not dry_run:
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(encoded, encoding="utf-8")
    return [f"{'WOULD_WRITE' if dry_run else 'WROTE'} {target}",
            "MANUAL: merge this server entry into your agent's MCP configuration"]


def android_export_command(args) -> int:
    sys.path.insert(0, str(Path(__file__).resolve().parent / "godot"))
    import android_export

    argv = [args.godot_dir, "--format", args.format, "--mode", args.mode,
            "--preset", args.preset]
    if args.output:
        argv.extend(["--out", args.output])
    if args.godot:
        argv.extend(["--godot", args.godot])
    if args.dry_run:
        argv.append("--dry-run")
    if args.json:
        argv.append("--json")
    if args.install_run:
        argv.append("--install-run")
    return android_export.main(argv)


def install_cli(root: Path, bin_dir: str | None) -> int:
    directory = Path(bin_dir or "~/.local/bin").expanduser()
    target = directory / "lopodev"
    source = root / "bin/lopodev"
    if not source.is_file():
        print(f"ERROR: launcher not found: {source}", file=sys.stderr)
        return 2
    if target.exists() and not target.is_symlink():
        print(f"ERROR: {target} exists and is not a symlink; not overwriting", file=sys.stderr)
        return 2
    if target.is_symlink() and target.resolve() != source.resolve():
        print(f"ERROR: {target} points elsewhere; not overwriting", file=sys.stderr)
        return 2
    directory.mkdir(parents=True, exist_ok=True)
    if target.is_symlink():
        target.unlink()
    target.symlink_to(source)
    print(f"INSTALLED_CLI={target}")
    print(f"CLI_TARGET={source}")
    return 0


def open_command(args) -> int:
    command = ["opencode", "--agent", "lopodev", *args.opencode_args]
    try:
        os.execvp(command[0], command)
    except OSError as exc:
        print(f"ERROR: cannot start opencode: {exc}", file=sys.stderr)
        return 2
    return 0


def doctor(root: Path, workspace: Path, live: bool = True, probe: bool = False) -> int:
    print(f"LopoDev {read_version(root)}")
    print(f"CLI Python: {sys.executable} ({platform.python_version()})")
    resources_ok = (root / 'tools').is_dir() and (root / 'resources/skills').is_dir() and (root / 'adapters').is_dir()
    print(f"resources: {'OK' if resources_ok else 'MISSING'} {root}")
    blender = os.environ.get("BLENDER") or shutil.which("blender") or ("/snap/bin/blender" if Path("/snap/bin/blender").is_file() else None)
    godot = os.environ.get("GODOT") or next((str(p) for pattern in (
        ".tools/godot/Godot_v*_linux.x86_64", ".tools/godot/Godot_v*_macos.universal")
        for p in root.glob(pattern) if p.is_file() and os.access(p, os.X_OK)), None)
    godot = godot or shutil.which("godot") or shutil.which("godot4")
    for found, label in ((blender, "Blender (optional for Godot-only work)"),
                         (godot, "Godot (project runtime/build)"),
                         ("opencode", "OpenCode (native adapter)"),
                         ("kilo", "Kilo Code (native adapter)")):
        if found in ("opencode", "kilo"):
            found = shutil.which(found)
        version = ""
        if found and Path(found).is_file() and os.access(found, os.X_OK):
            try:
                args = ["--version"]
                result = subprocess.run([found, *args], capture_output=True, text=True,
                                        timeout=30, check=False)
                version_line = (result.stdout or result.stderr).strip().splitlines()[0:1]
                if result.returncode == 0:
                    version = f" ({version_line[0]})" if version_line else " (version unavailable)"
                else:
                    version = f" (version probe exit={result.returncode})"
            except subprocess.TimeoutExpired:
                version = " (version probe timed out after 30s)"
            except OSError as exc:
                version = f" (version probe failed: {exc})"
        print(f"{label}: {found or 'not found'}{version}")
    projects = sorted((workspace / "projects").glob("*/project.json")) if (workspace / "projects").is_dir() else []
    print(f"LopoDev projects: {len(projects)}")
    for spec in projects:
        state_file = spec.parent / "pipeline_state.json"
        print(f"project {spec.parent.name}: spec=present state={'present' if state_file.is_file() else 'missing'}")
    print(f"workspace: {workspace} ({'exists' if workspace.is_dir() else 'missing'})")
    for rel, label in ((".opencode/agents/lopodev.md", "OpenCode project agent"),
                       (".kilo/agents/lopodev.md", "Kilo project agent"),
                       (".cursor/rules/lopodev.mdc", "Cursor project rule")):
        print(f"{label}: {'present' if (workspace / rel).exists() else 'not installed'}")
    try:
        import mcp  # noqa: F401
    except ImportError:
        print("MCP SDK: not installed (optional; install with `pip install 'mcp>=2,<3'`)")
    else:
        print("MCP SDK: available")
    print(f"approval mode: {approval.current_mode(workspace)} (change with `lopodev approval auto|manual`)")
    print(f"user data: {integrations.data_dir()} (knowledge, pinned integrations; kept on upgrade/uninstall)")
    has_opencode_workspace = (workspace / "opencode.json").is_file()
    rows = integrations.status(root, workspace if has_opencode_workspace else None, live=live)
    if probe:
        import mcp_probe
        for server in mcp_probe.READ_ONLY_CALLS:
            try:
                result = mcp_probe.probe(root, server, workspace)
                rows.append((f"mcp {server} tool call", result["status"],
                             f"{result.get('call')}: {result.get('detail', '')[:120]}"))
            except (FileNotFoundError, KeyError) as exc:
                rows.append((f"mcp {server} tool call", "NOT RUN", str(exc)))
    failures = 0
    print("== integrations ==")
    for check, result, detail in rows:
        print(f"{result:8} {check}: {detail}")
        failures += result == "FAIL"
    if failures:
        print(f"DOCTOR=FAIL failures={failures}")
        print("RECOVERY: `lopodev setup` installs pinned integrations; `lopodev install opencode "
              "--project <workspace>` wires them into a workspace; then start a new OpenCode session.")
        return 1
    print("DOCTOR=PASS")
    return 0


def integrations_disabled(argv: list[str]) -> bool:
    """`--no-integrations` or LOPODEV_NO_INTEGRATIONS=1 (offline/CI) skip `setup`."""
    return "--no-integrations" in argv or os.environ.get("LOPODEV_NO_INTEGRATIONS") == "1"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="lopodev", description=__doc__)
    parser.add_argument("--version", action="version",
                        version=f"lopodev {read_version(toolkit_root())}")
    sub = parser.add_subparsers(dest="command")
    doctor_parser = sub.add_parser("doctor", help="check tools, integrations, skills and MCP activation")
    doctor_parser.add_argument("--project", default=".", help="workspace root (default: current directory)")
    doctor_parser.add_argument("--no-live", action="store_true",
                               help="skip launching opencode to probe skill discovery and MCP connectivity")
    doctor_parser.add_argument("--probe", action="store_true",
                               help="also make one real read-only tool call to each MCP server")
    install = sub.add_parser("install", help="install a project-level agent adapter")
    install.add_argument("target", choices=("opencode", "kilo", "cursor", "mcp"))
    install.add_argument("--project", default=".", help="workspace root (default: current directory)")
    install.add_argument("--dry-run", action="store_true")
    install.add_argument("--python", help="Python executable with MCP SDK installed (MCP target only)")
    install.add_argument("--no-integrations", action="store_true",
                         help="do not install pinned MCP servers and vendored skills first")
    setup_parser = sub.add_parser("setup", help="install pinned MCP servers and vendored skills (per user)")
    setup_parser.add_argument("--dry-run", action="store_true")
    setup_parser.add_argument("--only", action="append", choices=("skills", "blender", "godot", "codemap"),
                              help="limit to a component (repeatable)")
    setup_parser.add_argument("--no-blender-addon", action="store_true",
                              help="do not copy/enable the Blender MCP addon in Blender's user preferences")
    mcp_run = sub.add_parser("mcp-run", help="launch a pinned MCP server (used by agent configs)")
    mcp_run.add_argument("server")
    mcp_run.add_argument("server_args", nargs=argparse.REMAINDER)
    approval_parser = sub.add_parser("approval", help="show or set the tool approval mode")
    approval_parser.add_argument("mode", nargs="?", choices=approval.MODES)
    approval_parser.add_argument("--project", default=".", help="workspace root (default: current directory)")
    for name, help_text in (("knowledge", "search, verify and reuse engineering knowledge"),
                            ("context", "print a bounded task brief for an agent session"),
                            ("world", "generate and validate procedural world plans")):
        passthrough = sub.add_parser(name, help=help_text)
        passthrough.add_argument("passthrough_args", nargs=argparse.REMAINDER)
    uninstall = sub.add_parser("uninstall", help="remove only unchanged files recorded as LopoDev-managed")
    uninstall.add_argument("target", choices=("opencode", "kilo", "cursor", "mcp"))
    uninstall.add_argument("--project", default=".", help="workspace root (default: current directory)")
    uninstall.add_argument("--dry-run", action="store_true")
    update = sub.add_parser("update", help="show the package-manager update command")
    update.add_argument("--dry-run", action="store_true", help="print without invoking a package manager")
    android = sub.add_parser(
        "android-export",
        help="export and verify a Godot Android APK or release AAB")
    android.add_argument("godot_dir", help="Godot project directory")
    android.add_argument("--format", choices=("apk", "aab"), default="apk")
    android.add_argument("--mode", choices=("debug", "release"), default="debug")
    android.add_argument("--preset", default="Android",
                         help="Android export preset name (default: Android)")
    android.add_argument("--out", dest="output", help="output .apk/.aab path")
    android.add_argument("--godot", help="Godot executable")
    android.add_argument("--dry-run", action="store_true",
                         help="validate the request without exporting")
    android.add_argument("--json", action="store_true", help="print a JSON result")
    android.add_argument("--install-run", action="store_true",
                         help="install and launch the APK on a connected device/emulator")
    open_parser = sub.add_parser("open", help="start OpenCode with the lopodev agent")
    open_parser.add_argument("opencode_args", nargs=argparse.REMAINDER)
    cli = sub.add_parser("install-cli", help="symlink this launcher onto PATH")
    cli.add_argument("bin_dir", nargs="?", default="~/.local/bin")
    new = sub.add_parser("new", help="bootstrap a new project in a workspace")
    new.add_argument("bootstrap_args", nargs=argparse.REMAINDER)
    verify = sub.add_parser("verify", help="run the toolkit verification checks")
    verify.add_argument("verify_args", nargs=argparse.REMAINDER)
    sub.add_parser("version", help="print version and toolkit root")
    sub.add_parser("help", help="show command help")
    argv = list(sys.argv[1:] if argv is None else argv)
    root = toolkit_root()
    if argv and argv[0] == "new":
        bootstrap_args = [arg for arg in argv[1:] if arg != "--no-integrations"]
        if not integrations_disabled(argv):
            messages, errors = integrations.setup(root)
            for message in messages:
                print(message)
            if errors:
                print(f"INTEGRATIONS=DEGRADED ({len(errors)} failed); the project is still created. "
                      "Run `lopodev doctor` for recovery steps.")
        return subprocess.call([sys.executable, str(root / "tools/bootstrap_project.py"),
                                *bootstrap_args])
    if argv and argv[0] == "verify":
        return subprocess.call([str(root / "tools/verify_lopodev.sh"), *argv[1:]])
    passthrough = {"knowledge": "knowledge.py", "context": "context_pack.py", "world": "world_plan.py"}
    if argv and argv[0] in passthrough:
        return subprocess.call([sys.executable, str(root / "tools" / passthrough[argv[0]]), *argv[1:]])
    if argv and argv[0] == "mcp-run":
        if len(argv) < 2:
            parser.error("mcp-run needs a server name")
        return integrations.mcp_run(root, argv[1], argv[2:])
    args = parser.parse_args(argv)
    if args.command in (None, "help"):
        parser.print_help()
        return 0
    if args.command == "doctor":
        return doctor(root, project_root(args.project), live=not args.no_live, probe=args.probe)
    if args.command == "setup":
        return setup_command(root, args)
    if args.command == "approval":
        return approval_command(root, project_root(args.project), args.mode)
    if args.command == "version":
        print(f"lopodev {read_version(root)}")
        print(f"root={root}")
        return 0
    if args.command == "update":
        print("Update with the package manager used to install LopoDev.")
        print("Homebrew: brew update && brew upgrade lopodev")
        return 0
    if args.command == "install-cli":
        return install_cli(root, args.bin_dir)
    if args.command == "open":
        return open_command(args)
    if args.command == "android-export":
        return android_export_command(args)
    workspace = project_root(args.project)
    if not workspace.is_dir():
        parser.error(f"workspace does not exist: {workspace}")
    if args.command == "install" and args.target != "mcp" and args.python:
        parser.error("--python is only valid for the mcp target")
    if args.command == "uninstall":
        try:
            for message in uninstall_target(workspace, args.target, args.dry_run):
                print(message)
        except (OSError, ValueError, json.JSONDecodeError) as exc:
            print(f"ERROR: {exc}", file=sys.stderr)
            return 2
        return 0
    installers = {"opencode": install_opencode, "kilo": install_kilo,
                  "cursor": install_cursor, "mcp": install_mcp}
    degraded: list[str] = []
    if args.target != "mcp" and not integrations_disabled(argv):
        setup_messages, degraded = integrations.setup(root, dry_run=args.dry_run)
        for message in setup_messages:
            print(message)
    try:
        # Fail closed before changing paths if ownership metadata is corrupt or
        # points outside the selected workspace.
        load_manifest(workspace)
        if args.target == "mcp":
            messages = install_mcp(root, workspace, args.dry_run, args.python)
        else:
            messages = installers[args.target](root, workspace, args.dry_run)
        if not args.dry_run:
            record_created(workspace, args.target, messages)
    except (OSError, ValueError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2
    for message in messages:
        print(message)
    print(f"INSTALL_TARGET={args.target} DRY_RUN={str(args.dry_run).lower()}")
    if degraded:
        print(f"INTEGRATIONS=DEGRADED ({len(degraded)} failed); run `lopodev doctor` for recovery steps")
    if args.target == "opencode" and not args.dry_run:
        print("ACTIVATION: new OpenCode sessions in this workspace load the changes. Running sessions "
              "keep their old tools until restarted; LopoDev never restarts them for you. "
              f"Verify with `lopodev doctor --project {workspace}`.")
    return 0


def setup_command(root: Path, args) -> int:
    messages, errors = integrations.setup(root, dry_run=args.dry_run,
                                          components=set(args.only) if args.only else None,
                                          blender_addon=not args.no_blender_addon)
    for message in messages:
        print(message)
    print(f"SETUP={'FAIL' if errors else 'PASS'} DRY_RUN={str(args.dry_run).lower()}")
    for error in errors:
        print(f"RECOVERY {error.split(':', 1)[0]}: fix the cause above, then rerun `lopodev setup`",
              file=sys.stderr)
    return 1 if errors else 0


def approval_command(root: Path, workspace: Path, mode: str | None) -> int:
    current = approval.current_mode(workspace)
    if mode is None:
        print(f"APPROVAL_MODE={current}")
        print("auto: edits and ordinary commands run without prompts; destructive, publishing and "
              "gate-approval commands still ask" if current == "auto" else
              "manual: every edit and non-read-only command asks first")
        return 0
    if not workspace.is_dir():
        print(f"ERROR: workspace does not exist: {workspace}", file=sys.stderr)
        return 2
    try:
        manifest = load_manifest(workspace)
        messages = workspace_config.merge(workspace, "opencode.json",
                                          {"permission": approval.policy(mode)}, manifest, False,
                                          skeleton={"$schema": "https://opencode.ai/config.json"})
        if any(message.startswith("PRESERVED") for message in messages):
            for message in messages:
                print(message)
            print("ERROR: opencode.json has a user-defined `permission` block; LopoDev will not "
                  "replace it. Remove it to let LopoDev manage approval mode.", file=sys.stderr)
            return 2
        save_manifest(workspace, manifest)
        approval.record_mode(workspace, mode, current, "lopodev approval")
    except (OSError, ValueError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2
    print(f"APPROVAL_MODE={mode} (was {current}); restart running OpenCode sessions to apply")
    return 0


if __name__ == "__main__":
    sys.exit(main())
