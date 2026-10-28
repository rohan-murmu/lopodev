import copy
import hashlib
import io
import json
import shutil
import subprocess
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import hermetic  # noqa: E402,F401  (no downloads, isolated user data)
import gltf_fixture  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))
sys.path.insert(0, str(ROOT / "tools/godot"))

import asset_catalog  # noqa: E402
import asset_pipeline  # noqa: E402
import asset_rank  # noqa: E402
import asset_requirements  # noqa: E402
import asset_sources  # noqa: E402
import integrations  # noqa: E402
import world_plan  # noqa: E402
import world_to_tscn  # noqa: E402
from asset_catalog import AssetError  # noqa: E402

FIXTURES = Path(__file__).resolve().parent / "fixtures/providers"
REGISTRY = asset_sources.load_registry()
POLICY, WEIGHTS = REGISTRY["license_policy"], REGISTRY["ranking_weights"]
GODOT = integrations.pinned_godot(ROOT)


def requirement(**fields) -> dict:
    base = {"id": "sm_thing", "class": "static_prop", "terms": ["thing"]}
    base.update(fields)
    return asset_requirements.normalize(base)


def candidate(asset_id: str, **fields) -> dict:
    record = {"asset_id": asset_id, "provider": "kenney", "kind": "model", "format": "glb",
              "tags": [], "categories": [], "name_tokens": [], "style": ["stylized"],
              "license": {"id": "CC0-1.0"},
              "capabilities": {"triangles": 500, "skinned": False, "animations": [], "importable": True}}
    for key, value in fields.items():
        if key == "caps":
            record["capabilities"] = {**record["capabilities"], **value}
        else:
            record[key] = value
    return record


class LicensePolicyTests(unittest.TestCase):
    def test_normalization(self) -> None:
        cases = {"CC0": "CC0-1.0", "Creative Commons Zero, CC0": "CC0-1.0",
                 "https://creativecommons.org/publicdomain/zero/1.0/": "CC0-1.0",
                 "CC-BY 4.0": "CC-BY-4.0", "cc by 3.0": "CC-BY-3.0", "CC-BY-SA 4.0": "CC-BY-SA-4.0",
                 "CC BY-NC 4.0": "CC-BY-NC-4.0", "creativecommons.org/licenses/by-nd/4.0": "CC-BY-ND-4.0",
                 "GPL 3.0 or later": "unknown", "GPL-3.0": "GPL-3.0", "": "unknown", "All rights reserved": "unknown"}
        for text, expected in cases.items():
            self.assertEqual(asset_sources.normalize_license(text), expected, text)

    def test_decisions_are_hard_categories(self) -> None:
        decide = lambda lid: asset_sources.license_decision(lid, POLICY)["decision"]  # noqa: E731
        self.assertEqual(decide("CC0-1.0"), "allowed")
        self.assertEqual(decide("CC-BY-4.0"), "attribution")
        self.assertEqual(decide("CC-BY-SA-4.0"), "review")
        self.assertEqual(decide("CC-BY-NC-4.0"), "rejected")
        self.assertEqual(decide("CC-BY-ND-4.0"), "rejected")
        self.assertEqual(decide("unknown"), "rejected")
        self.assertEqual(decide("WTFPL"), "review")


