"""Generate skeleton enemy rig with animations: idle, walk, attack, hit, death.

Usage (inside Blender):
  blender -b --factory-startup --python tools/blender/make_skeleton.py -- \
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
    "idle": (0, 24),
    "walk": (25, 48),
    "attack": (49, 72),
    "hit": (73, 84),
    "death": (85, 108),
}

SKELETON_COLORS = {
    "bone": (0.85, 0.82, 0.75),
    "dark_bone": (0.65, 0.62, 0.55),
    "eye": (0.90, 0.10, 0.10),
    "weapon": (0.45, 0.40, 0.35),
}

MATERIAL_SETTINGS = {
    "bone": (0.70, 0.05),
    "dark_bone": (0.75, 0.10),
    "eye": (0.20, 0.0, 3.0),
    "weapon": (0.40, 0.60),
}

DEFAULT_BUDGET = 2000


def build_skeleton_mesh() -> bpy.types.Object:
    """Build the skeleton mesh."""
    bone_mat = make_material("mat_skeleton_bone", SKELETON_COLORS["bone"],
                             roughness=MATERIAL_SETTINGS["bone"][0],
                             metallic=MATERIAL_SETTINGS["bone"][1])
    dark_bone_mat = make_material("mat_skeleton_dark", SKELETON_COLORS["dark_bone"],
                                  roughness=MATERIAL_SETTINGS["dark_bone"][0],
                                  metallic=MATERIAL_SETTINGS["dark_bone"][1])
    eye_mat = make_material("mat_skeleton_eye", SKELETON_COLORS["eye"],
                            roughness=MATERIAL_SETTINGS["eye"][0],
                            metallic=MATERIAL_SETTINGS["eye"][1],
                            emission_strength=MATERIAL_SETTINGS["eye"][2])
    weapon_mat = make_material("mat_skeleton_weapon", SKELETON_COLORS["weapon"],
                               roughness=MATERIAL_SETTINGS["weapon"][0],
                               metallic=MATERIAL_SETTINGS["weapon"][1])
    
    parts = []
    
    # Skull
    skull = create_icosphere("Skull", 0.16, (0.0, 0.0, 1.65), bone_mat, subdivisions=1)
    parts.append(skull)
    
    # Eye sockets (glowing eyes)
    for x in (-0.05, 0.05):
        eye = create_icosphere(f"Eye_{x}", 0.03, (x, 0.10, 1.68), eye_mat, subdivisions=1)
        parts.append(eye)
    
    # Jaw
    jaw = create_box("Jaw", (0.10, 0.06, 0.08), (0.0, 0.08, 1.55), dark_bone_mat)
    parts.append(jaw)
    
    # Spine/ribs
    ribs = create_box("Ribs", (0.25, 0.15, 0.35), (0.0, 0.0, 1.30), bone_mat)
    parts.append(ribs)
    lower_spine = create_box("LowerSpine", (0.18, 0.12, 0.25), (0.0, 0.0, 1.0), dark_bone_mat)
    parts.append(lower_spine)
    
    # Pelvis
    pelvis = create_box("Pelvis", (0.22, 0.12, 0.15), (0.0, 0.0, 0.75), bone_mat)
    parts.append(pelvis)
    
    # Arms
    for side, x in [("L", -0.18), ("R", 0.18)]:
        # Clavicle
        clavicle = create_cylinder(f"Clavicle_{side}", 0.03, 0.12, (x, 0.0, 1.45), bone_mat, vertices=6)
        parts.append(clavicle)
        # Upper arm
        upper_arm = create_cylinder(f"UpperArm_{side}", 0.04, 0.22, (x, 0.0, 1.25), bone_mat, vertices=6)
        parts.append(upper_arm)
        # Forearm
        forearm = create_cylinder(f"Forearm_{side}", 0.035, 0.20, (x, 0.0, 0.98), bone_mat, vertices=6)
        parts.append(forearm)
        # Hand (claw)
        hand = create_box(f"Hand_{side}", (0.08, 0.04, 0.12), (x, 0.0, 0.82), dark_bone_mat)
        parts.append(hand)
        # Claw fingers
        for i in range(3):
            finger = create_cone(f"Claw_{side}_{i}", 0.015, 0.0, 0.06,
                                 (x + (i-1)*0.02, 0.04, 0.82), dark_bone_mat, vertices=4)
            parts.append(finger)
    
    # Legs
    for side, x in [("L", -0.08), ("R", 0.08)]:
        # Thigh
        thigh = create_cylinder(f"Thigh_{side}", 0.05, 0.30, (x, 0.0, 0.55), bone_mat, vertices=6)
        parts.append(thigh)
        # Shin
        shin = create_cylinder(f"Shin_{side}", 0.045, 0.30, (x, 0.0, 0.25), bone_mat, vertices=6)
        parts.append(shin)
        # Foot
        foot = create_box(f"Foot_{side}", (0.10, 0.05, 0.18), (x, 0.04, 0.05), dark_bone_mat)
        parts.append(foot)
    
    # Weapon (rusty sword/axe) in right hand
    weapon_blade = create_box("WeaponBlade", (0.03, 0.6, 0.02), (0.18, 0.0, 1.0), weapon_mat)
    parts.append(weapon_blade)
    weapon_tip = create_cone("WeaponTip", 0.02, 0.0, 0.1, (0.18, 0.0, 1.35), weapon_mat, vertices=6)
    parts.append(weapon_tip)
    weapon_hilt = create_cylinder("WeaponHilt", 0.02, 0.1, (0.18, 0.0, 0.85), dark_bone_mat, vertices=6)
    parts.append(weapon_hilt)
    
    return join_objects(parts, "sm_skeleton")


def build_skeleton_rig(mesh: bpy.types.Object) -> bpy.types.Object:
    """Create armature for skeleton."""
    bpy.ops.object.armature_add(enter_editmode=True, location=(0.0, 0.0, 0.0))
    armature = bpy.context.object
    armature.name = "rig_skeleton"
    armature.data.name = "rig_skeleton"
    
    # Root at feet
    edit_bone = armature.data.edit_bones[0]
    edit_bone.name = "root"
    edit_bone.head = (0.0, 0.0, 0.0)
    edit_bone.tail = (0.0, 0.0, 0.1)
    
    # Spine
    spine_bones = [
        ("hips", (0.0, 0.0, 0.0), (0.0, 0.0, 0.75)),
        ("spine", (0.0, 0.0, 0.75), (0.0, 0.0, 1.1)),
        ("chest", (0.0, 0.0, 1.1), (0.0, 0.0, 1.4)),
        ("neck", (0.0, 0.0, 1.4), (0.0, 0.0, 1.55)),
        ("head", (0.0, 0.0, 1.55), (0.0, 0.0, 1.8)),
    ]
    
    prev_bone = "root"
    for name, head, tail in spine_bones:
        bone = armature.data.edit_bones.new(name)
        bone.head = head
        bone.tail = tail
        bone.parent = armature.data.edit_bones[prev_bone]
        prev_bone = name
    
    # Arms
    for side, x_sign in [("L", -1), ("R", 1)]:
        shoulder = armature.data.edit_bones.new(f"shoulder_{side}")
        shoulder.head = (x_sign * 0.15, 0.0, 1.4)
        shoulder.tail = (x_sign * 0.22, 0.0, 1.4)
        shoulder.parent = armature.data.edit_bones["chest"]
        
        upper_arm = armature.data.edit_bones.new(f"upper_arm_{side}")
        upper_arm.head = (x_sign * 0.22, 0.0, 1.4)
        upper_arm.tail = (x_sign * 0.22, 0.0, 1.15)
        upper_arm.parent = armature.data.edit_bones[f"shoulder_{side}"]
        
        forearm = armature.data.edit_bones.new(f"forearm_{side}")
        forearm.head = (x_sign * 0.22, 0.0, 1.15)
        forearm.tail = (x_sign * 0.22, 0.0, 0.90)
        forearm.parent = armature.data.edit_bones[f"upper_arm_{side}"]
        
        hand = armature.data.edit_bones.new(f"hand_{side}")
        hand.head = (x_sign * 0.22, 0.0, 0.90)
        hand.tail = (x_sign * 0.22, 0.0, 0.82)
        hand.parent = armature.data.edit_bones[f"forearm_{side}"]
    
    # Legs
    for side, x_sign in [("L", -1), ("R", 1)]:
        thigh = armature.data.edit_bones.new(f"thigh_{side}")
        thigh.head = (x_sign * 0.08, 0.0, 0.75)
        thigh.tail = (x_sign * 0.08, 0.0, 0.45)
        thigh.parent = armature.data.edit_bones["hips"]
        
        shin = armature.data.edit_bones.new(f"shin_{side}")
        shin.head = (x_sign * 0.08, 0.0, 0.45)
        shin.tail = (x_sign * 0.08, 0.0, 0.15)
        shin.parent = armature.data.edit_bones[f"thigh_{side}"]
        
        foot = armature.data.edit_bones.new(f"foot_{side}")
        foot.head = (x_sign * 0.08, 0.0, 0.15)
        foot.tail = (x_sign * 0.08, 0.05, 0.15)
        foot.parent = armature.data.edit_bones[f"shin_{side}"]
    
    # Weapon bone (attached to right hand)
    weapon = armature.data.edit_bones.new("weapon")
    weapon.head = (0.22, 0.0, 0.82)
    weapon.tail = (0.22, 0.0, 1.4)
    weapon.parent = armature.data.edit_bones["hand_R"]
    
    bpy.ops.object.mode_set(mode="OBJECT")
    
    # Create vertex groups
    for bone in armature.data.bones:
        mesh.vertex_groups.new(name=bone.name)
    
    # Assign vertices by position
    for v in mesh.data.vertices:
        z = v.co.z
        x = v.co.x
        
        if z < 0.2:
            if abs(x) < 0.1:
                mesh.vertex_groups["hips"].add([v.index], 1.0, "ADD")
            elif x < -0.1:
                mesh.vertex_groups["thigh_L"].add([v.index], 1.0, "ADD")
            elif x > 0.1:
                mesh.vertex_groups["thigh_R"].add([v.index], 1.0, "ADD")
        elif z < 0.5:
            if x < -0.05:
                mesh.vertex_groups["thigh_L"].add([v.index], 0.7, "ADD")
                mesh.vertex_groups["shin_L"].add([v.index], 0.3, "ADD")
            elif x > 0.05:
                mesh.vertex_groups["thigh_R"].add([v.index], 0.7, "ADD")
                mesh.vertex_groups["shin_R"].add([v.index], 0.3, "ADD")
        elif z < 0.8:
            if x < -0.05:
                mesh.vertex_groups["shin_L"].add([v.index], 1.0, "ADD")
            elif x > 0.05:
                mesh.vertex_groups["shin_R"].add([v.index], 1.0, "ADD")
        elif z < 1.1:
            mesh.vertex_groups["spine"].add([v.index], 0.5, "ADD")
            mesh.vertex_groups["chest"].add([v.index], 0.5, "ADD")
        elif z < 1.4:
            mesh.vertex_groups["chest"].add([v.index], 1.0, "ADD")
        elif z < 1.55:
            mesh.vertex_groups["neck"].add([v.index], 1.0, "ADD")
        else:
            mesh.vertex_groups["head"].add([v.index], 1.0, "ADD")
        
        # Arms
        if abs(x) > 0.18 and z > 0.8 and z < 1.4:
            if x < 0:
                if z > 1.2:
                    mesh.vertex_groups["upper_arm_L"].add([v.index], 1.0, "ADD")
                elif z > 0.95:
                    mesh.vertex_groups["forearm_L"].add([v.index], 1.0, "ADD")
                else:
                    mesh.vertex_groups["hand_L"].add([v.index], 1.0, "ADD")
            else:
                if z > 1.2:
                    mesh.vertex_groups["upper_arm_R"].add([v.index], 1.0, "ADD")
                elif z > 0.95:
                    mesh.vertex_groups["forearm_R"].add([v.index], 1.0, "ADD")
                else:
                    mesh.vertex_groups["hand_R"].add([v.index], 1.0, "ADD")
                    mesh.vertex_groups["weapon"].add([v.index], 1.0, "ADD")
    
    modifier = mesh.modifiers.new("Armature", "ARMATURE")
    modifier.object = armature
    mesh.parent = armature
    
    return armature


def animate_skeleton(armature: bpy.types.Object) -> list[bpy.types.Action]:
    """Create all skeleton animations."""
    scene = bpy.context.scene
    scene.render.fps = FPS
    scene.frame_start = 0
    scene.frame_end = 108
    
    armature.animation_data_create()
    actions = []
    
    def keyframe_bone(bone_name, frame, location=None, rotation=None):
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
    
    # === IDLE (0-24) ===
    action_idle = bpy.data.actions.new("anim_idle")
    action_idle.use_fake_user = True
    slot = action_idle.slots.new(id_type="OBJECT", name=armature.name)
    armature.animation_data.action = action_idle
    armature.animation_data.action_slot = slot
    
    for frame in [0, 12, 24]:
        breath = math.sin(frame / 12 * math.pi) * 0.015
        keyframe_bone("hips", frame, location=(0, 0, breath))
        keyframe_bone("chest", frame, location=(0, 0, breath * 0.5))
        keyframe_bone("head", frame, rotation=(breath * 0.1, 0, 0))
        keyframe_bone("upper_arm_L", frame, rotation=(0.1, 0, 0.2))
        keyframe_bone("upper_arm_R", frame, rotation=(0.1, 0, -0.2))
    
    actions.append(action_idle)
    
    # === WALK (25-48) ===
    action_walk = bpy.data.actions.new("anim_walk")
    action_walk.use_fake_user = True
    slot = action_walk.slots.new(id_type="OBJECT", name=armature.name)
    
    walk_frames = [25, 31, 37, 43, 48]
    for i, frame in enumerate(walk_frames):
        phase = i / 4 * math.tau
        leg_phase_L = phase
        leg_phase_R = phase + math.pi
        
        hip_y = math.sin(phase * 2) * 0.015
        keyframe_bone("hips", frame, location=(0, hip_y, 0))
        
        thigh_rot_L = math.sin(leg_phase_L) * 0.6
        shin_rot_L = max(0, math.sin(leg_phase_L + 0.3)) * 0.8
        foot_rot_L = -thigh_rot_L * 0.2
        keyframe_bone("thigh_L", frame, rotation=(thigh_rot_L, 0, 0))
        keyframe_bone("shin_L", frame, rotation=(shin_rot_L, 0, 0))
        keyframe_bone("foot_L", frame, rotation=(foot_rot_L, 0, 0))
        
        thigh_rot_R = math.sin(leg_phase_R) * 0.6
        shin_rot_R = max(0, math.sin(leg_phase_R + 0.3)) * 0.8
        foot_rot_R = -thigh_rot_R * 0.2
        keyframe_bone("thigh_R", frame, rotation=(thigh_rot_R, 0, 0))
        keyframe_bone("shin_R", frame, rotation=(shin_rot_R, 0, 0))
        keyframe_bone("foot_R", frame, rotation=(foot_rot_R, 0, 0))
        
        arm_swing_L = -math.sin(leg_phase_L) * 0.5
        arm_swing_R = -math.sin(leg_phase_R) * 0.5
        keyframe_bone("upper_arm_L", frame, rotation=(arm_swing_L, 0, 0.2))
        keyframe_bone("upper_arm_R", frame, rotation=(arm_swing_R, 0, -0.2))
        keyframe_bone("forearm_L", frame, rotation=(arm_swing_L * 0.3, 0, 0))
        keyframe_bone("forearm_R", frame, rotation=(arm_swing_R * 0.3, 0, 0))
        
        spine_twist = math.sin(phase) * 0.08
        keyframe_bone("spine", frame, rotation=(0, 0, spine_twist))
        keyframe_bone("chest", frame, rotation=(0, 0, -spine_twist * 0.5))
    
    actions.append(action_walk)
    
    # === ATTACK (49-72) ===
    action_attack = bpy.data.actions.new("anim_attack")
    action_attack.use_fake_user = True
    slot = action_attack.slots.new(id_type="OBJECT", name=armature.name)
    
    attack_keys = [
        (49, "windup_start"),
        (52, "windup_mid"),
        (55, "windup_end"),
        (57, "swing"),
        (60, "impact"),
        (63, "follow_through"),
        (66, "recovery_start"),
        (72, "recovery_end"),
    ]
    
    for frame, stage in attack_keys:
        if stage.startswith("windup"):
            windup = min(1, (frame - 49) / 6) * 1.2
            keyframe_bone("upper_arm_R", frame, rotation=(windup, 0, -0.4))
            keyframe_bone("forearm_R", frame, rotation=(windup * 0.5, 0, 0))
            keyframe_bone("spine", frame, rotation=(0, 0, -0.2))
            keyframe_bone("chest", frame, rotation=(0, 0, -0.4))
        elif stage == "swing":
            keyframe_bone("upper_arm_R", frame, rotation=(-1.2, 0, -0.2))
            keyframe_bone("forearm_R", frame, rotation=(-0.3, 0, 0))
            keyframe_bone("spine", frame, rotation=(0, 0, 0.2))
            keyframe_bone("chest", frame, rotation=(0, 0, 0.4))
        elif stage == "impact":
            keyframe_bone("upper_arm_R", frame, rotation=(-0.3, 0, -0.1))
            keyframe_bone("forearm_R", frame, rotation=(0, 0, 0))
            keyframe_bone("spine", frame, rotation=(0, 0, 0.1))
            keyframe_bone("chest", frame, rotation=(0, 0, 0.2))
        elif stage == "follow_through":
            keyframe_bone("upper_arm_R", frame, rotation=(0.2, 0, -0.1))
            keyframe_bone("forearm_R", frame, rotation=(0.2, 0, 0))
        else:
            recover = 1 - (frame - 63) / 9
            keyframe_bone("upper_arm_R", frame, rotation=(recover * 0.2, 0, -recover * 0.1))
            keyframe_bone("spine", frame, rotation=(0, 0, recover * 0.1))
            keyframe_bone("chest", frame, rotation=(0, 0, recover * 0.1))
    
    actions.append(action_attack)
    
    # === HIT (73-84) ===
    action_hit = bpy.data.actions.new("anim_hit")
    action_hit.use_fake_user = True
    slot = action_hit.slots.new(id_type="OBJECT", name=armature.name)
    
    hit_frames = [73, 75, 78, 81, 84]
    for i, frame in enumerate(hit_frames):
        intensity = 1 - i / 4
        keyframe_bone("hips", frame, location=(intensity * 0.08, 0, 0))
        keyframe_bone("chest", frame, rotation=(intensity * 0.25, 0, intensity * 0.15))
        keyframe_bone("head", frame, rotation=(intensity * 0.15, 0, intensity * 0.25))
        keyframe_bone("upper_arm_L", frame, rotation=(intensity * 0.4, 0, intensity * 0.2))
        keyframe_bone("upper_arm_R", frame, rotation=(intensity * 0.4, 0, -intensity * 0.2))
    
    actions.append(action_hit)
    
    # === DEATH (85-108) ===
    action_death = bpy.data.actions.new("anim_death")
    action_death.use_fake_user = True
    slot = action_death.slots.new(id_type="OBJECT", name=armature.name)
    
    death_frames = [85, 90, 95, 100, 108]
    for i, frame in enumerate(death_frames):
        t = i / 4
        fall_rot = t * 1.3
        keyframe_bone("hips", frame, location=(0, 0, -t * 0.25))
        keyframe_bone("spine", frame, rotation=(fall_rot * 0.3, 0, 0))
        keyframe_bone("chest", frame, rotation=(fall_rot * 0.5, 0, 0))
        keyframe_bone("neck", frame, rotation=(fall_rot * 0.3, 0, 0))
        keyframe_bone("head", frame, rotation=(fall_rot * 0.2, 0, 0))
        keyframe_bone("upper_arm_L", frame, rotation=(fall_rot * 0.2, 0, 0.3))
        keyframe_bone("upper_arm_R", frame, rotation=(fall_rot * 0.2, 0, -0.3))
        keyframe_bone("forearm_L", frame, rotation=(fall_rot * 0.1, 0, 0))
        keyframe_bone("forearm_R", frame, rotation=(fall_rot * 0.1, 0, 0))
        keyframe_bone("thigh_L", frame, rotation=(fall_rot * 0.3, 0, 0.2))
        keyframe_bone("thigh_R", frame, rotation=(fall_rot * 0.3, 0, -0.2))
        keyframe_bone("shin_L", frame, rotation=(fall_rot * 0.2, 0, 0))
        keyframe_bone("shin_R", frame, rotation=(fall_rot * 0.2, 0, 0))
    
    actions.append(action_death)
    
    scene.frame_set(0)
    return actions


def parse_args() -> argparse.Namespace:
    argv = sys.argv
    argv = argv[argv.index("--") + 1:] if "--" in argv else []
    parser = argparse.ArgumentParser(description="Generate skeleton enemy with animations")
    parser.add_argument("--out-dir", required=True,
                        help="project root, e.g. projects/crypt_runner")
    parser.add_argument("--name", default="rig_skeleton", help="asset id")
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
    mesh = build_skeleton_mesh()
    ground_origin(mesh)
    armature = build_skeleton_rig(mesh)
    actions = animate_skeleton(armature)

    mesh["asset_id"] = args.name
    mesh["asset_kind"] = "skeleton"
    mesh["source"] = "procedural"
    mesh["license"] = "generated-in-repo"
    mesh["generator"] = "tools/blender/make_skeleton.py"
    armature["rig_id"] = "rig_skeleton"
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
            "loop": action.name in ("anim_idle", "anim_walk"),
        })

    meta = build_common_meta(
        asset_id=args.name,
        kind="skeleton",
        out_dir=out_dir,
        glb_path=glb_path,
        blend_path=blend_path,
        stats=stats,
        triangles_budget=args.triangle_budget,
        animated=True,
        extra={
            "generator": "tools/blender/make_skeleton.py",
            "rig": {
                "id": "rig_skeleton",
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
    print(f"KIND=skeleton")
    print(f"TRIANGLES={stats['triangles']}")
    print(f"RIG={armature.name}")
    print(f"CLIPS={[a.name for a in actions]}")
    print(f"BLEND={blend_path}")
    print(f"GLB={glb_path}")
    print(f"META={meta_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())