import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import hermetic  # noqa: E402,F401  (no downloads, isolated user data)

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))

import knowledge  # noqa: E402

TOOL = ROOT / "tools/knowledge.py"


class KnowledgeCrossProjectTests(unittest.TestCase):
    """Each CLI call is a fresh process, as a new agent session would be."""

    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.workspace = Path(self.temp.name)
        self.data = self.workspace / "userdata"
        self.env = dict(os.environ, LOPODEV_DATA=str(self.data), LOPODEV_HOME=str(ROOT))
        for slug in ("game_a", "game_b"):
            (self.workspace / f"projects/{slug}/godot").mkdir(parents=True)
        self.game_a = self.workspace / "projects/game_a"
        self.game_b = self.workspace / "projects/game_b"

    def tearDown(self) -> None:
        self.temp.cleanup()

    def cli(self, *args: str, project: Path | None = None) -> subprocess.CompletedProcess[str]:
        command = [sys.executable, str(TOOL)]
        if project is not None:
            command += ["--project", str(project)]
        return subprocess.run([*command, *args], text=True, capture_output=True,
                              cwd=self.workspace, env=self.env, check=False)

    def write_draft(self, entry_id: str = "pinch-zoom-camera", **overrides) -> Path:
        draft = self.workspace / "draft"
        (draft / "artifacts" / entry_id).mkdir(parents=True, exist_ok=True)
        (draft / "artifacts" / entry_id / "pinch_zoom.gd").write_text("extends Node\n")
        entry = {
            "schema_version": 1, "id": entry_id, "kind": "recipe",
            "title": "Two-finger pinch zoom for a strategy camera",
            "topic": "input/touch", "tags": ["pinch", "zoom", "gesture", "camera", "touch"],
            "engine": {"name": "godot", "versions": ">=4.4,<4.7"}, "platforms": ["android"],
            "problem": "Strategy maps need pinch zoom without fighting single-finger pan.",
            "approach": "Track two finger indices; zoom by distance ratio.",
            "status": "verified",  # must be ignored on add
            "artifacts": [{"path": f"artifacts/{entry_id}/pinch_zoom.gd",
                           "install_to": "scripts/camera/pinch_zoom.gd"}],
            "validation": {"command": f'test -f "$LOPODEV_KNOWLEDGE_BASE/artifacts/{entry_id}/pinch_zoom.gd"'},
        }
        entry.update(overrides)
        path = draft / f"{entry_id}.json"
        path.write_text(json.dumps(entry))
        return path

    def test_recipe_learned_in_one_game_is_reused_in_another(self) -> None:
        added = self.cli("add", str(self.write_draft()), project=self.game_a)
        self.assertEqual(added.returncode, 0, added.stderr)
        self.assertIn("status=candidate", added.stdout)

        # Project memory never leaks into another game.
        leaked = self.cli("search", "pinch", "zoom", project=self.game_b)
        self.assertIn("NO_MATCH", leaked.stdout)

        # Unverified project knowledge cannot become global knowledge.
        early = self.cli("promote", "pinch-zoom-camera", "--note", "too early", project=self.game_a)
        self.assertEqual(early.returncode, 2)
        self.assertIn("before promoting", early.stderr)

        verified = self.cli("verify", "pinch-zoom-camera", "--run", project=self.game_a)
        self.assertEqual(verified.returncode, 0, verified.stdout + verified.stderr)
        self.assertTrue(list((self.game_a / "artifacts/logs").glob("pinch-zoom-camera-*.log")))

        promoted = self.cli("promote", "pinch-zoom-camera", "--note", "camera-agnostic gesture",
                            project=self.game_a)
        self.assertEqual(promoted.returncode, 0, promoted.stderr)

        # A promoted entry is global but starts over as a candidate.
        found = self.cli("search", "pinch", "zoom", "camera", "--engine-version", "4.6.1",
                         "--platform", "android", project=self.game_b)
        self.assertIn("pinch-zoom-camera [candidate] (user)", found.stdout)
        self.assertEqual(self.cli("verify", "pinch-zoom-camera", "--run").returncode, 0)
        found = self.cli("search", "pinch", "zoom", project=self.game_b)
        self.assertIn("pinch-zoom-camera [verified] (user)", found.stdout)

        godot_b = self.game_b / "godot"
        applied = self.cli("apply", "pinch-zoom-camera", "--godot-dir", str(godot_b), project=self.game_b)
        self.assertEqual(applied.returncode, 0, applied.stderr)
        self.assertTrue((godot_b / "scripts/camera/pinch_zoom.gd").is_file())
        record = json.loads((self.game_b / "knowledge/applied.json").read_text())
        self.assertEqual(record[0]["id"], "pinch-zoom-camera")
        self.assertFalse(record[0]["verified_in_project"])
        again = self.cli("apply", "pinch-zoom-camera", "--godot-dir", str(godot_b), project=self.game_b)
        self.assertIn("UNCHANGED", again.stdout)

        (godot_b / "scripts/camera/pinch_zoom.gd").write_text("user edit\n")
        clash = self.cli("apply", "pinch-zoom-camera", "--godot-dir", str(godot_b), project=self.game_b)
        self.assertEqual(clash.returncode, 2)
        self.assertEqual((godot_b / "scripts/camera/pinch_zoom.gd").read_text(), "user edit\n")

    def test_failed_validation_marks_entry_failed_and_hides_it(self) -> None:
        self.cli("add", str(self.write_draft(validation={"command": "exit 3"})), "--scope", "global")
        result = self.cli("verify", "pinch-zoom-camera", "--run")
        self.assertEqual(result.returncode, 1)
        self.assertIn("status=failed", result.stdout)
        self.assertIn("NO_MATCH", self.cli("search", "pinch", "zoom").stdout)
        self.assertIn("[failed]", self.cli("search", "pinch", "zoom", "--all").stdout)
        refused = self.cli("apply", "pinch-zoom-camera", "--godot-dir", str(self.game_b / "godot"),
                           project=self.game_b)
        self.assertEqual(refused.returncode, 2)
        self.assertIn("must not be reused", refused.stderr)

    def test_incompatible_engine_version_is_filtered(self) -> None:
        draft = self.write_draft(engine={"name": "godot", "versions": ">=3.5,<4.0"})
        self.cli("add", str(draft), "--scope", "global")
        self.assertIn("NO_MATCH", self.cli("search", "pinch", "--engine-version", "4.6.1").stdout)
        self.assertIn("pinch-zoom-camera", self.cli("search", "pinch", "--engine-version", "3.6").stdout)

    def test_secrets_are_rejected(self) -> None:
        draft = self.write_draft(approach="Set password: hunter2hunter2 in export_presets.cfg")
        result = self.cli("add", str(draft), "--scope", "global")
        self.assertEqual(result.returncode, 2)
        self.assertIn("possible secret", result.stderr)
        self.assertFalse((self.data / "knowledge/entries/pinch-zoom-camera.json").exists())

    def test_overlay_fails_bundled_entry_without_touching_toolkit(self) -> None:
        bundled = ROOT / "resources/knowledge/entries/godot-screen-router.json"
        before = bundled.read_bytes()
        self.assertIn("godot-screen-router", self.cli("search", "pause", "menu", "back").stdout)
        marked = self.cli("fail", "godot-screen-router", "--reason", "broke on 4.7 beta")
        self.assertEqual(marked.returncode, 0, marked.stderr)
        self.assertNotIn("godot-screen-router", self.cli("search", "pause", "menu", "back").stdout)
        self.assertEqual(bundled.read_bytes(), before)

    def test_bundled_knowledge_is_valid_and_verified_with_evidence(self) -> None:
        entries = knowledge.load_entries(None)
        bundled = [entry for entry in entries if entry["_store"] == "bundled"]
        self.assertGreaterEqual(len(bundled), 4)
        for entry in bundled:
            errors = knowledge.validate_entry(knowledge.public(entry), Path(entry["_base"]))
            self.assertEqual(errors, [], entry["id"])
            if entry["status"] == "verified":
                for evidence in entry["validation"]["evidence"]:
                    self.assertTrue((Path(entry["_base"]) / evidence).is_file(), evidence)

    def test_context_brief_is_bounded_and_surfaces_matching_knowledge(self) -> None:
        import context_pack

        spec = json.loads((ROOT / "templates/project.json").read_text())
        spec["tasks"] = [{"id": "T1", "title": "Touch joystick look and fire controls",
                          "skills": ["godot-input"], "depends_on": [], "verify": "smoke",
                          "status": "planned", "owner": "gameplay"}]
        (self.game_a / "project.json").write_text(json.dumps(spec))
        import pipeline_state

        state = pipeline_state.new_state("game_a", "Game A", str(self.workspace), str(self.game_a))
        state["tasks"] = [dict(spec["tasks"][0], acceptance="smoke")]
        state["issues"] = [{"id": "I1", "status": "open", "title": "fire button ignored while moving"}]
        (self.game_a / "pipeline_state.json").write_text(json.dumps(state))
        brief = context_pack.build(self.game_a, "T1", max_chars=6000)
        self.assertIn("godot-mobile-touch-controls [verified]", brief)
        self.assertIn("MCP tools available to gameplay: godot, codemap", brief)
        self.assertIn("fire button ignored while moving", brief)
        self.assertLessEqual(len(context_pack.build(self.game_a, "T1", max_chars=400)), 500)
        (self.game_a / "pipeline_state.json").write_text("{}")
        self.assertIn("unreadable", context_pack.build(self.game_a, "T1"))

    def test_version_constraints(self) -> None:
        self.assertTrue(knowledge.version_matches(">=4.3,<4.7", "4.6.1"))
        self.assertFalse(knowledge.version_matches(">=4.3,<4.7", "4.7.0"))
        self.assertTrue(knowledge.version_matches("4.6", "4.6.1"))
        self.assertFalse(knowledge.version_matches("4.5", "4.6.1"))


if __name__ == "__main__":
    unittest.main()
