"""Generate a deterministic prop, save .blend, and export GLB.

Usage (inside Blender):
  blender -b --factory-startup --python tools/blender/make_prop.py -- \
    --kind crate --out-dir projects/prop_poc
"""

from __future__ import annotations

import argparse
import math
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import bpy  # noqa: E402

from lib_asset import (  # noqa: E402
    build_common_meta,
    create_box,
    create_cone,
    create_cylinder,
    create_icosphere,
    export_glb,
    ground_origin,
    join_objects,
    make_material,
    mesh_stats,
    reset_scene,
    save_blend,
    write_meta,
)

PALETTES = {
    "crate": [(0.44, 0.28, 0.14), (0.20, 0.11, 0.05)],
    "barrel": [(0.38, 0.22, 0.10), (0.17, 0.17, 0.18)],
    "rock": [(0.32, 0.34, 0.32)],
    "pillar": [(0.55, 0.53, 0.47), (0.40, 0.39, 0.35)],
    "drone": [(0.05, 0.20, 0.22)],
    "crystal": [(0.05, 0.85, 0.90)],
    "arena": [(0.20, 0.24, 0.30)],
}

MATERIAL_SETTINGS = {
    "drone": (0.45, 0.35),
    "crystal": (0.25, 0.0),
    "arena": (0.90, 0.05),
}

EMISSION_STRENGTH = {
    "crystal": 2.5,
}

DEFAULT_BUDGETS = {
    "drone": 900,
    "crystal": 250,
    "arena": 1800,
}


def build_crate(materials: list[bpy.types.Material]) -> bpy.types.Object:
    body, frame = materials[0], materials[1]
    parts = [create_box("CrateBody", (0.94, 0.94, 0.94), (0.0, 0.0, 0.5), body)]
    for x in (-0.47, 0.47):
        for y in (-0.47, 0.47):
            parts.append(create_box("CratePost", (0.10, 0.10, 1.00),
                                    (x, y, 0.50), frame))
    for y in (-0.47, 0.47):
        for z in (0.05, 0.95):
            parts.append(create_box("CrateRailX", (1.04, 0.10, 0.10),
                                    (0.0, y, z), frame))
    for x in (-0.47, 0.47):
        for z in (0.05, 0.95):
            parts.append(create_box("CrateRailY", (0.10, 1.04, 0.10),
                                    (x, 0.0, z), frame))
    for y in (-0.505, 0.505):
        parts.append(create_box("CrateBrace", (1.12, 0.07, 0.09),
                                (0.0, y, 0.50), frame,
                                rotation=(0.0, math.radians(42.0), 0.0)))
    return join_objects(parts, "sm_crate")


def build_barrel(materials: list[bpy.types.Material]) -> bpy.types.Object:
    wood, metal = materials[0], materials[1]
    parts = [
        create_cylinder("BarrelBody", 0.36, 1.00, (0.0, 0.0, 0.50), wood, vertices=12),
        create_cylinder("BarrelTop", 0.30, 0.04, (0.0, 0.0, 1.00), wood, vertices=12),
    ]
    for z in (0.20, 0.50, 0.80):
        parts.append(create_cylinder("BarrelBand", 0.385, 0.07,
                                     (0.0, 0.0, z), metal, vertices=12))
    return join_objects(parts, "sm_barrel")


def build_rock(material: bpy.types.Material, seed: int = 7) -> bpy.types.Object:
    obj = create_icosphere("RockBody", 0.58, (0.0, 0.0, 0.48), material,
                           subdivisions=2, seed=seed)
    return join_objects([obj], "sm_rock")


def build_pillar(materials: list[bpy.types.Material]) -> bpy.types.Object:
    stone, trim = materials[0], materials[1]
    parts = [
        create_box("PillarBase", (0.80, 0.80, 0.18), (0.0, 0.0, 0.09), trim),
        create_box("PillarShaft", (0.52, 0.52, 2.10), (0.0, 0.0, 1.23), stone),
        create_box("PillarCapital", (0.78, 0.78, 0.20), (0.0, 0.0, 2.38), trim),
    ]
    return join_objects(parts, "sm_pillar")


def build_drone(materials: list[bpy.types.Material]) -> bpy.types.Object:
    body_material = materials[0]
    parts = []
    body = create_icosphere("DroneBody", 0.42, (0.0, 0.0, 0.27), body_material,
                            subdivisions=3, seed=3)
    for vertex in body.data.vertices:
        vertex.co.z *= 0.55
    parts.append(body)
    cockpit = create_icosphere("DroneCockpit", 0.17, (0.0, 0.0, 0.46),
                               body_material, subdivisions=2)
    for vertex in cockpit.data.vertices:
        vertex.co.z *= 0.60
    parts.append(cockpit)
    for y in (-0.24, 0.24):
        parts.append(create_box("DroneSkid", (0.55, 0.06, 0.05),
                                (0.0, y, 0.025), body_material))
    for sx in (-1.0, 1.0):
        for sy in (-1.0, 1.0):
            parts.append(create_box(
                "DroneArm", (0.63, 0.10, 0.06),
                (sx * 0.21, sy * 0.21, 0.34), body_material,
                rotation=(0.0, 0.0, math.atan2(sy, sx))))
            parts.append(create_cylinder(
                "DroneRotor", 0.17, 0.04,
                (sx * 0.42, sy * 0.42, 0.38), body_material, vertices=12))
            parts.append(create_cylinder(
                "DroneHub", 0.05, 0.07,
                (sx * 0.42, sy * 0.42, 0.40), body_material, vertices=8))
    return join_objects(parts, "sm_hover_drone")


