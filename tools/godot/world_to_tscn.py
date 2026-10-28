#!/usr/bin/env python3
"""Assemble a resolved world plan into a Godot scene.

Writes a .tscn that instances each placement under Props/, plus Marker3D
nodes for spawns (Spawn_<id>), enemy spawns (Enemy_<id>), objectives
(Objective_<id>) and landmarks, so gameplay code finds them by name. It also
adds ground collision (a box, or a HeightMapShape3D for `terrain`), a sun and
environment, and a NavigationRegion3D that bakes from Props and Ground
(group `navigation_geometry`). Verify navigation in Godot with
tools/godot/checks/nav_check.gd.

Assets resolve to res://assets/models/<asset>.glb unless --asset-map
overrides them; `lopodev assets import` writes assets/asset_map.json pointing
at wrapper scenes that carry normalization and collision. A missing asset is
an error (no silent placeholders); --skip-missing omits and reports.

  python3 tools/godot/world_to_tscn.py resolved.json --godot-dir projects/<slug>/godot \
      --out scenes/World.tscn
"""

from __future__ import annotations

import argparse
import json
import math
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import world_plan  # noqa: E402

NAME_RE = re.compile(r"[^A-Za-z0-9_]")
HEIGHTFIELD_SCRIPT = "res://scripts/world/heightfield_mesh.gd"
RUNTIME = Path(__file__).resolve().parent / "runtime"


def node_name(prefix: str, value: str) -> str:
    return f"{prefix}{NAME_RE.sub('_', value)}"


def transform(x: float, z: float, y: float = 0.0, degrees: float = 0.0, scale: float = 1.0) -> str:
    """Transform3D text: basis rows (row-major) then origin; rotation about +Y."""
    angle = math.radians(degrees)
    c, s = math.cos(angle) * scale, math.sin(angle) * scale
    values = [c, 0.0, s, 0.0, scale, 0.0, -s, 0.0, c, x, y, z]
    return "Transform3D(" + ", ".join(f"{v:.6g}" for v in values) + ")"


def look_at(eye: list[float], target: list[float]) -> str:
    """Transform3D for a camera at `eye` looking at `target` (Godot looks down -Z)."""
    forward = [target[i] - eye[i] for i in range(3)]
    length = math.sqrt(sum(v * v for v in forward)) or 1.0
    back = [-v / length for v in forward]  # basis z axis
    up = [0.0, 1.0, 0.0]
    right = [up[1] * back[2] - up[2] * back[1], up[2] * back[0] - up[0] * back[2], up[0] * back[1] - up[1] * back[0]]
    norm = math.sqrt(sum(v * v for v in right)) or 1.0
    right = [v / norm for v in right]
    true_up = [back[1] * right[2] - back[2] * right[1], back[2] * right[0] - back[0] * right[2],
               back[0] * right[1] - back[1] * right[0]]
    # Transform3D text lists basis rows: (x.x, y.x, z.x, x.y, y.y, z.y, x.z, y.z, z.z).
    values = [right[0], true_up[0], back[0], right[1], true_up[1], back[1], right[2], true_up[2], back[2], *eye]
    return "Transform3D(" + ", ".join(f"{v:.6g}" for v in values) + ")"


def terrain_heights(plan: dict) -> tuple[int, int, float, list[float]]:
    """Heightfield samples on a grid covering the bounds (HeightMapShape3D layout)."""
    x0, z0, x1, z1 = world_plan.bounds(plan)
    step = float((plan.get("terrain") or {}).get("resolution", 1.0))
    width, depth = int(math.ceil((x1 - x0) / step)) + 1, int(math.ceil((z1 - z0) / step)) + 1
    heights = [world_plan.height(plan, x0 + i * step, z0 + j * step) for j in range(depth) for i in range(width)]
    return width, depth, step, heights


