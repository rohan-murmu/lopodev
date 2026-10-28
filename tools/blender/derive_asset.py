"""Derive a new asset from an existing one: import, edit with full bpy, export.

Run by `lopodev assets derive` (do not call directly):

  blender [-b] --factory-startup --python tools/blender/derive_asset.py -- \
    --source <cached original> [--with name=<file>]... --script <edit.py> \
    --out-glb <staging>.glb --out-blend <project>/blender/<id>.blend \
    --previews <dir> --report <report.json> [--live] [--hold 3]

The edit script defines `edit(ctx)` (see lib_edit.py). The source file is only
read. Without -b (live mode) every step runs from a timer so the window redraws
between steps, then Blender quits after `--hold` seconds. The report JSON
(status, stats before/after, operations, previews) is the result contract;
exit codes are not relied on in GUI mode.
"""

from __future__ import annotations

import argparse
import json
import os
import runpy
import sys
import time
import traceback

import bpy

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import lib_asset  # noqa: E402
import lib_edit  # noqa: E402
import render_preview  # noqa: E402


def parse_args() -> argparse.Namespace:
    argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", required=True)
    parser.add_argument("--with", dest="extras", action="append", default=[])
    parser.add_argument("--script")
    parser.add_argument("--from-blend", help="export an already-edited .blend instead of running a script")
    parser.add_argument("--out-glb", required=True)
    parser.add_argument("--out-blend", required=True)
    parser.add_argument("--previews", required=True)
    parser.add_argument("--report", required=True)
    parser.add_argument("--live", action="store_true")
    parser.add_argument("--hold", type=float, default=3.0)
    parser.add_argument("--views", default="front,three_quarter")
    return parser.parse_args(argv)


def clear_scene() -> None:
    for obj in list(bpy.data.objects):
        bpy.data.objects.remove(obj, do_unlink=True)
    for collection in list(bpy.data.collections):
        bpy.data.collections.remove(collection)


def import_file(path: str, collection_name: str) -> list:
    before = set(bpy.data.objects)
    extension = os.path.splitext(path)[1].lower()
    if extension in (".glb", ".gltf"):
        bpy.ops.import_scene.gltf(filepath=path)
    elif extension == ".fbx":
        bpy.ops.import_scene.fbx(filepath=path)
    elif extension == ".obj":
        bpy.ops.wm.obj_import(filepath=path)
    elif extension == ".blend":
        with bpy.data.libraries.load(path, link=False) as (source, target):
            target.objects = list(source.objects)
        for obj in target.objects:
            if obj is not None:
                bpy.context.scene.collection.objects.link(obj)
    else:
        raise ValueError(f"cannot import {extension} files")
    imported = [obj for obj in bpy.data.objects if obj not in before]
    for obj in imported:
        # glTF imports use quaternions; edit helpers and clips work in Euler
        # (Blender converts the current value when the mode changes).
        obj.rotation_mode = "XYZ"
    collection = bpy.data.collections.new(collection_name)
    bpy.context.scene.collection.children.link(collection)
    for obj in imported:
        for owner in list(obj.users_collection):
            owner.objects.unlink(obj)
        collection.objects.link(obj)
    return imported


def sync_viewport_colors() -> None:
    """Workbench previews use material.diffuse_color; imported glTF sets node colors."""
    for material in bpy.data.materials:
        bsdf = material.node_tree.nodes.get("Principled BSDF") if material.use_nodes and material.node_tree else None
        if bsdf is not None and not bsdf.inputs["Base Color"].links:
            material.diffuse_color = tuple(bsdf.inputs["Base Color"].default_value)


def render_views(directory: str, prefix: str, views: list[str]) -> list[str]:
    """Render with temporary camera/lights; remove them so they never export."""
    sync_viewport_colors()
    existing = set(bpy.data.objects)
    frame = bpy.context.scene.frame_current
    minimum, maximum = render_preview.union_bounds([frame])
    center = (minimum + maximum) * 0.5
    radius = max((maximum - minimum).length * 0.5, 0.1)
    render_preview.add_lights(center, radius)
    render_preview.configure_render(render_preview.choose_engine(None), 768, 768)
    paths = []
    for view in views:
        camera = render_preview.add_camera(center, radius, 768, 768, view)
        paths.append(render_preview.render_one(os.path.join(directory, f"{prefix}_{view}.png"), frame))
        bpy.data.objects.remove(camera, do_unlink=True)
    for obj in list(bpy.data.objects):
        if obj not in existing:
            bpy.data.objects.remove(obj, do_unlink=True)
    return paths


