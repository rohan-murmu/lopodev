"""Generate a rigged low-poly pickup with a looping action and export it to GLB.

Usage (inside Blender):
  blender -b --factory-startup --python tools/blender/make_animated_prop.py -- \
    --kind gem --out-dir projects/prop_poc
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
FRAME_START = 0
FRAME_END = 48


def parse_args() -> argparse.Namespace:
    argv = sys.argv
    argv = argv[argv.index("--") + 1:] if "--" in argv else []
    parser = argparse.ArgumentParser(description="Generate an animated low-poly prop")
    parser.add_argument("--kind", default="gem", choices=["gem"])
    parser.add_argument("--out-dir", required=True)
    parser.add_argument("--name", default="sm_gem")
    parser.add_argument("--seed", type=int, default=11)
    parser.add_argument("--triangle-budget", type=int, default=500)
    parser.add_argument("--clip", default="anim_spin")
    return parser.parse_args(argv)


def build_gem(seed: int) -> bpy.types.Object:
    material = make_material("mat_gem_body", (0.16, 0.55, 0.72),
                             roughness=0.25, metallic=0.15)
    gem = create_icosphere("GemBody", 0.42, (0.0, 0.0, 0.62), material,
                           subdivisions=1, seed=seed)
    gem.scale = (1.0, 1.0, 1.45)
    return join_objects([gem], "sm_gem")


def build_rig(mesh: bpy.types.Object) -> bpy.types.Object:
    bpy.ops.object.armature_add(enter_editmode=True, location=(0.0, 0.0, 0.0))
    armature = bpy.context.object
    armature.name = "rig_gem"
    armature.data.name = "rig_gem"
    edit_bone = armature.data.edit_bones[0]
    edit_bone.name = "root"
    edit_bone.head = (0.0, 0.0, 0.0)
    edit_bone.tail = (0.0, 0.0, 1.0)
    bpy.ops.object.mode_set(mode="OBJECT")

    vertex_group = mesh.vertex_groups.new(name="root")
    vertex_group.add(list(range(len(mesh.data.vertices))), 1.0, "REPLACE")
    modifier = mesh.modifiers.new("Armature", "ARMATURE")
    modifier.object = armature
    mesh.parent = armature
    return armature


def animate_armature(armature: bpy.types.Object, clip_name: str) -> bpy.types.Action:
    scene = bpy.context.scene
    scene.render.fps = FPS
    scene.frame_start = FRAME_START
    scene.frame_end = FRAME_END

    armature.animation_data_create()
    action = bpy.data.actions.new(clip_name)
    action.use_fake_user = True
    slot = action.slots.new(id_type="OBJECT", name=armature.name)
    armature.animation_data.action = action
    armature.animation_data.action_slot = slot

    pose_bone = armature.pose.bones["root"]
    pose_bone.rotation_mode = "XYZ"
    keys = [
        (0, 0.0, 0.0),
        (12, math.pi * 0.5, 0.10),
        (24, math.pi, 0.0),
        (36, math.pi * 1.5, -0.10),
        (48, math.tau, 0.0),
    ]
    for frame, spin, tilt in keys:
        scene.frame_set(frame)
        pose_bone.rotation_euler[0] = tilt
        pose_bone.rotation_euler[2] = spin
        pose_bone.keyframe_insert(data_path="rotation_euler", index=0, frame=frame)
        pose_bone.keyframe_insert(data_path="rotation_euler", index=2, frame=frame)

    scene.frame_set(FRAME_START)
    return action


def main() -> int:
    args = parse_args()
    if not args.name.startswith("sm_"):
        raise SystemExit("asset name must start with sm_")
    out_dir = os.path.abspath(args.out_dir)
    blend_path = os.path.join(out_dir, "blender", f"{args.name}.blend")
    glb_path = os.path.join(out_dir, "godot", "assets", "models", f"{args.name}.glb")
    meta_path = os.path.join(out_dir, "godot", "assets", "models", f"{args.name}.meta.json")

    reset_scene()
    mesh = build_gem(args.seed)
    ground_origin(mesh)
    armature = build_rig(mesh)
    action = animate_armature(armature, args.clip)

    mesh["asset_id"] = args.name
    mesh["asset_kind"] = args.kind
    mesh["source"] = "procedural"
    mesh["license"] = "generated-in-repo"
    mesh["generator"] = "tools/blender/make_animated_prop.py"
    armature["rig_id"] = "rig_gem"
    armature["clip"] = args.clip

    stats = mesh_stats(mesh)
    if stats["triangles"] > args.triangle_budget:
        raise SystemExit(
            f"triangle budget exceeded: {stats['triangles']} > {args.triangle_budget}")

    save_blend(blend_path)
    export_glb(glb_path, animations=True)

    duration = (FRAME_END - FRAME_START) / FPS
    meta = build_common_meta(
        asset_id=args.name,
        kind=args.kind,
        out_dir=out_dir,
        glb_path=glb_path,
        blend_path=blend_path,
        stats=stats,
        triangles_budget=args.triangle_budget,
        animated=True,
        extra={
            "generator": "tools/blender/make_animated_prop.py",
            "rig": {
                "id": "rig_gem",
                "bones": [bone.name for bone in armature.data.bones],
            },
            "animation": {
                "fps": FPS,
                "frame_start": FRAME_START,
                "frame_end": FRAME_END,
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

    print(f"GENERATED_ASSET={args.name}")
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
