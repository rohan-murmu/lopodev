"""Shared Blender helpers for deterministic asset generation.

Runs inside Blender (bpy/bmesh only). No third-party Python packages.
"""

from __future__ import annotations

import hashlib
import json
import os
from datetime import datetime, timezone

import bpy
from mathutils import Vector

GENERATED_LICENSE = "generated-in-repo"


def reset_scene() -> None:
    bpy.ops.wm.read_factory_settings(use_empty=True)
    scene = bpy.context.scene
    scene.unit_settings.system = "METRIC"
    scene.unit_settings.scale_length = 1.0
    scene.render.fps = 24
    scene.frame_start = 1
    scene.frame_end = 1


def make_material(name: str, color: tuple[float, float, float], roughness: float = 0.8,
                  metallic: float = 0.0,
                  emission_strength: float = 0.0) -> bpy.types.Material:
    material = bpy.data.materials.get(name)
    if material is None:
        material = bpy.data.materials.new(name)
    material.use_nodes = True
    material.diffuse_color = (*color, 1.0)
    nodes = material.node_tree.nodes
    bsdf = nodes.get("Principled BSDF")
    if bsdf is None:
        raise RuntimeError(f"material {name}: Principled BSDF node missing")
    bsdf.inputs["Base Color"].default_value = (*color, 1.0)
    bsdf.inputs["Roughness"].default_value = roughness
    bsdf.inputs["Metallic"].default_value = metallic
    if emission_strength > 0.0:
        bsdf.inputs["Emission Color"].default_value = (*color, 1.0)
        bsdf.inputs["Emission Strength"].default_value = emission_strength
    return material


def create_box(name: str, dimensions: tuple[float, float, float],
               location: tuple[float, float, float], material: bpy.types.Material,
               rotation: tuple[float, float, float] = (0.0, 0.0, 0.0)) -> bpy.types.Object:
    bpy.ops.mesh.primitive_cube_add(size=1.0, location=location)
    obj = bpy.context.object
    obj.name = name
    obj.dimensions = dimensions
    obj.rotation_euler = rotation
    bpy.ops.object.transform_apply(location=False, rotation=True, scale=True)
    obj.data.materials.append(material)
    return obj


def create_cylinder(name: str, radius: float, depth: float,
                    location: tuple[float, float, float], material: bpy.types.Material,
                    vertices: int = 12) -> bpy.types.Object:
    bpy.ops.mesh.primitive_cylinder_add(vertices=vertices, radius=radius, depth=depth,
                                        location=location)
    obj = bpy.context.object
    obj.name = name
    obj.data.materials.append(material)
    return obj


def create_cone(name: str, radius_bottom: float, radius_top: float, depth: float,
                location: tuple[float, float, float], material: bpy.types.Material,
                vertices: int = 8) -> bpy.types.Object:
    bpy.ops.mesh.primitive_cone_add(vertices=vertices, radius1=radius_bottom,
                                    radius2=radius_top, depth=depth,
                                    location=location)
    obj = bpy.context.object
    obj.name = name
    obj.data.materials.append(material)
    return obj


def create_icosphere(name: str, radius: float, location: tuple[float, float, float],
                     material: bpy.types.Material, subdivisions: int = 1,
                     seed: int = 0) -> bpy.types.Object:
    import random

    rng = random.Random(seed)
    bpy.ops.mesh.primitive_ico_sphere_add(subdivisions=subdivisions, radius=radius,
                                          location=location)
    obj = bpy.context.object
    obj.name = name
    for vertex in obj.data.vertices:
        factor = 1.0 + rng.uniform(-0.18, 0.18)
        vertex.co.x *= factor
        vertex.co.y *= factor
        vertex.co.z *= factor * 0.82
    obj.data.materials.append(material)
    return obj


def select_only(objects: list[bpy.types.Object], active: bpy.types.Object | None = None) -> None:
    bpy.ops.object.select_all(action="DESELECT")
    for obj in objects:
        obj.select_set(True)
    bpy.context.view_layer.objects.active = active or objects[0]


