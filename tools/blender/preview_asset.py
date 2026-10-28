"""Render preview images of a model file (glTF/GLB/FBX/OBJ) without changing it.

  blender -b --factory-startup --python tools/blender/preview_asset.py -- \
      --model <file> --out-dir <dir> [--views front,three_quarter,top]

Writes <out-dir>/<view>.png and prints PREVIEW_ASSET <json>.
"""

from __future__ import annotations

import argparse
import json
import os
import sys

import bpy

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import render_preview  # noqa: E402


def main() -> None:
    argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
    parser = argparse.ArgumentParser()
    parser.add_argument("--model", required=True)
    parser.add_argument("--out-dir", required=True)
    parser.add_argument("--views", default="front,three_quarter,top")
    parser.add_argument("--size", type=int, default=640)
    args = parser.parse_args(argv)
    for obj in list(bpy.data.objects):
        bpy.data.objects.remove(obj, do_unlink=True)
    extension = os.path.splitext(args.model)[1].lower()
    if extension in (".glb", ".gltf"):
        bpy.ops.import_scene.gltf(filepath=args.model)
    elif extension == ".fbx":
        bpy.ops.import_scene.fbx(filepath=args.model)
    elif extension == ".obj":
        bpy.ops.wm.obj_import(filepath=args.model)
    else:
        raise SystemExit(f"cannot preview {extension}")
    for material in bpy.data.materials:  # Workbench shows diffuse_color, glTF sets node colors
        tree = material.node_tree if material.use_nodes else None
        bsdf = tree.nodes.get("Principled BSDF") if tree else None
        if bsdf is not None and not bsdf.inputs["Base Color"].links:
            material.diffuse_color = tuple(bsdf.inputs["Base Color"].default_value)
    frame = bpy.context.scene.frame_current
    minimum, maximum = render_preview.union_bounds([frame])
    center, radius = (minimum + maximum) * 0.5, max((maximum - minimum).length * 0.5, 0.1)
    render_preview.add_lights(center, radius)
    render_preview.configure_render(render_preview.choose_engine(None), args.size, args.size)
    paths = []
    for view in [v for v in args.views.split(",") if v]:
        camera = render_preview.add_camera(center, radius, args.size, args.size, view)
        paths.append(render_preview.render_one(os.path.join(args.out_dir, f"{view}.png"), frame))
        bpy.data.objects.remove(camera, do_unlink=True)
    size = [round(maximum[i] - minimum[i], 4) for i in range(3)]
    print("PREVIEW_ASSET " + json.dumps({"status": "PASS", "paths": paths, "size_blender_m": size}), flush=True)


main()
