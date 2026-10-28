"""Rig and animate existing models (used by derive scripts and `lopodev assets rig`).

Modes:
  parts(ctx, clips)            rigid moving parts (bucket, crank, door, lid): each part
                               pivots and is animated as its own node; no skinning needed
  humanoid(ctx, clips)         Rigify's basic human metarig fitted to the mesh bounds,
                               bound with automatic weights, simple procedural clips
  transfer(ctx, donor)         copy skeleton + weights + clips from a rigged donor of
                               similar shape, so the model reuses the donor's animations
  creature(ctx, chains, clips) bone chains (tails, tentacles, necks) with automatic
                               weights and a sway clip

Every mode records a weight report (unweighted vertices, bones with no influence) in
ctx.rig_report. Automatic weights can deform badly at joints: always look at the clip
frames before calling a rig good.
"""

from __future__ import annotations

import math

import bpy
from mathutils import Vector

import lib_asset

AXES = {"x": 0, "y": 1, "z": 2}


def _meshes(ctx) -> list:
    return [obj for obj in ctx.objects() if obj.type == "MESH"]


def _bounds(objects: list) -> tuple[Vector, Vector]:
    bpy.context.view_layer.update()
    lo = Vector((math.inf,) * 3)
    hi = Vector((-math.inf,) * 3)
    for obj in objects:
        for corner in obj.bound_box:
            world = obj.matrix_world @ Vector(corner)
            lo = Vector(map(min, lo, world))
            hi = Vector(map(max, hi, world))
    return lo, hi


def _new_action(target, name: str):
    """Fresh action on `target`, previous one kept as an NLA strip so every clip exports."""
    data = target.animation_data or target.animation_data_create()
    if data.action is not None:
        _stash(target)
    action = bpy.data.actions.new(name)
    data.action = action
    return action


def _stash(target) -> None:
    data = target.animation_data
    if data is None or data.action is None:
        return
    action = data.action
    track = data.nla_tracks.new()
    track.name = action.name
    strip = track.strips.new(action.name, int(action.frame_range[0]), action)
    strip.name = action.name
    track.mute = True
    data.action = None


def finish_clips(targets: list) -> list[str]:
    """Stash the active action of each target so all clips live in NLA tracks."""
    for target in targets:
        _stash(target)
    bpy.context.scene.frame_start = 1
    bpy.context.scene.frame_end = max([int(a.frame_range[1]) for a in bpy.data.actions] + [1])
    return sorted(action.name for action in bpy.data.actions)


def parse_clip(spec: str) -> dict:
    """'crank_turn:Crank:rotate_x:360:1.0' -> clip dict (degrees or meters, seconds)."""
    parts = spec.split(":")
    if len(parts) != 5:
        raise ValueError(f"clip {spec!r} must be name:part:channel:amount:seconds")
    name, part, channel, amount, seconds = parts
    kind, _, axis = channel.partition("_")
    if kind not in ("rotate", "move", "bob", "scale") or axis not in AXES:
        raise ValueError(f"channel {channel!r} must be rotate_x|y|z, move_x|y|z, bob_x|y|z or scale_x|y|z")
    return {"name": name, "part": part, "kind": kind, "axis": axis, "amount": float(amount),
            "seconds": float(seconds)}


