"""Generate spike trap asset with animations: idle, extend, retract.

Usage (inside Blender):
  blender -b --factory-startup --python tools/blender/make_spike_trap.py -- \
    --out-dir projects/crypt_runner
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
FRAME_END = 60  # 2.5 seconds total for all clips

# Spike trap colors
SPIKE_COLORS = {
    "base": (0.25, 0.25, 0.28),      # dark metal base
    "spike": (0.45, 0.45, 0.50),     # metal spike
    "warning": (0.85, 0.20, 0.15),   # red warning glow
}

MATERIAL_SETTINGS = {
    "base": (0.70, 0.30),
    "spike": (0.50, 0.60),
    "warning": (0.30, 0.0, 2.0),  # emissive
}

DEFAULT_BUDGET = 400


def build_spike_trap() -> tuple[bpy.types.Object, bpy.types.Object]:
    """Build spike trap mesh and armature. Returns (mesh, armature)."""
    # Materials
    base_mat = make_material("mat_spike_base", SPIKE_COLORS["base"],
                             roughness=MATERIAL_SETTINGS["base"][0],
                             metallic=MATERIAL_SETTINGS["base"][1])
    spike_mat = make_material("mat_spike", SPIKE_COLORS["spike"],
                              roughness=MATERIAL_SETTINGS["spike"][0],
                              metallic=MATERIAL_SETTINGS["spike"][1])
    warning_mat = make_material("mat_spike_warning", SPIKE_COLORS["warning"],
                                roughness=MATERIAL_SETTINGS["warning"][0],
                                metallic=MATERIAL_SETTINGS["warning"][1],
                                emission_strength=MATERIAL_SETTINGS["warning"][2])
    
    # Base plate (1x1 meter, 0.1m thick)
    base = create_box("TrapBase", (1.0, 1.0, 0.1), (0.0, 0.0, 0.05), base_mat)
    
    # Spike cluster - 5 spikes in a cross pattern
    spike_height = 1.0  # fully extended height
    spike_base_radius = 0.06
    spike_positions = [
        (0.0, 0.0),      # center
        (-0.25, 0.0),    # left
        (0.25, 0.0),     # right
        (0.0, -0.25),    # back
        (0.0, 0.25),     # front
    ]
    
    spike_objects = []
    for i, (x, y) in enumerate(spike_positions):
        spike = create_cone(f"Spike_{i}", spike_base_radius, 0.0, spike_height,
                            (x, y, 0.1 + spike_height/2), spike_mat, vertices=6)
        spike_objects.append(spike)
    
    # Warning lights (small cones on base corners)
    warning_positions = [
        (-0.45, -0.45), (0.45, -0.45), (-0.45, 0.45), (0.45, 0.45)
    ]
    for i, (x, y) in enumerate(warning_positions):
        light = create_cone(f"WarningLight_{i}", 0.04, 0.0, 0.08,
                            (x, y, 0.14), warning_mat, vertices=6)
        spike_objects.append(light)
    
    # Join all mesh parts
    all_parts = [base] + spike_objects
    mesh = join_objects(all_parts, "sm_spike_trap")
    
    # Create armature with bones for each spike + base
    bpy.ops.object.armature_add(enter_editmode=True, location=(0.0, 0.0, 0.0))
    armature = bpy.context.object
    armature.name = "rig_spike_trap"
    armature.data.name = "rig_spike_trap"
    
    # Root bone
    edit_bone = armature.data.edit_bones[0]
    edit_bone.name = "root"
    edit_bone.head = (0.0, 0.0, 0.0)
    edit_bone.tail = (0.0, 0.0, 0.1)
    
    # Spike bones (children of root)
    for i in range(5):
        bone = armature.data.edit_bones.new(f"spike_{i}")
        bone.head = (spike_positions[i][0], spike_positions[i][1], 0.1)
        bone.tail = (spike_positions[i][0], spike_positions[i][1], 0.1 + spike_height)
        bone.parent = armature.data.edit_bones["root"]
    
    bpy.ops.object.mode_set(mode="OBJECT")
    
    # Create vertex groups and assign weights
    # Base vertices -> root bone (weight 1.0)
    root_vg = mesh.vertex_groups.new(name="root")
    base_verts = [v.index for v in mesh.data.vertices if v.co.z < 0.15]
    root_vg.add(base_verts, 1.0, "REPLACE")
    
    # Each spike's vertices -> corresponding spike bone
    # We need to identify which vertices belong to which spike
    # Since we joined objects, we can use the original object names
    # Actually, let's do it by position
    for i, (sx, sy) in enumerate(spike_positions):
        vg = mesh.vertex_groups.new(name=f"spike_{i}")
        spike_verts = []
        for v in mesh.data.vertices:
            # Check if vertex is near this spike's position and above base
            if (abs(v.co.x - sx) < 0.15 and 
                abs(v.co.y - sy) < 0.15 and 
                v.co.z > 0.15):
                spike_verts.append(v.index)
        if spike_verts:
            vg.add(spike_verts, 1.0, "REPLACE")
    
    # Warning lights -> root (they don't animate)
    warning_vg = mesh.vertex_groups.new(name="root")
    warning_verts = [v.index for v in mesh.data.vertices if v.co.z > 0.13 and v.co.z < 0.25]
    # Only add if not already in a spike group
    for v_idx in warning_verts:
        if len([vg for vg in mesh.vertex_groups if v_idx in [vg.index for vg in mesh.vertex_groups]]) == 0:
            pass  # Already handled
    
    # Add armature modifier
    modifier = mesh.modifiers.new("Armature", "ARMATURE")
    modifier.object = armature
    mesh.parent = armature
    
    return mesh, armature


def animate_spike_trap(armature: bpy.types.Object) -> list[bpy.types.Action]:
    """Create three animations: idle, extend, retract."""
    scene = bpy.context.scene
    scene.render.fps = FPS
    scene.frame_start = FRAME_START
    scene.frame_end = FRAME_END
    
    armature.animation_data_create()
    actions = []
    
    # Clip 1: Idle (frames 0-15) - spikes retracted (down)
    action_idle = bpy.data.actions.new("idle")
    action_idle.use_fake_user = True
    slot = action_idle.slots.new(id_type="OBJECT", name=armature.name)
    armature.animation_data.action = action_idle
    armature.animation_data.action_slot = slot
    
    # All spike bones at retracted position (z = 0.1)
    for i in range(5):
        pose_bone = armature.pose.bones[f"spike_{i}"]
        pose_bone.rotation_mode = "XYZ"
        # Retracted: scale Y to 0 (flat) or translate down
        # We'll use location keyframes
        scene.frame_set(0)
        pose_bone.location = (0.0, 0.0, 0.0)
        pose_bone.keyframe_insert(data_path="location", index=2, frame=0)
        scene.frame_set(15)
        pose_bone.location = (0.0, 0.0, 0.0)
        pose_bone.keyframe_insert(data_path="location", index=2, frame=15)
    
    # Warning lights pulse in idle
    # (We'll skip warning light animation for simplicity - they're on root)
    
    actions.append(action_idle)
    
    # Clip 2: Extend (frames 16-35) - spikes shoot up
    action_extend = bpy.data.actions.new("extend")
    action_extend.use_fake_user = True
    slot = action_extend.slots.new(id_type="OBJECT", name=armature.name)
    
    for i in range(5):
        pose_bone = armature.pose.bones[f"spike_{i}"]
        pose_bone.rotation_mode = "XYZ"
        # Start retracted
        scene.frame_set(16)
        pose_bone.location = (0.0, 0.0, 0.0)
        pose_bone.keyframe_insert(data_path="location", index=2, frame=16)
        # Extend quickly
        scene.frame_set(22)
        pose_bone.location = (0.0, 0.0, 1.0)  # full height
        pose_bone.keyframe_insert(data_path="location", index=2, frame=22)
        # Hold extended
        scene.frame_set(35)
        pose_bone.location = (0.0, 0.0, 1.0)
        pose_bone.keyframe_insert(data_path="location", index=2, frame=35)
    
    actions.append(action_extend)
    
    # Clip 3: Retract (frames 36-50) - spikes go down
    action_retract = bpy.data.actions.new("retract")
    action_retract.use_fake_user = True
    slot = action_retract.slots.new(id_type="OBJECT", name=armature.name)
    
    for i in range(5):
        pose_bone = armature.pose.bones[f"spike_{i}"]
        pose_bone.rotation_mode = "XYZ"
        # Start extended
        scene.frame_set(36)
        pose_bone.location = (0.0, 0.0, 1.0)
        pose_bone.keyframe_insert(data_path="location", index=2, frame=36)
        # Retract
        scene.frame_set(44)
        pose_bone.location = (0.0, 0.0, 0.0)
        pose_bone.keyframe_insert(data_path="location", index=2, frame=44)
        # Hold retracted
        scene.frame_set(50)
        pose_bone.location = (0.0, 0.0, 0.0)
        pose_bone.keyframe_insert(data_path="location", index=2, frame=50)
    
    actions.append(action_retract)
    
    scene.frame_set(FRAME_START)
    return actions


def parse_args() -> argparse.Namespace:
    argv = sys.argv
    argv = argv[argv.index("--") + 1:] if "--" in argv else []
    parser = argparse.ArgumentParser(description="Generate spike trap with animations")
    parser.add_argument("--out-dir", required=True,
                        help="project root, e.g. projects/crypt_runner")
    parser.add_argument("--name", default="sm_spike_trap", help="asset id")
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
    mesh, armature = build_spike_trap()
    ground_origin(mesh)
    actions = animate_spike_trap(armature)

    mesh["asset_id"] = args.name
    mesh["asset_kind"] = "spike_trap"
    mesh["source"] = "procedural"
    mesh["license"] = "generated-in-repo"
    mesh["generator"] = "tools/blender/make_spike_trap.py"
    armature["rig_id"] = "rig_spike_trap"
    armature["clips"] = [a.name for a in actions]

    stats = mesh_stats(mesh)
    if stats["triangles"] > args.triangle_budget:
        raise SystemExit(
            f"triangle budget exceeded: {stats['triangles']} > {args.triangle_budget}")

    save_blend(blend_path)
    export_glb(glb_path, animations=True)

    # Build meta with all clips
    clips_meta = []
    for action in actions:
        duration = (action.frame_range[1] - action.frame_range[0]) / FPS
        clips_meta.append({
            "name": action.name,
            "duration_seconds": round(duration, 4),
            "loop": action.name == "idle",
        })

    meta = build_common_meta(
        asset_id=args.name,
        kind="spike_trap",
        out_dir=out_dir,
        glb_path=glb_path,
        blend_path=blend_path,
        stats=stats,
        triangles_budget=args.triangle_budget,
        animated=True,
        extra={
            "generator": "tools/blender/make_spike_trap.py",
            "rig": {
                "id": "rig_spike_trap",
                "bones": [bone.name for bone in armature.data.bones],
            },
            "animation": {
                "fps": FPS,
                "frame_start": FRAME_START,
                "frame_end": FRAME_END,
                "clips": clips_meta,
            },
        },
    )
    write_meta(meta_path, meta)

    print(f"GENERATED_ASSET={args.name}")
    print(f"KIND=spike_trap")
    print(f"TRIANGLES={stats['triangles']}")
    print(f"RIG={armature.name}")
    print(f"CLIPS={[a.name for a in actions]}")
    print(f"BLEND={blend_path}")
    print(f"GLB={glb_path}")
    print(f"META={meta_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())