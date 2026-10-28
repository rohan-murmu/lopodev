#!/usr/bin/env python3
"""Local, reusable asset cache and catalog (per user, shared by all projects).

Layout under `$LOPODEV_DATA/assets/`:

  originals/<sha256>/<filename>   downloaded or added files, never modified
  packs/<provider>/<pack>/        extracted local packs (Kenney, Quaternius, ...)
  catalog.json                    asset records keyed by asset id

An asset record describes what an asset *provides* (license, format, hashes,
geometry, rig, animations). It is not a requirement and not a validation
report; see docs/assets.md for the three contracts.

Downloads go to a `.part` file, are size/hash checked, then renamed, so an
interrupted or corrupt transfer never becomes a cached original.
"""

from __future__ import annotations

import hashlib
import io
import json
import os
import re
import shutil
import struct
import sys
import urllib.request
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parent / "blender"))

import integrations  # noqa: E402
import validate_asset  # noqa: E402

SCHEMA_VERSION = 1
MODEL_FORMATS = {".glb": "glb", ".gltf": "gltf", ".fbx": "fbx", ".obj": "obj", ".blend": "blend"}
IMAGE_FORMATS = {".png", ".jpg", ".jpeg", ".webp", ".exr", ".hdr", ".ktx2"}

Fetcher = Callable[[str], bytes]


class AssetError(Exception):
    pass


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def assets_dir() -> Path:
    return integrations.data_dir() / "assets"


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def user_agent() -> str:
    root = Path(__file__).resolve().parent.parent
    try:
        version = (root / "VERSION").read_text(encoding="utf-8").strip()
    except OSError:
        version = "dev"
    return f"LopoDev/{version} (+https://github.com/rohan-murmu/lopodev)"


def http_fetch(url: str) -> bytes:
    """Default fetcher: identifies LopoDev, as provider terms ask."""
    request = urllib.request.Request(url, headers={"User-Agent": user_agent()})
    with urllib.request.urlopen(request, timeout=120) as response:  # noqa: S310 - registry URLs
        return response.read()


# ---------------------------------------------------------------- catalog

def catalog_path(base: Path | None = None) -> Path:
    return (base or assets_dir()) / "catalog.json"


def load_catalog(base: Path | None = None) -> dict:
    path = catalog_path(base)
    if not path.is_file():
        return {"schema_version": SCHEMA_VERSION, "records": {}}
    try:
        catalog = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise AssetError(f"{path} is corrupt ({exc}); move it aside and re-run `lopodev assets index`") from exc
    catalog.setdefault("records", {})
    return catalog


