"""Generate sword prop for player character.

Usage (inside Blender):
  blender -b --factory-startup --python tools/blender/make_sword.py -- \
    --out-dir projects/crypt_runner
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
    create_cone,
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

SWORD_COLORS = {
    "blade": (0.65, 0.65, 0.70),   # steel
    "hilt": (0.30, 0.20, 0.10),    # leather/brown
    "guard": (0.45, 0.40, 0.35),   # bronze/gold
    "pommel": (0.50, 0.45, 0.40),  # metal
}

MATERIAL_SETTINGS = {
    "blade": (0.30, 0.80),
    "hilt": (0.80, 0.10),
    "guard": (0.40, 0.60),
    "pommel": (0.40, 0.70),
}

DEFAULT_BUDGET = 200


def build_sword() -> bpy.types.Object:
    """Build a low-poly sword."""
    blade_mat = make_material("mat_sword_blade", SWORD_COLORS["blade"],
                              roughness=MATERIAL_SETTINGS["blade"][0],
                              metallic=MATERIAL_SETTINGS["blade"][1])
    hilt_mat = make_material("mat_sword_hilt", SWORD_COLORS["hilt"],
                             roughness=MATERIAL_SETTINGS["hilt"][0],
                             metallic=MATERIAL_SETTINGS["hilt"][1])
    guard_mat = make_material("mat_sword_guard", SWORD_COLORS["guard"],
                              roughness=MATERIAL_SETTINGS["guard"][0],
                              metallic=MATERIAL_SETTINGS["guard"][1])
    pommel_mat = make_material("mat_sword_pommel", SWORD_COLORS["pommel"],
                               roughness=MATERIAL_SETTINGS["pommel"][0],
                               metallic=MATERIAL_SETTINGS["pommel"][1])
    
    # Blade - long thin box tapering to point
    # We'll use a box for the main blade and a cone for the tip
    blade_base = create_box("BladeBase", (0.04, 0.8, 0.03), (0.0, 0.4, 0.0), blade_mat)
    blade_tip = create_cone("BladeTip", 0.02, 0.0, 0.15, (0.0, 0.85, 0.0), blade_mat, vertices=8)
    
    # Fuller (groove) - subtle indentation using darker material
    fuller = create_box("BladeFuller", (0.02, 0.6, 0.01), (0.0, 0.3, 0.015), hilt_mat)
    
    # Crossguard
    guard = create_box("Crossguard", (0.25, 0.04, 0.04), (0.0, 0.02, 0.0), guard_mat)
    
    # Hilt/grip
    grip = create_cylinder("Grip", 0.025, 0.2, (0.0, -0.1, 0.0), hilt_mat, vertices=8)
    
    # Pommel
    pommel = create_cone("Pommel", 0.035, 0.02, 0.04, (0.0, -0.22, 0.0), pommel_mat, vertices=8)
    
    return join_objects([blade_base, blade_tip, fuller, guard, grip, pommel], "sm_sword")


def parse_args() -> argparse.Namespace:
    argv = sys.argv
    argv = argv[argv.index("--") + 1:] if "--" in argv else []
    parser = argparse.ArgumentParser(description="Generate sword prop")
    parser.add_argument("--out-dir", required=True,
                        help="project root, e.g. projects/crypt_runner")
    parser.add_argument("--name", default="sm_sword", help="asset id")
    parser.add_argument("--triangle-budget", type=int, default=DEFAULT_BUDGET)
    return parser.parse_args(argv)


def main() -> int:
    args = parse_args()
    if not args.name.startswith("sm_"):
        raise SystemExit("asset name must start with sm_")
    out_dir = os.path.abspath(args.out_dir)
    blend_path = os.path.join(out_dir, "blender", f"{args.name}.blend")
    glb_path = os.path.join(out_dir, "godot", "assets", "models", f"{args.name}.glb")
    meta_path = os.path.join(out_dir, "godot", "assets", "models", f"{args.name}.meta.json")

    reset_scene()
    mesh = build_sword()
    ground_origin(mesh)

    mesh["asset_id"] = args.name
    mesh["asset_kind"] = "sword"
    mesh["source"] = "procedural"
    mesh["license"] = "generated-in-repo"
    mesh["generator"] = "tools/blender/make_sword.py"

    stats = mesh_stats(mesh)
    if stats["triangles"] > args.triangle_budget:
        raise SystemExit(
            f"triangle budget exceeded: {stats['triangles']} > {args.triangle_budget}")

    save_blend(blend_path)
    export_glb(glb_path, animations=False)

    meta = build_common_meta(
        asset_id=args.name,
        kind="sword",
        out_dir=out_dir,
        glb_path=glb_path,
        blend_path=blend_path,
        stats=stats,
        triangles_budget=args.triangle_budget,
        animated=False,
        extra={
            "generator": "tools/blender/make_sword.py",
            "palette": ["#%02x%02x%02x" % tuple(int(c * 255) for c in color)
                        for color in SWORD_COLORS.values()],
            "material_count": len(SWORD_COLORS),
        },
    )
    write_meta(meta_path, meta)

    print(f"GENERATED_ASSET={args.name}")
    print(f"KIND=sword")
    print(f"TRIANGLES={stats['triangles']}")
    print(f"BOUNDS_MIN={stats['bounds_blender']['min']}")
    print(f"BOUNDS_MAX={stats['bounds_blender']['max']}")
    print(f"BLEND={blend_path}")
    print(f"GLB={glb_path}")
    print(f"META={meta_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())