"""End-to-end stdio protocol test; skipped unless the official MCP SDK is installed."""

from __future__ import annotations

import asyncio
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import hermetic  # noqa: E402,F401  (no downloads, isolated user data)

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
            environment = {"LOPODEV_DATA": os.environ["LOPODEV_DATA"]}
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
                        "lopodev_android_export", "lopodev_task_brief",
                        "lopodev_knowledge_search", "lopodev_knowledge_show",
                    })
                    found = await client.call_tool("lopodev_knowledge_search",
                                                   {"query": "joystick touch", "engine_version": "4.6.1"})
                    self.assertFalse(found.is_error)
                    self.assertTrue(any("godot-mobile-touch-controls" in item.text
                                        for item in found.content if getattr(item, "text", None)))
                    brief = await client.call_tool("lopodev_task_brief", {"slug": "mcp_test"})
                    self.assertFalse(brief.is_error)
                    result = await client.call_tool("lopodev_status", {"slug": "mcp_test"})
                    self.assertFalse(result.is_error)
                    self.assertTrue(any("mcp_test" in item.text for item in result.content
                                        if getattr(item, "text", None)))
                    with self.assertRaises(Exception) as error:
                        await client.call_tool("lopodev_status", {"slug": "../escape"})
                    self.assertIn("snake_case", str(error.exception))

            asyncio.run(exercise())


class McpToolFunctionTests(unittest.TestCase):
    """The same tool bodies, exercised without the optional SDK."""

    def test_knowledge_and_brief_tools(self) -> None:
        sys.path.insert(0, str(ROOT / "tools"))
        import mcp_server

        with tempfile.TemporaryDirectory() as temporary:
            workspace = Path(temporary)
            (workspace / "projects/demo").mkdir(parents=True)
            (workspace / "projects/demo/project.json").write_text(json.dumps(
                {"title": "Demo", "genre": "shooter", "engine": {"version": "4.6.1"}}))
            found = mcp_server.knowledge_search(workspace, "pause menu back navigation",
                                                engine_version="4.6.1")
            self.assertEqual(found["results"][0]["id"], "godot-screen-router")
            shown = mcp_server.knowledge_show(workspace, "godot-screen-router")
            self.assertTrue(Path(shown["artifact_paths"][0]).is_file())
            brief = mcp_server.task_brief(workspace, "demo")
            self.assertIn("LopoDev context: demo", brief["brief"])
            with self.assertRaises(ValueError):
                mcp_server.task_brief(workspace, "../escape")


if __name__ == "__main__":
    unittest.main()
