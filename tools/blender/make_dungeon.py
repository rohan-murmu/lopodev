"""Generate dungeon environment assets: floor, walls, pillars.

Usage (inside Blender):
  blender -b --factory-startup --python tools/blender/make_dungeon.py -- \
    --kind floor --out-dir projects/crypt_runner
"""

from __future__ import annotations

import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import bpy  # noqa: E402

from lib_asset import (  # noqa: E402
    build_common_meta,
    create_box,
    create_cylinder,
    export_glb,
    ground_origin,
    join_objects,
    make_material,
    mesh_stats,
    reset_scene,
    save_blend,
    write_meta,
)

# Dungeon palette: dark stone
DUNGEON_COLORS = {
    "floor": [(0.18, 0.18, 0.20), (0.12, 0.12, 0.14)],  # base, accent
    "wall": [(0.22, 0.20, 0.18), (0.15, 0.14, 0.12)],   # stone, mortar
}

MATERIAL_SETTINGS = {
    "floor": (0.90, 0.05),
    "wall": (0.85, 0.10),
}

DEFAULT_BUDGETS = {
    "floor": 500,
    "wall": 800,
}


def build_dungeon_floor(materials: list[bpy.types.Material]) -> bpy.types.Object:
    """Build a 20x20 meter dungeon floor with tile pattern."""
    base_mat, accent_mat = materials[0], materials[1]
    parts = []
    
    # Main floor - 20x20, 0.1m thick
    parts.append(create_box("DungeonFloor", (20.0, 20.0, 0.1), (0.0, 0.0, 0.05), base_mat))
    
    # Tile grid lines (subtle raised edges)
    tile_size = 2.0
    line_width = 0.02
    line_height = 0.015
    
    # Horizontal lines
    for i in range(1, 10):
        y = -10.0 + i * tile_size
        parts.append(create_box(f"FloorLineH_{i}", (20.0, line_width, line_height),
                                (0.0, y, 0.1 + line_height/2), accent_mat))
    
    # Vertical lines
    for i in range(1, 10):
        x = -10.0 + i * tile_size
        parts.append(create_box(f"FloorLineV_{i}", (line_width, 20.0, line_height),
                                (x, 0.0, 0.1 + line_height/2), accent_mat))
    
    # Center decorative inlay
    parts.append(create_cylinder("FloorCenterInlay", 1.5, 0.02, (0.0, 0.0, 0.12),
                                 accent_mat, vertices=16))
    parts.append(create_cylinder("FloorCenterInlay2", 0.8, 0.03, (0.0, 0.0, 0.14),
                                 base_mat, vertices=12))
    
    return join_objects(parts, "sm_dungeon_floor")


def build_dungeon_wall(materials: list[bpy.types.Material]) -> bpy.types.Object:
    """Build 4 wall segments, each 5m wide x 5m high x 0.3m thick."""
    stone_mat, mortar_mat = materials[0], materials[1]
    parts = []
    
    wall_width = 5.0
    wall_height = 5.0
    wall_thickness = 0.3
    
    # Four walls: North, South, East, West
    # North wall (negative Y)
    parts.append(create_box("WallNorth", (wall_width, wall_thickness, wall_height),
                            (-wall_width/2, -10.0 + wall_thickness/2, wall_height/2), stone_mat))
    # South wall (positive Y)
    parts.append(create_box("WallSouth", (wall_width, wall_thickness, wall_height),
                            (-wall_width/2, 10.0 - wall_thickness/2, wall_height/2), stone_mat))
    # East wall (positive X)
    parts.append(create_box("WallEast", (wall_thickness, wall_width, wall_height),
                            (10.0 - wall_thickness/2, -wall_width/2, wall_height/2), stone_mat))
    # West wall (negative X)
    parts.append(create_box("WallWest", (wall_thickness, wall_width, wall_height),
                            (-10.0 + wall_thickness/2, -wall_width/2, wall_height/2), stone_mat))
    
    # Add mortar lines (horizontal bands)
    band_height = 0.05
    band_spacing = 1.0
    for wall_name, base_pos, rotation in [
        ("North", (-wall_width/2, -10.0 + wall_thickness/2, 0), (0, 0, 0)),
        ("South", (-wall_width/2, 10.0 - wall_thickness/2, 0), (0, 0, 0)),
        ("East", (10.0 - wall_thickness/2, -wall_width/2, 0), (0, 0, 1.5708)),
        ("West", (-10.0 + wall_thickness/2, -wall_width/2, 0), (0, 0, 1.5708)),
    ]:
        for i in range(1, int(wall_height / band_spacing)):
            z = i * band_spacing
            parts.append(create_box(f"WallMortar_{wall_name}_{i}",
                                    (wall_width, wall_thickness + 0.01, band_height),
                                    (base_pos[0], base_pos[1], z + band_height/2),
                                    mortar_mat, rotation=rotation))
    
    return join_objects(parts, "sm_dungeon_wall")


BUILDERS = {
    "floor": (build_dungeon_floor, 2),
    "wall": (build_dungeon_wall, 2),
}


def parse_args() -> argparse.Namespace:
    argv = sys.argv
    argv = argv[argv.index("--") + 1:] if "--" in argv else []
    parser = argparse.ArgumentParser(description="Generate dungeon environment asset")
    parser.add_argument("--kind", required=True, choices=sorted(BUILDERS))
    parser.add_argument("--out-dir", required=True,
                        help="project root, e.g. projects/crypt_runner")
    parser.add_argument("--name", default=None, help="asset id (default sm_dungeon_<kind>)")
    parser.add_argument("--triangle-budget", type=int, default=None)
    return parser.parse_args(argv)


def main() -> int:
    args = parse_args()
    name = args.name or f"sm_dungeon_{args.kind}"
    if not name.startswith("sm_"):
        raise SystemExit("asset name must start with sm_")
    out_dir = os.path.abspath(args.out_dir)
    blend_path = os.path.join(out_dir, "blender", f"{name}.blend")
    glb_path = os.path.join(out_dir, "godot", "assets", "models", f"{name}.glb")
    meta_path = os.path.join(out_dir, "godot", "assets", "models", f"{name}.meta.json")

    reset_scene()
    builder, material_count = BUILDERS[args.kind]
    colors = DUNGEON_COLORS[args.kind]
    triangle_budget = args.triangle_budget or DEFAULT_BUDGETS.get(args.kind, 2000)
    
    roughness, metallic = MATERIAL_SETTINGS[args.kind]
    materials = [
        make_material(f"mat_dungeon_{args.kind}_{index}", color,
                      roughness=roughness, metallic=metallic)
        for index, color in enumerate(colors[:material_count])
    ]
    
    obj = builder(materials)
    ground_origin(obj)

    obj["asset_id"] = name
    obj["asset_kind"] = f"dungeon_{args.kind}"
    obj["source"] = "procedural"
    obj["license"] = "generated-in-repo"
    obj["generator"] = "tools/blender/make_dungeon.py"

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
        kind=f"dungeon_{args.kind}",
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
    print(f"KIND=dungeon_{args.kind}")
    print(f"TRIANGLES={stats['triangles']}")
    print(f"BOUNDS_MIN={stats['bounds_blender']['min']}")
    print(f"BOUNDS_MAX={stats['bounds_blender']['max']}")
    print(f"BLEND={blend_path}")
    print(f"GLB={glb_path}")
    print(f"META={meta_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())