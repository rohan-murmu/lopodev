#!/usr/bin/env python3
"""Independently validate a binary glTF asset without Blender or third-party deps.

Checks the GLB container, mesh primitives, bounds, materials, skins, animations,
and triangle budgets. Exits non-zero on any error.
"""

from __future__ import annotations

import argparse
import json
import math
import struct
import sys
from pathlib import Path

GLB_MAGIC = 0x46546C67
JSON_CHUNK = 0x4E4F534A
BIN_CHUNK = 0x004E4942
COMPONENT_SIZE = {5120: 1, 5121: 1, 5122: 2, 5123: 2, 5125: 4, 5126: 4}
TYPE_COUNT = {"SCALAR": 1, "VEC2": 2, "VEC3": 3, "VEC4": 4, "MAT2": 4,
              "MAT3": 9, "MAT4": 16}
TARGET_PATH = {"translation", "rotation", "scale", "weights"}


class GlbError(Exception):
    pass


def parse_glb(path: Path) -> tuple[dict, bytes, dict]:
    raw = path.read_bytes()
    if len(raw) < 20:
        raise GlbError(f"file too small for GLB: {len(raw)} bytes")
    magic, version, declared_length = struct.unpack_from("<III", raw, 0)
    if magic != GLB_MAGIC:
        raise GlbError(f"bad magic 0x{magic:08x}, expected 0x{GLB_MAGIC:08x}")
    if version != 2:
        raise GlbError(f"unsupported glTF version {version}, expected 2")
    if declared_length != len(raw):
        raise GlbError(f"declared length {declared_length} != actual {len(raw)}")

    offset = 12
    gltf: dict | None = None
    bin_chunk = b""
    chunks = []
    while offset < len(raw):
        if offset + 8 > len(raw):
            raise GlbError("truncated chunk header")
        chunk_length, chunk_type = struct.unpack_from("<II", raw, offset)
        offset += 8
        if offset + chunk_length > len(raw):
            raise GlbError("chunk extends past end of file")
        data = raw[offset:offset + chunk_length]
        offset += chunk_length
        chunks.append({"type": chunk_type, "length": chunk_length})
        if chunk_type == JSON_CHUNK:
            if gltf is not None:
                raise GlbError("multiple JSON chunks")
            gltf = json.loads(data.decode("utf-8"))
        elif chunk_type == BIN_CHUNK:
            bin_chunk = data
    if gltf is None:
        raise GlbError("missing JSON chunk")
    if not isinstance(gltf, dict):
        raise GlbError("JSON chunk is not an object")
    return gltf, bin_chunk, {"bytes": len(raw), "chunks": chunks}


def accessor(gltf: dict, index: int, label: str, errors: list[str]) -> dict | None:
    accessors = gltf.get("accessors", [])
    if not isinstance(index, int) or index < 0 or index >= len(accessors):
        errors.append(f"{label}: invalid accessor index {index}")
        return None
    item = accessors[index]
    if not isinstance(item, dict):
        errors.append(f"{label}: accessor {index} is not an object")
        return None
    gltf_type = item.get("type")
    if gltf_type not in TYPE_COUNT:
        errors.append(f"{label}: accessor {index} has invalid type {gltf_type}")
    count = item.get("count")
    if not isinstance(count, int) or count <= 0:
        errors.append(f"{label}: accessor {index} has invalid count {count}")
    component = item.get("componentType")
    if component not in COMPONENT_SIZE:
        errors.append(f"{label}: accessor {index} has invalid componentType {component}")
    buffer_view = item.get("bufferView")
    buffer_views = gltf.get("bufferViews", [])
    if buffer_view is not None and (not isinstance(buffer_view, int)
                                    or buffer_view < 0 or buffer_view >= len(buffer_views)):
        errors.append(f"{label}: accessor {index} has invalid bufferView {buffer_view}")
    return item


def finite_triplet(value, label: str, errors: list[str]) -> bool:
    if not isinstance(value, list) or len(value) != 3:
        errors.append(f"{label}: expected a 3-element array")
        return False
    try:
        numbers = [float(v) for v in value]
    except (TypeError, ValueError):
        errors.append(f"{label}: non-numeric component")
        return False
    if not all(math.isfinite(v) for v in numbers):
        errors.append(f"{label}: non-finite component")
        return False
    return True


