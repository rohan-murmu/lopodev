import hashlib
import io
import json
import os
import subprocess
import sys
import tarfile
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import hermetic  # noqa: E402,F401  (no downloads, isolated user data)

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))

import approval  # noqa: E402
import integrations  # noqa: E402
import lopodev_cli  # noqa: E402
import workspace_config  # noqa: E402


def make_archive(files: dict[str, str], extra: list[tarfile.TarInfo] | None = None) -> bytes:
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode="w:gz") as tar:
        for name, text in files.items():
            data = text.encode()
            info = tarfile.TarInfo(f"pack-abc/{name}")
            info.size = len(data)
            tar.addfile(info, io.BytesIO(data))
        for info in extra or []:
            tar.addfile(info)
    return buffer.getvalue()


class TempDataMixin:
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.previous = os.environ.get("LOPODEV_DATA")
        os.environ["LOPODEV_DATA"] = str(Path(self.temp.name) / "data")
        self.workspace = Path(self.temp.name) / "ws"
        self.workspace.mkdir()

    def tearDown(self) -> None:
        os.environ["LOPODEV_DATA"] = self.previous or ""
        self.temp.cleanup()


class SkillPackTests(TempDataMixin, unittest.TestCase):
    def pack(self, archive: bytes) -> dict:
        return {"repo": "x/y", "commit": "a" * 40, "sha256": hashlib.sha256(archive).hexdigest(),
                "skills_dir": "skills", "skills": ["demo-skill"]}

    def test_pack_installs_once_and_links_stable_skill_path(self) -> None:
        archive = make_archive({"skills/demo-skill/SKILL.md": "---\nname: demo-skill\n---\n"})
        calls = []

        def fetch(url: str) -> bytes:
            calls.append(url)
            return archive

        data = integrations.data_dir()
        first = integrations.install_skill_pack(data, "demo", self.pack(archive), False, fetch)
        second = integrations.install_skill_pack(data, "demo", self.pack(archive), False, fetch)
        self.assertEqual(len(calls), 1, "a verified pack must not be downloaded again")
        self.assertTrue(any(m.startswith("DOWNLOADED") for m in first))
        self.assertTrue(any(m.startswith("UNCHANGED skill pack") for m in second))
        self.assertTrue((data / "skills/demo-skill/SKILL.md").is_file())
        self.assertIn("codeload.github.com/x/y/tar.gz/" + "a" * 40, calls[0])

    def test_checksum_mismatch_is_rejected_without_installing(self) -> None:
        archive = make_archive({"skills/demo-skill/SKILL.md": "x"})
        pack = dict(self.pack(archive), sha256="0" * 64)
        with self.assertRaisesRegex(ValueError, "checksum mismatch"):
            integrations.install_skill_pack(integrations.data_dir(), "demo", pack, False, lambda _: archive)
        self.assertFalse((integrations.data_dir() / "skills/demo-skill").exists())

    def test_unsafe_archive_paths_are_rejected(self) -> None:
        evil = tarfile.TarInfo("pack-abc/../../escape.txt")
        evil.size = 0
        with self.assertRaisesRegex(ValueError, "unsafe archive member"):
            integrations.safe_extract(make_archive({}, [evil]), Path(self.temp.name) / "out")
        self.assertFalse((Path(self.temp.name) / "escape.txt").exists())

    def test_user_owned_skill_directory_is_never_replaced(self) -> None:
        archive = make_archive({"skills/demo-skill/SKILL.md": "x"})
        user_skill = integrations.data_dir() / "skills/demo-skill"
        user_skill.mkdir(parents=True)
        (user_skill / "SKILL.md").write_text("mine")
        with self.assertRaises(FileExistsError):
            integrations.install_skill_pack(integrations.data_dir(), "demo", self.pack(archive), False,
                                            lambda _: archive)
        self.assertEqual((user_skill / "SKILL.md").read_text(), "mine")

    def test_pinned_manifest_is_complete(self) -> None:
        spec = integrations.load_spec(ROOT)
        for name, pack in spec["skill_packs"].items():
            self.assertRegex(pack["commit"], r"^[0-9a-f]{40}$", name)
            self.assertRegex(pack["sha256"], r"^[0-9a-f]{64}$", name)
            self.assertEqual(pack["license"], "MIT", name)
            self.assertFalse(set(pack["skills"]) & set(pack["excluded"]), name)
        own = {p.name for p in (ROOT / "resources/skills").iterdir()}
        self.assertFalse(own & set(integrations.vendored_skills(ROOT)), "vendored skill shadows a LopoDev skill")
        for server in spec["mcp_servers"].values():
            self.assertTrue(server["version"])
            self.assertTrue(server["agents"])


