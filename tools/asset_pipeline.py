#!/usr/bin/env python3
"""Asset Intelligence pipeline: requirements -> selection -> cache -> Godot.

  lopodev assets providers
  lopodev assets add-pack <zip|dir> --provider kenney --name nature-kit [--style stylized]
  lopodev assets requirements --project projects/<slug>
  lopodev assets search --project projects/<slug> [--requirement sm_tree] [--offline]
  lopodev assets resolve --project projects/<slug> [--offline] [--reselect]
  lopodev assets fetch --project projects/<slug>
  lopodev assets import --project projects/<slug> [--no-godot]
  lopodev assets credits --project projects/<slug>
  lopodev assets validate --project projects/<slug> [--strict]
  lopodev assets run --project projects/<slug> [--offline] [--no-godot]

Files:
  projects/<slug>/assets/requirements.json     what the game needs
  projects/<slug>/assets/asset_manifest.json   what was selected, why, and where it went
  projects/<slug>/assets/asset_map.json        requirement id -> res:// scene for world assembly
  projects/<slug>/artifacts/asset_validation.json  what was verified (PASS/FAIL/NOT RUN)
  projects/<slug>/CREDITS.md, ASSET_LICENSES.md    generated notices (managed block)

Selection never downloads; fetch never selects. An explicit (pinned) selection
is kept unless it becomes ineligible, and every change is recorded in history.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import asset_catalog  # noqa: E402
import asset_rank  # noqa: E402
import asset_requirements  # noqa: E402
import asset_sources  # noqa: E402
import integrations  # noqa: E402
import validate_spec  # noqa: E402
from asset_catalog import AssetError  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
MANIFEST_SCHEMA = "lopodev.asset-manifest/1"
VALIDATION_SCHEMA = "lopodev.asset-validation/1"
PROCEDURAL_SHAPES = {"box", "cylinder", "sphere", "capsule", "rock", "plane"}
BEGIN, END = "<!-- lopodev:assets:begin -->", "<!-- lopodev:assets:end -->"
STATIC_CLASSES = {"static_prop", "modular_environment", "animated_prop"}


# ---------------------------------------------------------------- project files

def paths(project: Path) -> dict[str, Path]:
    return {"requirements": project / "assets/requirements.json",
            "manifest": project / "assets/asset_manifest.json",
            "asset_map": project / "assets/asset_map.json",
            "validation": project / "artifacts/asset_validation.json",
            "credits": project / "CREDITS.md", "licenses": project / "ASSET_LICENSES.md"}


def load_spec(project: Path) -> dict:
    return json.loads((project / "project.json").read_text(encoding="utf-8"))


def godot_dir(project: Path, spec: dict) -> Path:
    return validate_spec._godot_dir(spec.get("godot_dir", "godot"), project.resolve())


def read_json(path: Path, default):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return default


def write_json(path: Path, data) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    os.replace(temporary, path)


def load_manifest(project: Path) -> dict:
    return read_json(paths(project)["manifest"], {"schema": MANIFEST_SCHEMA, "selections": {}, "history": []})


def note(manifest: dict, requirement_id: str, event: str, detail: str) -> None:
    manifest.setdefault("history", []).append(
        {"ts": asset_catalog.utc_now(), "requirement": requirement_id, "event": event, "detail": detail})


# ---------------------------------------------------------------- requirements

def requirements(project: Path) -> dict:
    result = asset_requirements.analyze(load_spec(project))
    write_json(paths(project)["requirements"], result)
    return result


# ---------------------------------------------------------------- search and selection

def candidates_for(requirement: dict, provs: dict, fetch, offline: bool, base: Path | None) -> tuple[list, list]:
    found: list[dict] = []
    provider_notes: list[str] = []
    names = requirement.get("providers") or list(provs)
    for name in names:
        provider = provs.get(name)
        if provider is None:
            provider_notes.append(f"{name}: not registered")
            continue
        status = provider.status()
        if not status["available"]:
            continue
        if offline and provider.automated:
            provider_notes.append(f"{name}: skipped (offline)")
            continue
        try:
            found += provider.search(requirement, fetch)
        except (AssetError, OSError, ValueError) as exc:
            provider_notes.append(f"{name}: unavailable ({exc}); other sources used")
    # Cached records (fetched earlier from any provider) are candidates too.
    seen = {c["asset_id"] for c in found}
    for record in asset_catalog.load_catalog(base)["records"].values():
        if record["asset_id"] not in seen and (not requirement.get("providers")
                                               or record["provider"] in requirement["providers"]):
            if record.get("local") and record["provider"] in provs:
                found.append(record)
    return found, provider_notes


def animation_sources(character: dict, required: list[str], base: Path | None) -> dict:
    """Find catalog clips for actions the character lacks, on a compatible skeleton."""
    caps = character.get("capabilities") or {}
    own = asset_rank.animation_map(required, caps.get("animations", []))
    missing = [action for action, clip in own.items() if not clip]
    plan = {"own": own, "external": {}, "missing": missing, "skeleton_checks": []}
    if not missing or not caps.get("joints"):
        return plan
    for record in asset_catalog.load_catalog(base)["records"].values():
        other = record.get("capabilities") or {}
        if record["asset_id"] == character["asset_id"] or not other.get("animations"):
            continue
        relation = asset_rank.compare_skeletons(other.get("joints", []), caps["joints"])
        if relation["relation"] == "incompatible":
            continue
        plan["skeleton_checks"].append({"source": record["asset_id"], **relation})
        found = asset_rank.animation_map(missing, other["animations"])
        for action, clip in found.items():
            if clip and action not in plan["external"]:
                plan["external"][action] = {"asset_id": record["asset_id"], "clip": clip,
                                            "relation": relation["relation"]}
    plan["missing"] = [action for action in missing if action not in plan["external"]]
    return plan


def select(requirement: dict, eligible: list, rejected: list, catalog: dict, previous: dict | None,
           reselect: bool, policy: dict, weights: dict, base: Path | None) -> dict:
    """Pick the selection for one requirement, applying pin and fallback rules."""
    excluded = set((previous or {}).get("excluded", []))
    eligible = [pair for pair in eligible if pair[0]["asset_id"] not in excluded]
    entry: dict = {"requirement": requirement["id"], "class": requirement["class"],
                   "excluded": sorted(excluded),
                   "rejected": [{"asset_id": c["asset_id"], "reason": r["rejection"]}
                                for c, r in rejected if r["rejection"] != "no semantic match"][:15],
                   "alternatives": [{"asset_id": c["asset_id"], "score": r["score"]} for c, r in eligible[1:6]],
                   "needs_review": [c["asset_id"] for c, r in rejected if r.get("license_decision") == "review"][:10]}
    by_id = {c["asset_id"]: (c, r) for c, r in eligible}
    if previous and previous.get("asset_id") and not reselect and previous.get("status") in ("selected", "fetched",
                                                                                          "imported"):
        if previous["asset_id"] in by_id:
            candidate, result = by_id[previous["asset_id"]]
            return {**entry, **choice(requirement, candidate, result, base), "pinned": previous.get("pinned", False),
                    "status": previous["status"], "import": previous.get("import"), "fetch": previous.get("fetch")}
        entry["replaced"] = {"asset_id": previous["asset_id"], "reason": "no longer eligible or not found"}
    if eligible:
        candidate, result = eligible[0]
        return {**entry, **choice(requirement, candidate, result, base), "status": "selected", "pinned": False}
    for fallback in requirement.get("fallbacks", []):
        kind, _, value = fallback.partition(":")
        if kind == "procedural" and value in PROCEDURAL_SHAPES:
            return {**entry, "status": "fallback", "fallback": fallback, "asset_id": None,
                    "procedural": value, "fidelity_reduced": True,
                    "reasons": [f"no eligible asset; procedural {value} keeps gameplay working"]}
        if kind == "asset" and value in catalog["records"]:
            candidate = catalog["records"][value]
            result = asset_rank.score(requirement, candidate, policy, weights)
            if result["eligible"]:
                return {**entry, **choice(requirement, candidate, result, base), "status": "selected",
                        "fallback": fallback, "fidelity_reduced": True, "pinned": False}
    relevant = [r for _, r in rejected if r["rejection"] != "no semantic match"]
    return {**entry, "status": "unmet", "asset_id": None,
            "reasons": [f"{len(relevant)} matching candidate(s) failed the license policy or hard requirements"
                        if relevant else "no matching candidates in available providers"]}


def choice(requirement: dict, candidate: dict, result: dict, base: Path | None) -> dict:
    data = {"asset_id": candidate["asset_id"], "provider": candidate["provider"],
            "source_url": candidate.get("source_url"), "title": candidate.get("title"),
            "license": candidate.get("license"), "license_decision": result["license_decision"],
            "score": result["score"], "score_parts": result["parts"], "reasons": result["reasons"],
            "capabilities": candidate.get("capabilities"), "thumbnail": candidate.get("thumbnail"),
            "record": candidate}
    if requirement["class"] == "skeletal_character":
        data["animation_plan"] = animation_sources(candidate, requirement.get("animations", []), base)
    return data


def resolve(project: Path, *, offline: bool = False, reselect: bool = False, fetch=asset_catalog.http_fetch,
            base: Path | None = None, registry: dict | None = None) -> dict:
    registry = registry or asset_sources.load_registry()
    provs = asset_sources.providers(registry, base)
    reqs = requirements(project)
    if reqs["errors"]:
        raise AssetError("invalid requirements: " + "; ".join(reqs["errors"]))
    manifest = load_manifest(project)
    catalog = asset_catalog.load_catalog(base)
    policy, weights = registry["license_policy"], registry["ranking_weights"]
    manifest.update({"schema": MANIFEST_SCHEMA, "project": reqs["project"], "license_policy": policy,
                     "weights": weights, "provider_notes": {}})
    selections = manifest.setdefault("selections", {})
    pending = [r for r in reqs["requirements"] if r["resolution"] == "discover"]
    for requirement in reqs["requirements"]:
        existing = selections.get(requirement["id"]) or {}
        if requirement["resolution"] == "derived" and existing.get("derive"):
            continue  # produced by `lopodev assets derive`; keep it
        if requirement["resolution"] != "discover":
            selections[requirement["id"]] = {"requirement": requirement["id"], "class": requirement["class"],
                                             "status": requirement["resolution"], "asset_id": None,
                                             "reasons": [f"resolution={requirement['resolution']} in project.json"]}
    for requirement in pending:
        found, notes = candidates_for(requirement, provs, fetch, offline, base)
        manifest["provider_notes"][requirement["id"]] = notes
        eligible, rejected = asset_rank.rank(requirement, found, policy, weights)
        previous = selections.get(requirement["id"])
        entry = select(requirement, eligible, rejected, catalog, previous, reselect, policy, weights, base)
        if previous and previous.get("asset_id") != entry.get("asset_id"):
            why = "reselect requested" if reselect else entry.get("replaced", {}).get("reason", "new best")
            note(manifest, requirement["id"], "selection_changed",
                 f"{previous.get('asset_id')} -> {entry.get('asset_id')} ({why})")
        elif not previous:
            note(manifest, requirement["id"], "selected", f"{entry.get('asset_id') or entry['status']}")
        selections[requirement["id"]] = entry
    # requirement:<id> fallbacks resolve after the referenced requirement.
    for requirement in pending:
        entry = selections[requirement["id"]]
        if entry["status"] != "unmet":
            continue
        for fallback in requirement.get("fallbacks", []):
            kind, _, other = fallback.partition(":")
            source = selections.get(other)
            if kind == "requirement" and source and source.get("asset_id"):
                selections[requirement["id"]] = {**source, "requirement": requirement["id"], "fallback": fallback,
                                                 "fidelity_reduced": True, "status": "selected", "import": None}
                note(manifest, requirement["id"], "fallback", f"reuses {other}")
                break
    write_json(paths(project)["manifest"], manifest)
    return manifest


# ---------------------------------------------------------------- fetch

def fetch_selected(project: Path, *, fetch=asset_catalog.http_fetch, base: Path | None = None,
                   registry: dict | None = None) -> dict:
    registry = registry or asset_sources.load_registry()
    provs = asset_sources.providers(registry, base)
    manifest = load_manifest(project)
    reqs = {r["id"]: r for r in read_json(paths(project)["requirements"], {"requirements": []})["requirements"]}
    catalog = asset_catalog.load_catalog(base)
    base_dir = base or asset_catalog.assets_dir()
    for requirement_id, entry in manifest.get("selections", {}).items():
        if not entry.get("asset_id") or entry["status"] not in ("selected", "fetched", "imported"):
            continue
        record = catalog["records"].get(entry["asset_id"]) or entry["record"]
        cached = Path(record["local"]["path"]) if record.get("local") else None
        from_cache = bool(cached and (cached.is_dir() or (cached.is_file() and asset_catalog.sha256_file(cached)
                                                          == record["local"].get("sha256"))))
        staging = base_dir / "staging" / re.sub(r"[^A-Za-z0-9_.-]", "_", record["asset_id"])
        try:
            if from_cache:
                local = cached
            else:
                if staging.exists():
                    shutil.rmtree(staging)  # leftovers of an interrupted fetch
                files = provs[record["provider"]].fetch(record, staging, fetch)
                model = asset_catalog.main_model(files) or files[0]
                local = model
                if staging.exists() and model.is_relative_to(staging):
                    material = record.get("kind") == "material"
                    source_root = staging / record["provider_id"] if material else model.parent
                    final = base_dir / "originals" / asset_catalog.sha256_file(model)
                    if final.exists():
                        shutil.rmtree(final)
                    shutil.copytree(source_root, final)
                    local = final if material else final / model.relative_to(source_root)
                    shutil.rmtree(staging)
        except (AssetError, KeyError) as exc:
            entry["fetch"] = {"status": "FAIL", "error": str(exc)}
            note(manifest, requirement_id, "fetch_failed", str(exc))
            if staging.exists():
                shutil.rmtree(staging)
            continue
        info = asset_catalog.inspect_model(local) if local.is_file() else {"inspected": False, "format": "material"}
        record = {**record, "local": {"path": str(local), "sha256": asset_catalog.sha256_file(local)
                                      if local.is_file() else None},
                  "inspection": info,
                  "capabilities": {**(record.get("capabilities") or {}),
                                   **({k: v for k, v in asset_sources.capabilities(info).items() if v is not None}
                                      if info.get("inspected") else {})},
                  "history": [] if from_cache else
                  [{"ts": asset_catalog.utc_now(), "event": "fetched", "detail": str(local)}]}
        record = asset_catalog.upsert(catalog, record)
        # Inspection can disprove provider metadata: re-apply the hard filters.
        requirement = reqs.get(requirement_id)
        if requirement:
            result = asset_rank.score(requirement, record, manifest["license_policy"], manifest["weights"])
            if not result["eligible"]:
                entry["status"] = "rejected_after_inspection"
                entry.setdefault("excluded", []).append(record["asset_id"])
                entry["fetch"] = {"status": "FAIL", "error": result["rejection"]}
                note(manifest, requirement_id, "rejected_after_inspection",
                     f"{record['asset_id']}: {result['rejection']}; run `lopodev assets resolve` again")
                continue
            entry.update(choice(requirement, record, result, base))
        previous_status = entry["status"]
        entry["fetch"] = {"status": "cached" if from_cache else "PASS", "path": str(local)}
        entry["status"] = "imported" if from_cache and previous_status == "imported" else "fetched"
        if not from_cache:
            note(manifest, requirement_id, "fetched", record["asset_id"])
    asset_catalog.save_catalog(catalog, base)
    write_json(paths(project)["manifest"], manifest)
    return manifest


# ---------------------------------------------------------------- Godot import

def pascal(identifier: str) -> str:
    return "".join(part.capitalize() for part in re.split(r"[^A-Za-z0-9]+", identifier) if part)


def normalization(requirement: dict, caps: dict) -> dict:
    """Uniform scale toward the required size; glTF is already +Y up, meters."""
    size = caps.get("size_m")
    target = requirement.get("size_m")
    scale, notes = 1.0, []
    if size and target and max(size) > 0:
        ratio = max(target) / max(size)
        if not 0.8 <= ratio <= 1.25:
            scale = round(ratio, 4)
            notes.append(f"scaled x{scale} toward {target} m (was {size} m)")
    elif size and max(size) > 50:
        notes.append(f"size {size} looks like centimeters; set size_m on the requirement")
    return {"scale": scale, "notes": notes}


def collision_block(requirement: dict, caps: dict, scale: float) -> tuple[list[str], list[str], dict]:
    """Sub-resource and node text for a simple collision shape, sized from bounds."""
    shape = requirement.get("collision", "none")
    if shape == "none" or requirement["class"] == "skeletal_character":
        return [], [], {"shape": shape if shape != "capsule" else "capsule (CharacterBody3D, gameplay-owned)"}
    lo, hi = caps.get("bounds_min"), caps.get("bounds_max")
    if not lo or not hi:
        lo, hi = [-0.5, 0.0, -0.5], [0.5, 1.0, 0.5]
    size = [max(0.05, (hi[i] - lo[i]) * scale) for i in range(3)]
    center = [(hi[i] + lo[i]) / 2 * scale for i in range(3)]
    notes = []
    if shape in ("convex", "trimesh"):
        notes.append(f"{shape} needs Godot mesh data; using a box from bounds (set the import option for exact shapes)")
        shape = "box"
    if shape == "box":
        resource = ['[sub_resource type="BoxShape3D" id="Shape"]', f"size = Vector3({size[0]:.4g}, {size[1]:.4g}, {size[2]:.4g})"]
    elif shape == "sphere":
        resource = ['[sub_resource type="SphereShape3D" id="Shape"]', f"radius = {max(size) / 2:.4g}"]
    elif shape in ("cylinder", "capsule"):
        kind = "CylinderShape3D" if shape == "cylinder" else "CapsuleShape3D"
        radius = max(size[0], size[2]) / 2 * (0.6 if shape == "cylinder" else 1.0)  # trunks, not canopies
        resource = [f'[sub_resource type="{kind}" id="Shape"]', f"radius = {radius:.4g}",
                    f"height = {max(size[1], radius * 2):.4g}"]
    else:
        return [], [], {"shape": shape, "error": "unknown shape"}
    nodes = ['[node name="Collision" type="StaticBody3D" parent="."]', "",
             '[node name="Shape" type="CollisionShape3D" parent="Collision"]',
             f"transform = Transform3D(1, 0, 0, 0, 1, 0, 0, 0, 1, {center[0]:.4g}, {center[1]:.4g}, {center[2]:.4g})",
             'shape = SubResource("Shape")', ""]
    return resource, nodes, {"shape": shape, "size": [round(v, 4) for v in size], "notes": notes}


def procedural_mesh(shape: str) -> list[str]:
    meshes = {"box": 'BoxMesh', "cylinder": "CylinderMesh", "sphere": "SphereMesh", "capsule": "CapsuleMesh",
              "rock": "SphereMesh", "plane": "PlaneMesh"}
    lines = [f'[sub_resource type="{meshes[shape]}" id="Mesh"]']
    if shape == "rock":
        lines += ["radial_segments = 6", "rings = 3"]
    return lines


def wrapper_scene(requirement: dict, model_res: str | None, caps: dict, norm: dict,
                  procedural: str | None) -> tuple[str, dict]:
    collision_res, collision_nodes, collision = collision_block(requirement, caps, norm["scale"])
    ext = [f'[ext_resource type="PackedScene" path="{model_res}" id="Model"]'] if model_res else []
    sub = (procedural_mesh(procedural) + [""] if procedural else []) + (collision_res + [""] if collision_res else [])
    steps = len(ext) + (1 if procedural else 0) + (1 if collision_res else 0) + 1
    scale = norm["scale"]
    lines = [f"[gd_scene load_steps={steps} format=3]", "", *ext, "", *sub,
             f'[node name="{pascal(requirement["id"])}" type="Node3D"]',
             f'metadata/lopodev_requirement = "{requirement["id"]}"',
             f'metadata/lopodev_collision = "{collision["shape"]}"', ""]
    if model_res:
        lines += ['[node name="Model" parent="." instance=ExtResource("Model")]',
                  f"transform = Transform3D({scale}, 0, 0, 0, {scale}, 0, 0, 0, {scale}, 0, 0, 0)", ""]
    else:
        lift = 0.5 if procedural in ("box", "cylinder", "sphere", "rock", "capsule") else 0.0
        lines += ['[node name="Model" type="MeshInstance3D" parent="."]',
                  f"transform = Transform3D(1, 0, 0, 0, 1, 0, 0, 0, 1, 0, {lift}, 0)", 'mesh = SubResource("Mesh")', ""]
    lines += collision_nodes
    return "\n".join(lines).rstrip() + "\n", collision


def material_resource(requirement_id: str, files: list[Path], res_dir: str) -> str | None:
    """StandardMaterial3D from common PBR map names (ambientCG, Poly Haven)."""
    roles = {"albedo_texture": ("_color", "_diff", "albedo", "basecolor", "diffuse"),
             "normal_texture": ("_normalgl", "_nor_gl", "normal_gl"),
             "roughness_texture": ("_roughness", "_rough")}
    found = {}
    for role, keys in roles.items():
        for path in sorted(files):
            if path.suffix.lower() in (".jpg", ".jpeg", ".png") and any(k in path.stem.lower() for k in keys):
                found[role] = path.name
                break
    if "albedo_texture" not in found:
        return None
    ext = [f'[ext_resource type="Texture2D" path="{res_dir}/{name}" id="{role}"]' for role, name in found.items()]
    body = [f'{role} = ExtResource("{role}")' for role in found]
    if "normal_texture" in found:
        body.insert(0, "normal_enabled = true")
    return "\n".join([f'[gd_resource type="StandardMaterial3D" load_steps={len(ext) + 1} format=3]', "", *ext, "",
                      "[resource]", f'resource_name = "{requirement_id}"', *body]) + "\n"


def write_owned(path: Path, content: bytes, owned: dict, key: str) -> None:
    """Write a generated file; refuse to replace a file LopoDev did not write."""
    digest = asset_catalog.sha256_bytes(content)
    if path.exists():
        current = asset_catalog.sha256_file(path)
        if current == digest:
            owned[key] = digest
            return
        if owned.get(key) != current:
            raise AssetError(f"{path} exists and was not written by LopoDev; move it or pick another id")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)
    owned[key] = digest


def import_assets(project: Path, *, run_godot: bool = True, base: Path | None = None) -> dict:
    spec = load_spec(project)
    gdir = godot_dir(project, spec)
    if not (gdir / "project.godot").is_file():
        raise AssetError(f"no Godot project at {gdir}")
    manifest = load_manifest(project)
    reqs = {r["id"]: r for r in read_json(paths(project)["requirements"], {"requirements": []})["requirements"]}
    owned = manifest.setdefault("owned_files", {})
    asset_map = {}
    checks = []
    for requirement_id, entry in manifest.get("selections", {}).items():
        requirement = reqs.get(requirement_id)
        if requirement is None:
            continue
        if entry["status"] == "provided":
            continue
        if entry["status"] == "fallback" and entry.get("procedural"):
            text, collision = wrapper_scene(requirement, None, {}, {"scale": 1.0, "notes": []}, entry["procedural"])
            target = gdir / "assets/wrapped" / f"{requirement_id}.tscn"
            write_owned(target, text.encode(), owned, str(target.relative_to(gdir)))
            res = f"res://assets/wrapped/{requirement_id}.tscn"
            entry["import"] = {"status": "procedural", "scene": res, "collision": collision}
            asset_map[requirement_id] = res
            checks.append({"id": requirement_id, "scene": res, "min_meshes": 1, "animations": []})
            continue
        if entry["status"] not in ("fetched", "imported") or not entry.get("fetch"):
            continue
        local = Path(entry["fetch"]["path"])
        inspection = (entry.get("record") or {}).get("inspection") or {}
        caps = {**(entry.get("capabilities") or {}),
                "bounds_min": inspection.get("bounds_min"), "bounds_max": inspection.get("bounds_max")}
        if requirement["class"] == "material":
            files = [p for p in (local.rglob("*") if local.is_dir() else local.parent.rglob("*")) if p.is_file()]
            target_dir = gdir / "assets/materials" / requirement_id
            images = [p for p in files if p.suffix.lower() in (".jpg", ".jpeg", ".png")]
            for image in images:
                write_owned(target_dir / image.name, image.read_bytes(), owned, f"assets/materials/{requirement_id}/{image.name}")
            text = material_resource(requirement_id, [target_dir / p.name for p in images],
                                     f"res://assets/materials/{requirement_id}")
            if text is None:
                entry["import"] = {"status": "FAIL", "error": "no albedo/color map found"}
                continue
            target = gdir / "assets/materials" / f"{requirement_id}.tres"
            write_owned(target, text.encode(), owned, f"assets/materials/{requirement_id}.tres")
            entry["import"] = {"status": "copied", "material": f"res://assets/materials/{requirement_id}.tres"}
            entry["status"] = "imported"
            asset_map[requirement_id] = entry["import"]["material"]
            continue
        # Models: original stays in the cache; the project gets a copy plus a wrapper scene.
        if local.suffix.lower() == ".glb":
            target = gdir / "assets/models" / f"{requirement_id}.glb"
            write_owned(target, local.read_bytes(), owned, f"assets/models/{requirement_id}.glb")
            model_res = f"res://assets/models/{requirement_id}.glb"
        elif local.suffix.lower() == ".gltf":
            folder = gdir / "assets/models" / requirement_id
            for path in local.parent.rglob("*"):
                if path.is_file():
                    relative = path.relative_to(local.parent)
                    write_owned(folder / relative, path.read_bytes(), owned,
                                f"assets/models/{requirement_id}/{relative.as_posix()}")
            model_res = f"res://assets/models/{requirement_id}/{local.name}"
        else:
            entry["import"] = {"status": "FAIL", "error": f"{local.suffix} needs conversion to glTF "
                                                          "(Blender processing task) before import"}
            continue
        norm = normalization(requirement, caps)
        text, collision = wrapper_scene(requirement, model_res, caps, norm, None)
        target = gdir / "assets/wrapped" / f"{requirement_id}.tscn"
        write_owned(target, text.encode(), owned, f"assets/wrapped/{requirement_id}.tscn")
        meta = {"requirement": requirement_id, "asset_id": entry["asset_id"], "provider": entry["provider"],
                "source_url": entry.get("source_url"), "license": entry.get("license"),
                "original_sha256": asset_catalog.sha256_file(local), "normalization": norm, "collision": collision}
        write_owned(gdir / "assets/models" / f"{requirement_id}.meta.json",
                    (json.dumps(meta, indent=2) + "\n").encode(), owned, f"assets/models/{requirement_id}.meta.json")
        res = f"res://assets/wrapped/{requirement_id}.tscn"
        plan = entry.get("animation_plan") or {}
        clips = [clip for clip in (plan.get("own") or {}).values() if clip]
        clips += [clip for clip in ((entry.get("derive") or {}).get("rig") or {}).get("clips", [])
                  if clip not in clips]
        entry["import"] = {"status": "copied", "model": model_res, "scene": res, "normalization": norm,
                           "collision": collision}
        entry["status"] = "imported"
        asset_map[requirement_id] = res
        checks.append({"id": requirement_id, "scene": res, "min_meshes": 1, "animations": clips,
                       "skeleton": requirement["class"] == "skeletal_character"})
    write_json(paths(project)["asset_map"], asset_map)
    manifest["godot_check"] = run_import_check(gdir, checks) if run_godot else \
        {"status": "NOT RUN", "reason": "--no-godot"}
    for item in manifest["godot_check"].get("assets", []):
        entry = manifest["selections"].get(item["id"])
        if entry and entry.get("import"):
            entry["import"]["godot"] = item
    write_json(paths(project)["manifest"], manifest)
    return manifest


def run_import_check(gdir: Path, checks: list[dict]) -> dict:
    godot = integrations.pinned_godot(ROOT)
    if not godot:
        return {"status": "NOT RUN", "reason": "Godot not found (set GODOT or install it)"}
    if not checks:
        return {"status": "NOT RUN", "reason": "nothing to check"}
    stage = gdir / ".pipeline"
    stage.mkdir(parents=True, exist_ok=True)
    shutil.copy2(ROOT / "tools/godot/checks/asset_import_check.gd", stage / "asset_import_check.gd")
    (stage / "asset_checks.json").write_text(json.dumps({"assets": checks}), encoding="utf-8")
    log_dir = gdir / ".pipeline/logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    imported = subprocess.run([godot, "--headless", "--path", str(gdir), "--import"], text=True,
                              capture_output=True, timeout=900, check=False)
    (log_dir / "asset_import.log").write_text(imported.stdout + imported.stderr, encoding="utf-8")
    result = subprocess.run([godot, "--headless", "--path", str(gdir), "--script",
                             "res://.pipeline/asset_import_check.gd"], text=True, capture_output=True,
                            timeout=600, check=False)
    (log_dir / "asset_check.log").write_text(result.stdout + result.stderr, encoding="utf-8")
    assets = [json.loads(line.removeprefix("ASSET_IMPORT_RESULT "))
              for line in result.stdout.splitlines() if line.startswith("ASSET_IMPORT_RESULT ")]
    import_errors = [line for line in (imported.stdout + imported.stderr).splitlines()
                     if line.startswith(("ERROR:", "SCRIPT ERROR:"))]
    status = "PASS" if assets and len(assets) == len(checks) and all(a["status"] == "PASS" for a in assets) \
        and imported.returncode == 0 and not import_errors else "FAIL"
    return {"status": status, "import_exit": imported.returncode, "import_errors": import_errors[:10],
            "check_exit": result.returncode, "assets": assets,
            "log": str(log_dir / "asset_check.log")}


# ---------------------------------------------------------------- credits and validation

def credits(project: Path, registry: dict | None = None) -> str:
    registry = registry or asset_sources.load_registry()
    manifest = load_manifest(project)
    rows, providers_used = [], set()
    for requirement_id, entry in sorted(manifest.get("selections", {}).items()):
        if not entry.get("asset_id"):
            continue
        license_info = entry.get("license") or {}
        providers_used.add(entry["provider"])
        attribution = license_info.get("attribution") or (
            f"\"{entry.get('title')}\" by {license_info.get('creator') or 'unknown creator'}, "
            f"{license_info.get('id')}, {entry.get('source_url')}")
        rows.append(f"| {requirement_id} | {entry.get('title')} | {entry['provider']} | "
                    f"{license_info.get('creator') or '-'} | {license_info.get('id')} | {entry.get('source_url') or '-'} | "
                    f"{attribution if entry.get('license_decision') == 'attribution' else 'not required'} |")
    lines = [BEGIN, "## Third-party assets (generated by `lopodev assets credits`)", "",
             "| Requirement | Asset | Provider | Creator | License | Source | Attribution |",
             "|---|---|---|---|---|---|---|", *rows, ""]
    for name in sorted(providers_used):
        credit = registry["providers"].get(name, {}).get("credit")
        if credit:
            lines.append(f"- {credit}")
    lines.append(END)
    block = "\n".join(lines) + "\n"
    for target in (paths(project)["credits"], paths(project)["licenses"]):
        existing = target.read_text(encoding="utf-8") if target.is_file() else \
            ("# Credits\n\n" if target.name == "CREDITS.md" else "# Asset Licenses\n\n")
        if BEGIN in existing and END in existing:
            head, rest = existing.split(BEGIN, 1)
            updated = head + block + rest.split(END, 1)[1].lstrip("\n")
        else:
            updated = existing.rstrip("\n") + "\n\n" + block
        target.write_text(updated, encoding="utf-8")
    return block


def validate(project: Path, base: Path | None = None, registry: dict | None = None) -> dict:
    registry = registry or asset_sources.load_registry()
    manifest = load_manifest(project)
    reqs = {r["id"]: r for r in read_json(paths(project)["requirements"], {"requirements": []})["requirements"]}
    policy = registry["license_policy"]
    gdir = godot_dir(project, load_spec(project))
    results: list[dict] = []

    def record(requirement_id: str, check: str, status: str, detail: str) -> None:
        results.append({"requirement": requirement_id, "check": check, "status": status, "detail": detail})

    if not reqs:
        record("*", "requirements", "FAIL", "no requirements; run `lopodev assets requirements`")
    for requirement_id, requirement in reqs.items():
        entry = manifest.get("selections", {}).get(requirement_id)
        if requirement["resolution"] == "derived" and not (entry or {}).get("derive"):
            record(requirement_id, "derive", "FAIL" if requirement["mandatory"] else "NOT RUN",
                   f"not derived yet: lopodev assets derive --from {requirement.get('derive_from')} "
                   f"--id {requirement_id} --script <edit.py>")
            continue
        if requirement["resolution"] not in ("discover", "derived"):
            record(requirement_id, "resolution", "NOT RUN",
                   f"{requirement['resolution']}: validated by its own pipeline (validate_asset.py)")
            continue
        if (entry or {}).get("derive"):
            derived = entry["derive"]
            record(requirement_id, "derive", derived.get("status", "FAIL"),
                   f"from {derived.get('source_asset')} ({len(derived.get('operations', []))} operations); "
                   f"previews {derived.get('previews', {}).get('after', [])[:1]}")
            if derived.get("rig"):
                weights = derived.get("weights", "NOT RUN")
                record(requirement_id, "rig_weights", "PASS" if weights == "PASS" else "FAIL" if weights.startswith(
                    "FAIL") else "NOT RUN", f"{derived['rig'].get('mode')}: {weights}; inspect clip frames "
                    f"{derived.get('previews', {}).get('clips', [])[:2]}")
        if not entry or entry["status"] in ("unmet", "rejected_after_inspection"):
            status = "FAIL" if requirement["mandatory"] else "NOT RUN"
            record(requirement_id, "selection", status, (entry or {}).get("reasons", ["not resolved"])[0]
                   if entry and entry.get("reasons") else "not resolved")
            continue
        if entry["status"] == "fallback":
            record(requirement_id, "selection", "PASS", f"procedural fallback {entry.get('procedural')} "
                                                         "(visual fidelity reduced)")
        else:
            license_id = (entry.get("license") or {}).get("id", "unknown")
            decision = asset_sources.license_decision(license_id, policy)["decision"]
            record(requirement_id, "license", "PASS" if decision in ("allowed", "attribution") else "FAIL",
                   f"{license_id} ({decision}); evidence: {(entry.get('license') or {}).get('evidence')}")
            fetched = entry.get("fetch") or {}
            if fetched.get("status") in ("PASS", "cached"):
                path = Path(fetched["path"])
                record(requirement_id, "integrity", "PASS" if path.exists() else "FAIL",
                       str(path) if path.exists() else f"cached file missing: {path}")
            else:
                record(requirement_id, "integrity", "FAIL" if fetched.get("status") == "FAIL" else "NOT RUN",
                       fetched.get("error", "not fetched"))
            caps = entry.get("capabilities") or {}
            inspection = (entry.get("record") or {}).get("inspection") or {}
            if requirement["class"] != "material":
                missing = inspection.get("missing_files") or []
                record(requirement_id, "dependencies", "FAIL" if missing else
                       ("PASS" if inspection.get("inspected") else "NOT RUN"),
                       f"missing {missing}" if missing else "all referenced files present"
                       if inspection.get("inspected") else "not inspected")
                norm = (entry.get("import") or {}).get("normalization") or {}
                anomalies = [n for n in norm.get("notes", []) if "centimeters" in n]
                record(requirement_id, "scale", "FAIL" if anomalies else ("PASS" if caps.get("size_m") else "NOT RUN"),
                       "; ".join(anomalies or norm.get("notes", [])) or f"size {caps.get('size_m')} m")
            if requirement["rig"] == "required":
                record(requirement_id, "rig", "PASS" if caps.get("skinned") else
                       ("NOT RUN" if caps.get("skinned") is None else "FAIL"),
                       f"{len(caps.get('joints', []))} joints" if caps.get("skinned") else "no skin")
            if requirement.get("animations"):
                plan = entry.get("animation_plan") or {}
                missing = plan.get("missing", requirement["animations"])
                external = plan.get("external", {})
                record(requirement_id, "animation_coverage", "FAIL" if missing else "PASS",
                       f"missing {missing}" if missing else
                       f"own {[a for a, c in (plan.get('own') or {}).items() if c]}, external {sorted(external)}")
                if external:
                    unproven = [a for a, e in external.items() if e["relation"] != "identical"]
                    record(requirement_id, "retarget", "NOT RUN" if unproven else "PASS",
                           f"retarget needed for {unproven} (not automated; pick a character with a "
                           "compatible set or retarget in Blender)" if unproven else
                           "external clips share an identical skeleton")
        imported = entry.get("import") or {}
        godot = imported.get("godot")
        if requirement["class"] == "material":
            record(requirement_id, "import", "PASS" if imported.get("material") else "NOT RUN",
                   imported.get("material") or "not imported")
            continue
        if not imported or imported.get("status") == "FAIL":
            record(requirement_id, "import", "FAIL" if imported else "NOT RUN",
                   imported.get("error", "not imported"))
            continue
        scene = gdir / imported["scene"].removeprefix("res://")
        record(requirement_id, "wrapper_scene", "PASS" if scene.is_file() else "FAIL", imported["scene"])
        collision = imported.get("collision") or {}
        expected = requirement["collision"]
        record(requirement_id, "collision", "PASS" if expected == "none" or requirement["class"] ==
               "skeletal_character" or collision.get("size") else "FAIL",
               f"{collision.get('shape')} {collision.get('size', '')}".strip())
        if godot:
            record(requirement_id, "godot_import", godot["status"], godot.get("detail", ""))
            if requirement.get("animations"):
                record(requirement_id, "animation_playback", godot.get("playback_status", "NOT RUN"),
                       godot.get("playback", ""))
        else:
            record(requirement_id, "godot_import", "NOT RUN",
                   (manifest.get("godot_check") or {}).get("reason", "Godot check not run"))
    statuses = [r["status"] for r in results]
    report = {"schema": VALIDATION_SCHEMA, "project": manifest.get("project"), "generated": asset_catalog.utc_now(),
              "status": "FAIL" if "FAIL" in statuses else "PASS",
              "counts": {s: statuses.count(s) for s in ("PASS", "FAIL", "NOT RUN")}, "checks": results}
    write_json(paths(project)["validation"], report)
    return report


# ---------------------------------------------------------------- derived assets

def source_for(project: Path, reference: str, base: Path | None) -> tuple[Path, dict]:
    """Resolve a requirement id (its fetched asset) or a catalog asset id to (file, record)."""
    manifest = load_manifest(project)
    catalog = asset_catalog.load_catalog(base)
    entry = manifest.get("selections", {}).get(reference)
    if entry:
        if not entry.get("asset_id") or not (entry.get("fetch") or {}).get("path"):
            raise AssetError(f"{reference} has no fetched asset yet; run `lopodev assets run` first")
        record = catalog["records"].get(entry["asset_id"]) or entry.get("record") or {}
        return Path(entry["fetch"]["path"]), {**record, "license": entry.get("license") or record.get("license")}
    record = catalog["records"].get(reference)
    if record and record.get("local"):
        return Path(record["local"]["path"]), record
    raise AssetError(f"{reference!r} is neither a selected requirement nor a cached catalog asset")


def inherited_license(records: list[dict], policy: dict) -> dict:
    """The derived asset's license: CC0 stays CC0; any CC-BY input makes it CC-BY with credits."""
    ids, credits = [], []
    for record in records:
        license_info = record.get("license") or {}
        license_id = license_info.get("id", "unknown")
        decision = asset_sources.license_decision(license_id, policy)["decision"]
        if decision not in ("allowed", "attribution"):
            raise AssetError(f"{record.get('asset_id')}: license {license_id} does not allow a modified "
                             "copy under the policy (ND, NC, unknown or review); pick another source")
        ids.append(license_id)
        if decision == "attribution":
            credits.append(f"\"{record.get('title')}\" by {license_info.get('creator') or 'unknown creator'}, "
                           f"{license_id}, {record.get('source_url')} (modified)")
    attribution_ids = [i for i in ids if i != "CC0-1.0"]
    license_id = "CC0-1.0" if not attribution_ids else sorted(attribution_ids)[-1]
    return {"id": license_id, "evidence": "inherited from " + ", ".join(r.get("asset_id", "?") for r in records),
            "creator": None, "attribution": "; ".join(credits) or None}