class RankingTests(unittest.TestCase):
    def test_license_is_a_hard_constraint_not_a_score(self) -> None:
        req = requirement(terms=["palm", "tree"], style=["stylized"])
        gorgeous = candidate("x:nc_palm", tags=["palm", "tree"], license={"id": "CC-BY-NC-4.0"})
        plain = candidate("x:cc0_palm", name_tokens=["palm"], style=["realistic"])
        eligible, rejected = asset_rank.rank(req, [gorgeous, plain], POLICY, WEIGHTS)
        self.assertEqual([c["asset_id"] for c, _ in eligible], ["x:cc0_palm"])
        self.assertIn("CC-BY-NC-4.0", rejected[0][1]["rejection"])

    def test_rigged_character_beats_prettier_static_mesh(self) -> None:
        req = requirement(id="sm_enemy", **{"class": "skeletal_character"}, terms=["soldier"],
                          animations=["idle", "run", "shoot", "death"])
        statue = candidate("x:statue", tags=["soldier", "military", "character"], caps={"skinned": False})
        rigged = candidate("x:rigged", name_tokens=["soldier"],
                           caps={"skinned": True, "animations": ["Idle", "Run_Gun", "Death_A"]})
        eligible, rejected = asset_rank.rank(req, [statue, rigged], POLICY, WEIGHTS)
        self.assertEqual(eligible[0][0]["asset_id"], "x:rigged")
        self.assertIn("no skin", rejected[0][1]["rejection"])
        self.assertEqual(eligible[0][1]["animation_map"]["shoot"], "Run_Gun")
        self.assertEqual(eligible[0][1]["animation_map"]["death"], "Death_A")

    def test_budget_semantics_and_explanations(self) -> None:
        req = requirement(terms=["palm", "tree"], budget_triangles=2000)
        heavy = candidate("x:heavy", tags=["palm", "tree"], caps={"triangles": 250000})
        light = candidate("x:light", tags=["palm", "tree"], caps={"triangles": 1200})
        unrelated = candidate("x:chair", tags=["chair"])
        named_only = candidate("x:named", name_tokens=["palm"], caps={"triangles": 1200})
        eligible, rejected = asset_rank.rank(req, [heavy, light, unrelated, named_only], POLICY, WEIGHTS)
        self.assertEqual([c["asset_id"] for c, _ in eligible], ["x:light", "x:named"])
        reasons = {c["asset_id"]: r["rejection"] for c, r in rejected}
        self.assertIn("twice the budget", reasons["x:heavy"])
        self.assertEqual(reasons["x:chair"], "no semantic match")
        self.assertTrue(any("tag:palm" in reason for reason in eligible[0][1]["reasons"]))

    def test_animation_map_prefers_plain_clips(self) -> None:
        mapping = asset_rank.animation_map(["run", "hit", "death", "reload"],
                                           ["Run_Shoot", "Run", "HitReact", "Die_Forward"])
        self.assertEqual(mapping, {"run": "Run", "hit": "HitReact", "death": "Die_Forward", "reload": None})

    def test_skeleton_comparison(self) -> None:
        chain = [{"name": "Hips", "parent": None}, {"name": "Spine", "parent": "Hips"},
                 {"name": "Head", "parent": "Spine"}]
        mixamo = [{"name": "mixamorig:" + j["name"], "parent": j["parent"] and "mixamorig:" + j["parent"]}
                  for j in chain]
        self.assertEqual(asset_rank.compare_skeletons(chain, copy.deepcopy(chain))["relation"], "identical")
        self.assertEqual(asset_rank.compare_skeletons(mixamo, chain)["relation"], "identical")
        extra = chain + [{"name": "Tail", "parent": "Hips"}]
        self.assertEqual(asset_rank.compare_skeletons(chain, extra)["relation"], "name_compatible")
        other = [{"name": "Root", "parent": None}, {"name": "Body", "parent": "Root"}]
        self.assertEqual(asset_rank.compare_skeletons(chain, other)["relation"], "incompatible")
        reparented = [{"name": "Hips", "parent": None}, {"name": "Spine", "parent": "Head"},
                      {"name": "Head", "parent": "Hips"}]
        self.assertEqual(asset_rank.compare_skeletons(chain, reparented)["relation"], "incompatible")


class RequirementTests(unittest.TestCase):
    def test_defaults_per_class_and_legacy_entries(self) -> None:
        enemy = asset_requirements.normalize({"id": "sm_enemy", "class": "skeletal_character", "terms": ["soldier"]})
        self.assertEqual((enemy["rig"], enemy["collision"], enemy["animations"]),
                         ("required", "capsule", ["idle", "walk"]))
        legacy = asset_requirements.normalize({"id": "sm_crate", "kind": "prop", "source": "procedural",
                                               "license": "generated-in-repo", "animated": False})
        self.assertEqual((legacy["class"], legacy["resolution"], legacy["terms"]), ("static_prop", "generate", ["crate"]))

    def test_validation_errors(self) -> None:
        bad = [asset_requirements.normalize({"id": "a", "class": "skeletal_character", "terms": ["x"],
                                             "collision": "box"}),
               asset_requirements.normalize({"id": "b", "class": "static_prop", "terms": ["x"],
                                             "animations": ["idle"]}),
               asset_requirements.normalize({"id": "c", "class": "static_prop", "terms": ["x"],
                                             "fallbacks": ["anything"]})]
        errors = [error for req in bad for error in asset_requirements.validate_requirement(req)]
        self.assertEqual(len(errors), 3, errors)

    def test_prompt_suggestion_covers_jungle_fps(self) -> None:
        ids = {a["id"]: a for a in asset_requirements.suggest("A stylized jungle FPS against soldier squads in ruins")}
        for expected in ("sm_tree", "sm_bush", "sm_rock", "mat_ground", "sm_weapon", "sm_enemy", "sm_ruin_wall"):
            self.assertIn(expected, ids)
        self.assertIn("shoot", ids["sm_enemy"]["animations"])
        self.assertEqual(ids["mat_ground"]["class"], "material")


class CatalogAndProviderTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.base = Path(self.temp.name) / "assets"

    def tearDown(self) -> None:
        self.temp.cleanup()

    def test_store_bytes_deduplicates_by_hash(self) -> None:
        first, digest = asset_catalog.store_bytes(b"model", "a.glb", self.base)
        again, digest2 = asset_catalog.store_bytes(b"model", "a.glb", self.base)
        self.assertEqual((first, digest), (again, digest2))
        self.assertEqual(len(list((self.base / "originals").iterdir())), 1)
        with self.assertRaises(AssetError):
            asset_catalog.safe_name("..")

    def test_download_rejects_truncated_and_corrupt_data(self) -> None:
        target = self.base / "x.bin"
        fetch = lambda url: b"half"  # noqa: E731
        with self.assertRaises(AssetError):
            asset_catalog.download("https://e/x", target, size=8, fetch=fetch)
        with self.assertRaises(AssetError):
            asset_catalog.download("https://e/x", target, md5="0" * 32, fetch=fetch)

        def broken(url: str) -> bytes:
            raise OSError("connection reset")
        with self.assertRaises(AssetError):
            asset_catalog.download("https://e/x", target, fetch=broken)
        self.assertFalse(target.exists())
        self.assertFalse(list(self.base.glob("*.part")))

    def test_zip_extraction_refuses_traversal_and_corruption(self) -> None:
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, "w") as archive:
            archive.writestr("../evil.txt", "x")
        with self.assertRaises(AssetError):
            asset_catalog.extract_zip(buffer.getvalue(), self.base / "out")
        with self.assertRaises(AssetError):
            asset_catalog.extract_zip(b"PK\x03\x04 not a zip", self.base / "out")
        self.assertFalse((self.base / "evil.txt").exists())

    def test_pack_index_license_and_format_preference(self) -> None:
        pack = gltf_fixture.make_pack(Path(self.temp.name) / "pack")
        result = asset_sources.index_pack(pack, "kenney", "jungle", style=["stylized"], tags=["nature"],
                                          base=self.base)
        self.assertEqual((result["license"], result["license_evidence"]), ("CC0-1.0", "License.txt"))
        records = asset_catalog.load_catalog(self.base)["records"]
        rock = [r for r in records.values() if r["title"].startswith("Rock_Large")]
        self.assertEqual([r["format"] for r in rock], ["glb"])
        soldier = next(r for r in records.values() if r["title"] == "Soldier")
        self.assertTrue(soldier["capabilities"]["skinned"])
        self.assertEqual(len(soldier["capabilities"]["joints"]), 4)
        self.assertIn("Shoot", soldier["capabilities"]["animations"])
        # Re-indexing replaces the pack's records instead of duplicating them.
        again = asset_sources.index_pack(pack, "kenney", "jungle", style=[], tags=[], base=self.base)
        self.assertEqual(again["removed_stale"], result["models"])

    def test_pack_without_or_with_conflicting_license(self) -> None:
        bare = gltf_fixture.make_pack(Path(self.temp.name) / "bare", license_text=None)
        result = asset_sources.index_pack(bare, "kenney", "bare", style=[], tags=[], base=self.base)
        self.assertEqual(result["license"], "unknown")
        record = next(iter(asset_catalog.load_catalog(self.base)["records"].values()))
        self.assertFalse(asset_rank.score(requirement(terms=["rock"]), record, POLICY, WEIGHTS)["eligible"])
        with self.assertRaises(AssetError):
            asset_sources.index_pack(gltf_fixture.make_pack(Path(self.temp.name) / "cc0"), "kenney", "cc0",
                                     style=[], tags=[], license_id="CC-BY-4.0", base=self.base)

    def polyhaven_fetch(self, corrupt: bool = False):
        gltf_body = json.dumps({"asset": {"version": "2.0"}, "buffers": [{"uri": "palm.bin", "byteLength": 4}],
                                "images": [{"uri": "textures/palm_diff_1k.jpg"}]}).encode()
        files = {"https://dl.example/palm.gltf": gltf_body, "https://dl.example/palm.bin": b"\0\0\0\0",
                 "https://dl.example/palm_diff_1k.jpg": b"jpgdata"}
        md5 = {url: hashlib.md5(data).hexdigest() for url, data in files.items()}  # noqa: S324
        listing = json.loads((FIXTURES / "polyhaven_models.json").read_text())
        manifest = {"gltf": {"1k": {"gltf": {"url": "https://dl.example/palm.gltf", "md5": md5["https://dl.example/palm.gltf"],
                                             "size": len(gltf_body), "include": {
                                                 "palm.bin": {"url": "https://dl.example/palm.bin",
                                                              "md5": md5["https://dl.example/palm.bin"], "size": 4},
                                                 "textures/palm_diff_1k.jpg": {"url": "https://dl.example/palm_diff_1k.jpg",
                                                                               "md5": md5["https://dl.example/palm_diff_1k.jpg"],
                                                                               "size": 7}}}}}}
        calls = []

        def fetch(url: str) -> bytes:
            calls.append(url)
            if url.endswith("/assets?t=models"):
                return json.dumps(listing).encode()
            if "/files/" in url:
                return json.dumps(manifest).encode()
            data = files[url]
            return data[:-1] if corrupt and url.endswith(".jpg") else data
        return fetch, calls

    def test_polyhaven_adapter_search_and_verified_fetch(self) -> None:
        provider = asset_sources.providers(REGISTRY, self.base)["polyhaven"]
        fetch, calls = self.polyhaven_fetch()
        results = provider.search(requirement(terms=["palm", "tree"]), fetch)
        self.assertEqual({r["provider_id"] for r in results}, {"jungle_palm_01", "dense_palm_02"})
        palm = next(r for r in results if r["provider_id"] == "jungle_palm_01")
        self.assertEqual(palm["capabilities"]["size_m"], [1.8, 5.2, 1.7])
        self.assertIsNone(palm["capabilities"]["skinned"])  # unknown, not "no"
        provider.search(requirement(terms=["palm"]), fetch)
        self.assertEqual(sum(url.endswith("t=models") for url in calls), 1, "listing is cached")
        files = provider.fetch(palm, self.base / "staging", fetch)
        self.assertEqual(files[0].name, "palm.gltf")
        self.assertTrue((files[0].parent / "textures/palm_diff_1k.jpg").is_file())
        info = asset_catalog.inspect_model(files[0])
        self.assertEqual(info["missing_files"], [])

        corrupt_fetch, _ = self.polyhaven_fetch(corrupt=True)
        with self.assertRaises(AssetError):
            provider.fetch(palm, self.base / "staging2", corrupt_fetch)

    def test_ambientcg_adapter_with_mocked_api(self) -> None:
        provider = asset_sources.providers(REGISTRY, self.base)["ambientcg"]
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, "w") as archive:
            archive.writestr("Ground054_1K-JPG_Color.jpg", "c")
            archive.writestr("Ground054_1K-JPG_NormalGL.jpg", "n")
        api = (FIXTURES / "ambientcg_ground.json").read_bytes()
        fetch = lambda url: api if "full_json" in url else buffer.getvalue()  # noqa: E731
        results = provider.search(requirement(**{"class": "material"}, terms=["ground", "dirt"]), fetch)
        self.assertEqual(results[0]["asset_id"], "ambientcg:Ground054")
        files = provider.fetch(results[0], self.base / "staging", fetch)
        self.assertTrue(any(path.name.endswith("_Color.jpg") for path in files))

    def test_unavailable_providers_say_why(self) -> None:
        provs = asset_sources.providers(REGISTRY, self.base)
        for name in ("polypizza", "opengameart"):
            status = provs[name].status()
            self.assertFalse(status["available"])
            self.assertTrue(status["reason"])
        self.assertIn("no packs indexed", provs["quaternius"].status()["reason"])