class ServerTests(TempDataMixin, unittest.TestCase):
    def test_node_server_installs_pinned_version_and_is_idempotent(self) -> None:
        spec = integrations.load_spec(ROOT)["mcp_servers"]["godot"]
        commands = []

        def runner(command, **kwargs):
            commands.append(command)
            prefix = Path(command[command.index("--prefix") + 1])
            entry = prefix / "node_modules/@coding-solo/godot-mcp/build/index.js"
            entry.parent.mkdir(parents=True)
            entry.write_text("// server")
            return subprocess.CompletedProcess(command, 0, "", "")

        which = lambda name: f"/usr/bin/{name}"  # noqa: E731
        data = integrations.data_dir()
        self.assertIn("INSTALLED", integrations.install_node_server(data, "godot", spec, False, runner, which))
        self.assertIn("UNCHANGED", integrations.install_node_server(data, "godot", spec, False, runner, which))
        self.assertEqual(len(commands), 1)
        self.assertIn("@coding-solo/godot-mcp@0.1.1", commands[0])

    def test_failed_install_leaves_nothing_behind(self) -> None:
        spec = integrations.load_spec(ROOT)["mcp_servers"]["blender"]

        def runner(command, **kwargs):
            if "pip" in command:
                return subprocess.CompletedProcess(command, 1, "", "network down")
            Path(command[-1]).mkdir(parents=True, exist_ok=True)
            return subprocess.CompletedProcess(command, 0, "", "")

        with self.assertRaisesRegex(RuntimeError, "network down"):
            integrations.install_python_server(integrations.data_dir(), "blender", spec, False,
                                               runner, lambda name: f"/usr/bin/{name}")
        self.assertFalse(integrations.server_dir(integrations.data_dir(), "blender", spec).exists())

    def test_existing_user_binary_is_reported_not_replaced(self) -> None:
        spec = integrations.load_spec(ROOT)["mcp_servers"]["codemap"]

        def runner(command, **kwargs):
            self.assertEqual(command[-1], "--version")
            return subprocess.CompletedProcess(command, 0, "codemap 9.9.9\n", "")

        message = integrations.ensure_binary("codemap", spec, False, runner, lambda n: "/opt/codemap")
        self.assertIn("PRESENT codemap 9.9.9", message)
        self.assertIn("not enforced", message)

    def test_mcp_run_reports_missing_install(self) -> None:
        env = dict(os.environ, LOPODEV_DATA=os.environ["LOPODEV_DATA"])
        result = subprocess.run([str(ROOT / "bin/lopodev"), "mcp-run", "godot"], text=True,
                                capture_output=True, env=env, timeout=30, check=False)
        self.assertEqual(result.returncode, 2)
        self.assertIn("lopodev setup", result.stderr)

    def test_status_reports_missing_integrations_as_failures(self) -> None:
        rows = {check: result for check, result, _ in integrations.status(ROOT, None, live=False)}
        self.assertEqual(rows["mcp godot installed"], "FAIL")
        self.assertEqual(rows["vendored skill links"], "FAIL")
        self.assertIn(rows["blender addon socket"], {"PASS", "NOT RUN"})