def blender_command(live: bool) -> list[str]:
    import live_session
    blender = live_session.find_blender()
    if not blender:
        raise AssetError("Blender not found (set BLENDER)")
    return [blender, "--factory-startup"] if live else [blender, "-b", "--factory-startup"]


def derive(project: Path, source_ref: str, target_id: str, *, script: Path | None = None,
           from_blend: Path | None = None, extras: dict[str, str] | None = None, live: bool | None = None,
           hold: float = 3.0, base: Path | None = None, registry: dict | None = None) -> dict:
    """Edit an existing asset in Blender into a new derived asset (the source is never modified)."""
    import live_session
    registry = registry or asset_sources.load_registry()
    if not re.fullmatch(r"(sm|rig)_[a-z0-9_]+", target_id):
        raise AssetError("derived ids look like sm_<noun> (or rig_<noun>)")
    if not script and not from_blend:
        raise AssetError("give --script <edit.py> (scripted) or --from-blend <file.blend> (edited live)")
    spec = load_spec(project)
    reqs = {r["id"]: r for r in requirements(project)["requirements"]}
    source_path, source_record = source_for(project, source_ref, base)
    extra_inputs = {name: source_for(project, ref, base) for name, ref in (extras or {}).items()}
    license_info = inherited_license([source_record, *[r for _, r in extra_inputs.values()]],
                                     registry["license_policy"])
    workspace = project.resolve().parent.parent
    live = live_session.enabled(workspace) if live is None else live
    inputs = [asset_catalog.sha256_file(source_path) if source_path.is_file() else source_ref,
              *(asset_catalog.sha256_file(path) if path.is_file() else str(path) for path, _ in extra_inputs.values()),
              asset_catalog.sha256_file(script) if script else asset_catalog.sha256_file(from_blend)]
    toolkit = [asset_catalog.sha256_file(ROOT / "tools/blender" / name)
               for name in ("derive_asset.py", "lib_edit.py", "lib_rig.py", "lib_asset.py")]
    key = asset_catalog.sha256_bytes("|".join(inputs + toolkit).encode())
    manifest = load_manifest(project)
    previous = manifest.get("selections", {}).get(target_id) or {}
    cached = previous.get("derive", {})
    if cached.get("key") == key and cached.get("status") == "PASS" and Path(cached.get("glb", "")).is_file():
        return {**previous, "unchanged": True}

    base_dir = base or asset_catalog.assets_dir()
    staging = base_dir / "staging" / f"derive_{target_id}"
    if staging.exists():
        shutil.rmtree(staging)
    staging.mkdir(parents=True)
    blend_out = project / "blender" / f"{target_id}.blend"
    owned = manifest.setdefault("owned_files", {})
    owned_key = f"blender/{target_id}.blend"
    if blend_out.exists() and owned.get(owned_key) != asset_catalog.sha256_file(blend_out):
        raise AssetError(f"{blend_out} exists and was not written by LopoDev; move it or choose another --id")
    requirement = reqs.get(target_id, {"class": "static_prop"})
    previews = project / "artifacts/assets" / requirement["class"] / target_id
    report_path = staging / "report.json"
    command = [*blender_command(live), "--python", str(ROOT / "tools/blender/derive_asset.py"), "--",
               "--source", str(source_path), "--out-glb", str(staging / f"{target_id}.glb"),
               "--out-blend", str(blend_out), "--previews", str(previews), "--report", str(report_path),
               "--hold", str(hold), *(["--live"] if live else [])]
    command += ["--script", str(script.resolve())] if script else ["--from-blend", str(from_blend.resolve())]
    for name, (path, _) in extra_inputs.items():
        command += ["--with", f"{name}={path}"]
    log = project / "artifacts/logs" / f"derive_{target_id}.log"
    log.parent.mkdir(parents=True, exist_ok=True)
    result = subprocess.run(command, text=True, capture_output=True, timeout=1800, check=False)
    log.write_text(result.stdout + result.stderr, encoding="utf-8")
    if blend_out.exists():
        owned[owned_key] = asset_catalog.sha256_file(blend_out)
    report = read_json(report_path, {"status": "FAIL", "error": f"no report; see {log}"})
    if report.get("status") != "PASS":
        note(manifest, target_id, "derive_failed", report.get("error", "")[-500:])
        write_json(paths(project)["manifest"], manifest)
        raise AssetError(f"derive failed: {report.get('error', '')[-800:]} (log {log})")
    glb = Path(report["glb"])
    budget = requirement.get("budget_triangles") or 10**9
    check = subprocess.run([sys.executable, str(ROOT / "tools/blender/validate_asset.py"), str(glb),
                            "--require-material", "--max-triangles", str(budget)],
                           text=True, capture_output=True, check=False)
    stored, digest = asset_catalog.store_bytes(glb.read_bytes(), f"{target_id}.glb", base)
    info = asset_catalog.inspect_model(stored)
    slug = spec.get("slug", project.name)
    record = {"schema_version": 1, "asset_id": f"derived:{slug}/{target_id}", "provider": "derived",
              "provider_id": f"{slug}/{target_id}", "kind": "model", "title": target_id,
              "tags": requirement.get("terms", []), "categories": [], "style": requirement.get("style", []),
              "format": "glb", "source_url": source_record.get("source_url"), "license": license_info,
              "local": {"path": str(stored), "sha256": digest},
              "derived_from": [{"asset_id": source_record.get("asset_id"), "sha256": inputs[0]},
                               *[{"asset_id": r.get("asset_id"), "name": n} for n, (_, r) in extra_inputs.items()]],
              "capabilities": asset_sources.capabilities(info), "inspection": info,
              "history": [{"ts": asset_catalog.utc_now(), "event": "derived",
                           "detail": f"{script or from_blend} ({len(report.get('operations', []))} operations)"}]}
    catalog = asset_catalog.load_catalog(base)
    asset_catalog.upsert(catalog, record)
    asset_catalog.save_catalog(catalog, base)
    entry = {"requirement": target_id, "class": requirement["class"], "status": "fetched",
             "asset_id": record["asset_id"], "provider": "derived", "title": target_id,
             "source_url": record["source_url"], "license": license_info, "license_decision":
             "allowed" if license_info["id"] == "CC0-1.0" else "attribution", "capabilities": record["capabilities"],
             "record": record, "reasons": [f"derived from {source_record.get('asset_id')}"],
             "fetch": {"status": "PASS", "path": str(stored)},
             "derive": {"status": "PASS" if check.returncode == 0 else "FAIL", "key": key, "glb": str(stored),
                        "blend": str(blend_out), "script": str(script) if script else None,
                        "from_blend": str(from_blend) if from_blend else None,
                        "reproducible": bool(script), "source_asset": source_record.get("asset_id"),
                        "operations": report.get("operations", []), "previews": report.get("previews", {}),
                        "rig": report.get("rig"),
                        "before": report.get("before"), "after": report.get("after"), "live": live,
                        "blender_version": report.get("blender_version"), "log": str(log),
                        "validation": check.stdout.strip().splitlines()[:1]}}
    if requirement.get("animations"):
        entry["animation_plan"] = animation_sources(record, requirement["animations"], base)
    manifest.setdefault("selections", {})[target_id] = entry
    note(manifest, target_id, "derived", f"{source_record.get('asset_id')} -> {record['asset_id']}")
    write_json(paths(project)["manifest"], manifest)
    shutil.rmtree(staging, ignore_errors=True)
    return entry


