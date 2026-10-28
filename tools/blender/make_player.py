"""Generate player character rig with animations: idle, run, attack, hit, death.

Usage (inside Blender):
  blender -b --factory-startup --python tools/blender/make_player.py -- \
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

# Animation frame ranges
ANIM_FRAMES = {
    "idle": (0, 24),      # 1 second loop
    "run": (25, 48),      # 1 second loop
    "attack": (49, 72),   # 1 second (not loop)
    "hit": (73, 84),      # 0.5 seconds (not loop)
    "death": (85, 108),   # 1 second (not loop)
}

PLAYER_COLORS = {
    "skin": (0.95, 0.75, 0.65),
    "clothes": (0.20, 0.30, 0.50),
    "leather": (0.30, 0.20, 0.10),
    "metal": (0.55, 0.55, 0.60),
    "hair": (0.25, 0.15, 0.10),
}

MATERIAL_SETTINGS = {
    "skin": (0.70, 0.05),
    "clothes": (0.85, 0.05),
    "leather": (0.80, 0.10),
    "metal": (0.40, 0.70),
    "hair": (0.90, 0.0),
}

DEFAULT_BUDGET = 3000


def build_player_mesh() -> bpy.types.Object:
    """Build low-poly humanoid mesh."""
    skin_mat = make_material("mat_player_skin", PLAYER_COLORS["skin"],
                             roughness=MATERIAL_SETTINGS["skin"][0],
                             metallic=MATERIAL_SETTINGS["skin"][1])
    clothes_mat = make_material("mat_player_clothes", PLAYER_COLORS["clothes"],
                                roughness=MATERIAL_SETTINGS["clothes"][0],
                                metallic=MATERIAL_SETTINGS["clothes"][1])
    leather_mat = make_material("mat_player_leather", PLAYER_COLORS["leather"],
                                roughness=MATERIAL_SETTINGS["leather"][0],
                                metallic=MATERIAL_SETTINGS["leather"][1])
    metal_mat = make_material("mat_player_metal", PLAYER_COLORS["metal"],
                              roughness=MATERIAL_SETTINGS["metal"][0],
                              metallic=MATERIAL_SETTINGS["metal"][1])
    hair_mat = make_material("mat_player_hair", PLAYER_COLORS["hair"],
                             roughness=MATERIAL_SETTINGS["hair"][0],
                             metallic=MATERIAL_SETTINGS["hair"][1])
    
    parts = []
    
    # Head
    head = create_icosphere("Head", 0.18, (0.0, 0.0, 1.65), skin_mat, subdivisions=1)
    parts.append(head)
    
    # Hair (simple cap)
    hair = create_icosphere("Hair", 0.20, (0.0, 0.0, 1.75), hair_mat, subdivisions=1)
    for v in hair.data.vertices:
        v.co.z *= 0.6
    parts.append(hair)
    
    # Neck
    neck = create_cylinder("Neck", 0.07, 0.12, (0.0, 0.0, 1.45), skin_mat, vertices=8)
    parts.append(neck)
    
    # Torso (chest + abdomen)
    chest = create_box("Chest", (0.35, 0.20, 0.35), (0.0, 0.0, 1.20), clothes_mat)
    parts.append(chest)
    abdomen = create_box("Abdomen", (0.30, 0.18, 0.25), (0.0, 0.0, 0.85), clothes_mat)
    parts.append(abdomen)
    
    # Hips/pelvis
    hips = create_box("Hips", (0.28, 0.18, 0.15), (0.0, 0.0, 0.65), leather_mat)
    parts.append(hips)
    
    # Arms - upper arms
    for side, x in [("L", -0.22), ("R", 0.22)]:
        upper_arm = create_cylinder(f"UpperArm_{side}", 0.06, 0.25, (x, 0.0, 1.25), skin_mat, vertices=8)
        parts.append(upper_arm)
        # Forearm
        forearm = create_cylinder(f"Forearm_{side}", 0.05, 0.22, (x, 0.0, 0.95), skin_mat, vertices=8)
        parts.append(forearm)
        # Hand
        hand = create_icosphere(f"Hand_{side}", 0.06, (x, 0.0, 0.78), skin_mat, subdivisions=1)
        parts.append(hand)
    
    # Legs - thighs
    for side, x in [("L", -0.10), ("R", 0.10)]:
        thigh = create_cylinder(f"Thigh_{side}", 0.08, 0.35, (x, 0.0, 0.45), clothes_mat, vertices=8)
        parts.append(thigh)
        # Shin
        shin = create_cylinder(f"Shin_{side}", 0.07, 0.35, (x, 0.0, 0.10), clothes_mat, vertices=8)
        parts.append(shin)
        # Foot
        foot = create_box(f"Foot_{side}", (0.12, 0.07, 0.20), (x, 0.05, -0.05), leather_mat)
        parts.append(foot)
    
    # Shoulder armor (pauldrons)
    for side, x in [("L", -0.25), ("R", 0.25)]:
        pauldron = create_cone(f"Pauldron_{side}", 0.12, 0.04, 0.15, (x, 0.0, 1.35), metal_mat, vertices=8)
        parts.append(pauldron)
    
    # Belt
    belt = create_cylinder("Belt", 0.29, 0.04, (0.0, 0.0, 0.72), leather_mat, vertices=12)
    parts.append(belt)
    
    return join_objects(parts, "sm_player")


def build_player_rig(mesh: bpy.types.Object) -> bpy.types.Object:
    """Create a humanoid armature for the player."""
    bpy.ops.object.armature_add(enter_editmode=True, location=(0.0, 0.0, 0.0))
    armature = bpy.context.object
    armature.name = "rig_player"
    armature.data.name = "rig_player"
    
    # Root bone at feet
    edit_bone = armature.data.edit_bones[0]
    edit_bone.name = "root"
    edit_bone.head = (0.0, 0.0, 0.0)
    edit_bone.tail = (0.0, 0.0, 0.1)
    
    # Spine chain
    spine_bones = [
        ("hips", (0.0, 0.0, 0.0), (0.0, 0.0, 0.65)),
        ("spine", (0.0, 0.0, 0.65), (0.0, 0.0, 1.0)),
        ("chest", (0.0, 0.0, 1.0), (0.0, 0.0, 1.35)),
        ("neck", (0.0, 0.0, 1.35), (0.0, 0.0, 1.55)),
        ("head", (0.0, 0.0, 1.55), (0.0, 0.0, 1.85)),
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
        # Shoulder
        shoulder = armature.data.edit_bones.new(f"shoulder_{side}")
        shoulder.head = (x_sign * 0.18, 0.0, 1.35)
        shoulder.tail = (x_sign * 0.25, 0.0, 1.35)
        shoulder.parent = armature.data.edit_bones["chest"]
        
        # Upper arm
        upper_arm = armature.data.edit_bones.new(f"upper_arm_{side}")
        upper_arm.head = (x_sign * 0.25, 0.0, 1.35)
        upper_arm.tail = (x_sign * 0.25, 0.0, 1.05)
        upper_arm.parent = armature.data.edit_bones[f"shoulder_{side}"]
        
        # Forearm
        forearm = armature.data.edit_bones.new(f"forearm_{side}")
        forearm.head = (x_sign * 0.25, 0.0, 1.05)
        forearm.tail = (x_sign * 0.25, 0.0, 0.80)
        forearm.parent = armature.data.edit_bones[f"upper_arm_{side}"]
        
        # Hand
        hand = armature.data.edit_bones.new(f"hand_{side}")
        hand.head = (x_sign * 0.25, 0.0, 0.80)
        hand.tail = (x_sign * 0.25, 0.0, 0.72)
        hand.parent = armature.data.edit_bones[f"forearm_{side}"]
    
    # Legs
    for side, x_sign in [("L", -1), ("R", 1)]:
        # Thigh
        thigh = armature.data.edit_bones.new(f"thigh_{side}")
        thigh.head = (x_sign * 0.10, 0.0, 0.65)
        thigh.tail = (x_sign * 0.10, 0.0, 0.30)
        thigh.parent = armature.data.edit_bones["hips"]
        
        # Shin
        shin = armature.data.edit_bones.new(f"shin_{side}")
        shin.head = (x_sign * 0.10, 0.0, 0.30)
        shin.tail = (x_sign * 0.10, 0.0, -0.05)
        shin.parent = armature.data.edit_bones[f"thigh_{side}"]
        
        # Foot
        foot = armature.data.edit_bones.new(f"foot_{side}")
        foot.head = (x_sign * 0.10, 0.0, -0.05)
        foot.tail = (x_sign * 0.10, 0.05, -0.05)
        foot.parent = armature.data.edit_bones[f"shin_{side}"]
    
    bpy.ops.object.mode_set(mode="OBJECT")
    
    # Assign vertex groups (automatic weights from bone envelopes)
    # We'll use a simple approach: assign vertices by proximity to bone positions
    # For a proper rig, we'd use automatic weights, but let's do manual assignment
    
    # Create vertex groups for each bone
    for bone in armature.data.bones:
        vg = mesh.vertex_groups.new(name=bone.name)
    
    # Assign vertices based on Z position and X position
    for v in mesh.data.vertices:
        z = v.co.z
        x = v.co.x
        
        # Root/hips area
        if z < 0.2:
            if abs(x) < 0.15:
                mesh.vertex_groups["hips"].add([v.index], 1.0, "ADD")
            elif x < -0.15:
                mesh.vertex_groups["thigh_L"].add([v.index], 1.0, "ADD")
            elif x > 0.15:
                mesh.vertex_groups["thigh_R"].add([v.index], 1.0, "ADD")
        # Legs
        elif z < 0.5:
            if x < -0.05:
                mesh.vertex_groups["thigh_L"].add([v.index], 0.7, "ADD")
                mesh.vertex_groups["shin_L"].add([v.index], 0.3, "ADD")
            elif x > 0.05:
                mesh.vertex_groups["thigh_R"].add([v.index], 0.7, "ADD")
                mesh.vertex_groups["shin_R"].add([v.index], 0.3, "ADD")
            else:
                mesh.vertex_groups["hips"].add([v.index], 1.0, "ADD")
        elif z < 0.8:
            if x < -0.05:
                mesh.vertex_groups["shin_L"].add([v.index], 1.0, "ADD")
            elif x > 0.05:
                mesh.vertex_groups["shin_R"].add([v.index], 1.0, "ADD")
            else:
                mesh.vertex_groups["hips"].add([v.index], 1.0, "ADD")
        # Torso
        elif z < 1.1:
            mesh.vertex_groups["spine"].add([v.index], 0.5, "ADD")
            mesh.vertex_groups["chest"].add([v.index], 0.5, "ADD")
        elif z < 1.4:
            mesh.vertex_groups["chest"].add([v.index], 1.0, "ADD")
        # Neck/head
        elif z < 1.6:
            mesh.vertex_groups["neck"].add([v.index], 1.0, "ADD")
        else:
            mesh.vertex_groups["head"].add([v.index], 1.0, "ADD")
        
        # Arms
        if abs(x) > 0.2 and z > 0.8 and z < 1.4:
            if x < 0:
                if z > 1.1:
                    mesh.vertex_groups["upper_arm_L"].add([v.index], 1.0, "ADD")
                elif z > 0.9:
                    mesh.vertex_groups["forearm_L"].add([v.index], 1.0, "ADD")
                else:
                    mesh.vertex_groups["hand_L"].add([v.index], 1.0, "ADD")
            else:
                if z > 1.1:
                    mesh.vertex_groups["upper_arm_R"].add([v.index], 1.0, "ADD")
                elif z > 0.9:
                    mesh.vertex_groups["forearm_R"].add([v.index], 1.0, "ADD")
                else:
                    mesh.vertex_groups["hand_R"].add([v.index], 1.0, "ADD")
    
    # Add armature modifier
    modifier = mesh.modifiers.new("Armature", "ARMATURE")
    modifier.object = armature
    mesh.parent = armature
    
    return armature


def animate_player(armature: bpy.types.Object) -> list[bpy.types.Action]:
    """Create all player animations."""
    scene = bpy.context.scene
    scene.render.fps = FPS
    scene.frame_start = 0
    scene.frame_end = 108
    
    armature.animation_data_create()
    actions = []
    
    # Helper to set keyframes
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
    
    # Breathing motion - subtle chest/hips movement
    for frame in [0, 12, 24]:
        breath = math.sin(frame / 12 * math.pi) * 0.01
        keyframe_bone("hips", frame, location=(0, 0, breath))
        keyframe_bone("chest", frame, location=(0, 0, breath * 0.5))
        keyframe_bone("head", frame, rotation=(breath * 0.1, 0, 0))
        # Subtle arm sway
        keyframe_bone("upper_arm_L", frame, rotation=(0, 0, breath * 0.2))
        keyframe_bone("upper_arm_R", frame, rotation=(0, 0, -breath * 0.2))
    
    actions.append(action_idle)
    
    # === RUN (25-48) ===
    action_run = bpy.data.actions.new("anim_run")
    action_run.use_fake_user = True
    slot = action_run.slots.new(id_type="OBJECT", name=armature.name)
    
    # Run cycle: 24 frames = 1 second at 24fps
    run_frames = [25, 31, 37, 43, 48]
    for i, frame in enumerate(run_frames):
        phase = i / 4 * math.tau
        # Legs alternate
        leg_phase_L = phase
        leg_phase_R = phase + math.pi
        
        # Hips bounce
        hip_y = math.sin(phase * 2) * 0.02
        keyframe_bone("hips", frame, location=(0, hip_y, 0))
        
        # Left leg
        thigh_rot_L = math.sin(leg_phase_L) * 0.8
        shin_rot_L = max(0, math.sin(leg_phase_L + 0.5)) * 1.0
        foot_rot_L = -thigh_rot_L * 0.3
        keyframe_bone("thigh_L", frame, rotation=(thigh_rot_L, 0, 0))
        keyframe_bone("shin_L", frame, rotation=(shin_rot_L, 0, 0))
        keyframe_bone("foot_L", frame, rotation=(foot_rot_L, 0, 0))
        
        # Right leg
        thigh_rot_R = math.sin(leg_phase_R) * 0.8
        shin_rot_R = max(0, math.sin(leg_phase_R + 0.5)) * 1.0
        foot_rot_R = -thigh_rot_R * 0.3
        keyframe_bone("thigh_R", frame, rotation=(thigh_rot_R, 0, 0))
        keyframe_bone("shin_R", frame, rotation=(shin_rot_R, 0, 0))
        keyframe_bone("foot_R", frame, rotation=(foot_rot_R, 0, 0))
        
        # Arms swing opposite to legs
        arm_swing_L = -math.sin(leg_phase_L) * 0.8
        arm_swing_R = -math.sin(leg_phase_R) * 0.8
        keyframe_bone("upper_arm_L", frame, rotation=(arm_swing_L, 0, 0.2))
        keyframe_bone("upper_arm_R", frame, rotation=(arm_swing_R, 0, -0.2))
        keyframe_bone("forearm_L", frame, rotation=(arm_swing_L * 0.5, 0, 0))
        keyframe_bone("forearm_R", frame, rotation=(arm_swing_R * 0.5, 0, 0))
        
        # Spine counter-rotation
        spine_twist = math.sin(phase) * 0.1
        keyframe_bone("spine", frame, rotation=(0, 0, spine_twist))
        keyframe_bone("chest", frame, rotation=(0, 0, -spine_twist * 0.5))
    
    actions.append(action_run)
    
    # === ATTACK (49-72) ===
    action_attack = bpy.data.actions.new("anim_attack")
    action_attack.use_fake_user = True
    slot = action_attack.slots.new(id_type="OBJECT", name=armature.name)
    
    # Windup (49-55), Swing (55-62), Recovery (62-72)
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
        t = (frame - 49) / 23  # 0 to 1
        
        if stage.startswith("windup"):
            # Pull back right arm
            windup = min(1, (frame - 49) / 6) * 1.5
            keyframe_bone("upper_arm_R", frame, rotation=(windup, 0, -0.5))
            keyframe_bone("forearm_R", frame, rotation=(windup * 0.5, 0, 0))
            keyframe_bone("hand_R", frame, rotation=(0, 0, 0))
            # Left arm forward for balance
            keyframe_bone("upper_arm_L", frame, rotation=(-0.5, 0, 0.3))
            # Body twist
            keyframe_bone("spine", frame, rotation=(0, 0, -0.3))
            keyframe_bone("chest", frame, rotation=(0, 0, -0.5))
            
        elif stage == "swing":
            # Fast forward swing
            keyframe_bone("upper_arm_R", frame, rotation=(-1.5, 0, -0.3))
            keyframe_bone("forearm_R", frame, rotation=(-0.5, 0, 0))
            keyframe_bone("spine", frame, rotation=(0, 0, 0.3))
            keyframe_bone("chest", frame, rotation=(0, 0, 0.5))
            
        elif stage == "impact":
            # Impact pose - arm extended
            keyframe_bone("upper_arm_R", frame, rotation=(-0.5, 0, -0.2))
            keyframe_bone("forearm_R", frame, rotation=(0, 0, 0))
            keyframe_bone("spine", frame, rotation=(0, 0, 0.2))
            keyframe_bone("chest", frame, rotation=(0, 0, 0.3))
            
        elif stage == "follow_through":
            keyframe_bone("upper_arm_R", frame, rotation=(0.2, 0, -0.1))
            keyframe_bone("forearm_R", frame, rotation=(0.3, 0, 0))
            keyframe_bone("spine", frame, rotation=(0, 0, 0.1))
            keyframe_bone("chest", frame, rotation=(0, 0, 0.1))
            
        else:  # recovery
            recover = 1 - (frame - 63) / 9
            keyframe_bone("upper_arm_R", frame, rotation=(recover * 0.2, 0, -recover * 0.1))
            keyframe_bone("forearm_R", frame, rotation=(recover * 0.3, 0, 0))
            keyframe_bone("spine", frame, rotation=(0, 0, recover * 0.1))
            keyframe_bone("chest", frame, rotation=(0, 0, recover * 0.1))
    
    actions.append(action_attack)
    
    # === HIT (73-84) ===
    action_hit = bpy.data.actions.new("anim_hit")
    action_hit.use_fake_user = True
    slot = action_hit.slots.new(id_type="OBJECT", name=armature.name)
    
    # Quick recoil
    hit_frames = [73, 75, 78, 81, 84]
    for i, frame in enumerate(hit_frames):
        intensity = 1 - i / 4
        keyframe_bone("hips", frame, location=(intensity * 0.1, 0, 0))
        keyframe_bone("chest", frame, rotation=(intensity * 0.3, 0, intensity * 0.2))
        keyframe_bone("head", frame, rotation=(intensity * 0.2, 0, intensity * 0.3))
        keyframe_bone("upper_arm_L", frame, rotation=(intensity * 0.5, 0, intensity * 0.3))
        keyframe_bone("upper_arm_R", frame, rotation=(intensity * 0.5, 0, -intensity * 0.3))
    
    actions.append(action_hit)
    
    # === DEATH (85-108) ===
    action_death = bpy.data.actions.new("anim_death")
    action_death.use_fake_user = True
    slot = action_death.slots.new(id_type="OBJECT", name=armature.name)
    
    # Fall forward and collapse
    death_frames = [85, 90, 95, 100, 108]
    for i, frame in enumerate(death_frames):
        t = i / 4
        # Fall forward
        fall_rot = t * 1.5  # ~85 degrees
        keyframe_bone("hips", frame, location=(0, 0, -t * 0.3))
        keyframe_bone("spine", frame, rotation=(fall_rot * 0.3, 0, 0))
        keyframe_bone("chest", frame, rotation=(fall_rot * 0.5, 0, 0))
        keyframe_bone("neck", frame, rotation=(fall_rot * 0.3, 0, 0))
        keyframe_bone("head", frame, rotation=(fall_rot * 0.2, 0, 0))
        # Arms go limp
        keyframe_bone("upper_arm_L", frame, rotation=(fall_rot * 0.2, 0, 0.3))
        keyframe_bone("upper_arm_R", frame, rotation=(fall_rot * 0.2, 0, -0.3))
        keyframe_bone("forearm_L", frame, rotation=(fall_rot * 0.1, 0, 0))
        keyframe_bone("forearm_R", frame, rotation=(fall_rot * 0.1, 0, 0))
        # Legs collapse
        keyframe_bone("thigh_L", frame, rotation=(fall_rot * 0.4, 0, 0.2))
        keyframe_bone("thigh_R", frame, rotation=(fall_rot * 0.4, 0, -0.2))
        keyframe_bone("shin_L", frame, rotation=(fall_rot * 0.2, 0, 0))
        keyframe_bone("shin_R", frame, rotation=(fall_rot * 0.2, 0, 0))
    
    actions.append(action_death)
    
    scene.frame_set(0)
    return actions


def parse_args() -> argparse.Namespace:
    argv = sys.argv
    argv = argv[argv.index("--") + 1:] if "--" in argv else []
    parser = argparse.ArgumentParser(description="Generate player character with animations")
    parser.add_argument("--out-dir", required=True,
                        help="project root, e.g. projects/crypt_runner")
    parser.add_argument("--name", default="rig_player", help="asset id")
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
    mesh = build_player_mesh()
    ground_origin(mesh)
    armature = build_player_rig(mesh)
    actions = animate_player(armature)

    mesh["asset_id"] = args.name
    mesh["asset_kind"] = "player"
    mesh["source"] = "procedural"
    mesh["license"] = "generated-in-repo"
    mesh["generator"] = "tools/blender/make_player.py"
    armature["rig_id"] = "rig_player"
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
            "loop": action.name in ("anim_idle", "anim_run"),
        })

    meta = build_common_meta(
        asset_id=args.name,
        kind="player",
        out_dir=out_dir,
        glb_path=glb_path,
        blend_path=blend_path,
        stats=stats,
        triangles_budget=args.triangle_budget,
        animated=True,
        extra={
            "generator": "tools/blender/make_player.py",
            "rig": {
                "id": "rig_player",
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
    print(f"KIND=player")
    print(f"TRIANGLES={stats['triangles']}")
    print(f"RIG={armature.name}")
    print(f"CLIPS={[a.name for a in actions]}")
    print(f"BLEND={blend_path}")
    print(f"GLB={glb_path}")
    print(f"META={meta_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())