def parts(ctx, clips: list[str], pivots: dict[str, tuple] | None = None, fps: int = 24) -> list[str]:
    """Animate rigid parts by name. Pivot defaults to the part's top-center (hanging items)
    for `bob`/`move`, and its bounds center for rotations, unless given in `pivots`."""
    bpy.context.scene.render.fps = fps
    animated = []
    for spec in clips:
        clip = parse_clip(spec)
        found = ctx.find(clip["part"])
        obj = found[0]
        if obj not in animated:
            lo, hi = _bounds([obj])
            pivot = Vector(pivots[obj.name]) if pivots and obj.name in pivots else (lo + hi) / 2
            bpy.context.scene.cursor.location = pivot
            lib_asset.select_only([obj], obj)
            bpy.ops.object.origin_set(type="ORIGIN_CURSOR")
            animated.append(obj)
        frames = max(2, int(clip["seconds"] * fps))
        obj.rotation_mode = "XYZ"
        _new_action(obj, clip["name"])
        index = AXES[clip["axis"]]
        rest_rotation, rest_location, rest_scale = obj.rotation_euler.copy(), obj.location.copy(), obj.scale.copy()
        for step in range(0, 5):
            t = step / 4
            frame = 1 + round(t * frames)
            obj.rotation_euler, obj.location, obj.scale = rest_rotation.copy(), rest_location.copy(), rest_scale.copy()
            if clip["kind"] == "rotate":
                obj.rotation_euler[index] = rest_rotation[index] + math.radians(clip["amount"]) * t
                obj.keyframe_insert("rotation_euler", frame=frame)
            elif clip["kind"] in ("move", "bob"):
                wave = math.sin(t * math.pi) if clip["kind"] == "bob" else t
                obj.location[index] = rest_location[index] + clip["amount"] * wave
                obj.keyframe_insert("location", frame=frame)
            else:
                obj.scale[index] = rest_scale[index] * (1 + (clip["amount"] - 1) * math.sin(t * math.pi))
                obj.keyframe_insert("scale", frame=frame)
        obj.rotation_euler, obj.location, obj.scale = rest_rotation, rest_location, rest_scale
        ctx.log(f"clip {clip['name']}: {clip['kind']} {obj.name} {clip['axis']} {clip['amount']} over {clip['seconds']}s")
    names = finish_clips(animated)
    ctx.rig_report = {"mode": "parts", "clips": names, "parts": [o.name for o in animated],
                      "unweighted_vertices": 0, "dead_bones": []}
    ctx.show(note=f"rigged parts {[o.name for o in animated]}")
    return names


def weight_report(armature, meshes: list) -> dict:
    deform = {bone.name for bone in armature.data.bones if bone.use_deform}
    used: set[str] = set()
    unweighted = 0
    total = 0
    for obj in meshes:
        names = {group.index: group.name for group in obj.vertex_groups}
        for vertex in obj.data.vertices:
            total += 1
            weights = [(names.get(g.group), g.weight) for g in vertex.groups if g.weight > 0.001]
            weights = [(n, w) for n, w in weights if n in deform]
            if not weights:
                unweighted += 1
            used |= {n for n, _ in weights}
    return {"vertices": total, "unweighted_vertices": unweighted, "deform_bones": len(deform),
            "dead_bones": sorted(deform - used)}


def _bind(armature, meshes: list) -> None:
    for obj in meshes:
        lib_asset.select_only([obj, armature], armature)
        bpy.ops.object.parent_set(type="ARMATURE_AUTO")


def _join_meshes(ctx, name: str):
    meshes = _meshes(ctx)
    if len(meshes) > 1:
        return lib_asset.join_objects(meshes, name)
    return meshes[0]


def _key_bones(armature, name: str, frames: int, poses: list[dict]) -> None:
    """poses: list of {bone: (x_deg, y_deg, z_deg)} spread evenly over the clip, looping."""
    _new_action(armature, name)
    bpy.context.view_layer.objects.active = armature
    for index, pose in enumerate(poses + [poses[0]]):
        frame = 1 + round(index * frames / len(poses))
        for bone in armature.pose.bones:
            bone.rotation_mode = "XYZ"
            bone.rotation_euler = [math.radians(v) for v in pose.get(bone.name, (0.0, 0.0, 0.0))]
            bone.keyframe_insert("rotation_euler", frame=frame)


