#!/usr/bin/env python3
"""Visible tool sessions: open Blender, Godot and the Android emulator on screen
while LopoDev works, and close only what LopoDev opened.

  lopodev live mode [auto|off]          show or set the mode (auto opens windows)
  lopodev live start blender [--blend F] [--project P]
  lopodev live start godot --project P  (Godot editor on the project)
  lopodev live run godot --project P [--scene res://...] [--seconds 8] [--screenshot out.png]
  lopodev live status
  lopodev live stop [blender|godot|emulator|all]

Ownership: every process LopoDev launches is recorded in
`.lopodev/live/<tool>.json` with its PID and kernel start time. `stop`
terminates a process only when both still match, so a Blender or Godot the
user opened (or a recycled PID) is never touched. If a tool is already running
(for example Blender's MCP port is taken), the running instance is reused.

Mode `auto` (default when a display is available) makes pipeline commands open
their tools visibly; `off`, or no display, keeps everything headless.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import signal
import socket
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import approval  # noqa: E402
import integrations  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
MODES = ("auto", "off")
TOOLS = ("blender", "godot", "godot-run", "emulator")
BLENDER_MCP_PORT = 9876


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def has_display() -> bool:
    if sys.platform == "darwin":
        return True
    return bool(os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY"))


def current_mode(workspace: Path) -> str:
    mode = approval.read_config(workspace).get("live_mode", "auto")
    return mode if mode in MODES else "auto"


def enabled(workspace: Path) -> bool:
    """True when pipeline commands should open visible tools."""
    return current_mode(workspace) == "auto" and has_display() and not os.environ.get("LOPODEV_HEADLESS")


def set_mode(workspace: Path, mode: str) -> str:
    previous = current_mode(workspace)
    config = approval.read_config(workspace)
    config["live_mode"] = mode
    path = approval.config_path(workspace)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(config, indent=2) + "\n", encoding="utf-8")
    os.replace(temporary, path)
    with (workspace / ".lopodev/events.jsonl").open("a", encoding="utf-8") as handle:
        handle.write(json.dumps({"ts": utc_now(), "event": "live_mode", "from": previous, "to": mode}) + "\n")
    return previous


# ---------------------------------------------------------------- ownership records

def record_path(workspace: Path, tool: str) -> Path:
    return workspace / ".lopodev/live" / f"{tool}.json"


def start_time(pid: int) -> str | None:
    """Kernel start time of a process (Linux /proc, else `ps`), or None if gone."""
    stat = Path(f"/proc/{pid}/stat")
    if stat.exists():
        try:
            fields = stat.read_text().rsplit(")", 1)[1].split()
            if fields[0] in ("Z", "X"):  # exited, waiting to be reaped: not running
                return None
            return fields[19]  # field 22 overall: starttime in clock ticks
        except (OSError, IndexError):
            return None
    try:
        result = subprocess.run(["ps", "-o", "lstart=", "-p", str(pid)], capture_output=True, text=True,
                                check=False, timeout=5)
    except (OSError, subprocess.TimeoutExpired):
        return None
    return result.stdout.strip() or None


def owned(record: dict) -> bool:
    """The recorded process is still the one LopoDev started."""
    pid = record.get("pid")
    return isinstance(pid, int) and start_time(pid) is not None and start_time(pid) == record.get("start_time")


def load_record(workspace: Path, tool: str) -> dict | None:
    try:
        return json.loads(record_path(workspace, tool).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def save_record(workspace: Path, tool: str, process: subprocess.Popen, command: list[str], log: Path) -> dict:
    record = {"tool": tool, "pid": process.pid, "start_time": start_time(process.pid), "command": command,
              "log": str(log), "started": utc_now(), "started_by": "lopodev"}
    path = record_path(workspace, tool)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(record, indent=2) + "\n", encoding="utf-8")
    return record


def launch(workspace: Path, tool: str, command: list[str], env: dict | None = None) -> dict:
    log = workspace / ".lopodev/live" / f"{tool}.log"
    log.parent.mkdir(parents=True, exist_ok=True)
    with log.open("ab") as handle:
        process = subprocess.Popen(command, stdout=handle, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL,
                                   start_new_session=True, env={**os.environ, **(env or {})})
    return save_record(workspace, tool, process, command, log)


def port_open(port: int, host: str = "127.0.0.1") -> bool:
    try:
        with socket.create_connection((host, port), timeout=0.5):
            return True
    except OSError:
        return False


# ---------------------------------------------------------------- tools

def find_blender() -> str | None:
    configured = os.environ.get("BLENDER")
    if configured and Path(configured).is_file():
        return configured
    return shutil.which("blender") or ("/snap/bin/blender" if Path("/snap/bin/blender").exists() else None)


def start_blender(workspace: Path, blend: Path | None = None) -> dict:
    existing = load_record(workspace, "blender")
    if existing and owned(existing):
        return {"status": "RUNNING", "owned": True, **existing}
    if port_open(BLENDER_MCP_PORT):
        return {"status": "REUSED", "owned": False,
                "detail": f"a Blender MCP server already listens on {BLENDER_MCP_PORT}; using that Blender"}
    if not has_display():
        return {"status": "NOT RUN", "detail": "no display; headless tools are used instead"}
    blender = find_blender()
    if not blender:
        return {"status": "FAIL", "detail": "Blender not found (set BLENDER)"}
    # The MCP add-on (enabled by `lopodev setup`) auto-starts its server in a GUI session.
    command = [blender, *([str(blend)] if blend else [])]
    record = launch(workspace, "blender", command)
    for _ in range(60):
        if port_open(BLENDER_MCP_PORT):
            return {"status": "STARTED", "owned": True, "mcp": "listening", **record}
        time.sleep(0.5)
    return {"status": "STARTED", "owned": True, "mcp": "not listening (is the add-on enabled? run `lopodev setup`)",
            **record}


def start_godot(workspace: Path, godot_dir: Path) -> dict:
    existing = load_record(workspace, "godot")
    if existing and owned(existing):
        return {"status": "RUNNING", "owned": True, **existing}
    if not has_display():
        return {"status": "NOT RUN", "detail": "no display"}
    godot = integrations.pinned_godot(ROOT)
    if not godot:
        return {"status": "FAIL", "detail": "Godot not found (set GODOT)"}
    return {"status": "STARTED", "owned": True, **launch(workspace, "godot", [godot, "-e", "--path", str(godot_dir)])}


def run_godot(workspace: Path, godot_dir: Path, scene: str | None, seconds: float, screenshot: Path | None) -> dict:
    """Show the game in a window for a bounded time, optionally capturing a frame."""
    if not has_display():
        return {"status": "NOT RUN", "detail": "no display"}
    godot = integrations.pinned_godot(ROOT)
    if not godot:
        return {"status": "FAIL", "detail": "Godot not found (set GODOT)"}
    command = [godot, "--path", str(godot_dir)]
    if screenshot:
        stage = godot_dir / ".pipeline"
        stage.mkdir(parents=True, exist_ok=True)
        shutil.copy2(ROOT / "tools/godot/checks/screenshot.gd", stage / "screenshot.gd")
        command += ["--script", "res://.pipeline/screenshot.gd"]
        # screenshot.gd quits after SCREENSHOT_FRAMES; keep the window up for `seconds`.
        env = {"SCREENSHOT_PATH": str(screenshot.resolve()), "SCREENSHOT_FRAMES": str(max(20, int(seconds * 60)))}
        if scene:
            env["SCENE_PATH"] = scene
    else:
        command += [scene] if scene else []
        env = {}
    record = launch(workspace, "godot-run", command, env)
    deadline = time.time() + seconds + (30 if screenshot else 0)
    while time.time() < deadline and owned(record):
        time.sleep(0.25)
    still = owned(record)
    if still:
        stop(workspace, "godot-run")
    result = {"status": "PASS", "seconds": seconds, "log": record["log"]}
    if screenshot:
        result["screenshot"] = str(screenshot)
        result["status"] = "PASS" if screenshot.is_file() and screenshot.stat().st_size > 0 else "FAIL"
    return result


def stop(workspace: Path, tool: str) -> dict:
    record = load_record(workspace, tool)
    path = record_path(workspace, tool)
    if record is None:
        return {"tool": tool, "status": "NONE"}
    if not owned(record):
        path.unlink(missing_ok=True)
        return {"tool": tool, "status": "STALE", "detail": "process already gone or not ours; record removed"}
    pid = record["pid"]
    if tool == "emulator":
        adb = shutil.which("adb") or str(Path(os.environ.get("ANDROID_SDK_ROOT", Path.home() / "Android/Sdk"))
                                          / "platform-tools/adb")
        subprocess.run([adb, "-s", record.get("serial", "emulator-5554"), "emu", "kill"], capture_output=True,
                       check=False, timeout=30)
    else:
        try:
            os.killpg(pid, signal.SIGTERM)  # its own session: closes child processes too
        except (ProcessLookupError, PermissionError):
            pass
    for _ in range(40):
        if not owned(record):
            break
        time.sleep(0.25)
    if owned(record):
        try:
            os.killpg(pid, signal.SIGKILL)
        except (ProcessLookupError, PermissionError):
            pass
    path.unlink(missing_ok=True)
    return {"tool": tool, "status": "STOPPED", "pid": pid}


def status(workspace: Path) -> list[dict]:
    rows = []
    for tool in TOOLS:
        record = load_record(workspace, tool)
        if record:
            rows.append({"tool": tool, "pid": record["pid"], "owned_and_running": owned(record),
                         "started": record.get("started")})
    return rows


def project_godot_dir(project: Path) -> Path:
    import validate_spec
    spec = json.loads((project / "project.json").read_text(encoding="utf-8"))
    return validate_spec._godot_dir(spec.get("godot_dir", "godot"), project.resolve())


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="lopodev live", description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--workspace", type=Path, default=Path("."))
    sub = parser.add_subparsers(dest="command", required=True)
    mode = sub.add_parser("mode")
    mode.add_argument("value", nargs="?", choices=MODES)
    start = sub.add_parser("start")
    start.add_argument("tool", choices=("blender", "godot"))
    start.add_argument("--blend", type=Path)
    start.add_argument("--project", type=Path)
    run = sub.add_parser("run")
    run.add_argument("tool", choices=("godot",))
    run.add_argument("--project", type=Path, required=True)
    run.add_argument("--scene")
    run.add_argument("--seconds", type=float, default=8.0)
    run.add_argument("--screenshot", type=Path)
    sub.add_parser("status")
    stopper = sub.add_parser("stop")
    stopper.add_argument("tool", nargs="?", default="all", choices=(*TOOLS, "all"))
    args = parser.parse_args(argv)
    workspace = args.workspace.resolve()
    if args.command == "mode":
        if args.value:
            previous = set_mode(workspace, args.value)
            print(f"LIVE_MODE={args.value} (was {previous})")
        else:
            print(f"LIVE_MODE={current_mode(workspace)} display={'yes' if has_display() else 'no'} "
                  f"active={'yes' if enabled(workspace) else 'no'}")
        return 0
    if args.command == "status":
        rows = status(workspace)
        for row in rows:
            print(f"{row['tool']:10} pid={row['pid']} running={row['owned_and_running']} since={row['started']}")
        if not rows:
            print("no LopoDev-owned live sessions")
        return 0
    if args.command == "stop":
        for tool in (TOOLS if args.tool == "all" else (args.tool,)):
            result = stop(workspace, tool)
            if result["status"] != "NONE":
                print(f"{result['status']} {tool} {result.get('detail', '')}".rstrip())
        return 0
    if args.command == "start":
        if args.tool == "blender":
            result = start_blender(workspace, args.blend)
        else:
            if not args.project:
                parser.error("start godot needs --project")
            result = start_godot(workspace, project_godot_dir(args.project))
    else:
        result = run_godot(workspace, project_godot_dir(args.project), args.scene, args.seconds, args.screenshot)
    print(json.dumps({k: v for k, v in result.items() if k != "command"}, indent=2))
    return 0 if result["status"] in ("STARTED", "RUNNING", "REUSED", "PASS", "NOT RUN") else 1


if __name__ == "__main__":
    raise SystemExit(main())
