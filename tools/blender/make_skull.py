"""Generate flying skull enemy rig with animations: idle/hover, attack, hit, death.

Usage (inside Blender):
  blender -b --factory-startup --python tools/blender/make_skull.py -- \
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

ANIM_FRAMES = {
    "idle": (0, 48),      # 2 second hover loop
    "attack": (49, 72),   # 1 second attack
    "hit": (73, 84),      # 0.5 second hit
    "death": (85, 108),   # 1 second death
}

SKULL_COLORS = {
    "bone": (0.80, 0.78, 0.72),
    "dark_bone": (0.55, 0.52, 0.45),
    "eye": (0.95, 0.20, 0.10),
    "jaw": (0.65, 0.62, 0.55),
}

MATERIAL_SETTINGS = {
    "bone": (0.65, 0.05),
    "dark_bone": (0.70, 0.10),
    "eye": (0.15, 0.0, 4.0),
    "jaw": (0.75, 0.05),
}

DEFAULT_BUDGET = 1500


def build_skull_mesh() -> bpy.types.Object:
    """Build the flying skull mesh."""
    bone_mat = make_material("mat_skull_bone", SKULL_COLORS["bone"],
                             roughness=MATERIAL_SETTINGS["bone"][0],
                             metallic=MATERIAL_SETTINGS["bone"][1])
    dark_bone_mat = make_material("mat_skull_dark", SKULL_COLORS["dark_bone"],
                                  roughness=MATERIAL_SETTINGS["dark_bone"][0],
                                  metallic=MATERIAL_SETTINGS["dark_bone"][1])
    eye_mat = make_material("mat_skull_eye", SKULL_COLORS["eye"],
                            roughness=MATERIAL_SETTINGS["eye"][0],
                            metallic=MATERIAL_SETTINGS["eye"][1],
                            emission_strength=MATERIAL_SETTINGS["eye"][2])
    jaw_mat = make_material("mat_skull_jaw", SKULL_COLORS["jaw"],
                            roughness=MATERIAL_SETTINGS["jaw"][0],
                            metallic=MATERIAL_SETTINGS["jaw"][1])
    
    parts = []
    
    # Main skull (cranium)
    cranium = create_icosphere("Cranium", 0.35, (0.0, 0.0, 0.0), bone_mat, subdivisions=2)
    # Flatten slightly
    for v in cranium.data.vertices:
        v.co.z *= 0.85
    parts.append(cranium)
    
    # Eye sockets (glowing)
    for x in (-0.12, 0.12):
        eye = create_icosphere(f"Eye_{x}", 0.06, (x, 0.22, 0.05), eye_mat, subdivisions=1)
        parts.append(eye)
    
    # Nose hole
    nose = create_cone("Nose", 0.04, 0.0, 0.08, (0.0, 0.25, -0.05), dark_bone_mat, vertices=6)
    parts.append(nose)
    
    # Jaw (separate for animation)
    jaw = create_box("Jaw", (0.22, 0.10, 0.15), (0.0, 0.15, -0.25), jaw_mat)
    parts.append(jaw)
    
    # Teeth (upper)
    for i in range(6):
        x = -0.15 + i * 0.06
        tooth = create_cone(f"ToothUpper_{i}", 0.015, 0.0, 0.05,
                            (x, 0.18, -0.15), bone_mat, vertices=4)
        parts.append(tooth)
    
    # Teeth (lower - on jaw)
    for i in range(6):
        x = -0.15 + i * 0.06
        tooth = create_cone(f"ToothLower_{i}", 0.015, 0.0, 0.05,
                            (x, 0.15, -0.32), bone_mat, vertices=4)
        parts.append(tooth)
    
    # Cheekbones
    for x in (-0.22, 0.22):
        cheek = create_cone(f"Cheek_{x}", 0.06, 0.0, 0.12,
                            (x, 0.0, -0.05), dark_bone_mat, vertices=6)
        parts.append(cheek)
    
    # Projectile (fireball) - separate object for attack animation
    fireball = create_icosphere("Fireball", 0.12, (0.0, 0.3, 0.0), eye_mat, subdivisions=1)
    parts.append(fireball)
    
    return join_objects(parts, "sm_skull")


def build_skull_rig(mesh: bpy.types.Object) -> bpy.types.Object:
    """Create armature for flying skull."""
    bpy.ops.object.armature_add(enter_editmode=True, location=(0.0, 0.0, 0.0))
    armature = bpy.context.object
    armature.name = "rig_skull"
    armature.data.name = "rig_skull"
    
    # Root at center of skull
    edit_bone = armature.data.edit_bones[0]
    edit_bone.name = "root"
    edit_bone.head = (0.0, 0.0, 0.0)
    edit_bone.tail = (0.0, 0.0, 0.2)
    
    # Jaw bone
    jaw = armature.data.edit_bones.new("jaw")
    jaw.head = (0.0, 0.15, -0.2)
    jaw.tail = (0.0, 0.15, -0.35)
    jaw.parent = armature.data.edit_bones["root"]
    
    # Fireball bone (for attack)
    fireball = armature.data.edit_bones.new("fireball")
    fireball.head = (0.0, 0.3, 0.0)
    fireball.tail = (0.0, 0.5, 0.0)
    fireball.parent = armature.data.edit_bones["root"]
    
    bpy.ops.object.mode_set(mode="OBJECT")
    
    # Create vertex groups
    for bone in armature.data.bones:
        mesh.vertex_groups.new(name=bone.name)
    
    # Assign vertices by position
    for v in mesh.data.vertices:
        z = v.co.z
        y = v.co.y
        x = v.co.x
        
        # Jaw area
        if z < -0.15 and y > 0.1:
            mesh.vertex_groups["jaw"].add([v.index], 1.0, "ADD")
        # Fireball
        elif y > 0.25 and abs(x) < 0.15 and abs(z) < 0.15:
            mesh.vertex_groups["fireball"].add([v.index], 1.0, "ADD")
        # Main skull
        else:
            mesh.vertex_groups["root"].add([v.index], 1.0, "ADD")
    
    modifier = mesh.modifiers.new("Armature", "ARMATURE")
    modifier.object = armature
    mesh.parent = armature
    
    return armature


def animate_skull(armature: bpy.types.Object) -> list[bpy.types.Action]:
    """Create all skull animations."""
    scene = bpy.context.scene
    scene.render.fps = FPS
    scene.frame_start = 0
    scene.frame_end = 108
    
    armature.animation_data_create()
    actions = []
    
    def keyframe_bone(bone_name, frame, location=None, rotation=None, scale=None):
        if bone_name not in armature.pose.bones:
            return
        pose_bone = armature.pose.bones[bone_name]
        pose_bone.rotation_mode = "XYZ"
        scene.frame_set(frame)
        if location:
            pose_bone.location = location
            pose_bone.keyframe_insert(data_path="location", frame=frame)
        if rotation:
            pose_bone.rotation_euler = rotation
            pose_bone.keyframe_insert(data_path="rotation_euler", frame=frame)
        if scale:
            pose_bone.scale = scale
            pose_bone.keyframe_insert(data_path="scale", frame=frame)
    
    # === IDLE/HOVER (0-48) ===
    action_idle = bpy.data.actions.new("anim_idle")
    action_idle.use_fake_user = True
    slot = action_idle.slots.new(id_type="OBJECT", name=armature.name)
    armature.animation_data.action = action_idle
    armature.animation_data.action_slot = slot
    
    # Hover: gentle up/down + slight rotation + jaw breathing
    idle_frames = [0, 12, 24, 36, 48]
    for i, frame in enumerate(idle_frames):
        phase = i / 4 * math.tau
        # Hover up/down
        hover_y = math.sin(phase) * 0.08
        keyframe_bone("root", frame, location=(0, hover_y, 0))
        # Gentle tilt
        tilt = math.sin(phase * 0.5) * 0.05
        keyframe_bone("root", frame, rotation=(tilt, 0, tilt * 0.5))
        # Jaw breathing
        jaw_open = math.sin(phase) * 0.08
        keyframe_bone("jaw", frame, rotation=(jaw_open, 0, 0))
        # Fireball hidden during idle
        keyframe_bone("fireball", frame, location=(0, -10, 0), scale=(0.01, 0.01, 0.01))
    
    actions.append(action_idle)
    
    # === ATTACK (49-72) ===
    action_attack = bpy.data.actions.new("anim_attack")
    action_attack.use_fake_user = True
    slot = action_attack.slots.new(id_type="OBJECT", name=armature.name)
    
    # Windup (49-56), Fire (56-62), Recoil (62-72)
    attack_keys = [
        (49, "windup_start"),
        (52, "windup_mid"),
        (56, "windup_end"),
        (58, "fire"),
        (60, "projectile_launch"),
        (64, "recoil"),
        (68, "recovery"),
        (72, "end"),
    ]
    
    for frame, stage in attack_keys:
        t = (frame - 49) / 23
        
        if stage.startswith("windup"):
            # Lean back, jaw opens, fireball grows
            lean = min(1, (frame - 49) / 7) * 0.3
            keyframe_bone("root", frame, rotation=(-lean, 0, 0))
            jaw_open = min(1, (frame - 49) / 7) * 0.5
            keyframe_bone("jaw", frame, rotation=(jaw_open, 0, 0))
            # Fireball appears and grows
            fireball_scale = min(1, (frame - 49) / 7) * 0.5
            keyframe_bone("fireball", frame, location=(0, 0.3, 0), scale=(fireball_scale, fireball_scale, fireball_scale))
            
        elif stage == "fire":
            # Snap forward, jaw wide
            keyframe_bone("root", frame, rotation=(0.2, 0, 0))
            keyframe_bone("jaw", frame, rotation=(0.8, 0, 0))
            # Fireball launches forward
            keyframe_bone("fireball", frame, location=(0, 1.5, 0), scale=(0.6, 0.6, 0.6))
            
        elif stage == "projectile_launch":
            # Fireball continues forward
            keyframe_bone("fireball", frame, location=(0, 3.0, 0), scale=(0.4, 0.4, 0.4))
            keyframe_bone("root", frame, rotation=(0.1, 0, 0))
            keyframe_bone("jaw", frame, rotation=(0.4, 0, 0))
            
        elif stage == "recoil":
            # Recoil back
            keyframe_bone("root", frame, rotation=(-0.15, 0, 0))
            keyframe_bone("jaw", frame, rotation=(0.2, 0, 0))
            keyframe_bone("fireball", frame, location=(0, -10, 0), scale=(0.01, 0.01, 0.01))
            
        else:  # recovery
            recover = 1 - (frame - 64) / 8
            keyframe_bone("root", frame, rotation=(-recover * 0.15, 0, 0))
            keyframe_bone("jaw", frame, rotation=(recover * 0.2, 0, 0))
    
    actions.append(action_attack)
    
    # === HIT (73-84) ===
    action_hit = bpy.data.actions.new("anim_hit")
    action_hit.use_fake_user = True
    slot = action_hit.slots.new(id_type="OBJECT", name=armature.name)
    
    hit_frames = [73, 75, 78, 81, 84]
    for i, frame in enumerate(hit_frames):
        intensity = 1 - i / 4
        # Knockback + spin
        keyframe_bone("root", frame, location=(intensity * 0.15, intensity * 0.1, 0),
                      rotation=(intensity * 0.3, intensity * 0.5, intensity * 0.2))
        keyframe_bone("jaw", frame, rotation=(intensity * 0.5, 0, 0))
    
    actions.append(action_hit)
    
    # === DEATH (85-108) ===
    action_death = bpy.data.actions.new("anim_death")
    action_death.use_fake_user = True
    slot = action_death.slots.new(id_type="OBJECT", name=armature.name)
    
    death_frames = [85, 90, 95, 100, 108]
    for i, frame in enumerate(death_frames):
        t = i / 4
        # Fall down, spin, jaw drops, fade
        keyframe_bone("root", frame, location=(0, -t * 0.5, 0),
                      rotation=(t * 1.5, t * 2.0, t * 1.0),
                      scale=(1 - t * 0.3, 1 - t * 0.3, 1 - t * 0.3))
        keyframe_bone("jaw", frame, rotation=(t * 0.8, 0, 0))
        keyframe_bone("fireball", frame, location=(0, -10, 0), scale=(0.01, 0.01, 0.01))
    
    actions.append(action_death)
    
    scene.frame_set(0)
    return actions


def parse_args() -> argparse.Namespace:
    argv = sys.argv
    argv = argv[argv.index("--") + 1:] if "--" in argv else []
    parser = argparse.ArgumentParser(description="Generate flying skull enemy with animations")
    parser.add_argument("--out-dir", required=True,
                        help="project root, e.g. projects/crypt_runner")
    parser.add_argument("--name", default="rig_skull", help="asset id")
    parser.add_argument("--triangle-budget", type=int, default=DEFAULT_BUDGET)
    return parser.parse_args(argv)


def main() -> int:
    args = parse_args()
    if not args.name.startswith("rig_"):
        raise SystemExit("asset name must start with rig_")
    out_dir = os.path.abspath(args.out_dir)
    blend_path = os.path.join(out_dir, "blender", f"{args.name}.blend")
    glb_path = os.path.join(out_dir, "godot", "assets", "models", f"{args.name}.glb")
    meta_path = os.path.join(out_dir, "godot", "assets", "models", f"{args.name}.meta.json")

    reset_scene()
    mesh = build_skull_mesh()
    ground_origin(mesh)
    armature = build_skull_rig(mesh)
    actions = animate_skull(armature)

    mesh["asset_id"] = args.name
    mesh["asset_kind"] = "skull"
    mesh["source"] = "procedural"
    mesh["license"] = "generated-in-repo"
    mesh["generator"] = "tools/blender/make_skull.py"
    armature["rig_id"] = "rig_skull"
    armature["clips"] = [a.name for a in actions]

    stats = mesh_stats(mesh)
    if stats["triangles"] > args.triangle_budget:
        raise SystemExit(
            f"triangle budget exceeded: {stats['triangles']} > {args.triangle_budget}")

    save_blend(blend_path)
    export_glb(glb_path, animations=True)

    clips_meta = []
    for action in actions:
        duration = (action.frame_range[1] - action.frame_range[0]) / FPS
        clips_meta.append({
            "name": action.name,
            "duration_seconds": round(duration, 4),
            "loop": action.name == "anim_idle",
        })

    meta = build_common_meta(
        asset_id=args.name,
        kind="skull",
        out_dir=out_dir,
        glb_path=glb_path,
        blend_path=blend_path,
        stats=stats,
        triangles_budget=args.triangle_budget,
        animated=True,
        extra={
            "generator": "tools/blender/make_skull.py",
            "rig": {
                "id": "rig_skull",
                "bones": [bone.name for bone in armature.data.bones],
            },
            "animation": {
                "fps": FPS,
                "frame_start": 0,
                "frame_end": 108,
                "clips": clips_meta,
            },
        },
    )
    write_meta(meta_path, meta)

    print(f"GENERATED_ASSET={args.name}")
    print(f"KIND=skull")
    print(f"TRIANGLES={stats['triangles']}")
    print(f"RIG={armature.name}")
    print(f"CLIPS={[a.name for a in actions]}")
    print(f"BLEND={blend_path}")
    print(f"GLB={glb_path}")
    print(f"META={meta_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())