def validate(path: Path, *, require_animation: bool, expect_animations: list[str],
             require_material: bool, require_skin: bool, min_triangles: int,
             max_triangles: int, ground_origin: bool,
             ground_tolerance: float, min_bytes: int) -> dict:
    errors: list[str] = []
    warnings: list[str] = []
    gltf, bin_chunk, container = parse_glb(path)

    if container["bytes"] < min_bytes:
        errors.append(f"file too small: {container['bytes']} < {min_bytes}")

    asset = gltf.get("asset", {})
    if asset.get("version") != "2.0":
        errors.append(f"asset.version must be 2.0, got {asset.get('version')!r}")

    buffers = gltf.get("buffers", [])
    for index, buffer in enumerate(buffers):
        byte_length = buffer.get("byteLength")
        if not isinstance(byte_length, int) or byte_length < 0:
            errors.append(f"buffers[{index}].byteLength invalid")
        elif not buffer.get("uri") and byte_length > len(bin_chunk):
            errors.append(f"buffers[{index}] byteLength exceeds BIN chunk")

    nodes = gltf.get("nodes", [])
    if not nodes:
        errors.append("no nodes in asset")

    meshes = gltf.get("meshes", [])
    materials = gltf.get("materials", [])
    if not meshes:
        errors.append("no meshes in asset")
    if require_material and not materials:
        errors.append("no materials in asset (required)")

    total_triangles = 0
    total_primitives = 0
    bounds_min = [math.inf, math.inf, math.inf]
    bounds_max = [-math.inf, -math.inf, -math.inf]
    primitives_without_material = 0

    for mesh_index, mesh in enumerate(meshes):
        primitives = mesh.get("primitives", []) if isinstance(mesh, dict) else []
        if not primitives:
            errors.append(f"meshes[{mesh_index}] has no primitives")
            continue
        for prim_index, primitive in enumerate(primitives):
            label = f"meshes[{mesh_index}].primitives[{prim_index}]"
            if not isinstance(primitive, dict):
                errors.append(f"{label} is not an object")
                continue
            total_primitives += 1
            attributes = primitive.get("attributes", {})
            position_index = attributes.get("POSITION")
            if position_index is None:
                errors.append(f"{label} has no POSITION attribute")
                continue
            pos_accessor = accessor(gltf, position_index, f"{label}.POSITION", errors)
            if pos_accessor is None:
                continue
            if pos_accessor.get("type") != "VEC3":
                errors.append(f"{label}.POSITION must be VEC3")
            if "min" not in pos_accessor or "max" not in pos_accessor:
                warnings.append(f"{label}.POSITION lacks min/max; bounds incomplete")
            else:
                if finite_triplet(pos_accessor["min"], f"{label}.POSITION.min", errors):
                    bounds_min = [min(bounds_min[i], float(pos_accessor["min"][i]))
                                  for i in range(3)]
                if finite_triplet(pos_accessor["max"], f"{label}.POSITION.max", errors):
                    bounds_max = [max(bounds_max[i], float(pos_accessor["max"][i]))
                                  for i in range(3)]

            mode = primitive.get("mode", 4)
            if "indices" in primitive:
                index_accessor = accessor(gltf, primitive["indices"],
                                          f"{label}.indices", errors)
                if index_accessor is None:
                    continue
                index_count = index_accessor.get("count", 0)
            else:
                index_count = pos_accessor.get("count", 0)

            if mode == 4:
                if index_count % 3 != 0:
                    errors.append(f"{label}: triangle index count {index_count} not divisible by 3")
                total_triangles += index_count // 3
            elif mode in (5, 6):
                total_triangles += max(0, index_count - 2)
            else:
                warnings.append(f"{label}: non-triangle primitive mode {mode}")

            if "material" in primitive:
                material_index = primitive["material"]
                if not isinstance(material_index, int) or material_index < 0 \
                        or material_index >= len(materials):
                    errors.append(f"{label}: invalid material index {material_index}")
            else:
                primitives_without_material += 1

    if total_triangles < min_triangles:
        errors.append(f"triangle count {total_triangles} below minimum {min_triangles}")
    if total_triangles > max_triangles:
        errors.append(f"triangle count {total_triangles} exceeds budget {max_triangles}")
    if primitives_without_material:
        warnings.append(f"{primitives_without_material} primitive(s) without a material")

    if math.isfinite(bounds_min[0]) and math.isfinite(bounds_max[0]):
        size = [round(bounds_max[i] - bounds_min[i], 6) for i in range(3)]
        if any(value <= 0 for value in size):
            errors.append(f"degenerate bounds size: {size}")
        if ground_origin and abs(bounds_min[1]) > ground_tolerance:
            errors.append(
                f"glTF ground origin expected min Y ~= 0, got {bounds_min[1]:.6f} "
                f"(tolerance {ground_tolerance})")
    else:
        errors.append("could not determine finite asset bounds")

    skins = gltf.get("skins", [])
    if require_skin and not skins:
        errors.append("no skins in asset (required)")
    for skin_index, skin in enumerate(skins):
        joints = skin.get("joints", []) if isinstance(skin, dict) else []
        if not joints:
            errors.append(f"skins[{skin_index}] has no joints")
        for joint in joints:
            if not isinstance(joint, int) or joint < 0 or joint >= len(nodes):
                errors.append(f"skins[{skin_index}] invalid joint node {joint}")
        if "inverseBindMatrices" in skin:
            ibm = accessor(gltf, skin["inverseBindMatrices"],
                           f"skins[{skin_index}].inverseBindMatrices", errors)
            if ibm is not None and ibm.get("count") != len(joints):
                errors.append(
                    f"skins[{skin_index}] inverseBindMatrices count {ibm.get('count')} "
                    f"!= joint count {len(joints)}")

    animations = gltf.get("animations", [])
    animation_summary = []
    for anim_index, animation in enumerate(animations):
        label = f"animations[{anim_index}]"
        if not isinstance(animation, dict):
            errors.append(f"{label} is not an object")
            continue
        name = animation.get("name", f"animation_{anim_index}")
        channels = animation.get("channels", [])
        samplers = animation.get("samplers", [])
        if not channels:
            errors.append(f"{label} ({name}) has no channels")
        if not samplers:
            errors.append(f"{label} ({name}) has no samplers")
        duration = 0.0
        for channel_index, channel in enumerate(channels):
            channel_label = f"{label}.channels[{channel_index}]"
            if not isinstance(channel, dict):
                errors.append(f"{channel_label} is not an object")
                continue
            sampler_index = channel.get("sampler")
            if not isinstance(sampler_index, int) or sampler_index < 0 \
                    or sampler_index >= len(samplers):
                errors.append(f"{channel_label} invalid sampler {sampler_index}")
            target = channel.get("target", {})
            if target.get("path") not in TARGET_PATH:
                errors.append(f"{channel_label} invalid target path {target.get('path')!r}")
            node_index = target.get("node")
            if node_index is not None and (not isinstance(node_index, int)
                                           or node_index < 0 or node_index >= len(nodes)):
                errors.append(f"{channel_label} invalid target node {node_index}")
        for sampler_index, sampler in enumerate(samplers):
            sampler_label = f"{label}.samplers[{sampler_index}]"
            if not isinstance(sampler, dict):
                errors.append(f"{sampler_label} is not an object")
                continue
            input_accessor = accessor(gltf, sampler.get("input"),
                                      f"{sampler_label}.input", errors)
            accessor(gltf, sampler.get("output"), f"{sampler_label}.output", errors)
            if input_accessor is not None:
                if input_accessor.get("type") != "SCALAR":
                    errors.append(f"{sampler_label}.input must be SCALAR")
                maximum = input_accessor.get("max")
                if isinstance(maximum, list) and maximum:
                    try:
                        duration = max(duration, float(maximum[0]))
                    except (TypeError, ValueError):
                        errors.append(f"{sampler_label}.input.max is not numeric")
                else:
                    warnings.append(f"{sampler_label}.input lacks time max")
        animation_summary.append({
            "name": name,
            "channels": len(channels),
            "samplers": len(samplers),
            "duration_seconds": round(duration, 4),
        })

    if require_animation and not animations:
        errors.append("no animations in asset (required)")
    names = {item["name"] for item in animation_summary}
    for expected in expect_animations:
        if expected not in names:
            errors.append(f"expected animation {expected!r} not found; got {sorted(names)}")

    status = "PASS" if not errors else "FAIL"
    report = {
        "asset": str(path),
        "status": status,
        "errors": errors,
        "warnings": warnings,
        "container": container,
        "gltf_version": asset.get("version"),
        "generator": asset.get("generator"),
        "nodes": len(nodes),
        "meshes": len(meshes),
        "primitives": total_primitives,
        "triangles": total_triangles,
        "materials": [material.get("name", f"material_{i}")
                      for i, material in enumerate(materials)],
        "bounds_gltf": {
            "min": [round(value, 6) for value in bounds_min]
            if math.isfinite(bounds_min[0]) else None,
            "max": [round(value, 6) for value in bounds_max]
            if math.isfinite(bounds_max[0]) else None,
        },
        "skins": len(skins),
        "animations": animation_summary,
        "checks": {
            "require_animation": require_animation,
            "expected_animations": expect_animations,
            "require_material": require_material,
            "require_skin": require_skin,
            "min_triangles": min_triangles,
            "max_triangles": max_triangles,
            "ground_origin": ground_origin,
        },
    }
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("glb", type=Path)
    parser.add_argument("--require-animation", action="store_true")
    parser.add_argument("--expect-animation", action="append", default=[])
    parser.add_argument("--require-material", action="store_true")
    parser.add_argument("--require-skin", action="store_true")
    parser.add_argument("--min-triangles", type=int, default=1)
    parser.add_argument("--max-triangles", type=int, default=6000)
    parser.add_argument("--require-ground-origin", action="store_true",
                        help="expect glTF min Y ~= 0 (Blender ground-plane props)")
    parser.add_argument("--ground-tolerance", type=float, default=0.02)
    parser.add_argument("--min-bytes", type=int, default=64)
    parser.add_argument("--report", type=Path)
    parser.add_argument("--dump-json", action="store_true",
                        help="dump the raw glTF JSON chunk")
    args = parser.parse_args()

    try:
        report = validate(
            args.glb,
            require_animation=args.require_animation,
            expect_animations=args.expect_animation,
            require_material=args.require_material,
            require_skin=args.require_skin,
            min_triangles=args.min_triangles,
            max_triangles=args.max_triangles,
            ground_origin=args.require_ground_origin,
            ground_tolerance=args.ground_tolerance,
            min_bytes=args.min_bytes,
        )
    except (OSError, GlbError, json.JSONDecodeError) as exc:
        print(f"ASSET_VALIDATION=FAIL\nERROR: {exc}")
        return 2

    if args.dump_json:
        gltf, _, _ = parse_glb(args.glb)
        print(json.dumps(gltf, indent=2)[:20000])

    if args.report:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(json.dumps(report, indent=2) + "\n")

    print(f"ASSET_VALIDATION={report['status']}")
    print(f"ASSET={report['asset']}")
    print(f"BYTES={report['container']['bytes']} NODES={report['nodes']} "
          f"MESHES={report['meshes']} PRIMITIVES={report['primitives']}")
    print(f"TRIANGLES={report['triangles']} MATERIALS={len(report['materials'])} "
          f"SKINS={report['skins']}")
    print(f"BOUNDS_GLTF_MIN={report['bounds_gltf']['min']} "
          f"BOUNDS_GLTF_MAX={report['bounds_gltf']['max']}")
    if report["animations"]:
        for clip in report["animations"]:
            print(f"ANIMATION={clip['name']} CHANNELS={clip['channels']} "
                  f"DURATION={clip['duration_seconds']}s")
    for warning in report["warnings"]:
        print(f"WARNING: {warning}")
    for error in report["errors"]:
        print(f"ERROR: {error}")
    return 0 if report["status"] == "PASS" else 1


if __name__ == "__main__":
    sys.exit(main())