HUMANOID_CLIPS = {
    # bone names from Rigify's basic human metarig
    "idle": [{"spine.001": (2, 0, 0)}, {"spine.001": (-2, 0, 0)}],
    "walk": [{"thigh.L": (25, 0, 0), "thigh.R": (-25, 0, 0), "upper_arm.L": (-20, 0, 0), "upper_arm.R": (20, 0, 0)},
             {"thigh.L": (-25, 0, 0), "thigh.R": (25, 0, 0), "upper_arm.L": (20, 0, 0), "upper_arm.R": (-20, 0, 0)}],
    "run": [{"thigh.L": (45, 0, 0), "thigh.R": (-40, 0, 0), "shin.L": (-40, 0, 0), "upper_arm.L": (-40, 0, 0),
             "upper_arm.R": (40, 0, 0), "spine": (8, 0, 0)},
            {"thigh.L": (-40, 0, 0), "thigh.R": (45, 0, 0), "shin.R": (-40, 0, 0), "upper_arm.L": (40, 0, 0),
             "upper_arm.R": (-40, 0, 0), "spine": (8, 0, 0)}],
    "attack": [{"upper_arm.R": (0, 0, 0)}, {"upper_arm.R": (-80, 0, 20), "forearm.R": (-30, 0, 0)}],
    "hit": [{"spine": (0, 0, 0)}, {"spine": (-15, 0, 5), "spine.001": (-10, 0, 0)}],
    "death": [{"spine": (0, 0, 0)}, {"spine": (-60, 0, 0), "thigh.L": (30, 0, 0), "thigh.R": (30, 0, 0)}],
}


def humanoid(ctx, clips: list[str] | None = None, fps: int = 24) -> list[str]:
    """Fit Rigify's basic human metarig to the model and bind with automatic weights."""
    import addon_utils
    addon_utils.enable("rigify", default_set=True, persistent=False)
    mesh = _join_meshes(ctx, "Body")
    lo, hi = _bounds([mesh])
    height = hi.z - lo.z
    if height <= 0:
        raise RuntimeError("model has no height")
    bpy.context.scene.cursor.location = (0, 0, 0)
    bpy.ops.object.armature_basic_human_metarig_add()
    rig = bpy.context.object
    rig.name = "Armature"
    rig_lo, rig_hi = _bounds([rig])
    scale = height / max(rig.dimensions.z, 1e-6)
    rig.scale = (scale,) * 3
    bpy.context.view_layer.update()
    rig_lo, rig_hi = _bounds([rig])
    center = (lo + hi) / 2
    rig.location += Vector((center.x - (rig_lo.x + rig_hi.x) / 2, center.y - (rig_lo.y + rig_hi.y) / 2,
                            lo.z - rig_lo.z))
    lib_asset.select_only([rig], rig)
    bpy.ops.object.transform_apply(location=True, rotation=True, scale=True)
    _bind(rig, [mesh])
    report = weight_report(rig, [mesh])
    bpy.context.scene.render.fps = fps
    names = []
    for clip in clips or ["idle", "walk"]:
        if clip not in HUMANOID_CLIPS:
            raise ValueError(f"no built-in humanoid clip {clip!r}; built-in: {sorted(HUMANOID_CLIPS)}")
        _key_bones(rig, clip, fps if clip != "run" else int(fps * 0.6), HUMANOID_CLIPS[clip])
        names.append(clip)
    finish_clips([rig])
    ctx.rig_report = {"mode": "humanoid", "skeleton": "rigify basic human metarig", "clips": names, **report}
    ctx.log(f"humanoid rig: {len(rig.data.bones)} bones, {report['unweighted_vertices']} unweighted vertices")
    ctx.show(note="humanoid rig bound")
    return names