def rig(project: Path, source_ref: str, target_id: str, mode: str, *, clips: list[str] | None = None,
        chains: list[str] | None = None, donor: str | None = None, live: bool | None = None,
        hold: float = 3.0, base: Path | None = None) -> dict:
    """Rig/animate an existing asset; a derive with a generated, recorded edit script."""
    if mode == "transfer" and not donor:
        raise AssetError("--mode transfer needs --donor <rigged requirement or asset id>")
    if mode == "creature" and not chains:
        raise AssetError("--mode creature needs at least one --chain Name=x,y,z:x,y,z:segments")
    if mode == "parts" and not clips:
        raise AssetError("--mode parts needs --clip name:Part:channel:amount:seconds")
    calls = {"parts": f"ctx.rig.parts(ctx, {clips!r})",
             "humanoid": f"ctx.rig.humanoid(ctx, {clips or None!r})",
             "transfer": 'ctx.rig.transfer(ctx, ctx.extra("donor"))',
             "creature": f"ctx.rig.creature(ctx, {chains!r}, {clips or None!r})"}
    if mode not in calls:
        raise AssetError(f"unknown rig mode {mode!r}")
    script = project / "blender" / f"rig_{target_id}.py"
    text = (f'"""Generated by `lopodev assets rig --mode {mode}`; edit freely and rerun derive."""\n\n\n'
            f"def edit(ctx):\n    {calls[mode]}\n")
    script.parent.mkdir(parents=True, exist_ok=True)
    if not script.exists() or script.read_text(encoding="utf-8") != text:
        script.write_text(text, encoding="utf-8")
    entry = derive(project, source_ref, target_id, script=script, extras={"donor": donor} if donor else None,
                   live=live, hold=hold, base=base)
    rig_info = (entry.get("derive") or {}).get("rig") or {}
    problems = []
    if rig_info.get("unweighted_vertices"):
        problems.append(f"{rig_info['unweighted_vertices']} unweighted vertices")
    if rig_info.get("dead_bones"):
        problems.append(f"{len(rig_info['dead_bones'])} deform bones without influence")
    entry["derive"]["weights"] = "PASS" if not problems else "FAIL: " + "; ".join(problems)
    manifest = load_manifest(project)
    manifest["selections"][target_id] = entry
    write_json(paths(project)["manifest"], manifest)
    return entry