def build(plan: dict, godot_dir: Path, asset_map: dict, skip_missing: bool) -> tuple[str, list[str]]:
    if not plan.get("resolved"):
        raise ValueError("plan is not resolved; run `tools/world_plan.py generate` first")
    placements = list(plan.get("placements", []))
    placements += [dict(item, rotation=item.get("rotation", 0.0), y=world_plan.height(plan, *item["pos"]))
                   for item in plan.get("landmarks", []) if item.get("asset")]
    resources: dict[str, str] = {}
    missing: list[str] = []
    for item in placements:
        asset = item["asset"]
        if asset in resources or asset in missing:
            continue
        path = asset_map.get(asset, f"res://assets/models/{asset}.glb")
        if not (godot_dir / path.removeprefix("res://")).is_file():
            missing.append(asset)
            continue
        resources[asset] = path
    if missing and not skip_missing:
        raise FileNotFoundError(f"assets not found in {godot_dir}: {', '.join(missing)} "
                                "(generate them first, map them with --asset-map, or pass --skip-missing)")
    x0, z0, x1, z1 = world_plan.bounds(plan)
    ground = plan.get("ground") or {}
    ground_key = ground.get("material") or next((key for key in sorted(asset_map)
                                                 if key.startswith("mat_ground")), "")
    material = asset_map.get(ground_key)
    if material and not (godot_dir / material.removeprefix("res://")).is_file():
        material = None
    terrain = (plan.get("terrain") or {}).get("type", "flat") != "flat"
    ids = {asset: f"{index + 1}_{asset}" for index, asset in enumerate(sorted(resources))}
    ext = [f'[ext_resource type="PackedScene" path="{resources[asset]}" id="{rid}"]' for asset, rid in ids.items()]
    if material:
        ext.append(f'[ext_resource type="Material" path="{material}" id="ground_material"]')
    sub = ['[sub_resource type="Environment" id="Env"]', "background_mode = 1",
           "background_color = Color(0.55, 0.7, 0.85, 1)", "ambient_light_source = 2",
           "ambient_light_color = Color(0.6, 0.65, 0.7, 1)", "ambient_light_energy = 0.6", ""]
    slope = float((plan.get("terrain") or {}).get("max_walkable_slope_deg", 40.0))
    radius = world_plan.setting(plan, "enemy_radius") if plan.get("enemy_spawns") else \
        world_plan.setting(plan, "player_radius")
    sub += ['[sub_resource type="NavigationMesh" id="NavMesh"]', "geometry_parsed_geometry_type = 1",
            "geometry_source_geometry_mode = 1", 'geometry_source_group_name = &"navigation_geometry"',
            "cell_size = 0.25", "cell_height = 0.25", f"agent_radius = {max(radius, 0.25):.3g}",
            "agent_height = 1.8", "agent_max_climb = 0.5", f"agent_max_slope = {slope:.3g}", ""]
    width = x1 - x0
    depth = z1 - z0
    if terrain:
        columns, rows, step, heights = terrain_heights(plan)
        sub += ['[sub_resource type="HeightMapShape3D" id="GroundShape"]', f"map_width = {columns}",
                f"map_depth = {rows}",
                "map_data = PackedFloat32Array(" + ", ".join(f"{h:.4g}" for h in heights) + ")", ""]
        ext.append(f'[ext_resource type="Script" path="{HEIGHTFIELD_SCRIPT}" id="heightfield"]')
    else:
        sub += ['[sub_resource type="BoxShape3D" id="GroundShape"]', f"size = Vector3({width:.4g}, 1, {depth:.4g})", "",
                '[sub_resource type="PlaneMesh" id="GroundMesh"]', f"size = Vector2({width:.4g}, {depth:.4g})", ""]
    lines = [f"[gd_scene load_steps={len(ext) + len([x for x in sub if x.startswith('[sub_resource')]) + 1} format=3]",
             "", *ext, "", *sub,
             '[node name="World" type="Node3D"]', "",
             '[node name="Environment" type="WorldEnvironment" parent="."]', 'environment = SubResource("Env")', "",
             '[node name="Sun" type="DirectionalLight3D" parent="."]',
             "transform = Transform3D(0.866, -0.354, 0.354, 0, 0.707, 0.707, -0.5, -0.612, 0.612, 0, 20, 0)",
             "shadow_enabled = true", "",
             '[node name="Ground" type="StaticBody3D" parent="." groups=["navigation_geometry"]]',
             f"transform = Transform3D(1, 0, 0, 0, 1, 0, 0, 0, 1, {(x0 + x1) / 2:.4g}, 0, {(z0 + z1) / 2:.4g})", ""]
    if terrain:
        lines += ['[node name="Shape" type="CollisionShape3D" parent="Ground"]',
                  f"transform = Transform3D({step:.4g}, 0, 0, 0, 1, 0, 0, 0, {step:.4g}, 0, 0, 0)",
                  'shape = SubResource("GroundShape")', "",
                  '[node name="Mesh" type="MeshInstance3D" parent="Ground"]',
                  f"transform = Transform3D({step:.4g}, 0, 0, 0, 1, 0, 0, 0, {step:.4g}, 0, 0, 0)",
                  'script = ExtResource("heightfield")', ""]
    else:
        lines += ['[node name="Shape" type="CollisionShape3D" parent="Ground"]',
                  "transform = Transform3D(1, 0, 0, 0, 1, 0, 0, 0, 1, 0, -0.5, 0)",
                  'shape = SubResource("GroundShape")', "",
                  '[node name="Mesh" type="MeshInstance3D" parent="Ground"]', 'mesh = SubResource("GroundMesh")', ""]
    if material:
        lines.insert(len(lines) - 1, 'surface_material_override/0 = ExtResource("ground_material")')
    # Overview camera (gameplay replaces it with the player camera): behind the
    # spawn, looking across the level, so the visual gate shows the world.
    spawn = (plan.get("spawns") or [{"pos": [(x0 + x1) / 2, z0]}])[0]["pos"]
    eye = [spawn[0], world_plan.height(plan, *spawn) + max(6.0, depth * 0.25), spawn[1] - max(4.0, depth * 0.15)]
    target = [(x0 + x1) / 2, 0.0, (z0 + z1) / 2]
    lines += ['[node name="OverviewCamera" type="Camera3D" parent="."]',
              "transform = " + look_at(eye, target), "current = true", "far = 1000.0", ""]
    lines += ['[node name="Navigation" type="NavigationRegion3D" parent="."]', 'navigation_mesh = SubResource("NavMesh")', "",
              '[node name="Props" type="Node3D" parent="." groups=["navigation_geometry"]]', ""]
    used: set[str] = set()
    for item in placements:
        if item["asset"] not in ids:
            continue
        name = node_name("", item["id"])
        while name in used:
            name += "_"
        used.add(name)
        lines.append(f'[node name="{name}" parent="Props" instance=ExtResource("{ids[item["asset"]]}")]')
        lines.append("transform = " + transform(item["pos"][0], item["pos"][1], item.get("y", 0.0),
                                                item.get("rotation", 0.0), item.get("scale", 1.0)))
        lines.append(f'metadata/collision = "{item.get("collision", "static")}"')
        lines.append("")
    lines += ['[node name="Markers" type="Node3D" parent="."]', ""]
    for group, prefix in (("spawns", "Spawn_"), ("enemy_spawns", "Enemy_"), ("objectives", "Objective_"),
                          ("landmarks", "Landmark_")):
        for item in plan.get(group, []):
            lines.append(f'[node name="{node_name(prefix, item["id"])}" type="Marker3D" parent="Markers"]')
            lines.append("transform = " + transform(item["pos"][0], item["pos"][1],
                                                    item.get("y", world_plan.height(plan, *item["pos"]))))
            lines.append("")
    notes = [f"SKIPPED_MISSING {asset}" for asset in missing]
    return "\n".join(lines).rstrip() + "\n", notes


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("plan", type=Path)
    parser.add_argument("--godot-dir", type=Path, required=True)
    parser.add_argument("--out", required=True, help="scene path relative to the Godot project")
    parser.add_argument("--asset-map", type=Path, help='JSON {"sm_tree": "res://path.glb"}')
    parser.add_argument("--skip-missing", action="store_true")
    parser.add_argument("--force", action="store_true", help="overwrite an existing generated scene")
    args = parser.parse_args(argv)
    try:
        plan = json.loads(args.plan.read_text(encoding="utf-8"))
        asset_map = json.loads(args.asset_map.read_text(encoding="utf-8")) if args.asset_map else {}
        text, notes = build(plan, args.godot_dir, asset_map, args.skip_missing)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2
    out = args.godot_dir / args.out
    if out.exists() and not args.force and out.read_text(encoding="utf-8") != text:
        print(f"ERROR: {out} exists; inspect it and pass --force to regenerate", file=sys.stderr)
        return 2
    out.parent.mkdir(parents=True, exist_ok=True)
    if HEIGHTFIELD_SCRIPT in text:
        script = args.godot_dir / HEIGHTFIELD_SCRIPT.removeprefix("res://")
        source = (RUNTIME / "heightfield_mesh.gd").read_text(encoding="utf-8")
        if script.exists() and script.read_text(encoding="utf-8") != source and not args.force:
            print(f"ERROR: {script} differs from the LopoDev runtime copy; pass --force to replace", file=sys.stderr)
            return 2
        script.parent.mkdir(parents=True, exist_ok=True)
        script.write_text(source, encoding="utf-8")
    out.write_text(text, encoding="utf-8")
    for note in notes:
        print(note)
    props = text.count('parent="Props"')
    print(f"WORLD_SCENE={out} props={props}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
