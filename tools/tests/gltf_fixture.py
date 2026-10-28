"""Build tiny, valid GLB files for tests (no binaries are checked in).

`box_glb` writes a box mesh with one material. With `joints`, the box is
skinned to a joint chain (one vertex group per joint along Y) and each name
in `animations` becomes a clip rotating the joints, so Godot sees a real
Skeleton3D and AnimationPlayer.
"""

from __future__ import annotations

import json
import math
import struct
from pathlib import Path


def _pad(data: bytes, fill: bytes = b"\0") -> bytes:
    return data + fill * ((4 - len(data) % 4) % 4)


def box_glb(path: Path, size=(1.0, 1.0, 1.0), joints: list[str] | None = None,
            animations: list[str] | None = None, name: str = "Box") -> Path:
    sx, sy, sz = size
    corners = [(x * sx / 2, y * sy, z * sz / 2) for x in (-1, 1) for y in (0, 1) for z in (-1, 1)]
    faces = [(0, 1, 3, 2), (4, 6, 7, 5), (0, 4, 5, 1), (2, 3, 7, 6), (0, 2, 6, 4), (1, 5, 7, 3)]
    positions, indices, normals = [], [], []
    face_normals = [(-1, 0, 0), (1, 0, 0), (0, -1, 0), (0, 1, 0), (0, 0, -1), (0, 0, 1)]
    for face, normal in zip(faces, face_normals):
        base = len(positions)
        positions += [corners[i] for i in face]
        normals += [normal] * 4
        indices += [base, base + 1, base + 2, base, base + 2, base + 3]
    blobs: list[bytes] = []
    views, accessors = [], []

    def add(data: bytes, component: int, count: int, kind: str, target=None, minmax=None) -> int:
        offset = sum(len(b) for b in blobs)
        blobs.append(_pad(data))
        view = {"buffer": 0, "byteOffset": offset, "byteLength": len(data)}
        if target:
            view["target"] = target
        views.append(view)
        accessor = {"bufferView": len(views) - 1, "componentType": component, "count": count, "type": kind}
        if minmax:
            accessor["min"], accessor["max"] = minmax
        accessors.append(accessor)
        return len(accessors) - 1

    flat = [c for p in positions for c in p]
    pos = add(struct.pack(f"<{len(flat)}f", *flat), 5126, len(positions), "VEC3", 34962,
              ([min(p[i] for p in positions) for i in range(3)], [max(p[i] for p in positions) for i in range(3)]))
    idx = add(struct.pack(f"<{len(indices)}H", *indices), 5123, len(indices), "SCALAR", 34963)
    flat_normals = [c for n in normals for c in n]
    attributes = {"POSITION": pos,
                  "NORMAL": add(struct.pack(f"<{len(flat_normals)}f", *flat_normals), 5126, len(normals), "VEC3", 34962)}
    nodes = [{"name": name, "mesh": 0}]
    gltf: dict = {"asset": {"version": "2.0", "generator": "lopodev-test-fixture"},
                  "scene": 0, "scenes": [{"nodes": [0]}],
                  "materials": [{"name": f"mat_{name.lower()}", "pbrMetallicRoughness":
                                 {"baseColorFactor": [0.4, 0.6, 0.3, 1.0]}}]}
    if joints:
        count = len(joints)
        weights, joint_ids = [], []
        for x, y, z in positions:
            joint = min(count - 1, int(y / sy * count)) if sy else 0
            joint_ids += [joint, 0, 0, 0]
            weights += [1.0, 0.0, 0.0, 0.0]
        attributes["JOINTS_0"] = add(struct.pack(f"<{len(joint_ids)}B", *joint_ids), 5121, len(positions), "VEC4", 34962)
        attributes["WEIGHTS_0"] = add(struct.pack(f"<{len(weights)}f", *weights), 5126, len(positions), "VEC4", 34962)
        step = sy / count
        first = len(nodes) + 1  # node 1 is the armature root
        nodes[0]["skin"] = 0
        nodes.append({"name": "Armature", "children": [first]})
        for i, joint in enumerate(joints):
            node = {"name": joint, "translation": [0.0, step if i else 0.0, 0.0]}
            if i < count - 1:
                node["children"] = [first + i + 1]
            nodes.append(node)
        ibm = []
        for i in range(count):
            ibm += [1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0, 0, -step * i, 0, 1]
        ibm_index = add(struct.pack(f"<{len(ibm)}f", *ibm), 5126, count, "MAT4")
        gltf["skins"] = [{"joints": list(range(first, first + count)), "inverseBindMatrices": ibm_index,
                          "skeleton": first}]
        gltf["scenes"][0]["nodes"] = [0, 1]
        clips = []
        for index, clip in enumerate(animations or []):
            times = add(struct.pack("<3f", 0.0, 0.5, 1.0), 5126, 3, "SCALAR", minmax=([0.0], [1.0]))
            angle = 0.2 + 0.1 * index
            values = []
            for t in (0.0, angle, 0.0):
                values += [math.sin(t / 2), 0.0, 0.0, math.cos(t / 2)]
            rotation = add(struct.pack(f"<{len(values)}f", *values), 5126, 3, "VEC4")
            channels, samplers = [], []
            for j in range(count):
                samplers.append({"input": times, "output": rotation, "interpolation": "LINEAR"})
                channels.append({"sampler": j, "target": {"node": first + j, "path": "rotation"}})
            clips.append({"name": clip, "channels": channels, "samplers": samplers})
        if clips:
            gltf["animations"] = clips
    gltf["meshes"] = [{"name": name, "primitives": [{"attributes": attributes, "indices": idx, "material": 0}]}]
    gltf["nodes"] = nodes
    gltf["accessors"] = accessors
    gltf["bufferViews"] = views
    binary = b"".join(blobs)
    gltf["buffers"] = [{"byteLength": len(binary)}]
    text = _pad(json.dumps(gltf, separators=(",", ":")).encode(), b" ")
    total = 12 + 8 + len(text) + 8 + len(binary)
    data = struct.pack("<III", 0x46546C67, 2, total) + struct.pack("<II", len(text), 0x4E4F534A) + text \
        + struct.pack("<II", len(binary), 0x004E4942) + binary
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    return path