def save_catalog(catalog: dict, base: Path | None = None) -> None:
    path = catalog_path(base)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(catalog, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    os.replace(temporary, path)


def upsert(catalog: dict, record: dict) -> dict:
    """Insert or merge a record; history is appended, never rewritten."""
    existing = catalog["records"].get(record["asset_id"])
    if existing:
        history = existing.get("history", [])
        merged = {**existing, **record, "history": history + record.get("history", [])}
        catalog["records"][record["asset_id"]] = merged
        return merged
    record.setdefault("history", [])
    catalog["records"][record["asset_id"]] = record
    return record


# ---------------------------------------------------------------- originals

def store_bytes(data: bytes, filename: str, base: Path | None = None) -> tuple[Path, str]:
    """Store content by hash; identical content is stored once."""
    digest = sha256_bytes(data)
    target = (base or assets_dir()) / "originals" / digest / safe_name(filename)
    if target.is_file() and sha256_file(target) == digest:
        return target, digest
    target.parent.mkdir(parents=True, exist_ok=True)
    partial = target.with_name(target.name + ".part")
    partial.write_bytes(data)
    os.replace(partial, target)
    return target, digest


def safe_name(name: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9._-]", "_", Path(name).name)
    if cleaned in ("", ".", ".."):
        raise AssetError(f"unsafe file name: {name!r}")
    return cleaned


def download(url: str, destination: Path, *, size: int | None = None, md5: str | None = None,
             sha256: str | None = None, fetch: Fetcher = http_fetch) -> str:
    """Download to `destination` atomically; return its sha256. Raises on any mismatch."""
    try:
        data = fetch(url)
    except Exception as exc:  # network, HTTP and fetcher errors all mean "not downloaded"
        raise AssetError(f"download failed: {url}: {exc}") from exc
    if size is not None and len(data) != size:
        raise AssetError(f"incomplete download {url}: {len(data)} of {size} bytes")
    if md5 and hashlib.md5(data).hexdigest() != md5:  # noqa: S324 - provider-published checksum
        raise AssetError(f"md5 mismatch for {url}")
    digest = sha256_bytes(data)
    if sha256 and digest != sha256:
        raise AssetError(f"sha256 mismatch for {url}")
    destination.parent.mkdir(parents=True, exist_ok=True)
    partial = destination.with_name(destination.name + ".part")
    partial.write_bytes(data)
    os.replace(partial, destination)
    return digest


def extract_zip(data: bytes, destination: Path) -> list[Path]:
    """Extract regular files from a zip, refusing absolute or escaping paths."""
    try:
        archive = zipfile.ZipFile(io.BytesIO(data))
    except zipfile.BadZipFile as exc:
        raise AssetError(f"corrupt archive: {exc}") from exc
    files = []
    with archive:
        bad = archive.testzip()
        if bad is not None:
            raise AssetError(f"corrupt archive member: {bad}")
        for member in archive.infolist():
            relative = Path(member.filename)
            if relative.is_absolute() or ".." in relative.parts:
                raise AssetError(f"unsafe archive member: {member.filename}")
            if member.is_dir():
                continue
            target = destination / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(archive.read(member))
            files.append(target)
    return files


# ---------------------------------------------------------------- inspection

def read_gltf(path: Path) -> tuple[dict, bytes | None]:
    if path.suffix.lower() == ".glb":
        gltf, binary, _ = validate_asset.parse_glb(path)
        return gltf, binary
    return json.loads(path.read_text(encoding="utf-8")), None


def joint_tree(gltf: dict) -> list[dict]:
    """Joints of the first skin as {name, parent} (parent is a joint name or None)."""
    skins = gltf.get("skins") or []
    if not skins:
        return []
    nodes = gltf.get("nodes", [])
    parent_of: dict[int, int] = {}
    for index, node in enumerate(nodes):
        for child in node.get("children", []):
            parent_of[child] = index
    joints = skins[0].get("joints", [])
    joint_set = set(joints)

    def name(index: int) -> str:
        return nodes[index].get("name") or f"joint_{index}"

    tree = []
    for joint in joints:
        parent = parent_of.get(joint)
        while parent is not None and parent not in joint_set:
            parent = parent_of.get(parent)
        tree.append({"name": name(joint), "parent": name(parent) if parent is not None else None})
    return tree


def inspect_model(path: Path) -> dict:
    """Measure what a model file actually contains. Only glTF/GLB are parsed."""
    fmt = MODEL_FORMATS.get(path.suffix.lower(), path.suffix.lower().lstrip("."))
    info: dict = {"format": fmt, "bytes": path.stat().st_size, "inspected": False}
    if fmt not in ("glb", "gltf"):
        info["note"] = f"{fmt} is not inspected; convert to glTF (Blender) before use"
        return info
    try:
        gltf, _ = read_gltf(path)
    except (OSError, ValueError, validate_asset.GlbError, struct.error) as exc:
        return {**info, "error": f"unreadable {fmt}: {exc}"}
    missing = []
    external = []
    for group in ("buffers", "images"):
        for item in gltf.get(group, []):
            uri = item.get("uri")
            if uri and not uri.startswith("data:"):
                external.append(uri)
                if not (path.parent / uri).is_file():
                    missing.append(uri)
    metrics: dict = {}
    if fmt == "glb":
        try:
            report = validate_asset.validate(path, require_animation=False, expect_animations=[],
                                             require_material=False, require_skin=False, min_triangles=0,
                                             max_triangles=10**9, ground_origin=False, ground_tolerance=0.0,
                                             min_bytes=0)
            metrics = {"triangles": report["triangles"], "bounds_min": report["bounds_gltf"]["min"],
                       "bounds_max": report["bounds_gltf"]["max"], "materials": report["materials"],
                       "errors": report["errors"]}
        except (validate_asset.GlbError, ValueError, KeyError) as exc:
            metrics = {"errors": [str(exc)]}
    else:
        metrics = gltf_metrics(gltf)
    measured = world_bounds(gltf)
    if measured:
        metrics["bounds_min"], metrics["bounds_max"] = measured
    bounds = None
    if metrics.get("bounds_min") and metrics.get("bounds_max"):
        bounds = [round(metrics["bounds_max"][i] - metrics["bounds_min"][i], 4) for i in range(3)]
    joints = joint_tree(gltf)
    animations = [{"name": a.get("name", f"animation_{i}"), "channels": len(a.get("channels", []))}
                  for i, a in enumerate(gltf.get("animations", []))]
    return {**info, "inspected": True, "triangles": metrics.get("triangles"), "size_m": bounds,
            "bounds_min": metrics.get("bounds_min"), "bounds_max": metrics.get("bounds_max"),
            "materials": metrics.get("materials", [m.get("name", "") for m in gltf.get("materials", [])]),
            "images": len(gltf.get("images", [])),
            "skinned": bool(gltf.get("skins")), "joints": joints, "animations": animations,
            "external_files": external, "missing_files": missing, "errors": metrics.get("errors", [])}


def _matrix(node: dict) -> list[float]:
    """Column-major 4x4 local matrix of a glTF node."""
    if "matrix" in node:
        return [float(v) for v in node["matrix"]]
    tx, ty, tz = node.get("translation", [0, 0, 0])
    qx, qy, qz, qw = node.get("rotation", [0, 0, 0, 1])
    sx, sy, sz = node.get("scale", [1, 1, 1])
    r = [1 - 2 * (qy * qy + qz * qz), 2 * (qx * qy + qz * qw), 2 * (qx * qz - qy * qw),
         2 * (qx * qy - qz * qw), 1 - 2 * (qx * qx + qz * qz), 2 * (qy * qz + qx * qw),
         2 * (qx * qz + qy * qw), 2 * (qy * qz - qx * qw), 1 - 2 * (qx * qx + qy * qy)]
    return [r[0] * sx, r[1] * sx, r[2] * sx, 0, r[3] * sy, r[4] * sy, r[5] * sy, 0,
            r[6] * sz, r[7] * sz, r[8] * sz, 0, tx, ty, tz, 1]


def _multiply(a: list[float], b: list[float]) -> list[float]:
    return [sum(a[k * 4 + row] * b[col * 4 + k] for k in range(4)) for col in range(4) for row in range(4)]


def world_bounds(gltf: dict) -> tuple[list[float], list[float]] | None:
    """Scene bounds with node transforms applied (accessor min/max are mesh-local)."""
    nodes, meshes, accessors = gltf.get("nodes", []), gltf.get("meshes", []), gltf.get("accessors", [])
    scenes = gltf.get("scenes") or [{"nodes": list(range(len(nodes)))}]
    roots = scenes[gltf.get("scene", 0)].get("nodes", [])
    lo, hi = [float("inf")] * 3, [float("-inf")] * 3
    stack = [(index, [1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1]) for index in roots]
    seen = 0
    while stack and seen < 10000:
        index, parent = stack.pop()
        seen += 1
        node = nodes[index]
        matrix = _multiply(parent, _matrix(node))
        if "mesh" in node and node["mesh"] < len(meshes) and "skin" not in node:
            for primitive in meshes[node["mesh"]].get("primitives", []):
                position = accessors[primitive["attributes"]["POSITION"]]
                if "min" not in position:
                    continue
                for corner in [(x, y, z) for x in (position["min"][0], position["max"][0])
                               for y in (position["min"][1], position["max"][1])
                               for z in (position["min"][2], position["max"][2])]:
                    world = [matrix[row] * corner[0] + matrix[4 + row] * corner[1] + matrix[8 + row] * corner[2]
                             + matrix[12 + row] for row in range(3)]
                    lo = [min(lo[i], world[i]) for i in range(3)]
                    hi = [max(hi[i], world[i]) for i in range(3)]
        elif "mesh" in node and node["mesh"] < len(meshes):
            # Skinned meshes are posed by joints; their bind-space bounds are the useful size.
            for primitive in meshes[node["mesh"]].get("primitives", []):
                position = accessors[primitive["attributes"]["POSITION"]]
                if "min" in position:
                    lo = [min(lo[i], position["min"][i]) for i in range(3)]
                    hi = [max(hi[i], position["max"][i]) for i in range(3)]
        stack.extend((child, matrix) for child in node.get("children", []))
    if lo[0] == float("inf"):
        return None
    return [round(v, 6) for v in lo], [round(v, 6) for v in hi]


def gltf_metrics(gltf: dict) -> dict:
    """Triangles and bounds from accessor metadata (no buffer reads needed)."""
    accessors = gltf.get("accessors", [])
    triangles = 0
    lo, hi = [float("inf")] * 3, [float("-inf")] * 3
    for mesh in gltf.get("meshes", []):
        for primitive in mesh.get("primitives", []):
            position = accessors[primitive["attributes"]["POSITION"]]
            count = accessors[primitive["indices"]]["count"] if "indices" in primitive else position["count"]
            if primitive.get("mode", 4) == 4:
                triangles += count // 3
            if "min" in position and "max" in position:
                lo = [min(lo[i], position["min"][i]) for i in range(3)]
                hi = [max(hi[i], position["max"][i]) for i in range(3)]
    finite = lo[0] != float("inf")
    return {"triangles": triangles, "bounds_min": lo if finite else None, "bounds_max": hi if finite else None,
            "materials": [m.get("name", "") for m in gltf.get("materials", [])], "errors": []}


def main_model(files: list[Path]) -> Path | None:
    """Pick the primary model file: glb, then gltf, then other formats."""
    for suffix in (".glb", ".gltf", ".fbx", ".obj", ".blend"):
        matches = sorted(path for path in files if path.suffix.lower() == suffix)
        if matches:
            return matches[0]
    return None


def copy_tree(source: Path, destination: Path) -> None:
    if destination.exists():
        shutil.rmtree(destination)
    shutil.copytree(source, destination)