def transfer(ctx, donor_objects: list) -> list[str]:
    """Move the donor's skeleton, weights and clips onto the model (similar body shape)."""
    donor_rig = next((obj for obj in donor_objects if obj.type == "ARMATURE"), None)
    donor_meshes = [obj for obj in donor_objects if obj.type == "MESH" and obj.find_armature()]
    if donor_rig is None or not donor_meshes:
        raise RuntimeError("donor has no armature with a skinned mesh")
    target_meshes = [obj for obj in _meshes(ctx) if obj not in donor_objects]
    target = lib_asset.join_objects(target_meshes, "Body") if len(target_meshes) > 1 else target_meshes[0]
    t_lo, t_hi = _bounds([target])
    d_lo, d_hi = _bounds(donor_meshes)
    ratio = (t_hi.z - t_lo.z) / max(d_hi.z - d_lo.z, 1e-6)
    if not 0.5 <= ratio <= 2.0:
        ctx.log(f"warning: target is {ratio:.2f}x the donor height; scaling the target to match")
    scale = 1 / ratio
    target.scale = (scale,) * 3
    bpy.context.view_layer.update()
    t_lo, t_hi = _bounds([target])
    target.location += Vector(((d_lo.x + d_hi.x - t_lo.x - t_hi.x) / 2, (d_lo.y + d_hi.y - t_lo.y - t_hi.y) / 2,
                               d_lo.z - t_lo.z))
    lib_asset.select_only([target], target)
    bpy.ops.object.transform_apply(location=True, rotation=True, scale=True)
    donor = lib_asset.join_objects(donor_meshes, "DonorBody") if len(donor_meshes) > 1 else donor_meshes[0]
    for group in donor.vertex_groups:
        if group.name not in target.vertex_groups:
            target.vertex_groups.new(name=group.name)
    modifier = target.modifiers.new("WeightTransfer", "DATA_TRANSFER")
    modifier.object = donor
    modifier.use_vert_data = True
    modifier.data_types_verts = {"VGROUP_WEIGHTS"}
    modifier.vert_mapping = "POLYINTERP_NEAREST"
    modifier.layers_vgroup_select_src = "ALL"
    modifier.layers_vgroup_select_dst = "NAME"
    lib_asset.select_only([target], target)
    bpy.ops.object.modifier_apply(modifier=modifier.name)
    target.parent = donor_rig
    target.matrix_parent_inverse = donor_rig.matrix_world.inverted()
    armature_mod = target.modifiers.new("Armature", "ARMATURE")
    armature_mod.object = donor_rig
    bpy.data.objects.remove(donor, do_unlink=True)
    report = weight_report(donor_rig, [target])
    names = finish_clips([donor_rig])
    ctx.rig_report = {"mode": "transfer", "clips": names, "height_ratio": round(ratio, 3), **report}
    ctx.log(f"transferred {len(donor_rig.data.bones)} bones and {len(names)} clips; "
            f"{report['unweighted_vertices']} unweighted vertices")
    ctx.show(note="weights transferred from donor")
    return names


def creature(ctx, chains: list[str], clips: list[str] | None = None, fps: int = 24) -> list[str]:
    """chains: 'Tail=x0,y0,z0:x1,y1,z1:segments' in model space (meters)."""
    mesh = _join_meshes(ctx, "Body")
    armature_data = bpy.data.armatures.new("Armature")
    rig = bpy.data.objects.new("Armature", armature_data)
    bpy.context.scene.collection.objects.link(rig)
    lib_asset.select_only([rig], rig)
    bpy.ops.object.mode_set(mode="EDIT")
    bones = []
    for spec in chains:
        name, _, rest = spec.partition("=")
        start, end, segments = rest.split(":")
        start, end = Vector(map(float, start.split(","))), Vector(map(float, end.split(",")))
        parent = None
        for index in range(int(segments)):
            bone = armature_data.edit_bones.new(f"{name}.{index:02d}")
            bone.head = start.lerp(end, index / int(segments))
            bone.tail = start.lerp(end, (index + 1) / int(segments))
            bone.parent = parent
            bone.use_connect = parent is not None
            parent = bone
            bones.append(bone.name)
    bpy.ops.object.mode_set(mode="OBJECT")
    _bind(rig, [mesh])
    report = weight_report(rig, [mesh])
    names = []
    for clip in clips or ["sway"]:
        poses = [{bone: (0, 0, 12) for bone in bones}, {bone: (0, 0, -12) for bone in bones}]
        _key_bones(rig, clip, fps, poses)
        names.append(clip)
    finish_clips([rig])
    ctx.rig_report = {"mode": "creature", "clips": names, "chains": chains, **report}
    ctx.show(note=f"creature rig with {len(bones)} bones")
    return names