CC0_TEXT = ("License: (Creative Commons Zero, CC0)\n"
            "http://creativecommons.org/publicdomain/zero/1.0/\n"
            "You may use these assets in personal and commercial projects.\n")


def make_pack(directory: Path, license_text: str | None = CC0_TEXT) -> Path:
    """A small stylized jungle pack: trees, rocks, a log, a wall and two soldiers."""
    models = directory / "Models" / "GLB format"
    box_glb(models / "PalmTree_1.glb", (1.2, 4.5, 1.2), name="PalmTree")
    box_glb(models / "Tree_Jungle.glb", (2.0, 5.0, 2.0), name="Tree")
    box_glb(models / "Rock_Large.glb", (1.5, 1.0, 1.4), name="Rock")
    box_glb(models / "Log_Fallen.glb", (2.5, 0.5, 0.6), name="Log")
    box_glb(models / "Ruins_Wall.glb", (4.0, 2.5, 0.6), name="Wall")
    bones = ["Hips", "Spine", "Neck", "Head"]
    box_glb(directory / "Characters" / "Soldier.glb", (0.6, 1.8, 0.4), joints=bones,
            animations=["Idle", "Walk", "Run", "Shoot", "HitReact", "Death"], name="Soldier")
    box_glb(directory / "Characters" / "Statue_Soldier.glb", (0.6, 1.8, 0.4), name="StatueSoldier")
    # Same file shipped twice in different formats: the GLB must win.
    (models.parent / "OBJ format").mkdir(parents=True, exist_ok=True)
    (models.parent / "OBJ format" / "Rock_Large.obj").write_text("o Rock\n")
    if license_text is not None:
        (directory / "License.txt").write_text(license_text)
    return directory
