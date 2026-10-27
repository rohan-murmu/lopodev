"""Tests for agent adapters, MCP scoping, and Homebrew formula metadata handling."""

from __future__ import annotations

import json
import hashlib
import os
import shutil
import subprocess
import struct
import sys
import tempfile
import unittest
from pathlib import Path
import zlib

TOOLS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(TOOLS))

import homebrew_formula  # noqa: E402
import loopdev_cli  # noqa: E402
import mcp_server  # noqa: E402
import pipeline_state  # noqa: E402
import sanitize_local_paths  # noqa: E402


class AdapterTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.workspace = Path(self.temp.name) / "workspace"
        self.workspace.mkdir()
        self.project = self.workspace / "projects" / "test_game"
        self.project.mkdir(parents=True)
        self.state = pipeline_state.new_state("test_game", "Test Game",
                                              str(self.workspace), str(self.project))
        self.state["tasks"] = [
            {"id": "T1", "title": "Plan", "status": "verified", "depends_on": []},
            {"id": "T2", "title": "Build", "status": "planned", "depends_on": ["T1"]},
        ]
        pipeline_state.save_state(str(self.project), self.state)
        (self.project / "project.json").write_text(json.dumps({
            "schema_version": 1, "slug": "test_game", "title": "Test Game",
            "summary": "test", "status": "draft", "target_platform": "linux",
            "engine": {"name": "godot", "version": "4.6.1"},
            "blender": {"version": "5.2.2"}, "main_scene": "res://scenes/Main.tscn",
            "godot_dir": str(self.project / "godot"), "assets": [],
            "tasks": [{"id": "T1", "title": "Plan", "skills": ["game-planner"],
                       "depends_on": [], "verify": "review", "status": "planned"}],
            "acceptance": [{"id": "A1", "criterion": "reviewed", "gate": "manual",
                            "evidence": "artifacts/qa_report.json"}],
            "known_limitations": [], "adoption": {},
        }))
        (self.project / "GAME_SPEC.md").write_text("spec")
        (self.project / "godot/scenes").mkdir(parents=True)
        (self.project / "godot/scenes/Main.tscn").write_text("[gd_scene format=3]\n")

    def tearDown(self) -> None:
        self.temp.cleanup()

    def test_kilo_installer_is_idempotent_and_links_canonical_skills(self) -> None:
        first = loopdev_cli.install_kilo(loopdev_cli.toolkit_root(), self.workspace, False)
        second = loopdev_cli.install_kilo(loopdev_cli.toolkit_root(), self.workspace, False)
        self.assertTrue(any("LINKED" in item for item in first))
        self.assertFalse(any(item.startswith(("LINKED ", "WROTE ")) for item in second))
        self.assertTrue((self.workspace / ".kilo/agents/loopdev.md").is_file())
        skill = self.workspace / ".agents/skills/game-planner/SKILL.md"
        self.assertTrue(skill.is_file())
        self.assertEqual(skill.resolve(), (loopdev_cli.toolkit_root() /
                                           ".opencode/skills/game-planner/SKILL.md").resolve())

    @unittest.skipUnless(shutil.which("kilo"), "Kilo CLI is not installed")
    def test_kilo_cli_discovers_installed_native_agents(self) -> None:
        loopdev_cli.install_kilo(loopdev_cli.toolkit_root(), self.workspace, False)
        result = subprocess.run([shutil.which("kilo"), "agent", "list"], cwd=self.workspace,
                                text=True, capture_output=True, timeout=30, check=False)
        self.assertEqual(result.returncode, 0, result.stderr[-2000:])
        for name in ("loopdev", "game-design", "modeling", "animation", "level-design",
                     "gameplay", "ui", "optimization", "qa-release"):
            self.assertIn(name, result.stdout)
        # Kilo's debug skill command requires KILO_CONFIG_DIR to discover project skills
        env = dict(subprocess.os.environ, KILO_CONFIG_DIR=str(self.workspace / ".kilo"))
        skills = subprocess.run([shutil.which("kilo"), "debug", "skill"], cwd=self.workspace,
                                text=True, capture_output=True, timeout=30, check=False, env=env)
        self.assertEqual(skills.returncode, 0, skills.stderr[-2000:])
        for name in ("game-planner", "lopodev-workflow", "blender-modeling", "blender-animation",
                     "game-world", "godot-gameplay", "game-qa", "mobile-low-poly"):
            self.assertIn(name, skills.stdout)

    def test_uninstall_removes_unchanged_managed_files_but_keeps_user_edits(self) -> None:
        root = loopdev_cli.toolkit_root()
        messages = loopdev_cli.install_kilo(root, self.workspace, False)
        loopdev_cli.record_created(self.workspace, "kilo", messages)
        agent_file = self.workspace / ".kilo/agents/loopdev.md"
        agent_file.write_text(agent_file.read_text() + "\nuser edit\n")
        removed = loopdev_cli.uninstall_target(self.workspace, "kilo", False)
        self.assertFalse((self.workspace / ".agents/skills/game-planner").is_symlink())
        self.assertTrue(agent_file.is_file())
        self.assertTrue(any(item.startswith("PRESERVED ") for item in removed))
        manifest = json.loads(loopdev_cli.manifest_path(self.workspace).read_text())
        self.assertIn(".kilo/agents/loopdev.md", manifest["files"])

    def test_shared_links_are_retained_until_last_adapter_is_uninstalled(self) -> None:
        root = loopdev_cli.toolkit_root()
        for target, installer in (("kilo", loopdev_cli.install_kilo),
                                  ("cursor", loopdev_cli.install_cursor)):
            loopdev_cli.record_created(self.workspace, target,
                                       installer(root, self.workspace, False))
        loopdev_cli.uninstall_target(self.workspace, "kilo", False)
        self.assertTrue((self.workspace / "tools").is_symlink())
        self.assertTrue((self.workspace / ".agents/skills/game-planner").is_symlink())
        loopdev_cli.uninstall_target(self.workspace, "cursor", False)
        self.assertFalse((self.workspace / "tools").is_symlink())
        self.assertFalse((self.workspace / ".agents/skills/game-planner").is_symlink())

    def test_cursor_refuses_to_overwrite_custom_rule(self) -> None:
        target = self.workspace / ".cursor/rules/loopdev.mdc"
        target.parent.mkdir(parents=True)
        target.write_text("user rule")
        with self.assertRaises(FileExistsError):
            loopdev_cli.install_cursor(loopdev_cli.toolkit_root(), self.workspace, False)
        self.assertEqual(target.read_text(), "user rule")

    def test_install_refuses_paths_routed_through_external_symlink(self) -> None:
        with tempfile.TemporaryDirectory() as outside:
            (self.workspace / ".cursor").symlink_to(outside, target_is_directory=True)
            with self.assertRaises(ValueError):
                loopdev_cli.install_cursor(loopdev_cli.toolkit_root(), self.workspace, False)
            self.assertEqual(list(Path(outside).iterdir()), [])

    def test_cursor_installs_native_subagents_and_shared_skills(self) -> None:
        root = loopdev_cli.toolkit_root()
        first = loopdev_cli.install_cursor(root, self.workspace, False)
        second = loopdev_cli.install_cursor(root, self.workspace, False)
        self.assertTrue(any("LINKED" in item for item in first))
        self.assertFalse(any(item.startswith(("LINKED ", "WROTE ")) for item in second))
        self.assertTrue((self.workspace / ".cursor/agents/qa-release.md").is_file())
        self.assertTrue((self.workspace / ".agents/skills/game-qa/SKILL.md").is_file())

    def test_opencode_dry_run_does_not_write(self) -> None:
        loopdev_cli.install_opencode(loopdev_cli.toolkit_root(), self.workspace, True)
        self.assertFalse((self.workspace / ".opencode").exists())
        self.assertFalse((self.workspace / "opencode.json").exists())

    def test_opencode_installs_complete_native_layout_and_preserves_user_config(self) -> None:
        (self.workspace / "AGENTS.md").write_text("user instructions")
        original_config = '{"default_agent":"custom","model":"keep"}\n'
        (self.workspace / "opencode.json").write_text(original_config)
        messages = loopdev_cli.install_opencode(loopdev_cli.toolkit_root(), self.workspace, False)
        self.assertTrue(any(item.startswith("LINKED ") and ".opencode" in item for item in messages))
        self.assertTrue((self.workspace / "tools/pipeline_state.py").is_file())
        self.assertTrue((self.workspace / "templates/GAME_SPEC.md").is_file())
        self.assertEqual((self.workspace / "AGENTS.md").read_text(), "user instructions")
        self.assertEqual((self.workspace / "opencode.json").read_text(), original_config)

    def test_mcp_registration_is_idempotent_and_does_not_touch_client_config(self) -> None:
        unrelated = self.workspace / "mcp.json"
        unrelated.write_text('{"mcpServers":{"codemap":{}}}\n')
        root = loopdev_cli.toolkit_root()
        first = loopdev_cli.install_mcp(root, self.workspace, False)
        second = loopdev_cli.install_mcp(root, self.workspace, False)
        self.assertIn("WROTE", first[0])
        self.assertIn("UNCHANGED", second[0])
        self.assertEqual(unrelated.read_text(), '{"mcpServers":{"codemap":{}}}\n')
        config = json.loads((self.workspace / ".loopdev/mcp-server.json").read_text())
        self.assertEqual(config["mcpServers"]["loopdev"]["args"][-1], str(self.workspace))

    def test_mcp_tools_scope_project_and_checkpoint(self) -> None:
        self.assertEqual(mcp_server.status(self.workspace, "test_game")["slug"], "test_game")
        self.assertEqual(mcp_server.next_task(self.workspace, "test_game")["id"], "T2")
        result = mcp_server.checkpoint(self.workspace, "test_game", "resume asset validation")
        self.assertEqual(result["checkpoint"], "saved")
        self.assertEqual(pipeline_state.load_state(str(self.project))["recovery"]["next_step"],
                         "resume asset validation")
        with self.assertRaises(ValueError):
            mcp_server.project_path(self.workspace, "../outside")
        with self.assertRaises(ValueError):
            mcp_server.checkpoint(self.workspace, "test_game", " ")

    def test_homebrew_formula_requires_realistic_metadata_fields(self) -> None:
        formula = homebrew_formula.render(
            "1.2.3", "a" * 64, "MIT")
        self.assertIn('version "1.2.3"', formula)
        self.assertIn('url "https://github.com/rohan-murmu/lopodev/releases/download/v1.2.3/loopdev-1.2.3.tar.gz"', formula)
        self.assertIn('sha256 "' + "a" * 64 + '"', formula)
        with self.assertRaises(ValueError):
            homebrew_formula.render("1.2.3", "fake", "MIT")
        with self.assertRaises(ValueError):
            homebrew_formula.render("1.2.3", "a" * 64, "not a license")

    def test_homebrew_formula_cli_hashes_the_exact_archive(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            archive = Path(temporary) / "loopdev-1.2.3.tar.gz"
            content = b"versioned release archive test bytes"
            archive.write_bytes(content)
            output = Path(temporary) / "loopdev.rb"
            result = subprocess.run([
                sys.executable, str(TOOLS / "homebrew_formula.py"),
                "--version", "1.2.3", "--archive-file", str(archive),
                "--license", "MIT", "--output", str(output),
            ], text=True, capture_output=True, check=False)
            self.assertEqual(result.returncode, 0, result.stderr)
            digest = hashlib.sha256(content).hexdigest()
            self.assertIn(f'ARCHIVE_SHA256={digest}', result.stdout)
            self.assertIn(f'sha256 "{digest}"', output.read_text())

    def test_path_sanitizer_removes_local_path_from_png_text_without_changing_pixels(self) -> None:
        signature = sanitize_local_paths.PNG_SIGNATURE

        def chunk(kind: bytes, payload: bytes) -> bytes:
            body = kind + payload
            return struct.pack(">I", len(payload)) + body + struct.pack(">I", zlib.crc32(body))

        png = (signature + chunk(b"IHDR", b"header")
               + chunk(b"tEXt", b"Source\x00/media/owner/work/game.blend")
               + chunk(b"IDAT", b"pixel bytes stay") + chunk(b"IEND", b""))
        cleaned, changed = sanitize_local_paths.sanitize_png(png)
        self.assertTrue(changed)
        self.assertNotIn(b"/media/owner", cleaned)
        self.assertIn(chunk(b"IDAT", b"pixel bytes stay"), cleaned)
        self.assertEqual(sanitize_local_paths.sanitize_text("sdk=/Users/alice/Library/sdk"),
                         "sdk=<LOCAL_PATH>")

    def test_loopdev_launcher_loads_resources_outside_the_caller_directory(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            package = Path(temporary)
            (package / "tools").mkdir()
            (package / "tools/loopdev_cli.py").write_bytes((TOOLS / "loopdev_cli.py").read_bytes())
            (package / "VERSION").write_text("9.8.7-test\n")
            env = dict(os.environ, LOOPDEV_HOME=str(package))
            result = subprocess.run([str(TOOLS.parent / "bin/loopdev"), "--version"],
                                    cwd=temporary, env=env, text=True, capture_output=True,
                                    timeout=10, check=False)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(result.stdout.strip(), "loopdev 9.8.7-test")

    @unittest.skipUnless(shutil.which("brew"), "Homebrew CLI is not installed")
    def test_generated_formula_passes_homebrew_style_parser(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            formula = Path(temporary) / "loopdev.rb"
            formula.write_text(homebrew_formula.render("1.2.3", "a" * 64, "MIT"))
            result = subprocess.run([shutil.which("brew"), "style", str(formula)],
                                    text=True, capture_output=True, timeout=90, check=False)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)


if __name__ == "__main__":
    unittest.main()