def join_objects(objects: list[bpy.types.Object], name: str) -> bpy.types.Object:
    if not objects:
        raise ValueError("join_objects needs at least one object")
    if len(objects) == 1:
        obj = objects[0]
        select_only([obj], obj)
        bpy.ops.object.transform_apply(location=True, rotation=True, scale=True)
    else:
        select_only(objects, objects[0])
        bpy.ops.object.join()
        obj = bpy.context.object
        bpy.ops.object.transform_apply(location=True, rotation=True, scale=True)
    obj.name = name
    obj.data.name = name
    for polygon in obj.data.polygons:
        polygon.use_smooth = False
    return obj


def ground_origin(obj: bpy.types.Object) -> None:
    """Move mesh geometry so its lowest world point is Z=0 and origin is (0,0,0)."""
    bpy.context.scene.cursor.location = (0.0, 0.0, 0.0)
    select_only([obj], obj)
    bpy.ops.object.transform_apply(location=True, rotation=True, scale=True)
    min_z = min((obj.matrix_world @ Vector(corner)).z for corner in obj.bound_box)
    if abs(min_z) > 1e-6:
        for vertex in obj.data.vertices:
            vertex.co.z -= min_z
        obj.data.update()
    bpy.context.scene.cursor.location = (0.0, 0.0, 0.0)
    bpy.ops.object.origin_set(type="ORIGIN_CURSOR")
    obj.location = (0.0, 0.0, 0.0)


def mesh_stats(obj: bpy.types.Object) -> dict:
    obj.data.calc_loop_triangles()
    world_corners = [obj.matrix_world @ Vector(corner) for corner in obj.bound_box]
    bounds_min = [min(v[i] for v in world_corners) for i in range(3)]
    bounds_max = [max(v[i] for v in world_corners) for i in range(3)]
    return {
        "vertices": len(obj.data.vertices),
        "polygons": len(obj.data.polygons),
        "triangles": len(obj.data.loop_triangles),
        "materials": [slot.material.name for slot in obj.material_slots if slot.material],
        "bounds_blender": {
            "min": [round(v, 6) for v in bounds_min],
            "max": [round(v, 6) for v in bounds_max],
            "size": [round(bounds_max[i] - bounds_min[i], 6) for i in range(3)],
        },
    }


def ensure_parent(path: str) -> None:
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)


def save_blend(path: str) -> None:
    ensure_parent(path)
    bpy.ops.wm.save_as_mainfile(filepath=os.path.abspath(path))


def export_glb(path: str, *, animations: bool = False, animation_mode: str = "ACTIONS") -> None:
    ensure_parent(path)
    kwargs = dict(
        filepath=os.path.abspath(path),
        export_format="GLB",
        use_selection=False,
        export_yup=True,
        export_apply=False,
        export_materials="EXPORT",
        export_extras=True,
        export_cameras=False,
        export_lights=False,
        export_animations=animations,
    )
    if animations:
        kwargs.update(
            export_animation_mode=animation_mode,
            export_force_sampling=True,
        )
    bpy.ops.export_scene.gltf(**kwargs)
    if not os.path.isfile(path) or os.path.getsize(path) < 64:
        raise RuntimeError(f"GLB export did not produce a plausible file: {path}")


def sha256_file(path: str) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def write_meta(path: str, payload: dict) -> None:
    ensure_parent(path)
    with open(path, "w", encoding="utf-8") as handle:
        json.dump(payload, handle, indent=2, sort_keys=True)
        handle.write("\n")


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def build_common_meta(*, asset_id: str, kind: str, out_dir: str, glb_path: str,
                      blend_path: str, stats: dict, triangles_budget: int,
                      animated: bool = False, extra: dict | None = None) -> dict:
    payload = {
        "asset_id": asset_id,
        "kind": kind,
        "source": "procedural",
        "license": GENERATED_LICENSE,
        "generator": "tools/blender/make_prop.py",
        "animated": animated,
        "generated_at_utc": utc_now(),
        "blender_version": bpy.app.version_string,
        "triangle_budget": triangles_budget,
        "glb": {
            "path": os.path.relpath(glb_path, out_dir),
            "bytes": os.path.getsize(glb_path),
            "sha256": sha256_file(glb_path),
        },
        "blend": {
            "path": os.path.relpath(blend_path, out_dir),
            "bytes": os.path.getsize(blend_path),
        },
        "mesh": stats,
        "notes": "Validate with tools/blender/validate_asset.py before Godot import.",
    }
    if extra:
        payload.update(extra)
    return payload
