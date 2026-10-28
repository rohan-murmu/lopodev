"""Helpers for changing existing assets in Blender (derive scripts).

Derive scripts define `edit(ctx)` and may use any Blender API through
`ctx.bpy`: modifiers, booleans, sculpt-style deformation, remeshing, UVs,
shader nodes, shape keys, armatures, actions. These helpers are shortcuts for
common steps, not a limit. In live mode `ctx.show()` redraws the visible
Blender so the user watches each step.

    def edit(ctx):
        well = ctx.find("well|stone")
        ctx.recolor(well, (0.18, 0.22, 0.16))           # mossy stone
        ctx.noise_displace(well, strength=0.03)          # aged, uneven stones
        water = ctx.find("water")
        ctx.set_material(water, ctx.material("witch_water", (0.2, 0.9, 0.3), emission=3.0))
        skull = ctx.extra("skull")                       # another cached asset
        ctx.place(skull, location=(0.6, 0.0, 0.9), scale=0.25)
        ctx.add("cone", "Roof", size=(1.8, 1.8, 0.9), location=(0, 0, 2.3),
                material=ctx.material("roof", (0.15, 0.1, 0.2)))
"""

from __future__ import annotations

import math
import re

import bpy
from mathutils import Vector

import lib_asset


class EditContext:
    def __init__(self, source: list, extras: dict[str, list], live: bool):
        self.bpy = bpy
        self.Vector = Vector
        self.source = source
        self.extras = extras
        self.live = live
        self.operations: list[str] = []
        self.rig_report: dict | None = None
        import lib_rig
        self.rig = lib_rig  # ctx.rig.parts(ctx, [...]), humanoid, transfer, creature

    # ------------------------------------------------------------ inspection
    def log(self, message: str) -> None:
        self.operations.append(message)
        print(f"DERIVE_STEP {message}", flush=True)

    def objects(self) -> list:
        return [obj for obj in bpy.context.scene.objects if obj.type == "MESH"]

    def parts(self) -> list[dict]:
        return [{"name": obj.name, "materials": [slot.material.name for slot in obj.material_slots if slot.material],
                 "dimensions": [round(v, 4) for v in obj.dimensions], "location": [round(v, 4) for v in obj.location],
                 "triangles": sum(len(p.vertices) - 2 for p in obj.data.polygons)} for obj in self.objects()]

    def find(self, pattern: str, required: bool = True) -> list:
        """Mesh objects whose name or material name matches a regex (case-insensitive)."""
        regex = re.compile(pattern, re.IGNORECASE)
        found = [obj for obj in self.objects() if regex.search(obj.name)
                 or any(slot.material and regex.search(slot.material.name) for slot in obj.material_slots)]
        if required and not found:
            raise LookupError(f"no part matches {pattern!r}; parts: {[p['name'] for p in self.parts()]}")
        return found

    def extra(self, name: str) -> list:
        if name not in self.extras:
            raise LookupError(f"no extra asset {name!r}; pass --with {name}=<asset id>")
        return self.extras[name]

    def stats(self) -> dict:
        bpy.context.view_layer.update()  # matrix_world lags behind location edits
        lo = Vector((math.inf,) * 3)
        hi = Vector((-math.inf,) * 3)
        triangles = 0
        for obj in self.objects():
            triangles += sum(len(p.vertices) - 2 for p in obj.data.polygons)
            for corner in obj.bound_box:
                world = obj.matrix_world @ Vector(corner)
                lo = Vector(map(min, lo, world))
                hi = Vector(map(max, hi, world))
        materials = sorted({slot.material.name for obj in self.objects() for slot in obj.material_slots
                            if slot.material})
        return {"objects": len(self.objects()), "triangles": triangles, "materials": materials,
                "bounds_min": list(lo) if triangles else None, "bounds_max": list(hi) if triangles else None}

    # ------------------------------------------------------------ live view
    def show(self, focus: list | None = None, note: str | None = None) -> None:
        """Redraw the visible Blender (live mode) and frame `focus`."""
        if note:
            self.log(note)
        if not self.live or bpy.app.background:
            return
        for window in bpy.context.window_manager.windows:
            for area in window.screen.areas:
                if area.type != "VIEW_3D":
                    continue
                region = next((r for r in area.regions if r.type == "WINDOW"), None)
                if region is None:
                    continue
                with bpy.context.temp_override(window=window, area=area, region=region):
                    if focus:
                        bpy.ops.object.select_all(action="DESELECT")
                        for obj in focus:
                            obj.select_set(True)
                        bpy.ops.view3d.view_selected()
                    else:
                        bpy.ops.view3d.view_all()
                area.spaces.active.shading.type = "MATERIAL"
        bpy.ops.wm.redraw_timer(type="DRAW_WIN_SWAP", iterations=1)

    # ------------------------------------------------------------ materials
    def material(self, name: str, color, roughness: float = 0.8, metallic: float = 0.0,
                 emission: float = 0.0):
        return lib_asset.make_material(name, tuple(color), roughness, metallic, emission)

    def set_material(self, objects: list, material) -> None:
        for obj in objects:
            obj.data.materials.clear()
            obj.data.materials.append(material)
        self.log(f"set material {material.name} on {[o.name for o in objects]}")
        self.show(objects)

    def recolor(self, objects: list, color, roughness: float | None = None) -> None:
        """Tint every material used by `objects` (copies, so other parts keep theirs)."""
        tinted: dict = {}  # one tinted copy per source material, shared by these parts
        for obj in objects:
            for slot in obj.material_slots:
                if slot.material is None:
                    continue
                if slot.material.name in tinted:
                    slot.material = tinted[slot.material.name]
                    continue
                material = slot.material.copy()
                material.name = f"{slot.material.name}_tinted"[:60]
                tinted[slot.material.name] = material
                bsdf = material.node_tree.nodes.get("Principled BSDF") if material.use_nodes else None
                if bsdf is not None:
                    link = bsdf.inputs["Base Color"].links
                    for item in list(link):
                        material.node_tree.links.remove(item)  # replace a texture with the tint
                    bsdf.inputs["Base Color"].default_value = (*color, 1.0)
                    if roughness is not None:
                        bsdf.inputs["Roughness"].default_value = roughness
                material.diffuse_color = (*color, 1.0)
                slot.material = material
        self.log(f"recolor {[o.name for o in objects]} -> {tuple(round(c, 3) for c in color)}")
        self.show(objects)

    # ------------------------------------------------------------ geometry
    def add(self, kind: str, name: str, size=(1.0, 1.0, 1.0), location=(0.0, 0.0, 0.0), material=None,
            rotation=(0.0, 0.0, 0.0)):
        material = material or self.material(f"mat_{name.lower()}", (0.6, 0.6, 0.6))
        if kind == "box":
            obj = lib_asset.create_box(name, tuple(size), tuple(location), material, tuple(rotation))
        elif kind == "cylinder":
            obj = lib_asset.create_cylinder(name, size[0] / 2, size[2], tuple(location), material)
        elif kind == "cone":
            obj = lib_asset.create_cone(name, size[0] / 2, 0.0, size[2], tuple(location), material)
        elif kind == "sphere":
            obj = lib_asset.create_icosphere(name, size[0] / 2, tuple(location), material)
        else:
            raise ValueError(f"unknown primitive {kind!r} (box, cylinder, cone, sphere); use ctx.bpy for others")
        obj.rotation_euler = rotation
        self.log(f"add {kind} {name} at {tuple(location)}")
        self.show([obj])
        return obj

    def place(self, objects: list, location=None, rotation=None, scale=None) -> None:
        for obj in objects:
            if obj.parent is not None:
                continue  # move hierarchies by their roots
            if location is not None:
                obj.location = location
            if rotation is not None:
                obj.rotation_mode = "XYZ"
                obj.rotation_euler = rotation
            if scale is not None:
                obj.scale = (scale,) * 3 if isinstance(scale, (int, float)) else scale
        self.log(f"place {[o.name for o in objects]} loc={location} rot={rotation} scale={scale}")
        self.show(objects)

    def remove(self, objects: list) -> None:
        names = [obj.name for obj in objects]
        for obj in objects:
            bpy.data.objects.remove(obj, do_unlink=True)
        self.log(f"remove {names}")
        self.show()

    def modifier(self, obj, kind: str, apply: bool = True, **settings):
        """Add any Blender modifier (e.g. 'BEVEL', 'SOLIDIFY', 'ARRAY'); optionally apply it."""
        mod = obj.modifiers.new(name=kind.title(), type=kind)
        for key, value in settings.items():
            setattr(mod, key, value)
        if apply:
            lib_asset.select_only([obj], obj)
            bpy.ops.object.modifier_apply(modifier=mod.name)
        self.log(f"modifier {kind} on {obj.name} {settings}{' (applied)' if apply else ''}")
        self.show([obj])
        return mod

    def noise_displace(self, objects: list, strength: float = 0.05, scale: float = 0.5, subdivide: int = 1) -> None:
        """Weathered/organic look: subdivide, then displace along normals with noise."""
        texture = bpy.data.textures.new("LopoNoise", type="CLOUDS")
        texture.noise_scale = scale
        for obj in objects:
            if subdivide:
                self.modifier(obj, "SUBSURF", levels=subdivide, render_levels=subdivide, subdivision_type="SIMPLE")
            mod = obj.modifiers.new("Displace", "DISPLACE")
            mod.texture = texture
            mod.strength = strength
            mod.texture_coords = "OBJECT"
            lib_asset.select_only([obj], obj)
            bpy.ops.object.modifier_apply(modifier=mod.name)
        self.log(f"noise displace {[o.name for o in objects]} strength={strength}")
        self.show(objects)

    def boolean(self, obj, cutter, operation: str = "DIFFERENCE", keep_cutter: bool = False) -> None:
        mod = obj.modifiers.new("Boolean", "BOOLEAN")
        mod.operation = operation
        mod.object = cutter
        lib_asset.select_only([obj], obj)
        bpy.ops.object.modifier_apply(modifier=mod.name)
        if not keep_cutter:
            bpy.data.objects.remove(cutter, do_unlink=True)
        self.log(f"boolean {operation} on {obj.name}")
        self.show([obj])

    def decimate(self, objects: list, ratio: float) -> None:
        for obj in objects:
            self.modifier(obj, "DECIMATE", ratio=ratio)

    def join(self, objects: list, name: str):
        obj = lib_asset.join_objects(objects, name)
        self.log(f"join {len(objects)} parts into {name}")
        return obj

    def uv_unwrap(self, objects: list, angle_limit: float = 66.0) -> None:
        for obj in objects:
            lib_asset.select_only([obj], obj)
            bpy.ops.object.mode_set(mode="EDIT")
            bpy.ops.mesh.select_all(action="SELECT")
            bpy.ops.uv.smart_project(angle_limit=math.radians(angle_limit))
            bpy.ops.object.mode_set(mode="OBJECT")
        self.log(f"uv unwrap {[o.name for o in objects]}")

    def set_origin_ground(self) -> None:
        """Move everything so the lowest point sits at Z=0 and the footprint is centered."""
        stats = self.stats()
        if not stats["bounds_min"]:
            return
        lo, hi = stats["bounds_min"], stats["bounds_max"]
        offset = Vector((-(lo[0] + hi[0]) / 2, -(lo[1] + hi[1]) / 2, -lo[2]))
        for obj in bpy.context.scene.objects:
            if obj.parent is None and obj.type in ("MESH", "EMPTY", "ARMATURE"):
                obj.location += offset
        bpy.context.view_layer.update()
        self.log(f"ground origin offset {tuple(round(v, 4) for v in offset)}")
