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

sys.path.insert(0, str(Path(__file__).resolve().parent))
import hermetic  # noqa: E402,F401  (no downloads, isolated user data)

TOOLS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(TOOLS))

import homebrew_formula  # noqa: E402
import lopodev_cli  # noqa: E402
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
        first = lopodev_cli.install_kilo(lopodev_cli.toolkit_root(), self.workspace, False)
        second = lopodev_cli.install_kilo(lopodev_cli.toolkit_root(), self.workspace, False)
        self.assertTrue(any("LINKED" in item for item in first))
        self.assertFalse(any(item.startswith(("LINKED ", "WROTE ")) for item in second))
        self.assertTrue((self.workspace / ".kilo/agents/lopodev.md").is_file())
        skill = self.workspace / ".agents/skills/game-planner/SKILL.md"
        self.assertTrue(skill.is_file())
        self.assertEqual(skill.resolve(), (lopodev_cli.toolkit_root() /
                                           "resources/skills/game-planner/SKILL.md").resolve())

    def test_kilo_install_links_kilo_skills_and_uninstall_removes_them(self) -> None:
        root = lopodev_cli.toolkit_root()
        messages = lopodev_cli.install_kilo(root, self.workspace, False)
        lopodev_cli.record_created(self.workspace, "kilo", messages)
        kilo_skill = self.workspace / ".kilo/skills/game-planner"
        self.assertTrue(kilo_skill.is_symlink())
        self.assertEqual(kilo_skill.resolve(),
                         (root / "resources/skills/game-planner").resolve())
        removed = lopodev_cli.uninstall_target(self.workspace, "kilo", False)
        self.assertFalse(any("PRESERVED" in item for item in removed))
        self.assertFalse(kilo_skill.exists() or kilo_skill.is_symlink())
        self.assertFalse((self.workspace / ".kilo").exists())

    def test_adapter_sources_mirror_install_layout(self) -> None:
        root = lopodev_cli.toolkit_root()
        for relative in ("adapters/opencode/agents/lopodev.md",
                         "adapters/opencode/commands/lopodev.md",
                         "adapters/kilo/agents/lopodev.md",
                         "adapters/cursor/rules/lopodev.mdc",
                         "adapters/cursor/agents/qa-release.md",
                         "resources/skills/game-planner/SKILL.md"):
            self.assertTrue((root / relative).is_file(), relative)
    def test_opencode_generates_component_links_and_removes_them(self) -> None:
        root = lopodev_cli.toolkit_root()
        messages = lopodev_cli.install_opencode(root, self.workspace, False)
        lopodev_cli.record_created(self.workspace, "opencode", messages)
        opencode = self.workspace / ".opencode"
        self.assertTrue(opencode.is_dir() and not opencode.is_symlink())
        self.assertEqual((opencode / "agents").resolve(),
                         (root / "adapters/opencode/agents").resolve())
        self.assertEqual((opencode / "commands").resolve(),
                         (root / "adapters/opencode/commands").resolve())
        self.assertEqual((opencode / "skills/game-planner").resolve(),
                         (root / "resources/skills/game-planner").resolve())
        removed = lopodev_cli.uninstall_target(self.workspace, "opencode", False)
        self.assertFalse(any("PRESERVED" in item for item in removed))
        self.assertFalse(opencode.exists())

    def test_specialists_handle_direct_invocation(self) -> None:
        root = lopodev_cli.toolkit_root()
        for path in sorted((root / "adapters/opencode/agents").glob("*.md")):
            if path.stem == "lopodev":
                continue
            text = path.read_text()
            self.assertIn("## When you are invoked directly", text, path.name)
            self.assertIn("## Playbook", text, path.name)
            self.assertIn(f"--owner {path.stem}", text, path.name)
        for platform in ("kilo", "cursor"):
            for path in (root / f"adapters/{platform}/agents").glob("*.md"):
                if path.stem != "lopodev":
                    self.assertIn("invoked directly", path.read_text(), f"{platform}/{path.name}")

    def test_reinstall_replaces_links_to_renamed_skills(self) -> None:
        root = lopodev_cli.toolkit_root()
        old = self.workspace / ".opencode/skills/mobile-low-poly"  # pre-0.3 name
        old.parent.mkdir(parents=True)
        old.symlink_to(root / "resources/skills/mobile-low-poly", target_is_directory=True)  # pre-0.3 name
        user_link = self.workspace / ".opencode/skills/my-skill"
        user_link.symlink_to(self.workspace / "missing", target_is_directory=True)
        messages = lopodev_cli.install_opencode(root, self.workspace, False)
        self.assertTrue(any("renamed skill link" in m for m in messages))
        self.assertFalse(old.is_symlink())
        self.assertTrue(user_link.is_symlink(), "unrelated dangling user links are left alone")
        self.assertEqual((self.workspace / ".opencode/skills/mobile-game").resolve(),
                         (root / "resources/skills/mobile-game").resolve())

    def test_shared_contract_file_survives_uninstall_of_one_target(self) -> None:
        root = lopodev_cli.toolkit_root()
        for target, installer in (("opencode", lopodev_cli.install_opencode),
                                  ("kilo", lopodev_cli.install_kilo)):
            messages = installer(root, self.workspace, False)
            lopodev_cli.record_created(self.workspace, target, messages)
        agents = self.workspace / "AGENTS.md"
        self.assertTrue(agents.is_file())
        removed = lopodev_cli.uninstall_target(self.workspace, "opencode", False)
        self.assertFalse(any(str(agents) in item and "REMOVED" in item for item in removed))
        self.assertTrue(agents.is_file())
        manifest = lopodev_cli.load_manifest(self.workspace)
        self.assertEqual(manifest["files"]["AGENTS.md"]["owners"], ["kilo"])

    @unittest.skipUnless(shutil.which("kilo"), "Kilo CLI is not installed")
    def test_kilo_cli_discovers_installed_native_agents(self) -> None:
        lopodev_cli.install_kilo(lopodev_cli.toolkit_root(), self.workspace, False)
        result = subprocess.run([shutil.which("kilo"), "agent", "list"], cwd=self.workspace,
                                text=True, capture_output=True, timeout=30, check=False)
        self.assertEqual(result.returncode, 0, result.stderr[-2000:])
        for name in ("lopodev", "game-design", "modeling", "animation", "level-design",
                     "gameplay", "ui", "optimization", "qa-release"):
            self.assertIn(name, result.stdout)
        # Kilo's debug skill command requires KILO_CONFIG_DIR to discover project skills
        env = dict(subprocess.os.environ, KILO_CONFIG_DIR=str(self.workspace / ".kilo"))
        skills = subprocess.run([shutil.which("kilo"), "debug", "skill"], cwd=self.workspace,
                                text=True, capture_output=True, timeout=30, check=False, env=env)
        self.assertEqual(skills.returncode, 0, skills.stderr[-2000:])
        for name in ("game-planner", "lopodev-workflow", "blender-modeling", "blender-animation",
                     "game-world", "godot-gameplay", "game-qa", "mobile-game"):
            self.assertIn(name, skills.stdout)

    def test_uninstall_removes_unchanged_managed_files_but_keeps_user_edits(self) -> None:
        root = lopodev_cli.toolkit_root()
        messages = lopodev_cli.install_kilo(root, self.workspace, False)
        lopodev_cli.record_created(self.workspace, "kilo", messages)
        agent_file = self.workspace / ".kilo/agents/lopodev.md"
        agent_file.write_text(agent_file.read_text() + "\nuser edit\n")
        removed = lopodev_cli.uninstall_target(self.workspace, "kilo", False)
        self.assertFalse((self.workspace / ".agents/skills/game-planner").is_symlink())
        self.assertTrue(agent_file.is_file())
        self.assertTrue(any(item.startswith("PRESERVED ") for item in removed))
        manifest = json.loads(lopodev_cli.manifest_path(self.workspace).read_text())
        self.assertIn(".kilo/agents/lopodev.md", manifest["files"])

    def test_shared_links_are_retained_until_last_adapter_is_uninstalled(self) -> None:
        root = lopodev_cli.toolkit_root()
        for target, installer in (("kilo", lopodev_cli.install_kilo),
                                  ("cursor", lopodev_cli.install_cursor)):
            lopodev_cli.record_created(self.workspace, target,
                                       installer(root, self.workspace, False))
        lopodev_cli.uninstall_target(self.workspace, "kilo", False)
        self.assertTrue((self.workspace / "tools").is_symlink())
        self.assertTrue((self.workspace / ".agents/skills/game-planner").is_symlink())
        lopodev_cli.uninstall_target(self.workspace, "cursor", False)
        self.assertFalse((self.workspace / "tools").is_symlink())
        self.assertFalse((self.workspace / ".agents/skills/game-planner").is_symlink())

    def test_cursor_refuses_to_overwrite_custom_rule(self) -> None:
        target = self.workspace / ".cursor/rules/lopodev.mdc"
        target.parent.mkdir(parents=True)
        target.write_text("user rule")
        with self.assertRaises(FileExistsError):
            lopodev_cli.install_cursor(lopodev_cli.toolkit_root(), self.workspace, False)
        self.assertEqual(target.read_text(), "user rule")

    def test_install_refuses_paths_routed_through_external_symlink(self) -> None:
        with tempfile.TemporaryDirectory() as outside:
            (self.workspace / ".cursor").symlink_to(outside, target_is_directory=True)
            with self.assertRaises(ValueError):
                lopodev_cli.install_cursor(lopodev_cli.toolkit_root(), self.workspace, False)
            self.assertEqual(list(Path(outside).iterdir()), [])

    def test_cursor_installs_native_subagents_and_shared_skills(self) -> None:
        root = lopodev_cli.toolkit_root()
        first = lopodev_cli.install_cursor(root, self.workspace, False)
        second = lopodev_cli.install_cursor(root, self.workspace, False)
        self.assertTrue(any("LINKED" in item for item in first))
        self.assertFalse(any(item.startswith(("LINKED ", "WROTE ")) for item in second))
        self.assertTrue((self.workspace / ".cursor/agents/qa-release.md").is_file())
        self.assertTrue((self.workspace / ".agents/skills/game-qa/SKILL.md").is_file())

    def test_opencode_dry_run_does_not_write(self) -> None:
        lopodev_cli.install_opencode(lopodev_cli.toolkit_root(), self.workspace, True)
        self.assertFalse((self.workspace / ".opencode").exists())
        self.assertFalse((self.workspace / "opencode.json").exists())

    def test_opencode_installs_complete_native_layout_and_preserves_user_config(self) -> None:
        (self.workspace / "AGENTS.md").write_text("user instructions")
        original_config = '{"default_agent":"custom","model":"keep"}\n'
        (self.workspace / "opencode.json").write_text(original_config)
        messages = lopodev_cli.install_opencode(lopodev_cli.toolkit_root(), self.workspace, False)
        self.assertTrue(any(item.startswith("LINKED ") and ".opencode" in item for item in messages))
        self.assertTrue((self.workspace / "tools/pipeline_state.py").is_file())
        self.assertTrue((self.workspace / "templates/GAME_SPEC.md").is_file())
        self.assertEqual((self.workspace / "AGENTS.md").read_text(), "user instructions")
        # User values survive; LopoDev adds only the keys it manages and
        # keeps a backup of the original file.
        config = json.loads((self.workspace / "opencode.json").read_text())
        self.assertEqual(config["default_agent"], "custom")
        self.assertEqual(config["model"], "keep")
        self.assertTrue(any("PRESERVED opencode.json:default_agent" in m for m in messages))
        self.assertEqual(set(config["mcp"]), {"blender", "godot", "codemap"})
        self.assertIs(config["tools"]["blender_*"], False)
        self.assertEqual(config["permission"]["bash"]["git push*"], "ask")
        backups = list((self.workspace / ".lopodev/backups").glob("opencode.json.*"))
        self.assertEqual([b.read_text() for b in backups], [original_config])

    def test_mcp_registration_is_idempotent_and_does_not_touch_client_config(self) -> None:
        unrelated = self.workspace / "mcp.json"
        unrelated.write_text('{"mcpServers":{"codemap":{}}}\n')
        root = lopodev_cli.toolkit_root()
        first = lopodev_cli.install_mcp(root, self.workspace, False)
        second = lopodev_cli.install_mcp(root, self.workspace, False)
        self.assertIn("WROTE", first[0])
        self.assertIn("UNCHANGED", second[0])
        self.assertEqual(unrelated.read_text(), '{"mcpServers":{"codemap":{}}}\n')
        config = json.loads((self.workspace / ".lopodev/mcp-server.json").read_text())
        self.assertEqual(config["mcpServers"]["lopodev"]["args"][-1], str(self.workspace))

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
        self.assertIn('url "https://github.com/rohan-murmu/lopodev/releases/download/v1.2.3/lopodev-1.2.3.tar.gz"', formula)
        self.assertIn('sha256 "' + "a" * 64 + '"', formula)
        with self.assertRaises(ValueError):
            homebrew_formula.render("1.2.3", "fake", "MIT")
        with self.assertRaises(ValueError):
            homebrew_formula.render("1.2.3", "a" * 64, "not a license")

    def test_committed_formula_matches_generator(self) -> None:
        # Formula/lopodev.rb is generated; hand edits must go through the helper.
        self.assertEqual(homebrew_formula.check(TOOLS.parent / "Formula/lopodev.rb", "MIT"), [])
        with tempfile.TemporaryDirectory() as temporary:
            stable = Path(temporary) / "lopodev.rb"
            stable.write_text(homebrew_formula.render("1.2.3", "b" * 64, "MIT"))
            self.assertEqual(homebrew_formula.check(stable, "MIT"), [])
            stable.write_text(stable.read_text().replace("depends_on", "# depends_on"))
            self.assertTrue(homebrew_formula.check(stable, "MIT"))

    def test_formula_uses_stable_opt_paths_and_functional_test(self) -> None:
        for formula in (homebrew_formula.render(None, None, "MIT"),
                        homebrew_formula.render("1.2.3", "a" * 64, "MIT")):
            self.assertIn('export LOPODEV_HOME="#{opt_libexec}"', formula)
            self.assertIn('export LOPODEV_LAUNCHER="#{opt_bin}/lopodev"', formula)
            self.assertIn('export LOPODEV_BUILD="#{version}"', formula)
            self.assertIn('head "https://github.com/rohan-murmu/lopodev.git", branch: "main"', formula)
            self.assertIn("KNOWLEDGE_VALIDATE=PASS", formula)
            self.assertNotIn("/media/", formula)
            self.assertNotIn("/home/", formula)
        self.assertNotIn("sha256", homebrew_formula.render(None, None, "MIT"))

    def test_homebrew_formula_cli_hashes_the_exact_archive(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            archive = Path(temporary) / "lopodev-1.2.3.tar.gz"
            content = b"versioned release archive test bytes"
            archive.write_bytes(content)
            output = Path(temporary) / "lopodev.rb"
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
               + chunk(b"tEXt", b"Source\x00" + ("/" + "media/owner/work/game.blend").encode())
               + chunk(b"IDAT", b"pixel bytes stay") + chunk(b"IEND", b""))
        cleaned, changed = sanitize_local_paths.sanitize_png(png)
        self.assertTrue(changed)
        self.assertNotIn(("/" + "media/owner").encode(), cleaned)
        self.assertIn(chunk(b"IDAT", b"pixel bytes stay"), cleaned)
        self.assertEqual(sanitize_local_paths.sanitize_text("sdk=" + "/" + "Users/alice/Library/sdk"),
                         "sdk=<LOCAL_PATH>")

    def test_lopodev_launcher_loads_resources_outside_the_caller_directory(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            package = Path(temporary)
            (package / "tools").mkdir()
            for module in ("lopodev_cli.py", "approval.py", "integrations.py", "workspace_config.py"):
                (package / "tools" / module).write_bytes((TOOLS / module).read_bytes())
            (package / "VERSION").write_text("9.8.7-test\n")
            env = dict(os.environ, LOPODEV_HOME=str(package))
            result = subprocess.run([str(TOOLS.parent / "bin/lopodev"), "--version"],
                                    cwd=temporary, env=env, text=True, capture_output=True,
                                    timeout=10, check=False)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(result.stdout.strip(), "lopodev 9.8.7-test")

    @unittest.skipUnless(shutil.which("brew"), "Homebrew CLI is not installed")
    def test_generated_formula_passes_homebrew_style_parser(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            formula = Path(temporary) / "lopodev.rb"
            for text in (homebrew_formula.render("1.2.3", "a" * 64, "MIT"),
                         homebrew_formula.render(None, None, "MIT")):
                formula.write_text(text)
                # DuplicateMethods fires only because the real tap defines the
                # same Lopodev class when it is installed on this machine.
                result = subprocess.run([shutil.which("brew"), "style", "--except-cops",
                                         "Lint/DuplicateMethods", str(formula)],
                                        text=True, capture_output=True, timeout=90, check=False)
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)


if __name__ == "__main__":
    unittest.main()