# ---------------------------------------------------------------- image library

def previews(project: Path, *, fetch=asset_catalog.http_fetch, offline: bool = False, force: bool = False) -> dict:
    """Images of every selected asset under artifacts/assets/<class>/<id>/ plus index.md."""
    import live_session
    manifest = load_manifest(project)
    root = project / "artifacts/assets"
    blender = live_session.find_blender()
    rows, results = [], {}
    for requirement_id, entry in sorted(manifest.get("selections", {}).items()):
        if not entry.get("asset_id") and entry.get("status") != "fallback":
            continue
        folder = root / entry.get("class", "static_prop") / requirement_id
        folder.mkdir(parents=True, exist_ok=True)
        images = {}
        thumbnail = entry.get("thumbnail")
        target = folder / "source_thumbnail.png"
        if thumbnail and not offline and (force or not target.exists()):
            try:
                asset_catalog.download(thumbnail, target, fetch=fetch)
            except AssetError as exc:
                images["source_thumbnail"] = f"NOT RUN ({exc})"
        model = Path((entry.get("fetch") or {}).get("path", ""))
        stamp = folder / ".rendered_sha256"
        digest = asset_catalog.sha256_file(model) if model.is_file() else None
        if digest and model.suffix.lower() in (".glb", ".gltf", ".fbx", ".obj") and blender and \
                (force or not stamp.exists() or stamp.read_text().strip() != digest):
            result = subprocess.run([blender, "-b", "--factory-startup", "--python",
                                     str(ROOT / "tools/blender/preview_asset.py"), "--", "--model", str(model),
                                     "--out-dir", str(folder)], text=True, capture_output=True, timeout=600,
                                    check=False)
            line = next((l for l in result.stdout.splitlines() if l.startswith("PREVIEW_ASSET ")), None)
            if line:
                stamp.write_text(digest)
            else:
                images["render"] = f"FAIL (exit {result.returncode}): {(result.stderr or result.stdout)[-300:]}"
        elif not blender and digest:
            images["render"] = "NOT RUN (Blender not found)"
        files = sorted(p.name for p in folder.glob("*.png"))
        results[requirement_id] = {"folder": str(folder), "images": files, **images}
        entry.setdefault("images", {}).update({"folder": str(folder.relative_to(project)), "files": files})
        license_info = entry.get("license") or {}
        cells = " ".join(f"![{name}]({entry.get('class', 'static_prop')}/{requirement_id}/{name})"
                         for name in files if not name.startswith("clip_"))
        rows.append(f"### {requirement_id} ({entry.get('class')})\n\n"
                    f"- asset: `{entry.get('asset_id') or entry.get('procedural')}` from {entry.get('provider', '-')}"
                    f" ({entry.get('source_url') or 'n/a'})\n- license: {license_info.get('id', '-')}; "
                    f"status: {entry.get('status')}"
                    + (f"; derived from `{entry['derive']['source_asset']}`" if entry.get("derive") else "")
                    + f"\n\n{cells}\n")
    (root / "index.md").write_text("# Asset gallery (generated by `lopodev assets previews`)\n\n"
                                   + "\n".join(rows), encoding="utf-8")
    write_json(paths(project)["manifest"], manifest)
    return {"index": str(root / "index.md"), "assets": results}