class PipelineTests(unittest.TestCase):
    """Prompt -> requirements -> selection -> cache -> Godot files, offline."""

    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.base = self.root / "data/assets"
        self.project = self.root / "ws/projects/jungle"
        godot = self.root / "ws/projects/jungle/godot"
        godot.mkdir(parents=True)
        (godot / "project.godot").write_text('config_version=5\n[application]\nconfig/name="Jungle"\n')
        gltf_fixture.make_pack(self.root / "pack")
        asset_sources.index_pack(self.root / "pack", "kenney", "jungle", style=["stylized"], tags=["nature"],
                                 base=self.base)
        assets = asset_requirements.suggest("stylized jungle fps vs soldier enemies in ruins", ["stylized"])
        keep = {"sm_tree", "sm_rock", "sm_log", "sm_enemy", "sm_ruin_wall"}
        assets = [a for a in assets if a["id"] in keep]
        assets.append({"id": "sm_crate", "class": "static_prop", "terms": ["crate"],
                       "fallbacks": ["procedural:box"]})
        assets.append({"id": "sm_idol", "class": "static_prop", "terms": ["idol"], "mandatory": False})
        self.spec = {"slug": "jungle", "godot_dir": "projects/jungle/godot", "art_style": "stylized",
                     "assets": assets}
        (self.project / "project.json").write_text(json.dumps(self.spec))

    def tearDown(self) -> None:
        self.temp.cleanup()

    def run_pipeline(self, run_godot: bool = False) -> dict:
        asset_pipeline.resolve(self.project, offline=True, base=self.base)
        asset_pipeline.fetch_selected(self.project, base=self.base)
        asset_pipeline.import_assets(self.project, run_godot=run_godot, base=self.base)
        asset_pipeline.credits(self.project)
        return asset_pipeline.validate(self.project, base=self.base)

    def test_end_to_end_offline(self) -> None:
        report = self.run_pipeline()
        manifest = asset_pipeline.load_manifest(self.project)
        selections = manifest["selections"]
        self.assertEqual(selections["sm_enemy"]["asset_id"], "kenney:jungle/Characters/Soldier")
        self.assertEqual(selections["sm_enemy"]["animation_plan"]["missing"], [])
        self.assertTrue(selections["sm_tree"]["asset_id"].endswith(("PalmTree_1", "Tree_Jungle")))
        self.assertEqual(selections["sm_crate"]["status"], "fallback")
        self.assertTrue(selections["sm_crate"]["fidelity_reduced"])
        self.assertEqual(selections["sm_idol"]["status"], "unmet")
        godot = self.project / "godot"
        self.assertTrue((godot / "assets/models/sm_rock.glb").is_file())
        wrapper = (godot / "assets/wrapped/sm_tree.tscn").read_text()
        self.assertIn("CylinderShape3D", wrapper)
        enemy = (godot / "assets/wrapped/sm_enemy.tscn").read_text()
        self.assertNotIn("StaticBody3D", enemy, "characters get a gameplay-owned capsule, not a static body")
        rock = (godot / "assets/wrapped/sm_rock.tscn").read_text()
        self.assertIn("size = Vector3(1.5, 1, 1.4)", rock)
        meta = json.loads((godot / "assets/models/sm_rock.meta.json").read_text())
        self.assertEqual(meta["license"]["id"], "CC0-1.0")
        # Originals stay untouched in the cache.
        self.assertTrue(Path(selections["sm_rock"]["fetch"]["path"]).is_file())
        credits = (self.project / "CREDITS.md").read_text()
        self.assertIn("Soldier", credits)
        self.assertIn("CC0-1.0", (self.project / "ASSET_LICENSES.md").read_text())
        statuses = {(c["requirement"], c["check"]): c["status"] for c in report["checks"]}
        self.assertEqual(statuses[("sm_enemy", "animation_coverage")], "PASS")
        self.assertEqual(statuses[("sm_enemy", "godot_import")], "NOT RUN")
        self.assertEqual(statuses[("sm_idol", "selection")], "NOT RUN")
        self.assertEqual(report["status"], "PASS")
        asset_map = json.loads((self.project / "assets/asset_map.json").read_text())
        self.assertEqual(asset_map["sm_rock"], "res://assets/wrapped/sm_rock.tscn")

    def test_mandatory_unmet_requirement_fails_validation(self) -> None:
        self.spec["assets"][-1]["mandatory"] = True
        (self.project / "project.json").write_text(json.dumps(self.spec))
        report = self.run_pipeline()
        self.assertEqual(report["status"], "FAIL")

    def test_selection_is_kept_and_changes_are_recorded(self) -> None:
        asset_pipeline.resolve(self.project, offline=True, base=self.base)
        first = asset_pipeline.load_manifest(self.project)["selections"]["sm_rock"]["asset_id"]
        catalog = asset_catalog.load_catalog(self.base)
        catalog["records"]["kenney:jungle/Extra/Rock_Big"] = {
            **catalog["records"][first], "asset_id": "kenney:jungle/Extra/Rock_Big", "tags": ["rock", "boulder", "stone"]}
        asset_catalog.save_catalog(catalog, self.base)
        asset_pipeline.resolve(self.project, offline=True, base=self.base)
        self.assertEqual(asset_pipeline.load_manifest(self.project)["selections"]["sm_rock"]["asset_id"], first)
        del catalog["records"][first]
        asset_catalog.save_catalog(catalog, self.base)
        manifest = asset_pipeline.resolve(self.project, offline=True, base=self.base)
        self.assertNotEqual(manifest["selections"]["sm_rock"]["asset_id"], first)
        self.assertTrue(any(h["event"] == "selection_changed" and h["requirement"] == "sm_rock"
                            for h in manifest["history"]))

    def test_provider_outage_falls_back_to_other_sources(self) -> None:
        def down(url: str) -> bytes:
            raise OSError("503")
        manifest = asset_pipeline.resolve(self.project, offline=False, base=self.base, fetch=down)
        self.assertEqual(manifest["selections"]["sm_rock"]["status"], "selected")
        notes = " ".join(manifest["provider_notes"]["sm_rock"])
        self.assertIn("polyhaven: unavailable", notes)

    def test_import_never_overwrites_user_files(self) -> None:
        user_file = self.project / "godot/assets/models/sm_rock.glb"
        user_file.parent.mkdir(parents=True)
        user_file.write_bytes(b"my own rock")
        asset_pipeline.resolve(self.project, offline=True, base=self.base)
        asset_pipeline.fetch_selected(self.project, base=self.base)
        with self.assertRaises(AssetError):
            asset_pipeline.import_assets(self.project, run_godot=False, base=self.base)
        self.assertEqual(user_file.read_bytes(), b"my own rock")

    def test_inspection_can_reject_provider_metadata(self) -> None:
        catalog = asset_catalog.load_catalog(self.base)
        statue = next(r for r in catalog["records"].values() if r["title"] == "Statue_Soldier")
        statue["capabilities"]["skinned"] = None  # pretend the provider did not say
        statue["tags"] = ["soldier", "character", "enemy"]
        statue["capabilities"]["animations"] = ["Idle", "Walk", "Run", "Shoot", "Hit", "Death"]
        soldier = next(r for r in catalog["records"].values() if r["title"] == "Soldier")
        del catalog["records"][soldier["asset_id"]]
        asset_catalog.save_catalog(catalog, self.base)
        asset_pipeline.resolve(self.project, offline=True, base=self.base)
        self.assertEqual(asset_pipeline.load_manifest(self.project)["selections"]["sm_enemy"]["asset_id"],
                         statue["asset_id"])
        manifest = asset_pipeline.fetch_selected(self.project, base=self.base)
        self.assertEqual(manifest["selections"]["sm_enemy"]["status"], "rejected_after_inspection")
        manifest = asset_pipeline.resolve(self.project, offline=True, base=self.base)
        self.assertEqual(manifest["selections"]["sm_enemy"]["status"], "unmet")

    @unittest.skipUnless(GODOT, "Godot is not available")
    def test_godot_import_playback_and_navigation(self) -> None:
        project_godot = self.project / "godot/project.godot"
        project_godot.write_text('config_version=5\n[application]\nconfig/name="Jungle"\n'
                                 '[rendering]\nrenderer/rendering_method="gl_compatibility"\n')
        report = self.run_pipeline(run_godot=True)
        statuses = {(c["requirement"], c["check"]): c["status"] for c in report["checks"]}
        self.assertEqual(statuses[("sm_enemy", "godot_import")], "PASS", report)
        self.assertEqual(statuses[("sm_enemy", "animation_playback")], "PASS")
        self.assertEqual(statuses[("sm_crate", "godot_import")], "PASS")

        plan = {"schema_version": 1, "seed": 11, "bounds": {"min": [-15, -15], "max": [15, 15]},
                "terrain": {"type": "noise", "amplitude": 0.8, "scale": 12, "max_walkable_slope_deg": 35},
                "spawns": [{"id": "player", "pos": [0, -12]}],
                "enemy_spawns": [{"id": "e1", "pos": [-10, 10]}],
                "objectives": [{"id": "radio", "pos": [8, 10]}],
                "scatter": [{"asset": "sm_tree", "count": 20, "radius": 0.5, "min_spacing": 1.5,
                             "distribution": "poisson"},
                            {"asset": "sm_rock", "count": 8, "radius": 0.8}]}
        resolved = world_plan.generate(plan)
        self.assertEqual(world_plan.validate(resolved)["status"], "PASS")
        asset_map = json.loads((self.project / "assets/asset_map.json").read_text())
        godot_dir = self.project / "godot"
        self.assertEqual(self.godot_nav(resolved, asset_map, godot_dir), 0, getattr(self, "last_nav", ""))

        walled = copy.deepcopy(plan)
        walled["blockers"] = [{"min": [-15, 5], "max": [15, 6]}]
        walled_resolved = world_plan.generate(walled)
        self.assertEqual({c["check"]: c["status"] for c in world_plan.validate(walled_resolved)["checks"]}
                         ["enemy_navigation"], "FAIL")
        walled_resolved["landmarks"] = [{"id": f"wall_{i}", "pos": [x, 5.5], "radius": 2.0, "asset": "sm_ruin_wall",
                                         "rotation": 0} for i, x in enumerate(range(-14, 16, 4))]
        asset_map["sm_ruin_wall"] = self.solid_wall(godot_dir)
        self.assertNotEqual(self.godot_nav(walled_resolved, asset_map, godot_dir), 0,
                            "a wall across the map must break enemy navigation in Godot too")

    def solid_wall(self, godot_dir: Path) -> str:
        (godot_dir / "assets/wrapped/test_wall.tscn").write_text(
            '[gd_scene load_steps=2 format=3]\n\n[sub_resource type="BoxShape3D" id="S"]\n'
            'size = Vector3(4.2, 4, 1)\n\n[node name="Wall" type="StaticBody3D"]\n\n'
            '[node name="Shape" type="CollisionShape3D" parent="."]\n'
            'transform = Transform3D(1, 0, 0, 0, 1, 0, 0, 0, 1, 0, 2, 0)\nshape = SubResource("S")\n')
        return "res://assets/wrapped/test_wall.tscn"

    def godot_nav(self, resolved: dict, asset_map: dict, godot_dir: Path) -> int:
        text, _ = world_to_tscn.build(resolved, godot_dir, asset_map, False)
        (godot_dir / "scenes").mkdir(exist_ok=True)
        (godot_dir / "scenes/World.tscn").write_text(text)
        script = godot_dir / "scripts/world/heightfield_mesh.gd"
        script.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(ROOT / "tools/godot/runtime/heightfield_mesh.gd", script)
        shutil.copy2(ROOT / "tools/godot/checks/nav_check.gd", godot_dir / ".pipeline/nav_check.gd")
        subprocess.run([GODOT, "--headless", "--path", str(godot_dir), "--import"], capture_output=True,
                       timeout=600, check=False)
        result = subprocess.run([GODOT, "--headless", "--path", str(godot_dir), "--script",
                                 "res://.pipeline/nav_check.gd", "--", "res://scenes/World.tscn"],
                                text=True, capture_output=True, timeout=600, check=False)
        self.assertIn("NAV_POLYGONS=", result.stdout, result.stdout[-2000:] + result.stderr[-2000:])
        self.assertNotIn("SCRIPT ERROR", result.stderr)
        self.last_nav = result.stdout + result.stderr[-1500:]
        return result.returncode