def render_clips(directory: str) -> list[str]:
    """Two frames per clip (start, middle) so a human can judge the motion."""
    paths = []
    owners = [(obj, track) for obj in bpy.data.objects if obj.animation_data
              for track in obj.animation_data.nla_tracks for _ in track.strips]
    for obj, track in owners:
        action = track.strips[0].action
        if action is None:
            continue
        previous = obj.animation_data.action
        track.mute = True
        obj.animation_data.action = action
        if hasattr(obj.animation_data, "action_slot") and getattr(action, "slots", None):
            obj.animation_data.action_slot = action.slots[0]
        start, end = (int(v) for v in action.frame_range)
        for label, frame in (("start", start), ("mid", (start + end) // 2)):
            bpy.context.scene.frame_set(frame)
            paths += render_views(directory, f"clip_{action.name}_{label}", ["three_quarter"])
        obj.animation_data.action = previous
        bpy.context.scene.frame_set(1)
    return paths


def write_report(path: str, report: dict) -> None:
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    with open(path, "w", encoding="utf-8") as handle:
        json.dump(report, handle, indent=2)


def steps(args: argparse.Namespace, report: dict):
    """Generator of steps; live mode yields between them so the window redraws."""
    views = [v for v in args.views.split(",") if v]
    clear_scene()
    if args.from_blend:
        bpy.ops.wm.open_mainfile(filepath=os.path.abspath(args.from_blend))
        ctx = lib_edit.EditContext(list(bpy.context.scene.objects), {}, args.live)
        report["mode"] = "from-blend"
        yield "loaded edited .blend"
    else:
        source = import_file(args.source, "Source")
        extras = {}
        for item in args.extras:
            name, _, path = item.partition("=")
            extras[name] = import_file(path, f"Extra_{name}")
        ctx = lib_edit.EditContext(source, extras, args.live)
        report["before"] = ctx.stats()
        ctx.show(note="imported source")
        yield "imported source"
        report["previews"]["before"] = render_views(args.previews, "before", views)
        yield "rendered before"
        if args.script:
            module = runpy.run_path(os.path.abspath(args.script))
            if "edit" not in module:
                raise RuntimeError(f"{args.script} must define edit(ctx)")
            module["edit"](ctx)
            ctx.show(note="edit script finished")
            yield "edited"
    report["after"] = ctx.stats()
    report["operations"] = ctx.operations
    report["rig"] = ctx.rig_report
    if report["after"]["triangles"] == 0:
        raise RuntimeError("no mesh left after editing")
    report["previews"]["after"] = render_views(args.previews, "after", views)
    yield "rendered after"
    report["previews"]["clips"] = render_clips(args.previews)
    if report["previews"]["clips"]:
        yield "rendered clip frames"
    lib_asset.save_blend(args.out_blend)
    animated = bool(bpy.data.actions)
    stashed = [track for obj in bpy.data.objects if obj.animation_data for track in obj.animation_data.nla_tracks]
    for track in stashed:
        track.mute = False  # muted tracks are skipped by the exporter
    # Clips stashed as NLA tracks (lib_rig) export one animation per track name,
    # merged across objects; plain actions keep the ACTIONS mode.
    lib_asset.export_glb(args.out_glb, animations=animated,
                         animation_mode="NLA_TRACKS" if stashed else "ACTIONS")
    report.update({"status": "PASS", "glb": args.out_glb, "blend": args.out_blend, "animated": animated,
                   "blender_version": bpy.app.version_string})
    yield "exported"


def main() -> None:
    args = parse_args()
    report: dict = {"status": "FAIL", "previews": {}, "live": args.live}
    os.makedirs(args.previews, exist_ok=True)
    runner = steps(args, report)

    def finish(error: str | None = None) -> None:
        if error:
            report["status"] = "FAIL"
            report["error"] = error
            print(error, file=sys.stderr)
        write_report(args.report, report)
        print(f"DERIVE_RESULT={report['status']}", flush=True)

    if bpy.app.background or not args.live:
        try:
            for step in runner:
                print(f"DERIVE_PHASE {step}", flush=True)
        except Exception:
            finish(traceback.format_exc())
            sys.exit(1)
        finish()
        return

    state = {"done_at": None}

    def tick():
        if state["done_at"] is not None:
            if time.time() - state["done_at"] >= args.hold:
                bpy.ops.wm.quit_blender()
                return None
            return 0.25
        try:
            print(f"DERIVE_PHASE {next(runner)}", flush=True)
            return 0.4
        except StopIteration:
            finish()
        except Exception:
            finish(traceback.format_exc())
        state["done_at"] = time.time()
        return 0.25

    bpy.app.timers.register(tick, first_interval=1.0)


main()