# ---------------------------------------------------------------- CLI

def print_manifest(manifest: dict) -> None:
    for requirement_id, entry in sorted(manifest.get("selections", {}).items()):
        detail = entry.get("asset_id") or entry.get("procedural") or ""
        score = f" score={entry['score']}" if entry.get("score") is not None else ""
        print(f"{entry['status'].upper():9} {requirement_id}: {detail}{score}")
        for reason in entry.get("reasons", [])[:3]:
            print(f"          - {reason}")
        plan = entry.get("animation_plan")
        if plan and plan.get("missing"):
            print(f"          - missing animations: {plan['missing']}")
    for requirement_id, notes in (manifest.get("provider_notes") or {}).items():
        for line in notes:
            print(f"NOTE {requirement_id}: {line}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="lopodev assets", description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("providers", help="list registered sources and their status")
    pack = sub.add_parser("add-pack", help="index a downloaded asset pack (zip or folder)")
    pack.add_argument("source", type=Path)
    pack.add_argument("--provider", required=True)
    pack.add_argument("--name", required=True)
    pack.add_argument("--style", action="append", default=[])
    pack.add_argument("--tag", action="append", default=[])
    pack.add_argument("--license", help="SPDX id when the pack has no license file (you verified it)")
    pack.add_argument("--license-evidence", help="URL or note proving --license")
    deriver = sub.add_parser("derive", help="edit an existing asset in Blender into a new derived asset")
    deriver.add_argument("--project", type=Path, required=True)
    deriver.add_argument("--from", dest="source", required=True, help="requirement id or catalog asset id")
    deriver.add_argument("--id", required=True, help="new asset id, e.g. sm_witch_well")
    deriver.add_argument("--script", type=Path, help="edit script defining edit(ctx); any bpy is allowed")
    deriver.add_argument("--from-blend", type=Path, help="export a .blend you edited live instead of a script")
    deriver.add_argument("--with", dest="extras", action="append", default=[],
                         help="name=<requirement or asset id> to merge another asset (repeatable)")
    visibility = deriver.add_mutually_exclusive_group()
    visibility.add_argument("--live", dest="live", action="store_true", default=None,
                            help="show the edit in a Blender window")
    visibility.add_argument("--headless", dest="live", action="store_false")
    deriver.add_argument("--hold", type=float, default=3.0, help="seconds to keep the window after the edit")
    deriver.add_argument("--no-godot", action="store_true")
    rigger = sub.add_parser("rig", help="rig and animate an existing asset (parts, humanoid, transfer, creature)")
    rigger.add_argument("--project", type=Path, required=True)
    rigger.add_argument("--from", dest="source", required=True)
    rigger.add_argument("--id", required=True)
    rigger.add_argument("--mode", required=True, choices=("parts", "humanoid", "transfer", "creature"))
    rigger.add_argument("--clip", action="append", default=[],
                        help="parts: name:Part:rotate_x|move_y|bob_z|scale_x:amount:seconds; "
                             "humanoid/creature: clip name (idle, walk, run, attack, hit, death, sway)")
    rigger.add_argument("--chain", action="append", default=[], help="creature: Name=x,y,z:x,y,z:segments")
    rigger.add_argument("--donor", help="transfer: rigged requirement or asset id to copy skeleton and clips from")
    rig_visibility = rigger.add_mutually_exclusive_group()
    rig_visibility.add_argument("--live", dest="live", action="store_true", default=None)
    rig_visibility.add_argument("--headless", dest="live", action="store_false")
    rigger.add_argument("--hold", type=float, default=3.0)
    rigger.add_argument("--no-godot", action="store_true")
    for name, help_text in (("requirements", "derive asset requirements from project.json"),
                            ("search", "rank candidates for each requirement (no download)"),
                            ("resolve", "select assets and write the manifest"),
                            ("fetch", "download/cache selected assets and inspect them"),
                            ("import", "copy selected assets into Godot with wrappers and collision"),
                            ("credits", "write CREDITS.md and the ASSET_LICENSES.md block"),
                            ("previews", "render images of every selected asset into artifacts/assets/"),
                            ("validate", "check licenses, files, imports, rigs, animations"),
                            ("run", "requirements, resolve, fetch, import, credits, validate")):
        command = sub.add_parser(name, help=help_text)
        command.add_argument("--project", type=Path, required=True)
        command.add_argument("--offline", action="store_true", help="only local packs and the cache")
        command.add_argument("--reselect", action="store_true", help="re-pick even pinned/previous selections")
        command.add_argument("--requirement")
        command.add_argument("--no-godot", action="store_true")
        command.add_argument("--strict", action="store_true", help="NOT RUN counts as failure")
    args = parser.parse_args(argv)
    try:
        if args.command == "providers":
            for name, provider in asset_sources.providers().items():
                status = provider.status()
                spec = provider.spec
                print(f"{name:12} {'available' if status['available'] else 'unavailable':11} "
                      f"{'auto' if status['automated'] else 'manual':6} license={spec.get('license')}  "
                      f"{status['reason']}")
            return 0
        if args.command == "add-pack":
            result = asset_sources.index_pack(args.source, args.provider, args.name, style=args.style,
                                              tags=args.tag, license_id=args.license,
                                              license_evidence=args.license_evidence)
            print(json.dumps(result, indent=2))
            if result["license"] == "unknown":
                print("WARNING: license unknown; these assets go to manual review and are never auto-selected")
            return 0
        if args.command in ("derive", "rig"):
            project = args.project.resolve()
            if args.command == "rig":
                entry = rig(project, args.source, args.id, args.mode, clips=args.clip, chains=args.chain,
                            donor=args.donor, live=args.live, hold=args.hold)
            else:
                extras = dict(item.split("=", 1) for item in args.extras)
                entry = derive(project, args.source, args.id, script=args.script, from_blend=args.from_blend,
                               extras=extras, live=args.live, hold=args.hold)
            if entry.get("unchanged"):
                print(f"UNCHANGED {args.id}: same source and script as the last derive")
            derived = entry["derive"]
            for step in derived.get("operations", []):
                print(f"STEP {step}")
            if derived.get("rig"):
                print(f"RIG {json.dumps(derived['rig'])}")
                print(f"WEIGHTS {derived.get('weights', 'n/a')}")
            for kind in ("before", "after", "clips"):
                for image in derived.get("previews", {}).get(kind, []):
                    print(f"PREVIEW_{kind.upper()} {image}")
            print(f"DERIVE={derived['status']} {entry['asset_id']} license={entry['license']['id']} "
                  f"triangles {derived['before'] and derived['before'].get('triangles')} -> "
                  f"{derived['after'].get('triangles')} live={derived['live']}")
            if args.id not in {r["id"] for r in requirements(project)["requirements"]}:
                print(f"NOTE {args.id} is not in project.json assets; add it with \"source\": \"derived\", "
                      f"\"derive_from\": \"{args.source}\" so it is imported and validated")
                return 0 if derived["status"] == "PASS" else 1
            manifest = import_assets(project, run_godot=not args.no_godot)
            godot = (manifest["selections"][args.id].get("import") or {}).get("godot", {})
            print(f"IMPORT {manifest['selections'][args.id]['status']} godot={godot.get('status', 'NOT RUN')}")
            return 0 if derived["status"] == "PASS" else 1
        project = args.project.resolve()
        if not (project / "project.json").is_file():
            print(f"ERROR: no project.json in {project}", file=sys.stderr)
            return 2
        if args.command == "requirements":
            result = requirements(project)
            for req in result["requirements"]:
                print(f"{req['id']:20} {req['class']:20} {req['resolution']:9} terms={req['terms']} "
                      f"rig={req['rig']} anims={req['animations']} collision={req['collision']}")
            for error in result["errors"]:
                print(f"ERROR: {error}")
            return 1 if result["errors"] else 0
        if args.command == "search":
            registry = asset_sources.load_registry()
            provs = asset_sources.providers(registry)
            for req in requirements(project)["requirements"]:
                if req["resolution"] != "discover" or (args.requirement and req["id"] != args.requirement):
                    continue
                found, notes = candidates_for(req, provs, asset_catalog.http_fetch, args.offline, None)
                eligible, rejected = asset_rank.rank(req, found, registry["license_policy"],
                                                     registry["ranking_weights"])
                print(f"== {req['id']} ({req['class']}): {len(eligible)} eligible, {len(rejected)} rejected")
                for candidate, result in eligible[:5]:
                    print(f"  {result['score']:.3f} {candidate['asset_id']}  {'; '.join(result['reasons'][:3])}")
                for candidate, result in rejected[:3]:
                    print(f"  REJECT {candidate['asset_id']}: {result['rejection']}")
                for line in notes:
                    print(f"  NOTE {line}")
            return 0
        if args.command in ("resolve", "run"):
            print_manifest(resolve(project, offline=args.offline, reselect=args.reselect))
        if args.command in ("fetch", "run"):
            manifest = fetch_selected(project)
            for requirement_id, entry in sorted(manifest["selections"].items()):
                if entry.get("fetch"):
                    print(f"FETCH {entry['fetch']['status']} {requirement_id}: "
                          f"{entry['fetch'].get('path') or entry['fetch'].get('error')}")
        if args.command in ("import", "run"):
            manifest = import_assets(project, run_godot=not args.no_godot)
            check = manifest["godot_check"]
            print(f"GODOT_ASSET_CHECK={check['status']} {check.get('reason', check.get('log', ''))}")
        if args.command in ("previews", "run"):
            result = previews(project, offline=args.offline, force=args.reselect)
            failed = [k for k, v in result["assets"].items() if str(v.get("render", "")).startswith("FAIL")]
            print(f"ASSET_GALLERY={result['index']} assets={len(result['assets'])} render_failures={failed}")
        if args.command in ("credits", "run"):
            credits(project)
            print(f"CREDITS={paths(project)['credits']}")
        if args.command in ("validate", "run"):
            report = validate(project)
            for item in report["checks"]:
                print(f"{item['status']:7} {item['requirement']} {item['check']}: {item['detail']}")
            print(f"ASSET_VALIDATION={report['status']} pass={report['counts']['PASS']} "
                  f"fail={report['counts']['FAIL']} not_run={report['counts']['NOT RUN']}")
            if report["status"] == "FAIL" or (args.strict and report["counts"]["NOT RUN"]):
                return 1
        if args.command in ("resolve", "run"):
            manifest = load_manifest(project)
            unmet = [r for r, e in manifest["selections"].items() if e["status"] == "unmet"]
            if unmet and args.command == "resolve":
                print(f"UNMET {unmet}: add a pack, a fallback, or relax the requirement")
                return 1
        return 0
    except (AssetError, OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