class WorldConstraintTests(unittest.TestCase):
    PLAN = {"schema_version": 1, "seed": 5, "bounds": {"min": [-20, -20], "max": [20, 20]},
            "spawns": [{"id": "player", "pos": [0, -16]}], "objectives": [{"id": "goal", "pos": [0, 16]}],
            "scatter": [{"asset": "sm_tree", "count": 60, "radius": 0.5, "min_spacing": 1.0,
                         "distribution": "poisson"}]}

    def checks(self, plan: dict) -> dict:
        return {c["check"]: c["status"] for c in world_plan.validate(world_plan.generate(plan))["checks"]}

    def test_poisson_is_deterministic_and_spaced(self) -> None:
        first, second = world_plan.generate(self.PLAN), world_plan.generate(copy.deepcopy(self.PLAN))
        self.assertEqual(first["placements"], second["placements"])
        other = world_plan.generate(dict(self.PLAN, seed=6))
        self.assertNotEqual(first["placements"], other["placements"])
        points = [p["pos"] for p in first["placements"]]
        nearest = min(((a[0] - b[0]) ** 2 + (a[1] - b[1]) ** 2) ** 0.5
                      for i, a in enumerate(points) for b in points[i + 1:])
        self.assertGreaterEqual(nearest, 2.0 - 1e-6)
        self.assertEqual(self.checks(self.PLAN)["no_overlap"], "PASS")

    def test_spatial_hash_finds_the_same_overlaps_as_brute_force(self) -> None:
        resolved = world_plan.generate(self.PLAN)
        resolved["placements"].append(dict(resolved["placements"][0], id="dupe"))
        result = {c["check"]: c for c in world_plan.validate(resolved)["checks"]}
        self.assertEqual(result["no_overlap"]["status"], "FAIL")
        self.assertIn("dupe", result["no_overlap"]["detail"])

    def test_exclusions_and_slope_limits(self) -> None:
        plan = dict(self.PLAN, exclusions=[{"id": "arena", "circle": [0, 0, 6]}],
                    terrain={"type": "noise", "amplitude": 6.0, "scale": 8, "seed": 2})
        plan["scatter"] = [dict(plan["scatter"][0], max_slope_deg=20)]
        resolved = world_plan.generate(plan)
        for item in resolved["placements"]:
            self.assertGreaterEqual((item["pos"][0] ** 2 + item["pos"][1] ** 2) ** 0.5, 6.5 - 1e-6)
            self.assertLessEqual(world_plan.slope_deg(plan, *item["pos"]), 20 + 1e-6)
            self.assertAlmostEqual(item["y"], world_plan.height(plan, *item["pos"]), places=3)
        self.assertGreater(resolved["generation"][0]["rejected"].get("slope", 0), 0)
        checks = {c["check"]: c["status"] for c in world_plan.validate(resolved)["checks"]}
        self.assertEqual((checks["exclusions_clear"], checks["slope"], checks["on_terrain"]), ("PASS",) * 3)
        moved = copy.deepcopy(resolved)
        moved["placements"][0]["pos"] = [0.5, 0.5]
        self.assertEqual({c["check"]: c["status"] for c in world_plan.validate(moved)["checks"]}
                         ["exclusions_clear"], "FAIL")

    def test_flatten_zone_is_level(self) -> None:
        plan = {"terrain": {"type": "noise", "amplitude": 3, "scale": 10,
                            "flatten": [{"pos": [0, 0], "radius": 3}]}, "seed": 1}
        self.assertEqual(world_plan.height(plan, 1, 1), 0.0)
        self.assertNotEqual(world_plan.height(plan, 15, 15), world_plan.height(plan, 15.5, 17))

    def test_enemy_navigation_sightlines_and_combat_zones(self) -> None:
        plan = dict(self.PLAN, scatter=[], enemy_spawns=[{"id": "e1", "pos": [10, 10]}],
                    sightlines=[{"id": "view", "from": [0, -10], "to": [0, 10]}],
                    combat_zones=[{"id": "arena", "center": [0, 0], "radius": 5, "max_cover_ratio": 0.2}])
        self.assertEqual({k: v for k, v in self.checks(plan).items()
                          if k in ("enemy_navigation", "sightlines", "combat_zones")},
                         {"enemy_navigation": "PASS", "sightlines": "PASS", "combat_zones": "PASS"})
        blocked = dict(plan, blockers=[{"min": [-20, 4], "max": [20, 5]}],
                       obstacles=[{"id": "boulder", "asset": "sm_rock", "pos": [0, 0], "radius": 3.0}])
        checks = self.checks(blocked)
        self.assertEqual(checks["enemy_navigation"], "FAIL")
        self.assertEqual(checks["sightlines"], "FAIL")
        self.assertEqual(checks["combat_zones"], "FAIL")
        self.assertEqual(checks["objectives_reachable"], "FAIL")

    def test_scene_has_ground_navigation_and_collision_wrappers(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            godot = Path(temp)
            (godot / "assets/wrapped").mkdir(parents=True)
            (godot / "assets/wrapped/sm_tree.tscn").write_text("[gd_scene format=3]\n")
            plan = dict(self.PLAN, terrain={"type": "noise", "amplitude": 1, "scale": 10},
                        enemy_spawns=[{"id": "e1", "pos": [10, 10]}])
            text, _ = world_to_tscn.build(world_plan.generate(plan), godot,
                                          {"sm_tree": "res://assets/wrapped/sm_tree.tscn"}, False)
            for expected in ("HeightMapShape3D", "NavigationRegion3D", 'groups=["navigation_geometry"]',
                             "DirectionalLight3D", "Enemy_e1", "res://assets/wrapped/sm_tree.tscn",
                             "agent_radius = 0.5"):
                self.assertIn(expected, text)
            flat, _ = world_to_tscn.build(world_plan.generate(self.PLAN), godot,
                                          {"sm_tree": "res://assets/wrapped/sm_tree.tscn"}, False)
            self.assertIn("BoxShape3D", flat)
            self.assertNotIn("HeightMapShape3D", flat)


if __name__ == "__main__":
    unittest.main()
