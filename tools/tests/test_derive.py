import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import hermetic  # noqa: E402,F401  (no downloads, isolated user data)
import gltf_fixture  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))

import asset_catalog  # noqa: E402
import asset_pipeline  # noqa: E402
import asset_sources  # noqa: E402
import integrations  # noqa: E402
import live_session  # noqa: E402
from asset_catalog import AssetError  # noqa: E402

POLICY = asset_sources.load_registry()["license_policy"]
BLENDER = live_session.find_blender()

EDIT = '''
def edit(ctx):
    box = ctx.find("box|well|rock")
    ctx.recolor(box, (0.2, 0.25, 0.15))
    ctx.add("box", "Lid", size=(0.6, 0.6, 0.1), location=(0, 0, 1.2),
            material=ctx.material("lid", (0.4, 0.2, 0.1)))
    ctx.add("sphere", "Skull", size=(0.2, 0.2, 0.2), location=(0.3, 0.3, 1.0))
    ctx.set_origin_ground()
'''


class LicenseInheritanceTests(unittest.TestCase):
    def test_cc0_cc_by_and_refusals(self) -> None:
        cc0 = {"asset_id": "a", "license": {"id": "CC0-1.0"}}
        by = {"asset_id": "b", "title": "Lamp", "source_url": "https://x", "license": {"id": "CC-BY-4.0",
                                                                                      "creator": "Ann"}}
        self.assertEqual(asset_pipeline.inherited_license([cc0, cc0], POLICY)["id"], "CC0-1.0")
        mixed = asset_pipeline.inherited_license([cc0, by], POLICY)
        self.assertEqual(mixed["id"], "CC-BY-4.0")
        self.assertIn("Ann", mixed["attribution"])
        self.assertIn("(modified)", mixed["attribution"])
        for bad in ("CC-BY-ND-4.0", "unknown", "CC-BY-SA-4.0"):
            with self.assertRaises(AssetError):
                asset_pipeline.inherited_license([{"asset_id": "c", "license": {"id": bad}}], POLICY)


@unittest.skipUnless(BLENDER, "Blender is not available")
class DeriveAndRigTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        root = Path(self.temp.name)
        self.base = Path(integrations.data_dir()) / "assets"
        self.project = root / "ws/projects/village"
        godot = self.project / "godot"
        godot.mkdir(parents=True)
        (godot / "project.godot").write_text('config_version=5\n[application]\nconfig/name="Village"\n'
                                             '[rendering]\nrenderer/rendering_method="gl_compatibility"\n')
        pack = root / "pack"
        gltf_fixture.box_glb(pack / "Models/WaterWell.glb", (1.2, 1.0, 1.2), name="Well")
        (pack / "License.txt").write_text(gltf_fixture.CC0_TEXT)
        asset_sources.index_pack(pack, "kenney", "village", style=["stylized"], tags=[], base=self.base)
        self.spec = {"slug": "village", "godot_dir": "projects/village/godot", "assets": [
            {"id": "sm_water_well", "class": "static_prop", "terms": ["well"], "providers": ["kenney"]},
            {"id": "sm_witch_well", "class": "static_prop", "source": "derived", "derive_from": "sm_water_well",
             "terms": ["well"]},
            {"id": "sm_witch_well_anim", "class": "animated_prop", "source": "derived",
             "derive_from": "sm_witch_well", "terms": ["well"]}]}
        (self.project / "project.json").write_text(json.dumps(self.spec))
        self.script = root / "derive_witch.py"
        self.script.write_text(EDIT)

    def tearDown(self) -> None:
        self.temp.cleanup()
        shutil.rmtree(self.base, ignore_errors=True)

    def test_derive_rig_import_and_provenance(self) -> None:
        asset_pipeline.resolve(self.project, offline=True, base=self.base)
        asset_pipeline.fetch_selected(self.project, base=self.base)
        report = asset_pipeline.validate(self.project, base=self.base)
        statuses = {(c["requirement"], c["check"]): c["status"] for c in report["checks"]}
        self.assertEqual(statuses[("sm_witch_well", "derive")], "FAIL", "pending derive must not pass")

        source = Path(asset_pipeline.load_manifest(self.project)["selections"]["sm_water_well"]["fetch"]["path"])
        before = asset_catalog.sha256_file(source)
        entry = asset_pipeline.derive(self.project, "sm_water_well", "sm_witch_well", script=self.script,
                                      live=False, base=self.base)
        derived = entry["derive"]
        self.assertEqual(derived["status"], "PASS", derived)
        self.assertEqual(asset_catalog.sha256_file(source), before, "the source asset is never modified")
        self.assertEqual(entry["license"]["id"], "CC0-1.0")
        self.assertGreater(derived["after"]["objects"], derived["before"]["objects"])
        self.assertIn("lid", derived["after"]["materials"])
        for image in derived["previews"]["before"] + derived["previews"]["after"]:
            self.assertGreater(Path(image).stat().st_size, 1000, image)
        self.assertTrue((self.project / "blender/sm_witch_well.blend").is_file())
        again = asset_pipeline.derive(self.project, "sm_water_well", "sm_witch_well", script=self.script,
                                      live=False, base=self.base)
        self.assertTrue(again.get("unchanged"))

        rigged = asset_pipeline.rig(self.project, "sm_witch_well", "sm_witch_well_anim", "parts",
                                    clips=["lid_open:Lid:rotate_x:-80:1.0", "skull_bob:Skull:bob_z:0.1:1.0"],
                                    live=False, base=self.base)
        self.assertEqual(rigged["derive"]["rig"]["clips"], ["lid_open", "skull_bob"])
        self.assertEqual(rigged["derive"]["weights"], "PASS")
        self.assertEqual(len(rigged["derive"]["previews"]["clips"]), 4)
        glb = Path(rigged["fetch"]["path"])
        clips = [a["name"] for a in asset_catalog.inspect_model(glb)["animations"]]
        self.assertEqual(sorted(clips), ["lid_open", "skull_bob"], "every clip must reach the GLB")

        manifest = asset_pipeline.import_assets(self.project, run_godot=bool(integrations.pinned_godot(ROOT)),
                                                base=self.base)
        if integrations.pinned_godot(ROOT):
            godot = manifest["selections"]["sm_witch_well_anim"]["import"]["godot"]
            self.assertEqual(godot["playback_status"], "PASS", godot)
        report = asset_pipeline.validate(self.project, base=self.base)
        statuses = {(c["requirement"], c["check"]): c["status"] for c in report["checks"]}
        self.assertEqual(statuses[("sm_witch_well", "derive")], "PASS")
        self.assertEqual(statuses[("sm_witch_well_anim", "rig_weights")], "PASS")

    def test_derive_refuses_to_overwrite_user_blend(self) -> None:
        asset_pipeline.resolve(self.project, offline=True, base=self.base)
        asset_pipeline.fetch_selected(self.project, base=self.base)
        blend = self.project / "blender/sm_witch_well.blend"
        blend.parent.mkdir(parents=True)
        blend.write_bytes(b"user work")
        with self.assertRaises(AssetError):
            asset_pipeline.derive(self.project, "sm_water_well", "sm_witch_well", script=self.script,
                                  live=False, base=self.base)
        self.assertEqual(blend.read_bytes(), b"user work")


if __name__ == "__main__":
    unittest.main()
