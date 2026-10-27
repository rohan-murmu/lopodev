"""End-to-end stdio protocol test; skipped unless the official MCP SDK is installed."""

from __future__ import annotations

import asyncio
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

try:
    from mcp import Client, StdioServerParameters
except ImportError:
    Client = None
    StdioServerParameters = None

ROOT = Path(__file__).resolve().parents[2]


@unittest.skipIf(Client is None, "optional official MCP SDK is not installed")
class McpProtocolTests(unittest.TestCase):
    def test_server_lists_tools_and_handles_scoped_status_call(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            workspace = Path(temporary)
            project = workspace / "projects" / "mcp_test"
            project.mkdir(parents=True)
            now = "2026-10-26T00:00:00+00:00"
            state = {
                "schema_version": 1, "slug": "mcp_test", "title": "MCP test",
                "workspace": str(workspace), "project_dir": str(project),
                "created_at_utc": now, "updated_at_utc": now, "current_gate": "A",
                "gates": {gate: {"name": gate, "status": "pending", "revision": 0,
                                 "proposed_at_utc": None, "approved_at_utc": None,
                                 "rejected_at_utc": None, "reopened_at_utc": None,
                                 "user_statement": "", "reason": "", "skip_reason": "",
                                 "note": "", "evidence": []}
                          for gate in "ABCDEF"},
                "tasks": [], "assets": [], "tests": [], "approvals": [],
                "rejections": [], "reopenings": [], "issues": [],
                "recovery": {"next_step": "plan game", "last_command": "", "notes": []},
            }
            (project / "pipeline_state.json").write_text(json.dumps(state))
            environment = {}
            if os.environ.get("PYTHONPATH"):
                environment["PYTHONPATH"] = os.environ["PYTHONPATH"]
            server = StdioServerParameters(
                command=sys.executable,
                args=[str(ROOT / "tools/mcp_server.py"), "--root", str(workspace)],
                env=environment,
            )

            async def exercise() -> None:
                async with Client(server) as client:
                    tools = await client.list_tools()
                    self.assertEqual({tool.name for tool in tools.tools}, {
                        "lopodev_status", "lopodev_next", "lopodev_validate",
                        "lopodev_context", "lopodev_checkpoint",
                        "lopodev_android_export",
                    })
                    result = await client.call_tool("lopodev_status", {"slug": "mcp_test"})
                    self.assertFalse(result.is_error)
                    self.assertTrue(any("mcp_test" in item.text for item in result.content
                                        if getattr(item, "text", None)))
                    with self.assertRaises(Exception) as error:
                        await client.call_tool("lopodev_status", {"slug": "../escape"})
                    self.assertIn("snake_case", str(error.exception))

            asyncio.run(exercise())


if __name__ == "__main__":
    unittest.main()
