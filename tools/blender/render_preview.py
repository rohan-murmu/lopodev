"""Render inspectable previews of a saved .blend without modifying it.

Usage (inside Blender):
  blender -b --factory-startup --python tools/blender/render_preview.py -- \
    --blend projects/<slug>/blender/sm_crate.blend \
    --out projects/<slug>/artifacts/previews/sm_crate.png
"""

from __future__ import annotations

import argparse
import json
import math
import os
import sys

import bpy  # noqa: E402
from mathutils import Vector  # noqa: E402


# Camera directions from the subject (Blender +Z up, front faces -Y).
VIEWS = {
    "three_quarter": (0.95, -1.25, 0.78),
    "front": (0.0, -1.0, 0.12),
    "back": (0.0, 1.0, 0.12),
    "left": (-1.0, 0.0, 0.12),
    "right": (1.0, 0.0, 0.12),
    "top": (0.0, -0.001, 1.0),
}


def parse_args() -> argparse.Namespace:
    argv = sys.argv
    argv = argv[argv.index("--") + 1:] if "--" in argv else []
    parser = argparse.ArgumentParser(description="Render a .blend preview")
    parser.add_argument("--blend", required=True)
    parser.add_argument("--out", required=True)
    parser.add_argument("--frame", type=int, default=None)
    parser.add_argument("--frames", default=None,
                        help="comma-separated frame numbers for an animation strip")
    parser.add_argument("--views", default="three_quarter",
                        help="comma-separated: " + ",".join(VIEWS) + " (silhouette and proportion review)")
    parser.add_argument("--width", type=int, default=640)
    parser.add_argument("--height", type=int, default=480)
    parser.add_argument("--engine", default=None)
    return parser.parse_args(argv)


def choose_engine(requested: str | None) -> str:
    try:
        engines = [item.identifier for item in
                   bpy.types.RenderSettings.bl_rna.properties["engine"].enum_items]
    except Exception:
        engines = []
    if requested:
        if requested not in engines:
            raise SystemExit(f"engine {requested!r} not available; choose from {engines}")
        return requested
    for candidate in ("BLENDER_WORKBENCH", "BLENDER_EEVEE_NEXT",
                      "BLENDER_EEVEE", "CYCLES"):
        if candidate in engines:
            return candidate
    raise SystemExit(f"no supported render engine found; available: {engines}")


def mesh_bounds(frame: int) -> tuple[Vector, Vector]:
    """Bounds after modifiers and armature deformation at one frame."""
    scene = bpy.context.scene
    scene.frame_set(frame)
    depsgraph = bpy.context.evaluated_depsgraph_get()
    minimum = Vector((math.inf, math.inf, math.inf))
    maximum = Vector((-math.inf, -math.inf, -math.inf))
    found = False
    for obj in scene.objects:
        if obj.type != "MESH" or obj.hide_render:
            continue
        evaluated = obj.evaluated_get(depsgraph)
        mesh = evaluated.to_mesh()
        if len(mesh.vertices) == 0:
            evaluated.to_mesh_clear()
            continue
        found = True
        for vertex in mesh.vertices:
            world = evaluated.matrix_world @ vertex.co
            minimum.x = min(minimum.x, world.x)
            minimum.y = min(minimum.y, world.y)
            minimum.z = min(minimum.z, world.z)
            maximum.x = max(maximum.x, world.x)
            maximum.y = max(maximum.y, world.y)
            maximum.z = max(maximum.z, world.z)
        evaluated.to_mesh_clear()
    if not found:
        raise SystemExit("no visible mesh objects with vertices in the .blend")
    return minimum, maximum


def union_bounds(frames: list[int]) -> tuple[Vector, Vector]:
    minimum = Vector((math.inf, math.inf, math.inf))
    maximum = Vector((-math.inf, -math.inf, -math.inf))
    for frame in frames:
        frame_min, frame_max = mesh_bounds(frame)
        minimum.x = min(minimum.x, frame_min.x)
        minimum.y = min(minimum.y, frame_min.y)
        minimum.z = min(minimum.z, frame_min.z)
        maximum.x = max(maximum.x, frame_max.x)
        maximum.y = max(maximum.y, frame_max.y)
        maximum.z = max(maximum.z, frame_max.z)
    return minimum, maximum


def add_camera(center: Vector, radius: float, width: int,
               height: int, view: str = "three_quarter") -> bpy.types.Object:
    camera_data = bpy.data.cameras.new("PreviewCamera")
    camera = bpy.data.objects.new("PreviewCamera", camera_data)
    bpy.context.scene.collection.objects.link(camera)
    camera.data.lens = 50.0
    camera.data.sensor_fit = "AUTO"
    aspect = max(width, 1) / max(height, 1)
    horizontal_fov = camera.data.angle
    vertical_fov = 2.0 * math.atan(math.tan(horizontal_fov * 0.5) / aspect)
    limiting_fov = min(horizontal_fov, vertical_fov)
    distance = max(radius / math.sin(limiting_fov * 0.5) * 1.18, radius * 2.0, 1.0)
    direction = Vector(VIEWS[view]).normalized()
    camera.location = center + direction * distance
    camera.rotation_mode = "QUATERNION"
    camera.rotation_quaternion = (center - camera.location).to_track_quat("-Z", "Y")
    bpy.context.scene.camera = camera
    return camera


