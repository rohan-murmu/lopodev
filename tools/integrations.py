#!/usr/bin/env python3
"""Install, verify, and launch LopoDev's pinned third-party integrations.

Everything third-party lives in the per-user data directory, never in a
workspace or the global Python/Node environment:

  $LOPODEV_DATA (default ${XDG_DATA_HOME:-~/.local/share}/lopodev)
    vendor/<pack>-<commit12>/     checksum-verified skill-pack archives
    skills/<skill> -> vendor/...  stable links that workspaces point at
    mcp/<server>-<version>/       isolated venv or node prefix per MCP server
    integrations.lock.json        what was installed, from which pin

Pins and checksums come from resources/integrations.json.
"""

from __future__ import annotations

import hashlib
import io
import json
import os
import re
import shutil
import socket
import subprocess
import sys
import tarfile
import tempfile
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

Runner = Callable[..., subprocess.CompletedProcess]
Fetcher = Callable[[str], bytes]

MCP_TOOL_PATTERNS = {"blender": "blender_*", "godot": "godot_*", "codemap": "codemap_*"}

# Runs inside Blender; mirrors the upstream setup's enable step without
# touching any MCP client configuration.
_ENABLE_ADDON_SCRIPT = r"""
import json, sys
import addon_utils, bpy
module = sys.argv[sys.argv.index("--") + 1]
result = {"enabled": False, "already": False, "error": None}
try:
    if module in {a.module for a in bpy.context.preferences.addons}:
        result["already"] = True
    else:
        result["enabled"] = addon_utils.enable(module, default_set=True) is not None
        if result["enabled"]:
            bpy.ops.wm.save_userpref()
        else:
            result["error"] = "Blender could not load " + module
except Exception as exc:
    result["error"] = str(exc)
print("LOPODEV_ADDON " + json.dumps(result))
"""


def data_dir() -> Path:
    configured = os.environ.get("LOPODEV_DATA")
    if configured:
        return Path(os.path.abspath(Path(configured).expanduser()))
    base = os.environ.get("XDG_DATA_HOME") or "~/.local/share"
    return Path(os.path.abspath(Path(base).expanduser())) / "lopodev"


def load_spec(root: Path) -> dict:
    return json.loads((root / "resources/integrations.json").read_text(encoding="utf-8"))


def lock_file(data: Path) -> Path:
    return data / "integrations.lock.json"


