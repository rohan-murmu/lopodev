"""Tests for the non-destructive workspace bootstrap."""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

TOOLKIT = Path(__file__).resolve().parents[2]
SCRIPT = TOOLKIT / "tools" / "bootstrap_project.py"


class BootstrapProjectTests(unittest.TestCase):
    def test_bootstraps_workspace_layout_and_state(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            workspace = Path(temp) / "my_game_workspace"
            result = subprocess.run(
                [sys.executable, str(SCRIPT), "--workspace", str(workspace),
                 "--slug", "test_game", "--title", "Test Game"],
                capture_output=True, text=True, check=False,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn("PROJECT_BOOTSTRAPPED=", result.stdout)
            project = workspace / "projects" / "test_game"
            for relative in ("project.json", "GAME_SPEC.md", "ASSET_LICENSES.md",
                             "pipeline_state.json", "godot/project.godot",
                             "godot/export_presets.cfg"):
                self.assertTrue((project / relative).is_file(), relative)
            self.assertTrue((workspace / "tools").is_symlink())
            self.assertTrue((workspace / "AGENTS.md").is_symlink())
            data = json.loads((project / "pipeline_state.json").read_text())
            self.assertEqual(data["slug"], "test_game")
            self.assertEqual(data["current_gate"], "A")
            self.assertEqual(data["gates"]["A"]["status"], "pending")

    def test_refuses_to_overwrite_existing_project(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            workspace = Path(temp)
            command = [sys.executable, str(SCRIPT), "--workspace", str(workspace),
                       "--slug", "test_game", "--title", "Test Game"]
            first = subprocess.run(command, capture_output=True, text=True,
                                   check=False)
            self.assertEqual(first.returncode, 0, first.stderr)
            second = subprocess.run(command, capture_output=True, text=True,
                                    check=False)
            self.assertEqual(second.returncode, 2)
            self.assertIn("refusing to overwrite", second.stderr)


if __name__ == "__main__":
    unittest.main()
