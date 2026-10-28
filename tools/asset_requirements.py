#!/usr/bin/env python3
"""Turn the game plan's asset list into structured asset requirements.

The planner (an LLM) writes intent into `project.json` `assets`; this module
normalizes it with deterministic defaults per asset class so later stages do
not depend on wording. A requirement says what the game *needs*; it is not a
selected asset (see asset records) and not proof (see validation reports).

Classes:
  static_prop          rocks, crates, weapons on racks: no rig, simple collision
  skeletal_character   players/enemies/NPCs: rig + named animations, capsule
  animated_prop        doors, chests: node animation, no skeleton needed
  modular_environment  walls, ruins, building kits: box/convex collision
  procedural_element   grass/foliage scatter: no or cheap collision
  material / hdri      surfaces and skies, no geometry

`suggest(prompt)` bootstraps a list from a prompt using a small keyword table;
the planner reviews and edits it in project.json.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import asset_sources  # noqa: E402

SCHEMA = "lopodev.asset-requirements/1"
CLASSES = {"static_prop", "skeletal_character", "animated_prop", "modular_environment",
           "procedural_element", "material", "hdri"}
LEGACY_KIND = {"prop": "static_prop", "character": "skeletal_character", "environment": "modular_environment",
               "foliage": "procedural_element", "material": "material", "hdri": "hdri",
               "animated_prop": "animated_prop"}
CLASS_DEFAULTS = {
    "static_prop": {"rig": "none", "collision": "box", "budget_triangles": 2000},
    "skeletal_character": {"rig": "required", "collision": "capsule", "budget_triangles": 6000,
                           "animations": ["idle", "walk"]},
    "animated_prop": {"rig": "optional", "collision": "box", "budget_triangles": 2000},
    "modular_environment": {"rig": "none", "collision": "box", "budget_triangles": 3000},
    "procedural_element": {"rig": "none", "collision": "none", "budget_triangles": 500},
    "material": {"rig": "none", "collision": "none", "budget_triangles": None},
    "hdri": {"rig": "none", "collision": "none", "budget_triangles": None},
}
COLLISION_SHAPES = {"none", "box", "sphere", "capsule", "cylinder", "convex", "trimesh"}
RESOLUTIONS = {"discover", "generate", "procedural", "provided", "derived"}

# keyword -> requirement templates; a starting point the planner edits, not a final list.
ARCHETYPES = {
    "jungle": [("tree", "static_prop", ["tree", "palm"], {"collision": "cylinder"}),
               ("bush", "procedural_element", ["bush", "plant"], {}),
               ("grass", "procedural_element", ["grass"], {}),
               ("rock", "static_prop", ["rock"], {}),
               ("log", "static_prop", ["log"], {}),
               ("ground", "material", ["ground", "grass", "dirt"], {})],
    "forest": [("tree", "static_prop", ["tree"], {"collision": "cylinder"}),
               ("rock", "static_prop", ["rock"], {}), ("bush", "procedural_element", ["bush"], {}),
               ("ground", "material", ["ground", "grass"], {})],
    "ruins": [("ruin_wall", "modular_environment", ["wall", "ruin"], {}),
              ("pillar", "modular_environment", ["pillar", "column"], {"collision": "cylinder"})],
    "fps": [("weapon", "static_prop", ["gun", "rifle", "weapon"], {"collision": "none", "budget_triangles": 3000})],
    "soldier": [("enemy", "skeletal_character", ["soldier", "character"],
                 {"animations": ["idle", "walk", "run", "shoot", "hit", "death"]})],
    "enemy": [("enemy", "skeletal_character", ["enemy", "character"],
               {"animations": ["idle", "walk", "attack", "hit", "death"]})],
    "dungeon": [("dungeon_wall", "modular_environment", ["wall", "dungeon"], {}),
                ("crate", "static_prop", ["crate", "barrel"], {})],
    "city": [("building", "modular_environment", ["building"], {}), ("car", "static_prop", ["car"], {})],
}


BUDGETS = Path(__file__).resolve().parent.parent / "resources/budgets.json"


def budget_profile(spec: dict) -> tuple[str, dict]:
    """Pick the platform budget profile: explicit `budget_profile`, else mobile when a
    mobile target is declared, else desktop."""
    profiles = json.loads(BUDGETS.read_text(encoding="utf-8"))["profiles"]
    name = spec.get("budget_profile")
    if not name:
        platforms = json.dumps([spec.get("target_platform"), spec.get("platforms")]).lower()
        name = "mobile" if isinstance(spec.get("mobile"), dict) or "android" in platforms or "ios" in platforms else "desktop"
    if name not in profiles:
        raise ValueError(f"unknown budget_profile {name!r}; choose one of {sorted(profiles)}")
    return name, profiles[name]


def normalize(asset: dict, profile: dict | None = None) -> dict:
    """Spec asset entry -> requirement with explicit defaults."""
    asset_class = asset.get("class") or LEGACY_KIND.get(asset.get("kind", ""), "static_prop")
    defaults = CLASS_DEFAULTS.get(asset_class, CLASS_DEFAULTS["static_prop"])
    source = asset.get("source", "discover")
    resolution = "generate" if source in ("procedural", "generated-in-repo", "blender", "custom") else \
        "provided" if source == "provided" else "derived" if source == "derived" else "discover"
    terms = asset.get("terms") or asset_sources.tokens(asset.get("role", "") or asset["id"].removeprefix("sm_"))
    requirement = {
        "id": asset["id"], "role": asset.get("role") or asset.get("brief", asset["id"]),
        "class": asset_class, "resolution": resolution, "terms": [t.lower() for t in terms],
        "style": asset.get("style", []), "size_m": asset.get("size_m"),
        "formats": asset.get("formats", ["glb", "gltf"]),
        "rig": asset.get("rig", "required" if asset.get("animated") and asset_class == "skeletal_character"
                         else defaults["rig"]),
        "animations": asset.get("animations", defaults.get("animations", []) if asset_class ==
                                "skeletal_character" else []),
        "collision": asset.get("collision", defaults["collision"]),
        "budget_triangles": asset.get("budget_triangles",
                                      (profile or {}).get(asset_class, defaults["budget_triangles"])),
        "texture_max_px": asset.get("texture_max_px", (profile or {}).get("texture_max_px", 2048)),
        "mandatory": asset.get("mandatory", True),
        "fallbacks": asset.get("fallbacks", []),
        "providers": asset.get("providers", []),
    }
    if resolution == "derived":
        requirement["derive_from"] = asset.get("derive_from")
        requirement["edit_brief"] = asset.get("edit_brief") or asset.get("brief", "")
    return requirement


def validate_requirement(req: dict) -> list[str]:
    errors = []
    prefix = f"requirement {req.get('id')}"
    if req.get("class") not in CLASSES:
        errors.append(f"{prefix}: class must be one of {sorted(CLASSES)}")
    if req.get("resolution") not in RESOLUTIONS:
        errors.append(f"{prefix}: resolution must be one of {sorted(RESOLUTIONS)}")
    if req.get("collision") not in COLLISION_SHAPES:
        errors.append(f"{prefix}: collision must be one of {sorted(COLLISION_SHAPES)}")
    if req.get("rig") not in ("none", "optional", "required"):
        errors.append(f"{prefix}: rig must be none, optional or required")
    if req.get("resolution") == "derived" and not req.get("derive_from"):
        errors.append(f"{prefix}: derived assets need derive_from (a requirement id or catalog asset id)")
    if req.get("resolution") == "discover" and not req.get("terms"):
        errors.append(f"{prefix}: discovery needs search terms")
    if req.get("class") == "skeletal_character" and req.get("collision") not in ("capsule", "none"):
        errors.append(f"{prefix}: characters use capsule collision")
    if req.get("animations") and req.get("class") in ("static_prop", "procedural_element", "material", "hdri"):
        errors.append(f"{prefix}: {req['class']} must not require animations")
    size = req.get("size_m")
    if size is not None and (not isinstance(size, list) or len(size) != 3 or min(size) <= 0):
        errors.append(f"{prefix}: size_m must be [x, y, z] meters > 0")
    for fallback in req.get("fallbacks", []):
        if not (fallback.startswith("asset:") or fallback.startswith("requirement:")
                or fallback.startswith("procedural:")):
            errors.append(f"{prefix}: fallback {fallback!r} must start with asset:, requirement: or procedural:")
    return errors


def analyze(spec: dict) -> dict:
    profile_name, profile = budget_profile(spec)
    requirements = [normalize(asset, profile) for asset in spec.get("assets", [])]
    style = spec.get("art_style") or spec.get("style")
    for req in requirements:
        if not req["style"] and style:
            req["style"] = [style] if isinstance(style, str) else list(style)
    errors = [error for req in requirements for error in validate_requirement(req)]
    return {"schema": SCHEMA, "project": spec.get("slug"), "budget_profile": profile_name,
            "requirements": requirements, "errors": errors}


def suggest(prompt: str, style: list[str] | None = None) -> list[dict]:
    words = set(asset_sources.tokens(prompt))
    assets: dict[str, dict] = {}
    for keyword, templates in ARCHETYPES.items():
        if keyword not in words:
            continue
        for name, asset_class, terms, extra in templates:
            asset_id = f"{'mat' if asset_class == 'material' else 'sm'}_{name}"
            assets.setdefault(asset_id, {"id": asset_id, "class": asset_class, "role": name.replace("_", " "),
                                         "terms": terms, "style": style or [], **extra})
    return list(assets.values())


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--project", type=Path, help="project dir with project.json")
    parser.add_argument("--prompt", help="suggest an asset list from a game prompt (printed, not saved)")
    parser.add_argument("--style", action="append", default=[])
    args = parser.parse_args(argv)
    if args.prompt:
        print(json.dumps(suggest(args.prompt, args.style), indent=2))
        return 0
    if not args.project:
        parser.error("--project or --prompt is required")
    spec = json.loads((args.project / "project.json").read_text(encoding="utf-8"))
    result = analyze(spec)
    print(json.dumps(result, indent=2))
    return 1 if result["errors"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
