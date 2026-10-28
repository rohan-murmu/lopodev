#!/usr/bin/env python3
"""Assemble a resolved world plan into a Godot scene.

Writes a .tscn that instances each placement's GLB under Props/, plus
Marker3D nodes for spawns (Spawn_<id>), objectives (Objective_<id>) and
landmarks, so gameplay code finds them by name. Assets resolve to
res://assets/models/<asset>.glb unless --asset-map overrides them. A missing
asset is an error (no silent placeholders); --skip-missing omits and reports.

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

NAME_RE = re.compile(r"[^A-Za-z0-9_]")


def node_name(prefix: str, value: str) -> str:
    return f"{prefix}{NAME_RE.sub('_', value)}"


def transform(x: float, z: float, y: float = 0.0, degrees: float = 0.0, scale: float = 1.0) -> str:
    """Transform3D text: basis rows (row-major) then origin; rotation about +Y."""
    angle = math.radians(degrees)
    c, s = math.cos(angle) * scale, math.sin(angle) * scale
    values = [c, 0.0, s, 0.0, scale, 0.0, -s, 0.0, c, x, y, z]
    return "Transform3D(" + ", ".join(f"{v:.6g}" for v in values) + ")"


def build(plan: dict, godot_dir: Path, asset_map: dict, skip_missing: bool) -> tuple[str, list[str]]:
    if not plan.get("resolved"):
        raise ValueError("plan is not resolved; run `tools/world_plan.py generate` first")
    placements = list(plan.get("placements", []))
    placements += [dict(item, rotation=item.get("rotation", 0.0)) for item in plan.get("landmarks", [])
                   if item.get("asset")]
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
    ids = {asset: f"{index + 1}_{asset}" for index, asset in enumerate(sorted(resources))}
    lines = [f"[gd_scene load_steps={len(ids) + 1} format=3]", ""]
    for asset, rid in ids.items():
        lines.append(f'[ext_resource type="PackedScene" path="{resources[asset]}" id="{rid}"]')
    lines += ["", '[node name="World" type="Node3D"]', "",
              '[node name="Props" type="Node3D" parent="."]', ""]
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
    for group, prefix in (("spawns", "Spawn_"), ("objectives", "Objective_"), ("landmarks", "Landmark_")):
        for item in plan.get(group, []):
            lines.append(f'[node name="{node_name(prefix, item["id"])}" type="Marker3D" parent="Markers"]')
            lines.append("transform = " + transform(item["pos"][0], item["pos"][1], item.get("y", 0.0)))
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
    out.write_text(text, encoding="utf-8")
    for note in notes:
        print(note)
    props = text.count('parent="Props"')
    print(f"WORLD_SCENE={out} props={props}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
