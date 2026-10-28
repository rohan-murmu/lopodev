#!/usr/bin/env python3
"""Call one tool on an installed MCP server over stdio and report the result.

Configuration that merely lists a server proves nothing; this performs the
MCP handshake, lists the tools, and makes one real, read-only call:

  python3 tools/mcp_probe.py godot   # get_godot_version
  python3 tools/mcp_probe.py codemap # first read-only tool listed
  python3 tools/mcp_probe.py blender # get_scene_info (needs Blender + addon)
"""

from __future__ import annotations

import argparse
import json
import os
import selectors
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import integrations  # noqa: E402

# One read-only call per server; "{cwd}" is replaced with the workspace path.
READ_ONLY_CALLS = {
    "godot": ("get_godot_version", {}),
    "blender": ("get_scene_info", {}),
    "codemap": ("get_structure", {"path": "{cwd}"}),
}
# Some servers report failures as ordinary text instead of isError.
ERROR_PREFIXES = ("error", "could not", "failed", "exception")
# Failures caused by a missing runtime (not by LopoDev or the server).
ENVIRONMENT_MARKERS = ("could not connect to blender", "make sure the blender addon is running")


class StdioClient:
    def __init__(self, command: list[str], env: dict, cwd: Path) -> None:
        self.process = subprocess.Popen(command, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                        stderr=subprocess.PIPE, env=env, cwd=cwd, text=True)
        self.selector = selectors.DefaultSelector()
        self.selector.register(self.process.stdout, selectors.EVENT_READ)
        self.next_id = 1

    def request(self, method: str, params: dict, timeout: float = 60.0) -> dict:
        request_id = self.next_id
        self.next_id += 1
        self.send({"jsonrpc": "2.0", "id": request_id, "method": method, "params": params})
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if not self.selector.select(timeout=max(0.0, deadline - time.monotonic())):
                break
            line = self.process.stdout.readline()
            if not line:
                break
            try:
                message = json.loads(line)
            except json.JSONDecodeError:
                continue  # servers may log to stdout before speaking JSON-RPC
            if message.get("id") == request_id:
                return message
        raise TimeoutError(f"no response to {method} within {timeout:.0f}s")

    def send(self, payload: dict) -> None:
        self.process.stdin.write(json.dumps(payload) + "\n")
        self.process.stdin.flush()

    def close(self) -> str:
        self.process.terminate()
        try:
            _, stderr = self.process.communicate(timeout=10)
        except subprocess.TimeoutExpired:
            self.process.kill()
            _, stderr = self.process.communicate()
        return stderr or ""


def probe(root: Path, server: str, cwd: Path) -> dict:
    command, extra_env = integrations.server_command(root, server)
    env = dict(os.environ)
    for key, value in extra_env.items():
        env.setdefault(key, value)
    client = StdioClient(command, env, cwd)
    result: dict = {"server": server, "command": command}
    try:
        init = client.request("initialize", {"protocolVersion": "2025-06-18", "capabilities": {},
                                             "clientInfo": {"name": "lopodev-probe", "version": "1"}})
        result["server_info"] = init.get("result", {}).get("serverInfo", {})
        client.send({"jsonrpc": "2.0", "method": "notifications/initialized"})
        tools = client.request("tools/list", {}).get("result", {}).get("tools", [])
        result["tools"] = sorted(tool["name"] for tool in tools)
        name, template = READ_ONLY_CALLS[server]
        arguments = {key: value.replace("{cwd}", str(cwd)) if isinstance(value, str) else value
                     for key, value in template.items()}
        if name not in result["tools"]:
            result.update(status="FAIL", detail=f"tool {name!r} not offered")
            return result
        response = client.request("tools/call", {"name": name, "arguments": arguments}, timeout=90)
        payload = response.get("result") or {}
        text = " ".join(part.get("text", "") for part in payload.get("content", []) if isinstance(part, dict))
        lowered = text.strip().lower()
        failed = (bool(payload.get("isError")) or "error" in response
                  or lowered.startswith(ERROR_PREFIXES))
        status = "PASS"
        if failed:
            status = "NOT RUN" if any(marker in lowered for marker in ENVIRONMENT_MARKERS) else "FAIL"
        result.update(call=name, status=status,
                      detail=(text or json.dumps(response.get("error", {})))[:400])
        return result
    except (TimeoutError, OSError, ValueError) as exc:
        result.update(status="FAIL", detail=str(exc))
        return result
    finally:
        stderr = client.close()
        if result.get("status") != "PASS":
            result["stderr_tail"] = stderr.strip().splitlines()[-5:]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("server", choices=sorted(READ_ONLY_CALLS))
    parser.add_argument("--cwd", default=".", help="working directory for the server (a workspace)")
    args = parser.parse_args(argv)
    root = Path(__file__).resolve().parent.parent
    try:
        result = probe(root, args.server, Path(args.cwd).resolve())
    except (FileNotFoundError, KeyError) as exc:
        print(f"MCP_PROBE {args.server}=NOT RUN ({exc})")
        return 3
    print(json.dumps(result, indent=2))
    print(f"MCP_PROBE {args.server}={result['status']}")
    return {"PASS": 0, "NOT RUN": 3}.get(result["status"], 1)


if __name__ == "__main__":
    raise SystemExit(main())
