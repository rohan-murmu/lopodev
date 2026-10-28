import copy
import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import hermetic  # noqa: E402,F401  (no downloads, isolated user data)

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))
sys.path.insert(0, str(ROOT / "tools/godot"))

import integrations  # noqa: E402
import validate_spec  # noqa: E402
import world_plan  # noqa: E402
import world_to_tscn  # noqa: E402

TEMPLATE_PLAN = json.loads((ROOT / "templates/world_plan.json").read_text())
TEMPLATE_SPEC = json.loads((ROOT / "templates/project.json").read_text())


def statuses(result: dict) -> dict:
    return {check["check"]: check["status"] for check in result["checks"]}


class WorldPlanTests(unittest.TestCase):
    def test_template_plan_resolves_and_passes(self) -> None:
        result = world_plan.validate(world_plan.generate(TEMPLATE_PLAN))
        self.assertEqual(result["status"], "PASS", result["checks"])

    def test_generation_is_deterministic_per_seed(self) -> None:
        first = world_plan.generate(TEMPLATE_PLAN)["placements"]
        self.assertEqual(first, world_plan.generate(TEMPLATE_PLAN)["placements"])
        other = dict(TEMPLATE_PLAN, seed=TEMPLATE_PLAN["seed"] + 1)
        self.assertNotEqual(first, world_plan.generate(other)["placements"])

    def test_walled_in_objective_is_unreachable(self) -> None:
        plan = copy.deepcopy(TEMPLATE_PLAN)
        x, z = plan["objectives"][0]["pos"]
        plan["blockers"] = [{"min": [x - 3, z - 3], "max": [x + 3, z - 2.5]},
                            {"min": [x - 3, z + 2.5], "max": [x + 3, z + 3]},
                            {"min": [x - 3, z - 3], "max": [x - 2.5, z + 3]},
                            {"min": [x + 2.5, z - 3], "max": [x + 3, z + 3]}]
        result = world_plan.validate(world_plan.generate(plan))
        self.assertEqual(statuses(result)["objectives_reachable"], "FAIL")
        self.assertIn(plan["objectives"][0]["id"], json.dumps(result["checks"]))

    def test_overlapping_and_path_blocking_props_fail(self) -> None:
        plan = copy.deepcopy(TEMPLATE_PLAN)
        plan["scatter"] = []
        plan["obstacles"] = [{"id": "a", "asset": "sm_rock", "pos": [10, 0], "radius": 1.0},
                             {"id": "b", "asset": "sm_rock", "pos": [10.5, 0], "radius": 1.0},
                             {"id": "c", "asset": "sm_rock", "pos": [0, -10], "radius": 1.0}]
        result = statuses(world_plan.validate(world_plan.generate(plan)))
        self.assertEqual(result["no_overlap"], "FAIL")
        self.assertEqual(result["paths_clear"], "FAIL")

    def test_landmark_mesh_on_path_is_caught(self) -> None:
        plan = copy.deepcopy(TEMPLATE_PLAN)
        plan["landmarks"][0]["pos"] = [0, 12]
        self.assertEqual(statuses(world_plan.validate(world_plan.generate(plan)))["paths_clear"], "FAIL")

    def test_scatter_respects_spawn_clearance_and_budgets(self) -> None:
        resolved = world_plan.generate(TEMPLATE_PLAN)
        spawn = TEMPLATE_PLAN["spawns"][0]["pos"]
        for item in resolved["placements"]:
            if item.get("collision") == "static":
                distance = ((item["pos"][0] - spawn[0]) ** 2 + (item["pos"][1] - spawn[1]) ** 2) ** 0.5
                self.assertGreaterEqual(distance, item["radius"] + TEMPLATE_PLAN["spawn_clearance"] - 1e-6)
        tight = dict(TEMPLATE_PLAN, budgets={"max_instances": 10})
        self.assertEqual(statuses(world_plan.validate(world_plan.generate(tight)))["instance_budget"], "FAIL")

    def test_scene_assembly_refuses_missing_assets(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            with self.assertRaises(FileNotFoundError):
                world_to_tscn.build(world_plan.generate(TEMPLATE_PLAN), Path(temp), {}, False)
            text, notes = world_to_tscn.build(world_plan.generate(TEMPLATE_PLAN), Path(temp), {}, True)
            self.assertIn("Spawn_player_spawn", text)
            self.assertTrue(any("sm_tree" in note for note in notes))

    @unittest.skipUnless(integrations.pinned_godot(ROOT), "Godot is not available")
    def test_assembled_world_loads_in_godot(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            godot_dir = Path(temp) / "godot"
            shutil.copytree(ROOT / "projects/prop_poc/godot", godot_dir,
                            ignore=shutil.ignore_patterns(".godot", ".pipeline"))
            plan = {"schema_version": 1, "seed": 3, "bounds": {"min": [-10, -10], "max": [10, 10]},
                    "spawns": [{"id": "player", "pos": [0, -8]}],
                    "objectives": [{"id": "goal", "pos": [0, 8]}],
                    "scatter": [{"asset": "sm_crate", "count": 8, "radius": 0.6},
                                {"asset": "sm_gem", "count": 4, "radius": 0.3, "collision": "none"}]}
            text, _ = world_to_tscn.build(world_plan.generate(plan), godot_dir, {}, False)
            (godot_dir / "scenes/World.tscn").write_text(text)
            (godot_dir / "check_world.gd").write_text(
                "extends SceneTree\n"
                "func _initialize() -> void:\n"
                "\tvar world: Node3D = load(\"res://scenes/World.tscn\").instantiate()\n"
                "\troot.add_child(world)\n"
                "\tvar meshes := world.find_children(\"*\", \"MeshInstance3D\", true, false).size()\n"
                "\tvar spawn: Marker3D = world.get_node(\"Markers/Spawn_player\")\n"
                "\tvar ok := world.get_node(\"Props\").get_child_count() == 12 and meshes >= 12 "
                "and spawn.position.is_equal_approx(Vector3(0, 0, -8))\n"
                "\tprint(\"WORLD_CHECK=\", \"PASS\" if ok else \"FAIL\")\n"
                "\tquit(0 if ok else 1)\n")
            godot = integrations.pinned_godot(ROOT)
            subprocess.run([godot, "--headless", "--path", str(godot_dir), "--import"],
                           capture_output=True, timeout=300, check=False)
            result = subprocess.run([godot, "--headless", "--path", str(godot_dir), "--script",
                                     "res://check_world.gd"], text=True, capture_output=True,
                                    timeout=300, check=False)
            self.assertIn("WORLD_CHECK=PASS", result.stdout, result.stdout[-2000:] + result.stderr[-2000:])


class DesignValidationTests(unittest.TestCase):
    def errors(self, spec: dict) -> list[str]:
        return validate_spec.validate(spec)

    def test_template_spec_is_valid(self) -> None:
        # Regression: the shipped template used gate "android", which the
        # validator rejected, so every new project started invalid.
        self.assertEqual(self.errors(TEMPLATE_SPEC), [])

    def test_design_v2_requires_screens_navigation_and_controls(self) -> None:
        spec = copy.deepcopy(TEMPLATE_SPEC)
        for key in ("screens", "navigation", "controls", "core_loop"):
            spec.pop(key)
        errors = " ".join(self.errors(spec))
        for key in ("screens", "navigation", "controls", "core_loop"):
            self.assertIn(key, errors)

    def test_legacy_specs_without_design_keys_still_pass(self) -> None:
        spec = copy.deepcopy(TEMPLATE_SPEC)
        for key in ("design_version", "screens", "navigation", "controls", "core_loop"):
            spec.pop(key)
        self.assertEqual(self.errors(spec), [])

    def test_dead_end_unreachable_and_nonfunctional_controls(self) -> None:
        spec = copy.deepcopy(TEMPLATE_SPEC)
        spec["screens"].append({"id": "credits", "kind": "menu", "controls": ["back"]})
        spec["navigation"]["transitions"] = [t for t in spec["navigation"]["transitions"]
                                             if not (t["from"] == "victory" and t["on"] == "menu")]
        spec["screens"][0]["controls"].append("leaderboard")
        errors = " ".join(self.errors(spec))
        self.assertIn("credits is unreachable", errors)
        self.assertIn("credits is a dead end", errors)
        self.assertIn("'menu' has no transition", errors)
        self.assertIn("'leaderboard' has no transition", errors)

    def test_gameplay_without_pause_and_result_without_retry_fail(self) -> None:
        spec = copy.deepcopy(TEMPLATE_SPEC)
        spec["navigation"]["transitions"] = [t for t in spec["navigation"]["transitions"]
                                             if t["to"] != "pause" and t["from"] != "game_over"]
        spec["navigation"]["transitions"].append({"from": "game_over", "on": "quit", "to": "@quit"})
        spec["screens"] = [dict(s, controls=[]) for s in spec["screens"]]
        errors = " ".join(self.errors(spec))
        self.assertIn("needs a pause overlay", errors)
        self.assertIn("game_over needs retry", errors)

    def test_touch_conflicts_and_tiny_buttons_fail(self) -> None:
        spec = copy.deepcopy(TEMPLATE_SPEC)
        spec["controls"]["touch"][1]["zone"] = "bottom-left"
        spec["controls"]["touch"][2]["min_size_dp"] = 30
        errors = " ".join(self.errors(spec))
        self.assertIn("shares zone 'bottom-left'", errors)
        self.assertIn("min_size_dp must be >= 44", errors)

    def test_entry_must_be_menu_unless_justified(self) -> None:
        spec = copy.deepcopy(TEMPLATE_SPEC)
        spec["navigation"]["entry"] = "game"
        self.assertTrue(any("entry_reason" in e for e in self.errors(spec)))
        spec["navigation"]["entry_reason"] = "developer requested instant play"
        self.assertFalse(any("entry_reason" in e for e in self.errors(spec)))

    def test_spec_orientation_must_match_engine_setting(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            godot = Path(temp) / "godot"
            godot.mkdir()
            (godot / "project.godot").write_text("[display]\nwindow/handheld/orientation=1\n")
            spec = {"mobile": {"orientation": "landscape"}}
            self.assertTrue(validate_spec.check_engine_orientation(spec, godot))
            (godot / "project.godot").write_text("[display]\nwindow/handheld/orientation=0\n")
            self.assertEqual(validate_spec.check_engine_orientation(spec, godot), [])

    def test_vendored_skills_are_known_task_skills(self) -> None:
        self.assertIn("godot-input", validate_spec.KNOWN_SKILLS)
        self.assertIn("blender-lpm-skill", validate_spec.KNOWN_SKILLS)


if __name__ == "__main__":
    unittest.main()
