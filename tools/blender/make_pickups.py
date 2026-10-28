"""Generate pickup assets: coin (spin) and health pickup (pulse).

Usage (inside Blender):
  blender -b --factory-startup --python tools/blender/make_pickups.py -- \
    --kind coin --out-dir projects/crypt_runner
  blender -b --factory-startup --python tools/blender/make_pickups.py -- \
    --kind health --out-dir projects/crypt_runner
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

FPS = 24

# Pickup configurations
PICKUP_CONFIGS = {
    "coin": {
        "name": "sm_coin",
        "budget": 150,
        "colors": {
            "gold": (0.95, 0.75, 0.10),
            "dark_gold": (0.70, 0.50, 0.05),
        },
        "materials": {
            "gold": (0.30, 0.80),
            "dark_gold": (0.40, 0.60),
        },
        "build": "build_coin",
        "animate": "animate_coin",
        "frames": 60,  # 2.5 seconds for full spin
    },
    "health": {
        "name": "sm_health_pickup",
        "budget": 150,
        "colors": {
            "red": (0.85, 0.15, 0.15),
            "dark_red": (0.50, 0.05, 0.05),
            "white": (0.95, 0.95, 0.95),
        },
        "materials": {
            "red": (0.40, 0.10),
            "dark_red": (0.50, 0.05),
            "white": (0.20, 0.0),
        },
        "build": "build_health",
        "animate": "animate_health",
        "frames": 48,  # 2 seconds for pulse
    },
}


def build_coin() -> bpy.types.Object:
    """Build a gold coin - cylinder with beveled edges."""
    gold_mat = make_material("mat_coin_gold", PICKUP_CONFIGS["coin"]["colors"]["gold"],
                             roughness=PICKUP_CONFIGS["coin"]["materials"]["gold"][0],
                             metallic=PICKUP_CONFIGS["coin"]["materials"]["gold"][1])
    dark_gold_mat = make_material("mat_coin_dark", PICKUP_CONFIGS["coin"]["colors"]["dark_gold"],
                                  roughness=PICKUP_CONFIGS["coin"]["materials"]["dark_gold"][0],
                                  metallic=PICKUP_CONFIGS["coin"]["materials"]["dark_gold"][1])
    
    # Coin body - thin cylinder (lower poly)
    body = create_cylinder("CoinBody", 0.15, 0.03, (0.0, 0.0, 0.15), gold_mat, vertices=12)
    # Rim
    rim = create_cylinder("CoinRim", 0.17, 0.04, (0.0, 0.0, 0.15), dark_gold_mat, vertices=12)
    # Face detail (smaller cylinder on top)
    face = create_cylinder("CoinFace", 0.10, 0.01, (0.0, 0.0, 0.185), dark_gold_mat, vertices=8)
    
    return join_objects([body, rim, face], "sm_coin")


def build_health() -> bpy.types.Object:
    """Build a heart-shaped health pickup."""
    red_mat = make_material("mat_health_red", PICKUP_CONFIGS["health"]["colors"]["red"],
                            roughness=PICKUP_CONFIGS["health"]["materials"]["red"][0],
                            metallic=PICKUP_CONFIGS["health"]["materials"]["red"][1])
    dark_red_mat = make_material("mat_health_dark", PICKUP_CONFIGS["health"]["colors"]["dark_red"],
                                 roughness=PICKUP_CONFIGS["health"]["materials"]["dark_red"][0],
                                 metallic=PICKUP_CONFIGS["health"]["materials"]["dark_red"][1])
    white_mat = make_material("mat_health_white", PICKUP_CONFIGS["health"]["colors"]["white"],
                              roughness=PICKUP_CONFIGS["health"]["materials"]["white"][0],
                              metallic=PICKUP_CONFIGS["health"]["materials"]["white"][1])
    
    # Heart shape: two spheres (top lobes) + cone (bottom point)
    # Left lobe
    left_lobe = create_icosphere("HeartLeft", 0.12, (-0.10, 0.0, 0.22), red_mat, subdivisions=1)
    # Right lobe
    right_lobe = create_icosphere("HeartRight", 0.12, (0.10, 0.0, 0.22), red_mat, subdivisions=1)
    # Bottom cone
    bottom = create_cone("HeartBottom", 0.15, 0.0, 0.20, (0.0, 0.0, 0.10), red_mat, vertices=12)
    # Center highlight
    highlight = create_icosphere("HeartHighlight", 0.05, (0.0, -0.08, 0.25), white_mat, subdivisions=1)
    # Dark outline ring
    ring = create_cylinder("HeartRing", 0.18, 0.02, (0.0, 0.0, 0.02), dark_red_mat, vertices=16)
    
    return join_objects([left_lobe, right_lobe, bottom, highlight, ring], "sm_health_pickup")


def build_rig(mesh: bpy.types.Object, rig_name: str) -> bpy.types.Object:
    """Create a simple single-bone armature for the pickup."""
    bpy.ops.object.armature_add(enter_editmode=True, location=(0.0, 0.0, 0.0))
    armature = bpy.context.object
    armature.name = rig_name
    armature.data.name = rig_name
    edit_bone = armature.data.edit_bones[0]
    edit_bone.name = "root"
    edit_bone.head = (0.0, 0.0, 0.0)
    edit_bone.tail = (0.0, 0.0, 0.3)
    bpy.ops.object.mode_set(mode="OBJECT")
    
    # Assign all vertices to root bone
    vertex_group = mesh.vertex_groups.new(name="root")
    vertex_group.add(list(range(len(mesh.data.vertices))), 1.0, "REPLACE")
    
    modifier = mesh.modifiers.new("Armature", "ARMATURE")
    modifier.object = armature
    mesh.parent = armature
    return armature


def animate_coin(armature: bpy.types.Object, frames: int) -> bpy.types.Action:
    """Animate coin spinning 360 degrees on Y axis."""
    scene = bpy.context.scene
    scene.render.fps = FPS
    scene.frame_start = 0
    scene.frame_end = frames
    
    armature.animation_data_create()
    action = bpy.data.actions.new("anim_spin")
    action.use_fake_user = True
    slot = action.slots.new(id_type="OBJECT", name=armature.name)
    armature.animation_data.action = action
    armature.animation_data.action_slot = slot
    
    pose_bone = armature.pose.bones["root"]
    pose_bone.rotation_mode = "XYZ"
    
    # Spin 360 degrees on Y axis (index 1)
    scene.frame_set(0)
    pose_bone.rotation_euler[1] = 0.0
    pose_bone.keyframe_insert(data_path="rotation_euler", index=1, frame=0)
    
    scene.frame_set(frames)
    pose_bone.rotation_euler[1] = math.tau  # 2*pi
    pose_bone.keyframe_insert(data_path="rotation_euler", index=1, frame=frames)
    
    # Linear interpolation for constant speed
    try:
        for fcu in action.fcurves:
            for kf in fcu.keyframe_points:
                kf.interpolation = 'LINEAR'
    except AttributeError:
        # Blender 5.2+ may have different API
        pass
    
    scene.frame_set(0)
    return action


def animate_health(armature: bpy.types.Object, frames: int) -> bpy.types.Action:
    """Animate health pickup pulsing (scale up and down)."""
    scene = bpy.context.scene
    scene.render.fps = FPS
    scene.frame_start = 0
    scene.frame_end = frames
    
    armature.animation_data_create()
    action = bpy.data.actions.new("anim_pulse")
    action.use_fake_user = True
    slot = action.slots.new(id_type="OBJECT", name=armature.name)
    armature.animation_data.action = action
    armature.animation_data.action_slot = slot
    
    pose_bone = armature.pose.bones["root"]
    pose_bone.rotation_mode = "XYZ"
    
    # Pulse: scale from 1.0 to 1.2 and back
    keyframes = [
        (0, 1.0),
        (frames // 4, 1.2),
        (frames // 2, 1.0),
        (3 * frames // 4, 1.2),
        (frames, 1.0),
    ]
    
    for frame, scale in keyframes:
        scene.frame_set(frame)
        pose_bone.scale = (scale, scale, scale)
        pose_bone.keyframe_insert(data_path="scale", frame=frame)
    
    # Smooth interpolation
    try:
        for fcu in action.fcurves:
            for kf in fcu.keyframe_points:
                kf.interpolation = 'BEZIER'
    except AttributeError:
        # Blender 5.2+ may have different API
        pass
    
    scene.frame_set(0)
    return action


def parse_args() -> argparse.Namespace:
    argv = sys.argv
    argv = argv[argv.index("--") + 1:] if "--" in argv else []
    parser = argparse.ArgumentParser(description="Generate pickup assets with animations")
    parser.add_argument("--kind", required=True, choices=["coin", "health"])
    parser.add_argument("--out-dir", required=True,
                        help="project root, e.g. projects/crypt_runner")
    parser.add_argument("--name", default=None, help="asset id (default from config)")
    parser.add_argument("--triangle-budget", type=int, default=None)
    return parser.parse_args(argv)


def main() -> int:
    args = parse_args()
    config = PICKUP_CONFIGS[args.kind]
    name = args.name or config["name"]
    if not name.startswith("sm_"):
        raise SystemExit("asset name must start with sm_")
    out_dir = os.path.abspath(args.out_dir)
    blend_path = os.path.join(out_dir, "blender", f"{name}.blend")
    glb_path = os.path.join(out_dir, "godot", "assets", "models", f"{name}.glb")
    meta_path = os.path.join(out_dir, "godot", "assets", "models", f"{name}.meta.json")

    reset_scene()
    
    # Build mesh
    if config["build"] == "build_coin":
        mesh = build_coin()
    else:
        mesh = build_health()
    
    ground_origin(mesh)
    
    # Build rig
    rig_name = f"rig_{args.kind}"
    armature = build_rig(mesh, rig_name)
    
    # Animate
    if config["animate"] == "animate_coin":
        action = animate_coin(armature, config["frames"])
    else:
        action = animate_health(armature, config["frames"])
    
    actions = [action]

    mesh["asset_id"] = name
    mesh["asset_kind"] = args.kind
    mesh["source"] = "procedural"
    mesh["license"] = "generated-in-repo"
    mesh["generator"] = "tools/blender/make_pickups.py"
    armature["rig_id"] = rig_name
    armature["clip"] = action.name

    stats = mesh_stats(mesh)
    triangle_budget = args.triangle_budget or config["budget"]
    if stats["triangles"] > triangle_budget:
        raise SystemExit(
            f"triangle budget exceeded: {stats['triangles']} > {triangle_budget}")

    save_blend(blend_path)
    export_glb(glb_path, animations=True)

    duration = (action.frame_range[1] - action.frame_range[0]) / FPS
    meta = build_common_meta(
        asset_id=name,
        kind=args.kind,
        out_dir=out_dir,
        glb_path=glb_path,
        blend_path=blend_path,
        stats=stats,
        triangles_budget=triangle_budget,
        animated=True,
        extra={
            "generator": "tools/blender/make_pickups.py",
            "rig": {
                "id": rig_name,
                "bones": [bone.name for bone in armature.data.bones],
            },
            "animation": {
                "fps": FPS,
                "frame_start": 0,
                "frame_end": config["frames"],
                "clips": [
                    {
                        "name": action.name,
                        "duration_seconds": round(duration, 4),
                        "loop": True,
                    }
                ],
            },
        },
    )
    write_meta(meta_path, meta)

    print(f"GENERATED_ASSET={name}")
    print(f"KIND={args.kind}")
    print(f"TRIANGLES={stats['triangles']}")
    print(f"RIG={armature.name}")
    print(f"CLIP={action.name}")
    print(f"DURATION_SECONDS={duration:.4f}")
    print(f"BLEND={blend_path}")
    print(f"GLB={glb_path}")
    print(f"META={meta_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())