def add_lights(center: Vector, radius: float) -> None:
    if any(obj.type == "LIGHT" for obj in bpy.context.scene.objects):
        return
    key_data = bpy.data.lights.new("PreviewKey", type="AREA")
    key_data.energy = max(300.0, radius * radius * 900.0)
    key_data.shape = "DISK"
    key_data.size = max(1.0, radius * 3.0)
    key = bpy.data.objects.new("PreviewKey", key_data)
    key.location = center + Vector((radius * 2.5, -radius * 2.5, radius * 4.0))
    key.rotation_euler = (center - key.location).to_track_quat("-Z", "Y").to_euler()
    bpy.context.scene.collection.objects.link(key)

    fill_data = bpy.data.lights.new("PreviewFill", type="AREA")
    fill_data.energy = max(80.0, radius * radius * 220.0)
    fill_data.size = max(1.0, radius * 4.0)
    fill = bpy.data.objects.new("PreviewFill", fill_data)
    fill.location = center + Vector((-radius * 3.0, -radius * 1.0, radius * 1.5))
    fill.rotation_euler = (center - fill.location).to_track_quat("-Z", "Y").to_euler()
    bpy.context.scene.collection.objects.link(fill)


def configure_render(engine: str, width: int, height: int) -> None:
    scene = bpy.context.scene
    scene.render.engine = engine
    scene.render.resolution_x = width
    scene.render.resolution_y = height
    scene.render.resolution_percentage = 100
    scene.render.image_settings.file_format = "PNG"
    scene.render.image_settings.color_mode = "RGB"
    scene.render.film_transparent = False
    if engine == "BLENDER_WORKBENCH":
        scene.display.shading.light = "STUDIO"
        scene.display.shading.color_type = "MATERIAL"
        scene.display.shading.show_shadows = True
        scene.display.shading.show_cavity = True
        scene.display.shading.cavity_type = "BOTH"
    else:
        try:
            scene.eevee.taa_render_samples = 32
        except AttributeError:
            pass


def render_one(path: str, frame: int) -> str:
    scene = bpy.context.scene
    scene.frame_set(frame)
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    scene.render.filepath = os.path.abspath(path)
    bpy.ops.render.render(write_still=True)
    if not os.path.isfile(path) or os.path.getsize(path) < 256:
        raise SystemExit(f"render did not produce a plausible PNG: {path}")
    return path


def main() -> int:
    args = parse_args()
    blend_path = os.path.abspath(args.blend)
    if not os.path.isfile(blend_path):
        raise SystemExit(f"blend file not found: {blend_path}")
    bpy.ops.wm.open_mainfile(filepath=blend_path)

    if args.frames:
        frames = [int(value.strip()) for value in args.frames.split(",")
                  if value.strip()]
    elif args.frame is not None:
        frames = [args.frame]
    else:
        frames = [bpy.context.scene.frame_start]
    if not frames:
        raise SystemExit("no frames selected for preview")

    views = [view.strip() for view in args.views.split(",") if view.strip()]
    unknown = [view for view in views if view not in VIEWS]
    if unknown or not views:
        raise SystemExit(f"unknown view(s) {unknown}; choose from {sorted(VIEWS)}")

    engine = choose_engine(args.engine)
    minimum, maximum = union_bounds(frames)
    center = (minimum + maximum) * 0.5
    radius = max((maximum - minimum).length * 0.5, 0.1)
    add_lights(center, radius)
    configure_render(engine, args.width, args.height)

    output = os.path.abspath(args.out)
    stem, extension = os.path.splitext(output)
    paths = []
    for view in views:
        camera = add_camera(center, radius, args.width, args.height, view)
        view_stem = stem if views == ["three_quarter"] else f"{stem}_{view}"
        for frame in frames:
            if len(frames) == 1:
                path = view_stem + (extension or ".png")
            else:
                path = f"{view_stem}_f{frame:04d}{extension or '.png'}"
            paths.append(render_one(path, frame))
        bpy.data.objects.remove(camera, do_unlink=True)

    report = {
        "status": "PASS",
        "blend": blend_path,
        "engine": engine,
        "frames": frames,
        "views": views,
        "paths": paths,
        "bounds": {
            "min": [round(value, 6) for value in minimum],
            "max": [round(value, 6) for value in maximum],
        },
        "resolution": [args.width, args.height],
    }
    print("PREVIEW_BEGIN")
    print(json.dumps(report, indent=2))
    print("PREVIEW_END")
    return 0


if __name__ == "__main__":
    sys.exit(main())
