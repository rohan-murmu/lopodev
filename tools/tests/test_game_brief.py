import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import hermetic  # noqa: E402,F401  (no downloads, isolated user data)

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))

import asset_requirements  # noqa: E402
import game_brief  # noqa: E402
import validate_spec  # noqa: E402

EXAMPLES = ROOT / "docs/examples"
TEMPLATE_SPEC = json.loads((ROOT / "templates/project.json").read_text())


def scaffold(name: str, **overrides):
    brief = game_brief.parse((EXAMPLES / name).read_text())
    brief.update(overrides)
    return game_brief.scaffold(brief, TEMPLATE_SPEC, "demo_game")


class BriefParsingTests(unittest.TestCase):
    def test_keys_lists_and_comments(self) -> None:
        brief = game_brief.parse("""# Game Brief
<!-- Genre: ignored comment -->
Title: Hex Hollow
Theme/setting: haunted village
Win/Lose: purify 3 wells / health reaches zero
Characters:
- Mira (player, idle/run/cast)
- spirit (enemy, float/attack/die)
Must-have assets: cauldron, lantern, herb bush
""")
        self.assertEqual(brief["title"], "Hex Hollow")
        self.assertEqual(brief["theme"], "haunted village")
        self.assertEqual((brief["win"], brief["lose"]), ("purify 3 wells", "health reaches zero"))
        self.assertEqual(len(brief["characters"]), 2)
        self.assertEqual(brief["assets"], ["cauldron", "lantern", "herb bush"])
        self.assertNotIn("genre", brief)

    def test_template_is_all_blank_and_examples_pass(self) -> None:
        template = game_brief.parse((ROOT / "templates/GAME_BRIEF.md").read_text())
        self.assertEqual(template, {})
        self.assertEqual(game_brief.check(template)["missing"], list(game_brief.REQUIRED))
        for example in EXAMPLES.glob("brief_*.md"):
            self.assertEqual(game_brief.check(game_brief.parse(example.read_text()))["status"], "PASS", example)

    def test_contradictions(self) -> None:
        problems = game_brief.check({"genre": "first-person shooter", "orientation": "portrait",
                                     "camera": "top-down", "platform": "desktop", "controls": "tilt",
                                     "core_loop": "shoot", "win": "survive"})["contradictions"]
        joined = " ".join(problems)
        for expected in ("landscape", "top-down", "desktop-only", "too short", "no lose condition"):
            self.assertIn(expected, joined)

    def test_character_parsing(self) -> None:
        character = game_brief.parse_character("spirit (enemy, float/attack/die)")
        self.assertEqual(character["role"], "enemy")
        self.assertIn("float", character["animations"])
        self.assertIn("death", character["animations"])
        self.assertEqual(character["animations"][0], "idle")


class ScaffoldTests(unittest.TestCase):
    def test_examples_scaffold_to_valid_specs(self) -> None:
        for name in ("brief_witch_village.md", "brief_jungle_shooter.md"):
            spec, world, _ = scaffold(name)
            self.assertEqual(validate_spec.validate(spec), [], name)
            self.assertEqual(asset_requirements.analyze(spec)["errors"], [], name)
            import world_plan
            self.assertEqual(world_plan.validate(world_plan.generate(world))["status"], "PASS", name)

    def test_witch_village_content(self) -> None:
        spec, world, assumptions = scaffold("brief_witch_village.md")
        assets = {a["id"]: a for a in spec["assets"]}
        self.assertEqual(assets["sm_witch_well"]["source"], "derived")
        self.assertEqual(assets["sm_witch_well"]["derive_from"], "sm_water_well")
        self.assertIn("witch", assets["sm_mira"]["terms"])
        self.assertIn("hit", assets["sm_mira"]["animations"])
        self.assertTrue(any("Derive sm_witch_well" in t["title"] for t in spec["tasks"]))
        actions = {c["action"] for c in spec["controls"]["touch"]}
        self.assertTrue({"move", "camera_look", "attack", "brew", "dodge", "pause"} <= actions)
        self.assertIn("game_over", [s["id"] for s in spec["screens"]])
        self.assertEqual(spec["mobile"]["orientation"], "landscape")
        self.assertEqual(spec["target_platform"], "android")
        self.assertTrue(any(a["gate"] == "android" for a in spec["acceptance"]))
        self.assertIn("enemy_spawns", world)
        self.assertTrue(all("suggested from theme" in a for a in assumptions))

    def test_blanks_become_assumptions_and_desktop_works(self) -> None:
        brief = {"genre": "puzzle", "core_loop": "slide tiles to connect pipes and open the gate",
                 "win": "open all gates", "lose": "none", "platform": "desktop", "controls": "mouse"}
        spec, _, assumptions = game_brief.scaffold(brief, TEMPLATE_SPEC, "pipes")
        self.assertEqual(validate_spec.validate(spec), [])
        self.assertNotIn("mobile", spec)
        self.assertIn("keyboard", spec["controls"])
        self.assertNotIn("game_over", [s["id"] for s in spec["screens"]])
        self.assertTrue(any(a.startswith("art_style") for a in assumptions))
        self.assertEqual(asset_requirements.analyze(spec)["budget_profile"], "desktop")

    def test_bootstrap_with_brief_and_draft_protection(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            workspace = Path(temp)
            result = subprocess.run([sys.executable, str(ROOT / "tools/bootstrap_project.py"), "--workspace",
                                     str(workspace), "--slug", "hex_hollow", "--title", "Hex Hollow", "--brief",
                                     str(EXAMPLES / "brief_witch_village.md"), "--no-scaffold"],
                                    text=True, capture_output=True, check=False)
            self.assertEqual(result.returncode, 0, result.stderr)
            project = workspace / "projects/hex_hollow"
            spec = json.loads((project / "project.json").read_text())
            self.assertEqual(spec["art_style"], "stylized dark fairytale")
            self.assertTrue((project / "docs/GAME_BRIEF.md").is_file())
            self.assertTrue((project / "docs/world_plan.json").is_file())
            spec["status"] = "approved"
            (project / "project.json").write_text(json.dumps(spec))
            with self.assertRaises(ValueError):
                game_brief.write_scaffold(EXAMPLES / "brief_jungle_shooter.md", project)


class BudgetProfileTests(unittest.TestCase):
    def test_profiles_and_overrides(self) -> None:
        mobile = asset_requirements.analyze({"mobile": {}, "assets": [
            {"id": "sm_a", "class": "static_prop", "terms": ["a"]},
            {"id": "sm_b", "class": "static_prop", "terms": ["b"], "budget_triangles": 900}]})
        self.assertEqual([r["budget_triangles"] for r in mobile["requirements"]], [5000, 900])
        desktop = asset_requirements.analyze({"target_platform": "linux-x86_64", "assets": [
            {"id": "sm_c", "class": "skeletal_character", "terms": ["c"]}]})
        self.assertEqual(desktop["requirements"][0]["budget_triangles"], 60000)
        with self.assertRaises(ValueError):
            asset_requirements.analyze({"budget_profile": "console", "assets": []})


if __name__ == "__main__":
    unittest.main()