class WorkspaceConfigTests(TempDataMixin, unittest.TestCase):
    def install(self) -> list[str]:
        messages = lopodev_cli.install_opencode(ROOT, self.workspace, False)
        lopodev_cli.record_created(self.workspace, "opencode", messages)
        return messages

    def config(self) -> dict:
        return json.loads((self.workspace / "opencode.json").read_text())

    def test_fresh_install_enables_all_integrations_through_launcher(self) -> None:
        self.install()
        config = self.config()
        for name in ("blender", "godot", "codemap"):
            self.assertEqual(config["mcp"][name]["command"][1:], ["mcp-run", name])
            self.assertTrue(config["mcp"][name]["enabled"])
        self.assertEqual(config["default_agent"], "lopodev")
        self.assertEqual(config["permission"], approval.policy("auto"))

    def test_reinstall_is_idempotent_and_upgrades_owned_keys(self) -> None:
        self.install()
        manifest = lopodev_cli.load_manifest(self.workspace)
        before = self.config()
        second = self.install()
        self.assertFalse(any(m.startswith(("SET", "UPDATED")) for m in second))
        self.assertEqual(self.config(), before)
        # A newer LopoDev changes a managed value: owned + unedited -> updated.
        desired = {"mcp.godot": dict(before["mcp"]["godot"], timeout=1234)}
        messages = workspace_config.merge(self.workspace, "opencode.json", desired, manifest, False)
        self.assertIn("UPDATED opencode.json:mcp.godot", messages)

    def test_user_edits_to_managed_keys_are_preserved_and_survive_uninstall(self) -> None:
        self.install()
        config = self.config()
        config["mcp"]["godot"]["environment"] = {"GODOT_PATH": "/my/godot"}
        config["model"] = "user-model"
        (self.workspace / "opencode.json").write_text(json.dumps(config))
        messages = self.install()
        self.assertTrue(any(m.startswith("PRESERVED opencode.json:mcp.godot") for m in messages))
        self.assertEqual(self.config()["mcp"]["godot"]["environment"], {"GODOT_PATH": "/my/godot"})
        removed = lopodev_cli.uninstall_target(self.workspace, "opencode", False)
        remaining = self.config()
        self.assertEqual(remaining["model"], "user-model")
        self.assertIn("godot", remaining["mcp"])
        self.assertNotIn("blender", remaining.get("mcp", {}))
        self.assertTrue(any("PRESERVED opencode.json:mcp.godot" in m for m in removed))

    def test_full_uninstall_removes_lopodev_config_entirely(self) -> None:
        self.install()
        lopodev_cli.uninstall_target(self.workspace, "opencode", False)
        self.assertFalse((self.workspace / "opencode.json").exists())
        self.assertFalse((self.workspace / ".opencode").exists())

    def test_legacy_blender_entry_migrates(self) -> None:
        legacy = {"$schema": "https://opencode.ai/config.json", "default_agent": "lopodev",
                  "mcp": {"blender": lopodev_cli.LEGACY_OPENCODE_VALUES["mcp.blender"][0]}}
        (self.workspace / "opencode.json").write_text(json.dumps(legacy))
        messages = self.install()
        self.assertIn("UPDATED opencode.json:mcp.blender", messages)
        self.assertEqual(self.config()["mcp"]["blender"]["command"][1:], ["mcp-run", "blender"])

    def test_approval_mode_switch_is_logged_and_consistent(self) -> None:
        self.install()
        cli = [str(ROOT / "bin/lopodev"), "approval"]
        run = lambda *a: subprocess.run([*cli, *a, "--project", str(self.workspace)],  # noqa: E731
                                        text=True, capture_output=True, timeout=30, check=False)
        self.assertIn("APPROVAL_MODE=auto", run().stdout)
        switched = run("manual")
        self.assertEqual(switched.returncode, 0, switched.stderr)
        self.assertEqual(self.config()["permission"], approval.policy("manual"))
        self.assertIn("APPROVAL_MODE=manual", run().stdout)
        # Reinstalling keeps the chosen mode instead of resetting to auto.
        self.install()
        self.assertEqual(self.config()["permission"], approval.policy("manual"))
        events = (self.workspace / ".lopodev/events.jsonl").read_text().splitlines()
        self.assertEqual(json.loads(events[-1])["to"], "manual")
        self.assertEqual(run("auto").returncode, 0)
        self.assertEqual(self.config()["permission"]["edit"], "allow")

    def test_user_permission_block_blocks_mode_switch(self) -> None:
        (self.workspace / "opencode.json").write_text(json.dumps({"permission": {"edit": "deny"}}))
        result = subprocess.run([str(ROOT / "bin/lopodev"), "approval", "auto", "--project",
                                 str(self.workspace)], text=True, capture_output=True, timeout=30, check=False)
        self.assertEqual(result.returncode, 2)
        self.assertEqual(self.config()["permission"], {"edit": "deny"})


class ApprovalPolicyTests(unittest.TestCase):
    def test_guarded_commands_ask_in_every_mode(self) -> None:
        for mode in approval.MODES:
            bash = approval.policy(mode)["bash"]
            for pattern in ("rm -rf *", "git push*", "*pipeline_state.py approve*", "gh release*",
                            "*jarsigner*", "git reset --hard*"):
                self.assertEqual(bash[pattern], "ask", (mode, pattern))
            # OpenCode applies the last matching rule: guards must follow "*".
            self.assertEqual(list(bash)[0], "*")

    def test_manual_asks_by_default_and_auto_allows(self) -> None:
        self.assertEqual(approval.policy("manual")["bash"]["*"], "ask")
        self.assertEqual(approval.policy("manual")["edit"], "ask")
        self.assertEqual(approval.policy("auto")["bash"]["*"], "allow")
        self.assertEqual(approval.policy("auto")["edit"], "allow")
        with self.assertRaises(ValueError):
            approval.policy("yolo")

    def test_agents_do_not_override_workspace_permissions(self) -> None:
        # Agent frontmatter rules are appended after the workspace config, so
        # an agent-level `bash: allow` would silently defeat the guards above.
        for adapter in ("opencode", "kilo"):
            for agent in (ROOT / "adapters" / adapter / "agents").glob("*.md"):
                front = agent.read_text().split("---")[1]
                for key in ("bash:", "edit:", "webfetch:"):
                    self.assertNotIn(f"\n  {key}", front, f"{agent} sets {key}")


if __name__ == "__main__":
    unittest.main()