def build_crystal(materials: list[bpy.types.Material]) -> bpy.types.Object:
    material = materials[0]
    parts = [
        create_cylinder("CrystalBase", 0.16, 0.06, (0.0, 0.0, 0.03),
                        material, vertices=10),
        create_cone("CrystalLower", 0.04, 0.17, 0.14, (0.0, 0.0, 0.13),
                    material, vertices=8),
        create_cone("CrystalUpper", 0.17, 0.0, 0.22, (0.0, 0.0, 0.31),
                    material, vertices=8),
    ]
    return join_objects(parts, "sm_crystal")


def build_arena(materials: list[bpy.types.Material]) -> bpy.types.Object:
    material = materials[0]
    parts = [
        create_box("ArenaFloor", (8.0, 8.0, 0.12), (0.0, 0.0, 0.06), material),
    ]
    for y in (-3.91, 3.91):
        parts.append(create_box("ArenaWallX", (8.0, 0.18, 0.50),
                                (0.0, y, 0.25), material))
    for x in (-3.91, 3.91):
        parts.append(create_box("ArenaWallY", (0.18, 8.0, 0.50),
                                (x, 0.0, 0.25), material))
    parts.append(create_cylinder("ArenaPad", 0.90, 0.08, (0.0, 0.0, 0.16),
                                 material, vertices=12))
    for sx in (-1.0, 1.0):
        for sy in (-1.0, 1.0):
            parts.append(create_box("ArenaPylon", (0.30, 0.30, 0.90),
                                    (sx * 3.50, sy * 3.50, 0.45), material))
    for y in (-1.40, 1.40):
        parts.append(create_box("ArenaInlayX", (5.0, 0.06, 0.02),
                                (0.0, y, 0.125), material))
    for x in (-1.40, 1.40):
        parts.append(create_box("ArenaInlayY", (0.06, 5.0, 0.02),
                                (x, 0.0, 0.125), material))
    return join_objects(parts, "sm_arena")


BUILDERS = {
    "crate": (build_crate, 2),
    "barrel": (build_barrel, 2),
    "rock": (build_rock, 1),
    "pillar": (build_pillar, 2),
    "drone": (build_drone, 1),
    "crystal": (build_crystal, 1),
    "arena": (build_arena, 1),
}


def parse_args() -> argparse.Namespace:
    argv = sys.argv
    argv = argv[argv.index("--") + 1:] if "--" in argv else []
    parser = argparse.ArgumentParser(description="Generate a prop")
    parser.add_argument("--kind", required=True, choices=sorted(BUILDERS))
    parser.add_argument("--out-dir", required=True,
                        help="project root, e.g. projects/prop_poc")
    parser.add_argument("--name", default=None, help="asset id (default sm_<kind>)")
    parser.add_argument("--seed", type=int, default=7)
    parser.add_argument("--triangle-budget", type=int, default=None)
    return parser.parse_args(argv)


def main() -> int:
    args = parse_args()
    name = args.name or f"sm_{args.kind}"
    if not name.startswith("sm_"):
        raise SystemExit("asset name must start with sm_")
    out_dir = os.path.abspath(args.out_dir)
    blend_path = os.path.join(out_dir, "blender", f"{name}.blend")
    glb_path = os.path.join(out_dir, "godot", "assets", "models", f"{name}.glb")
    meta_path = os.path.join(out_dir, "godot", "assets", "models", f"{name}.meta.json")

    reset_scene()
    builder, material_count = BUILDERS[args.kind]
    colors = PALETTES[args.kind]
    triangle_budget = args.triangle_budget or DEFAULT_BUDGETS.get(args.kind, 2000)
    if args.kind in MATERIAL_SETTINGS:
        roughness, metallic = MATERIAL_SETTINGS[args.kind]
        emission_strength = EMISSION_STRENGTH.get(args.kind, 0.0)
        materials = [
            make_material(f"mat_{args.kind}_{index}", color,
                          roughness=roughness, metallic=metallic,
                          emission_strength=emission_strength)
            for index, color in enumerate(colors[:material_count])
        ]
    else:
        materials = [
            make_material(f"mat_{args.kind}_{index}", color,
                          roughness=0.85, metallic=0.0 if index == 0 else 0.25)
            for index, color in enumerate(colors[:material_count])
        ]
    obj = build_rock(materials[0], args.seed) if args.kind == "rock" else builder(materials)
    ground_origin(obj)

    obj["asset_id"] = name
    obj["asset_kind"] = args.kind
    obj["source"] = "procedural"
    obj["license"] = "generated-in-repo"
    obj["generator"] = "tools/blender/make_prop.py"

    stats = mesh_stats(obj)
    min_z = stats["bounds_blender"]["min"][2]
    if abs(min_z) > 1e-4:
        raise SystemExit(f"asset origin is not at ground contact: min Z={min_z}")
    if stats["triangles"] > triangle_budget:
        raise SystemExit(
            f"triangle budget exceeded: {stats['triangles']} > {triangle_budget}")

    save_blend(blend_path)
    export_glb(glb_path, animations=False)

    meta = build_common_meta(
        asset_id=name,
        kind=args.kind,
        out_dir=out_dir,
        glb_path=glb_path,
        blend_path=blend_path,
        stats=stats,
        triangles_budget=triangle_budget,
        animated=False,
        extra={
            "palette": ["#%02x%02x%02x" % tuple(int(c * 255) for c in color)
                        for color in colors[:material_count]],
            "material_count": material_count,
        },
    )
    write_meta(meta_path, meta)

    print(f"GENERATED_ASSET={name}")
    print(f"KIND={args.kind}")
    print(f"TRIANGLES={stats['triangles']}")
    print(f"BOUNDS_MIN={stats['bounds_blender']['min']}")
    print(f"BOUNDS_MAX={stats['bounds_blender']['max']}")
    print(f"BLEND={blend_path}")
    print(f"GLB={glb_path}")
    print(f"META={meta_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
