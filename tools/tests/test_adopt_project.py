"""Tests for non-destructive adoption of an existing Godot project."""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

TOOLKIT = Path(__file__).resolve().parents[2]
ADOPT = TOOLKIT / "tools" / "adopt_project.py"
VALIDATE = TOOLKIT / "tools" / "validate_spec.py"


class AdoptProjectTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.godot = self.root / "existing" / "godot"
        (self.godot / "scenes").mkdir(parents=True)
        (self.godot / "scripts").mkdir()
        (self.godot / "project.godot").write_text(
            'config_version=5\n\n[application]\n\n'
            'config/name="Existing Game"\n'
            'run/main_scene="res://scenes/World.tscn"\n'
            'config/features=PackedStringArray("4.6", "GL Compatibility")\n\n'
            '[rendering]\n\nrenderer/rendering_method="gl_compatibility"\n'
        )
        (self.godot / "scenes" / "World.tscn").write_text("[gd_scene format=3]\n")
        (self.godot / "scripts" / "player.gd").write_text("extends Node3D\n")
        (self.godot / "assets").mkdir()
        (self.godot / "assets" / "sm_rock.glb").write_bytes(b"glTF" + b"\0" * 12)
        (self.godot / "assets" / "sm_rock.meta.json").write_text(json.dumps({
            "mesh": {"triangles": 120}, "animated": False,
            "license": "CC0", "source": "fixture",
        }))
        self.project = self.root / "workspace" / "projects" / "existing"
        self.workspace = self.root / "workspace"
        self.workspace.mkdir(parents=True)
        self.before = (self.godot / "project.godot").read_text()

    def tearDown(self) -> None:
        self.temp.cleanup()

    def run_adopt(self) -> subprocess.CompletedProcess:
        return subprocess.run([
            sys.executable, str(ADOPT),
            "--godot-dir", str(self.godot),
            "--project", str(self.project),
            "--workspace", str(self.workspace),
            "--slug", "existing", "--title", "Existing Game",
        ], capture_output=True, text=True, check=False)

    def test_adopts_without_touching_game_files(self) -> None:
        result = self.run_adopt()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual((self.godot / "project.godot").read_text(), self.before)
        for relative in ("project.json", "GAME_SPEC.md", "ASSET_LICENSES.md",
                         "pipeline_state.json", "docs/ADOPTION_REPORT.md"):
            self.assertTrue((self.project / relative).is_file(), relative)
        spec = json.loads((self.project / "project.json").read_text())
        self.assertEqual(spec["status"], "adoption_pending")
        self.assertEqual(spec["main_scene"], "res://scenes/World.tscn")
        self.assertEqual(spec["godot_dir"], str(self.godot))
        self.assertEqual(spec["assets"][0]["id"], "sm_rock")
        self.assertTrue(spec["adoption"]["source_unchanged"])
        state = json.loads((self.project / "pipeline_state.json").read_text())
        self.assertEqual(len(state["tasks"]), 5)
        event = json.loads((self.project / "artifacts" / "events.jsonl").read_text())
        self.assertEqual(event["event"], "project_adopted")
        check = subprocess.run([sys.executable, str(VALIDATE), str(self.project / "project.json")],
                               capture_output=True, text=True, check=False)
        self.assertEqual(check.returncode, 0, check.stdout + check.stderr)
        self.assertIn("SPEC_CHECK=PASS", check.stdout)

    def test_refuses_to_overwrite_context(self) -> None:
        self.assertEqual(self.run_adopt().returncode, 0)
        result = self.run_adopt()
        self.assertEqual(result.returncode, 2)
        self.assertIn("refusing to overwrite", result.stderr)

    def test_rejects_non_godot_directory(self) -> None:
        empty = self.root / "empty"
        empty.mkdir()
        result = subprocess.run([
            sys.executable, str(ADOPT), "--godot-dir", str(empty),
            "--project", str(self.root / "other"), "--slug", "other",
            "--title", "Other",
        ], capture_output=True, text=True, check=False)
        self.assertEqual(result.returncode, 2)
        self.assertIn("not a readable Godot project", result.stderr)


if __name__ == "__main__":
    unittest.main()