def read_lock(data: Path) -> dict:
    try:
        lock = json.loads(lock_file(data).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {"schema_version": 1, "components": {}}
    lock.setdefault("components", {})
    return lock


def write_lock(data: Path, lock: dict) -> None:
    data.mkdir(parents=True, exist_ok=True)
    temporary = lock_file(data).with_suffix(".tmp")
    temporary.write_text(json.dumps(lock, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    os.replace(temporary, lock_file(data))


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def default_fetch(url: str) -> bytes:
    with urllib.request.urlopen(url, timeout=120) as response:  # noqa: S310 - pinned https URL
        return response.read()


# ---------------------------------------------------------------- skill packs

def pack_dir(data: Path, name: str, spec: dict) -> Path:
    return data / "vendor" / f"{name}-{spec['commit'][:12]}"


def safe_extract(archive: bytes, destination: Path) -> int:
    """Extract regular files and directories only, stripping the top folder."""
    count = 0
    with tarfile.open(fileobj=io.BytesIO(archive), mode="r:gz") as tar:
        for member in tar.getmembers():
            parts = Path(member.name).parts
            if len(parts) <= 1:
                continue
            relative = Path(*parts[1:])
            if relative.is_absolute() or ".." in relative.parts:
                raise ValueError(f"unsafe archive member: {member.name}")
            target = destination / relative
            if member.isdir():
                target.mkdir(parents=True, exist_ok=True)
            elif member.isfile():
                target.parent.mkdir(parents=True, exist_ok=True)
                source = tar.extractfile(member)
                if source is None:
                    continue
                target.write_bytes(source.read())
                count += 1
            # Links, devices and FIFOs are skipped: skills never need them.
    return count


def install_skill_pack(data: Path, name: str, spec: dict, dry_run: bool,
                       fetch: Fetcher = default_fetch) -> list[str]:
    messages: list[str] = []
    target = pack_dir(data, name, spec)
    marker = target / ".lopodev-pack.json"
    current = None
    if marker.is_file():
        try:
            current = json.loads(marker.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            current = None
    if current and current.get("sha256") == spec["sha256"]:
        messages.append(f"UNCHANGED skill pack {name}@{spec['commit'][:12]}")
    elif dry_run:
        messages.append(f"WOULD_DOWNLOAD skill pack {name}@{spec['commit'][:12]}")
    else:
        url = f"https://codeload.github.com/{spec['repo']}/tar.gz/{spec['commit']}"
        archive = fetch(url)
        digest = hashlib.sha256(archive).hexdigest()
        if digest != spec["sha256"]:
            raise ValueError(f"checksum mismatch for {name}: expected {spec['sha256']}, got {digest}")
        target.parent.mkdir(parents=True, exist_ok=True)
        staging = Path(tempfile.mkdtemp(prefix=f".{name}-", dir=target.parent))
        try:
            files = safe_extract(archive, staging)
            (staging / ".lopodev-pack.json").write_text(json.dumps(
                {"pack": name, "repo": spec["repo"], "commit": spec["commit"],
                 "sha256": digest, "files": files, "installed_at": utc_now()}, indent=2) + "\n",
                encoding="utf-8")
            if target.exists():
                shutil.rmtree(target)
            os.replace(staging, target)
        finally:
            if staging.exists():
                shutil.rmtree(staging, ignore_errors=True)
        messages.append(f"DOWNLOADED skill pack {name}@{spec['commit'][:12]} sha256={digest[:12]}")
    for skill in spec["skills"]:
        messages.append(link_skill(data, skill, target / spec.get("skills_dir", ".") / skill, dry_run))
    return messages


def link_skill(data: Path, skill: str, source: Path, dry_run: bool) -> str:
    link = data / "skills" / skill
    if not dry_run and not (source / "SKILL.md").is_file():
        raise FileNotFoundError(f"pinned pack does not contain skill {skill}: {source}")
    if link.is_symlink():
        if Path(os.readlink(link)) == source:
            return f"UNCHANGED skill {skill}"
        if not Path(os.readlink(link)).is_relative_to(data / "vendor"):
            raise FileExistsError(f"refusing to replace user skill link: {link}")
    elif link.exists():
        raise FileExistsError(f"refusing to replace user skill directory: {link}")
    if dry_run:
        return f"WOULD_LINK skill {skill}"
    link.parent.mkdir(parents=True, exist_ok=True)
    temporary = link.with_name(f".{skill}.tmp")
    if temporary.is_symlink():
        temporary.unlink()
    temporary.symlink_to(source, target_is_directory=True)
    os.replace(temporary, link)
    return f"LINKED skill {skill}"


def vendored_skills(root: Path) -> list[str]:
    spec = load_spec(root)
    return [skill for pack in spec["skill_packs"].values() for skill in pack["skills"]]


# ---------------------------------------------------------------- MCP servers

def server_dir(data: Path, name: str, spec: dict) -> Path:
    return data / "mcp" / f"{name}-{spec['version']}"


def server_entry(data: Path, name: str, spec: dict) -> Path | None:
    """Absolute executable/script for a pinned server, or None for PATH binaries."""
    base = server_dir(data, name, spec)
    if spec["kind"] == "python":
        return base / "bin" / spec["entrypoint"]
    if spec["kind"] == "node":
        return base / "node_modules" / Path(*spec["package"].split("/")) / spec["entrypoint"]
    return None


def _run(runner: Runner, command: list[str], **kwargs) -> subprocess.CompletedProcess:
    result = runner(command, capture_output=True, text=True, check=False, **kwargs)
    if result.returncode != 0:
        detail = (result.stderr or result.stdout or "").strip().splitlines()[-3:]
        raise RuntimeError(f"command failed (exit {result.returncode}): {' '.join(command)}: "
                           + " | ".join(detail))
    return result


def install_python_server(data: Path, name: str, spec: dict, dry_run: bool,
                          runner: Runner = subprocess.run, which=shutil.which) -> str:
    entry = server_entry(data, name, spec)
    if entry and entry.is_file():
        return f"UNCHANGED mcp {name} {spec['package']}=={spec['version']}"
    uv = which("uv")
    if dry_run:
        return f"WOULD_INSTALL mcp {name} {spec['package']}=={spec['version']} via {'uv' if uv else 'venv+pip'}"
    # A venv embeds its own path, so build at the final location and remove
    # it again on any failure; the entrypoint check above makes reruns safe.
    target = server_dir(data, name, spec)
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.exists():
        shutil.rmtree(target)
    requirement = f"{spec['package']}=={spec['version']}"
    try:
        if uv:
            _run(runner, [uv, "venv", "--quiet", "--python", ">=3.10", str(target)])
            _run(runner, [uv, "pip", "install", "--quiet", "--python",
                          str(target / "bin/python"), requirement])
        else:
            _run(runner, [sys.executable, "-m", "venv", str(target)])
            _run(runner, [str(target / "bin/python"), "-m", "pip", "install", "--quiet", requirement])
        if not (entry and entry.is_file()):
            raise RuntimeError(f"{name}: entrypoint missing after install: {entry}")
    except BaseException:
        shutil.rmtree(target, ignore_errors=True)
        raise
    return f"INSTALLED mcp {name} {spec['package']}=={spec['version']}"


def install_node_server(data: Path, name: str, spec: dict, dry_run: bool,
                        runner: Runner = subprocess.run, which=shutil.which) -> str:
    entry = server_entry(data, name, spec)
    if entry and entry.is_file():
        return f"UNCHANGED mcp {name} {spec['package']}@{spec['version']}"
    npm = which("npm")
    if not npm:
        raise FileNotFoundError(f"{name}: npm not found; install Node.js 18+ and rerun `lopodev setup`")
    if dry_run:
        return f"WOULD_INSTALL mcp {name} {spec['package']}@{spec['version']} via npm"
    target = server_dir(data, name, spec)
    target.parent.mkdir(parents=True, exist_ok=True)
    staging = Path(tempfile.mkdtemp(prefix=f".{name}-", dir=target.parent))
    try:
        (staging / "package.json").write_text('{"private": true}\n', encoding="utf-8")
        _run(runner, [npm, "install", "--prefix", str(staging), "--no-audit", "--no-fund",
                      "--omit=dev", "--save-exact", f"{spec['package']}@{spec['version']}"])
        staged_entry = staging / "node_modules" / Path(*spec["package"].split("/")) / spec["entrypoint"]
        if not staged_entry.is_file():
            raise RuntimeError(f"{name}: entrypoint missing after npm install: {staged_entry}")
        if target.exists():
            shutil.rmtree(target)
        os.replace(staging, target)
    finally:
        if staging.exists():
            shutil.rmtree(staging, ignore_errors=True)
    return f"INSTALLED mcp {name} {spec['package']}@{spec['version']}"


def binary_version(executable: str, runner: Runner = subprocess.run) -> str | None:
    try:
        result = runner([executable, "--version"], capture_output=True, text=True,
                        timeout=20, check=False)
    except (OSError, subprocess.TimeoutExpired):
        return None
    match = re.search(r"\d+\.\d+\.\d+", result.stdout + result.stderr)
    return match.group(0) if match else None


def ensure_binary(name: str, spec: dict, dry_run: bool, runner: Runner = subprocess.run,
                  which=shutil.which) -> str:
    found = which(spec["entrypoint"])
    if found:
        version = binary_version(found, runner)
        if version == spec["version"]:
            return f"UNCHANGED {name} {version} ({found})"
        # Never replace a user's own tool; report the drift instead.
        return f"PRESENT {name} {version or 'unknown'} ({found}); pinned {spec['version']} not enforced"
    installers = spec.get("install", {})
    if which("brew") and installers.get("brew"):
        command = [which("brew"), "install", installers["brew"]]
    elif which("go") and installers.get("go"):
        command = [which("go"), "install", installers["go"]]
    else:
        raise FileNotFoundError(
            f"{name} not found and neither Homebrew nor Go is available; install it from {spec['upstream']}")
    if dry_run:
        return f"WOULD_RUN {' '.join(command)}"
    _run(runner, command)
    if not which(spec["entrypoint"]):
        raise RuntimeError(f"{name} installed but `{spec['entrypoint']}` is not on PATH")
    return f"INSTALLED {name} via {' '.join(command[1:3])}"


def find_blender(which=shutil.which) -> str | None:
    configured = os.environ.get("BLENDER")
    if configured and Path(configured).is_file():
        return configured
    for candidate in (which("blender"), "/snap/bin/blender",
                      "/Applications/Blender.app/Contents/MacOS/Blender"):
        if candidate and Path(candidate).is_file():
            return candidate
    return None


def install_blender_addon(data: Path, spec: dict, dry_run: bool, runner: Runner = subprocess.run,
                          which=shutil.which) -> list[str]:
    entry = server_entry(data, "blender", spec)
    blender = find_blender(which)
    if not blender:
        return ["SKIPPED blender addon: Blender not found (set BLENDER=/path/to/blender)"]
    if dry_run:
        return [f"WOULD_INSTALL blender addon with {blender}"]
    if not (entry and entry.is_file()):
        return ["SKIPPED blender addon: blender MCP server is not installed"]
    _run(runner, [str(entry), "install-addon"])
    with tempfile.NamedTemporaryFile("w", suffix=".py", delete=False) as script:
        script.write(_ENABLE_ADDON_SCRIPT)
    try:
        result = runner([blender, "--background", "--python", script.name, "--", "blender_mcp"],
                        capture_output=True, text=True, timeout=180, check=False)
    finally:
        os.unlink(script.name)
    line = next((l for l in result.stdout.splitlines() if l.startswith("LOPODEV_ADDON ")), None)
    if not line:
        return [f"FAILED blender addon enable: no result (exit {result.returncode})"]
    outcome = json.loads(line.split(" ", 1)[1])
    if outcome.get("error"):
        return [f"FAILED blender addon enable: {outcome['error']}"]
    return ["INSTALLED blender addon (copied by mcp-for-blender install-addon)",
            "UNCHANGED blender addon enabled" if outcome.get("already") else "ENABLED blender addon in user preferences"]


# ---------------------------------------------------------------- setup / run

def setup(root: Path, dry_run: bool = False, components: set[str] | None = None,
          blender_addon: bool = True, runner: Runner = subprocess.run,
          fetch: Fetcher = default_fetch, which=shutil.which) -> tuple[list[str], list[str]]:
    """Install every pinned integration. Returns (messages, errors)."""
    spec = load_spec(root)
    data = data_dir()
    lock = read_lock(data)
    messages: list[str] = [f"DATA_DIR {data}"]
    errors: list[str] = []
    wanted = components or {"skills", *spec["mcp_servers"]}

    def attempt(component: str, action: Callable[[], list[str] | str], record: dict | None) -> None:
        try:
            result = action()
            messages.extend([result] if isinstance(result, str) else result)
            if record is not None and not dry_run:
                lock["components"][component] = {**record, "installed_at": utc_now()}
        except (OSError, ValueError, RuntimeError, subprocess.SubprocessError) as exc:
            errors.append(f"{component}: {exc}")
            messages.append(f"FAILED {component}: {exc}")

    if "skills" in wanted:
        for name, pack in spec["skill_packs"].items():
            attempt(f"skills:{name}",
                    lambda name=name, pack=pack: install_skill_pack(data, name, pack, dry_run, fetch),
                    {"commit": pack["commit"], "sha256": pack["sha256"],
                     "path": str(pack_dir(data, name, pack))})
    for name, server in spec["mcp_servers"].items():
        if name not in wanted:
            continue
        if server["kind"] == "python":
            action = lambda name=name, server=server: install_python_server(data, name, server, dry_run, runner, which)
        elif server["kind"] == "node":
            action = lambda name=name, server=server: install_node_server(data, name, server, dry_run, runner, which)
        else:
            action = lambda name=name, server=server: ensure_binary(name, server, dry_run, runner, which)
        entry = server_entry(data, name, server)
        attempt(f"mcp:{name}", action, {"version": server["version"],
                                         "path": str(entry) if entry else server["entrypoint"]})
    if blender_addon and "blender" in wanted:
        attempt("blender-addon", lambda: install_blender_addon(
            data, spec["mcp_servers"]["blender"], dry_run, runner, which), None)
    if not dry_run:
        write_lock(data, lock)
    return messages, errors


def pinned_godot(root: Path) -> str | None:
    configured = os.environ.get("GODOT")
    if configured and Path(configured).is_file():
        return configured
    for pattern in (".tools/godot/Godot_v*_linux.x86_64", ".tools/godot/Godot_v*_macos.universal"):
        for path in sorted(root.glob(pattern)):
            if path.is_file() and os.access(path, os.X_OK):
                return str(path)
    return shutil.which("godot") or shutil.which("godot4")


def server_command(root: Path, name: str) -> tuple[list[str], dict[str, str]]:
    """Resolve the real command and extra environment for an installed server."""
    spec = load_spec(root)["mcp_servers"].get(name)
    if spec is None:
        raise KeyError(f"unknown MCP server: {name}")
    env = dict(spec.get("environment", {}))
    entry = server_entry(data_dir(), name, spec)
    if spec["kind"] == "python":
        command = [str(entry)]
    elif spec["kind"] == "node":
        node = shutil.which("node")
        if not node:
            raise FileNotFoundError("node not found on PATH")
        command = [node, str(entry)]
        if name == "godot":
            godot = pinned_godot(root)
            if godot:
                env["GODOT_PATH"] = godot
    else:
        found = shutil.which(spec["entrypoint"])
        if not found:
            raise FileNotFoundError(f"{spec['entrypoint']} not found on PATH")
        command = [found, *spec.get("args", [])]
    if entry is not None and not entry.is_file():
        raise FileNotFoundError(f"{name} MCP server is not installed; run `lopodev setup`")
    return command, env


def mcp_run(root: Path, name: str, extra: list[str]) -> int:
    """Exec the pinned server so agent configs need no machine-specific paths."""
    try:
        command, env = server_command(root, name)
    except (KeyError, FileNotFoundError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2
    merged = dict(os.environ)
    for key, value in env.items():
        merged.setdefault(key, value)
    os.execvpe(command[0], [*command, *extra], merged)
    return 0  # pragma: no cover


def opencode_mcp_block(root: Path, launcher: str) -> dict:
    """The `mcp` entries LopoDev manages in a workspace opencode.json."""
    spec = load_spec(root)
    block = {}
    for name, server in spec["mcp_servers"].items():
        entry = {"type": "local", "command": [launcher, "mcp-run", name], "enabled": True}
        if server.get("environment"):
            entry["environment"] = dict(server["environment"])
        if name == "blender":
            entry["timeout"] = 60000
        block[name] = entry
    return block


def opencode_tool_defaults(root: Path) -> dict:
    """MCP tools are off by default; agents opt in through their frontmatter."""
    return {MCP_TOOL_PATTERNS[name]: False for name in load_spec(root)["mcp_servers"]}


# ---------------------------------------------------------------- diagnostics

def blender_endpoint(spec: dict) -> tuple[bool, str]:
    host = os.environ.get("BLENDER_HOST", spec["environment"].get("BLENDER_HOST", "localhost"))
    port = os.environ.get("BLENDER_PORT", spec["environment"].get("BLENDER_PORT", "9876"))
    try:
        with socket.create_connection((host, int(port)), timeout=0.5):
            return True, f"{host}:{port}"
    except (OSError, ValueError):
        return False, f"{host}:{port}"


def opencode_skills(workspace: Path, runner: Runner = subprocess.run) -> set[str] | None:
    """Skills a fresh OpenCode session in `workspace` would discover."""
    opencode = shutil.which("opencode")
    if not opencode:
        return None
    # Bun truncates piped stdout near 64 KiB; capture through a real file.
    with tempfile.TemporaryFile("w+") as handle:
        try:
            runner([opencode, "debug", "skill"], cwd=workspace, stdout=handle,
                   stderr=subprocess.DEVNULL, timeout=90, check=False)
        except (OSError, subprocess.TimeoutExpired):
            return None
        handle.seek(0)
        try:
            return {item["name"] for item in json.load(handle)}
        except (json.JSONDecodeError, KeyError, TypeError):
            return None


def opencode_mcp_status(workspace: Path, runner: Runner = subprocess.run) -> dict[str, str] | None:
    """Connection status per server as reported by `opencode mcp list`."""
    opencode = shutil.which("opencode")
    if not opencode:
        return None
    try:
        result = runner([opencode, "mcp", "list"], cwd=workspace, capture_output=True,
                        text=True, timeout=120, check=False)
    except (OSError, subprocess.TimeoutExpired):
        return None
    text = re.sub(r"\x1b\[[0-9;]*m", "", result.stdout + result.stderr)
    status = {}
    for match in re.finditer(r"[✓✗×!]\s+([\w.-]+)\s+(\w[\w ]*)", text):
        status[match.group(1)] = match.group(2).strip()
    return status


def status(root: Path, workspace: Path | None = None, live: bool = True,
           runner: Runner = subprocess.run) -> list[tuple[str, str, str]]:
    """Return (check, PASS|FAIL|WARN|NOT RUN|PENDING, detail) rows."""
    spec = load_spec(root)
    data = data_dir()
    rows: list[tuple[str, str, str]] = []
    for name, pack in spec["skill_packs"].items():
        marker = pack_dir(data, name, pack) / ".lopodev-pack.json"
        ok = marker.is_file() and json.loads(marker.read_text()).get("sha256") == pack["sha256"]
        rows.append((f"skill-pack {name}", "PASS" if ok else "FAIL",
                     f"{pack['commit'][:12]}" if ok else "not installed; run `lopodev setup`"))
    broken = [skill for skill in vendored_skills(root)
              if not (data / "skills" / skill / "SKILL.md").is_file()]
    rows.append(("vendored skill links", "FAIL" if broken else "PASS",
                 f"missing: {', '.join(broken)}" if broken else f"{len(vendored_skills(root))} linked"))
    for name, server in spec["mcp_servers"].items():
        try:
            command, _ = server_command(root, name)
            rows.append((f"mcp {name} installed", "PASS", " ".join(command)))
        except (FileNotFoundError, KeyError) as exc:
            rows.append((f"mcp {name} installed", "FAIL", str(exc)))
    reachable, where = blender_endpoint(spec["mcp_servers"]["blender"])
    rows.append(("blender addon socket", "PASS" if reachable else "NOT RUN",
                 f"reachable at {where}" if reachable else
                 f"nothing listening at {where}; open Blender (addon starts the server) to use Blender MCP"))
    godot = pinned_godot(root)
    rows.append(("godot for godot-mcp", "PASS" if godot else "FAIL", godot or "set GODOT=/path/to/godot"))
    if workspace is None:
        return rows
    config_file = workspace / "opencode.json"
    try:
        config = json.loads(config_file.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        config = {}
    configured = config.get("mcp", {})
    for name in spec["mcp_servers"]:
        entry = configured.get(name)
        if not entry:
            rows.append((f"workspace mcp {name}", "FAIL", "not configured; run `lopodev install opencode`"))
        elif not entry.get("enabled", True):
            rows.append((f"workspace mcp {name}", "WARN", "configured but disabled"))
        else:
            rows.append((f"workspace mcp {name}", "PASS", " ".join(entry.get("command", []))))
    if not live:
        rows.append(("opencode skill discovery", "NOT RUN", "live checks skipped"))
        rows.append(("opencode mcp connectivity", "NOT RUN", "live checks skipped"))
        return rows
    skills = opencode_skills(workspace, runner)
    if skills is None:
        rows.append(("opencode skill discovery", "NOT RUN", "opencode not found or failed"))
    else:
        own = sorted(p.name for p in (root / "resources/skills").iterdir() if (p / "SKILL.md").is_file())
        expected = set(own) | {s for s in vendored_skills(root) if (data / "skills" / s).exists()}
        missing = sorted(expected - skills)
        rows.append(("opencode skill discovery", "FAIL" if missing else "PASS",
                     f"missing: {', '.join(missing)}" if missing else f"{len(expected)} LopoDev skills discovered"))
    mcp = opencode_mcp_status(workspace, runner)
    if mcp is None:
        rows.append(("opencode mcp connectivity", "NOT RUN", "opencode not found or failed"))
    else:
        for name in spec["mcp_servers"]:
            state = mcp.get(name)
            rows.append((f"opencode mcp {name}", "PASS" if state == "connected" else "FAIL",
                         state or "not listed by `opencode mcp list`"))
    return rows
