#!/usr/bin/env python3
"""Open asset source registry, license policy and provider adapters.

Providers are declared in `resources/asset_sources.json`. Each adapter
implements the same small interface:

  status()                     -> {"available", "automated", "reason"}
  search(requirement, fetch)   -> candidate asset records
  fetch(record, staging, fetch)-> local files for the record (main model first)

Only official APIs or files the user downloaded themselves are used: no
scraping. Providers without a supported interface are registered as
`unavailable` with the reason, so the gap is visible instead of guessed.
"""

from __future__ import annotations

import json
import os
import re
import sys
import time
from pathlib import Path, PurePosixPath

sys.path.insert(0, str(Path(__file__).resolve().parent))

import asset_catalog  # noqa: E402
from asset_catalog import AssetError, Fetcher  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
LICENSE_FILES = re.compile(r"^(licen[cs]e|copying)([._ -].*)?$", re.IGNORECASE)
README_FILES = re.compile(r"^(readme|credits?)([._ -].*)?$", re.IGNORECASE)
TOKEN_RE = re.compile(r"[A-Z]+(?=[A-Z][a-z])|[A-Z]?[a-z]+|[A-Z]+|\d+")


def load_registry(root: Path = ROOT) -> dict:
    return json.loads((root / "resources/asset_sources.json").read_text(encoding="utf-8"))


def tokens(*texts: str) -> list[str]:
    """Split names like 'PalmTree_02-large' into ['palm', 'tree', 'large']."""
    words: list[str] = []
    for text in texts:
        for part in re.split(r"[^A-Za-z0-9]+", text or ""):
            words += [word.lower() for word in TOKEN_RE.findall(part) if not word.isdigit()]
    return words


# ---------------------------------------------------------------- licenses

def normalize_license(text: str | None) -> str:
    """Map a free-form license string to an SPDX-like id; 'unknown' if unsure."""
    if not text:
        return "unknown"
    value = text.strip().lower().replace("_", "-")
    if "publicdomain/zero" in value or "cc0" in value or "creative commons zero" in value:
        return "CC0-1.0"
    if value.startswith("oga-by") or "oga-by" in value:
        return "OGA-BY-3.0"
    match = re.search(r"cc[ -]?by((?:[ -]?(?:sa|nc|nd))*)[ -]?(\d\.\d)?", value)
    url = re.search(r"creativecommons\.org/licenses/([a-z-]+)/(\d\.\d)", value)
    if url:
        return f"CC-{url.group(1).upper()}-{url.group(2)}"
    if match:
        parts = [p for p in re.split(r"[ -]", match.group(1).upper()) if p]
        version = match.group(2) or "4.0"
        return "-".join(["CC-BY", *parts, version])
    for spdx in ("GPL-2.0", "GPL-3.0", "LGPL-3.0", "MIT"):
        if spdx.lower() in value:
            return spdx
    return "unknown"


def license_decision(license_id: str, policy: dict) -> dict:
    """Hard eligibility: allowed | attribution | review | rejected."""
    if license_id in policy.get("allowed", []):
        return {"decision": "allowed", "attribution_required": False}
    if license_id in policy.get("allowed_with_attribution", []):
        return {"decision": "attribution", "attribution_required": True}
    if license_id in policy.get("review", []):
        return {"decision": "review", "reason": f"{license_id} needs manual review for this distribution"}
    for pattern in policy.get("rejected_patterns", []):
        if pattern.lower() in license_id.lower().split("-") or pattern.lower() == license_id.lower():
            return {"decision": "rejected", "reason": f"{license_id} is excluded by policy ({pattern})"}
    return {"decision": "review", "reason": f"{license_id} is not covered by the policy"}


def detect_pack_license(pack_dir: Path) -> tuple[str, str | None]:
    """Read license/readme files shipped in a pack. Returns (license id, evidence path)."""
    found: list[tuple[str, Path]] = []
    for pattern in (LICENSE_FILES, README_FILES):  # a readme only counts without a license file
        for path in sorted(pack_dir.rglob("*")):
            if path.is_file() and pattern.match(path.name) and path.stat().st_size < 200_000:
                found.append((normalize_license(path.read_text(encoding="utf-8", errors="replace")), path))
        if any(license_id != "unknown" for license_id, _ in found):
            break
    known = {license_id for license_id, _ in found if license_id != "unknown"}
    if len(known) == 1:
        license_id = known.pop()
        evidence = next(path for lid, path in found if lid == license_id)
        return license_id, str(evidence.relative_to(pack_dir))
    if len(known) > 1:
        return "unknown", f"conflicting license files: {sorted(known)}"
    return "unknown", None


# ---------------------------------------------------------------- adapters

class Provider:
    automated = False

    def __init__(self, name: str, spec: dict, base: Path | None = None):
        self.name, self.spec, self.base = name, spec, base

    def status(self) -> dict:
        return {"available": True, "automated": self.automated, "reason": self.spec.get("notes", "")}

    def search(self, requirement: dict, fetch: Fetcher) -> list[dict]:
        return []

    def fetch(self, record: dict, staging: Path, fetch: Fetcher) -> list[Path]:
        raise AssetError(f"{self.name} cannot download assets automatically")

    def base_record(self, provider_id: str, **fields) -> dict:
        license_id = fields.pop("license_id", self.spec.get("license", "unknown"))
        record = {
            "schema_version": 1, "asset_id": f"{self.name}:{provider_id}", "provider": self.name,
            "provider_id": provider_id, "kind": "model", "tags": [], "categories": [],
            "style": list(self.spec.get("style", [])),
            "license": {"id": license_id, "evidence": self.spec.get("license_evidence"),
                        "creator": None, "attribution": None},
        }
        record.update(fields)
        return record


class UnavailableProvider(Provider):
    def status(self) -> dict:
        return {"available": False, "automated": False, "reason": self.spec.get("notes", "no supported interface")}


class LocalPackProvider(Provider):
    """Packs the user downloaded (Kenney, Quaternius, KayKit, OpenGameArt...)."""

    def status(self) -> dict:
        catalog = asset_catalog.load_catalog(self.base)
        packs = {r.get("pack") for r in catalog["records"].values() if r["provider"] == self.name}
        packs.discard(None)
        reason = f"{len(packs)} pack(s) indexed" if packs else \
            f"no packs indexed; {self.spec.get('notes', 'add one with lopodev assets add-pack')}"
        return {"available": bool(packs), "automated": False, "reason": reason}

    def search(self, requirement: dict, fetch: Fetcher) -> list[dict]:
        catalog = asset_catalog.load_catalog(self.base)
        return [record for record in catalog["records"].values() if record["provider"] == self.name]

    def fetch(self, record: dict, staging: Path, fetch: Fetcher) -> list[Path]:
        path = Path(record["local"]["path"])
        if not path.is_file():
            raise AssetError(f"pack file is missing: {path}; re-add the pack")
        if record["local"].get("sha256") and asset_catalog.sha256_file(path) != record["local"]["sha256"]:
            raise AssetError(f"pack file changed since it was indexed: {path}")
        return [path]


def index_pack(source: Path, provider: str, pack: str, *, style: list[str], tags: list[str],
               license_id: str | None = None, license_evidence: str | None = None,
               base: Path | None = None, registry: dict | None = None) -> dict:
    """Add a downloaded pack (zip or folder) to the catalog."""
    registry = registry or load_registry()
    spec = registry["providers"].get(provider)
    if spec is None:
        raise AssetError(f"unknown provider {provider!r}; add it to resources/asset_sources.json")
    if not re.fullmatch(r"[a-z0-9][a-z0-9_-]*", pack):
        raise AssetError("pack name must be lowercase letters, digits, '-' or '_'")
    base = base or asset_catalog.assets_dir()
    target = base / "packs" / provider / pack
    original = None
    if source.is_file():
        data = source.read_bytes()
        original_path, digest = asset_catalog.store_bytes(data, source.name, base)
        original = {"path": str(original_path), "sha256": digest}
        staging = target.with_name(pack + ".staging")
        if staging.exists():
            asset_catalog.shutil.rmtree(staging)
        asset_catalog.extract_zip(data, staging)
        if target.exists():
            asset_catalog.shutil.rmtree(target)
        os.replace(staging, target)
    elif source.is_dir():
        if source.resolve() != target.resolve():
            asset_catalog.copy_tree(source, target)
    else:
        raise AssetError(f"pack not found: {source}")

    detected, evidence = detect_pack_license(target)
    if license_id:
        declared = normalize_license(license_id) if normalize_license(license_id) != "unknown" else license_id
        if detected not in ("unknown", declared):
            raise AssetError(f"declared license {declared} conflicts with the pack's own {detected} ({evidence})")
        detected, evidence = declared, license_evidence or evidence or "declared by user"
    elif detected == "unknown":
        evidence = evidence or "no license file found in pack"

    files = [path for path in target.rglob("*") if path.is_file()
             and path.suffix.lower() in asset_catalog.MODEL_FORMATS]
    # Packs often ship one model in several formats: keep the most importable.
    preferred: dict[str, Path] = {}
    rank = {".glb": 0, ".gltf": 1, ".fbx": 2, ".obj": 3, ".blend": 4}
    for path in files:
        key = path.stem.lower()
        if key not in preferred or rank[path.suffix.lower()] < rank[preferred[key].suffix.lower()]:
            preferred[key] = path
    catalog = asset_catalog.load_catalog(base)
    stale = [aid for aid, r in catalog["records"].items() if r.get("pack") == pack and r["provider"] == provider]
    for asset_id in stale:
        del catalog["records"][asset_id]
    added = []
    for path in sorted(preferred.values()):
        relative = path.relative_to(target)
        info = asset_catalog.inspect_model(path)
        folder_words = tokens(*relative.parent.parts)
        record = {
            "schema_version": 1, "asset_id": f"{provider}:{pack}/{relative.with_suffix('').as_posix()}",
            "provider": provider, "provider_id": relative.as_posix(), "pack": pack, "kind": "model",
            "title": path.stem, "tags": sorted(set(tags + folder_words)), "name_tokens": tokens(path.stem),
            "categories": folder_words, "style": style or list(spec.get("style", [])),
            "source_url": spec.get("homepage"), "format": info["format"],
            "license": {"id": detected, "evidence": evidence, "creator": spec.get("creator"),
                        "attribution": None},
            "local": {"path": str(path), "sha256": asset_catalog.sha256_file(path),
                      "pack_dir": str(target)},
            "original": original, "capabilities": capabilities(info), "inspection": info,
            "history": [{"ts": asset_catalog.utc_now(), "event": "indexed", "detail": str(source.name)}],
        }
        asset_catalog.upsert(catalog, record)
        added.append(record["asset_id"])
    asset_catalog.save_catalog(catalog, base)
    return {"provider": provider, "pack": pack, "license": detected, "license_evidence": evidence,
            "models": len(added), "removed_stale": len(stale), "path": str(target)}


def capabilities(info: dict) -> dict:
    """What an inspected model provides (None means unknown, not absent)."""
    if not info.get("inspected"):
        return {"triangles": None, "size_m": None, "skinned": None, "joints": [], "animations": [],
                "importable": info.get("format") in ("glb", "gltf"), "verified_by": "none"}
    return {"triangles": info.get("triangles"), "size_m": info.get("size_m"), "skinned": info.get("skinned"),
            "joints": info.get("joints", []), "animations": [a["name"] for a in info.get("animations", [])],
            "importable": not info.get("missing_files") and not info.get("errors"),
            "verified_by": "inspection"}


class PolyHavenProvider(Provider):
    automated = True
    TYPES = {"model": "models", "material": "textures", "hdri": "hdris"}

    def listing(self, kind: str, fetch: Fetcher) -> dict:
        cache = (self.base or asset_catalog.assets_dir()) / "provider_cache" / f"polyhaven_{kind}.json"
        if cache.is_file() and time.time() - cache.stat().st_mtime < 86400:
            return json.loads(cache.read_text(encoding="utf-8"))
        data = json.loads(fetch(f"{self.spec['api']}/assets?t={self.TYPES[kind]}"))
        if not isinstance(data, dict):
            raise AssetError("unexpected Poly Haven listing format")
        cache.parent.mkdir(parents=True, exist_ok=True)
        cache.write_text(json.dumps(data), encoding="utf-8")
        return data

    def search(self, requirement: dict, fetch: Fetcher) -> list[dict]:
        kind = {"material": "material", "hdri": "hdri"}.get(requirement.get("class"), "model")
        listing = self.listing(kind, fetch)
        wanted = set(requirement.get("terms", []))
        results = []
        for provider_id, item in listing.items():
            words = set(item.get("tags", [])) | set(item.get("categories", [])) | set(tokens(item.get("name", "")))
            if not wanted & {word.lower() for word in words}:
                continue
            dims = item.get("dimensions")
            results.append(self.base_record(
                provider_id, kind=kind, title=item.get("name", provider_id),
                tags=[t.lower() for t in item.get("tags", [])], categories=item.get("categories", []),
                name_tokens=tokens(item.get("name", "")), format="gltf" if kind == "model" else "zip",
                source_url=f"https://polyhaven.com/a/{provider_id}",
                thumbnail=f"https://cdn.polyhaven.com/asset_img/thumbs/{provider_id}.png?width=256",
                license={"id": "CC0-1.0", "evidence": self.spec["license_evidence"],
                         "creator": ", ".join(item.get("authors", {})) or None, "attribution": None},
                capabilities={"triangles": item.get("polycount"),
                              "size_m": [round(d / 1000, 3) for d in dims] if dims else None,
                              "skinned": None, "joints": [], "animations": [],
                              "texture_px": (item.get("max_resolution") or [None])[0],
                              "importable": True, "verified_by": "provider_metadata"}))
        return results

    def fetch(self, record: dict, staging: Path, fetch: Fetcher) -> list[Path]:
        files = json.loads(fetch(f"{self.spec['api']}/files/{record['provider_id']}"))
        gltf = files.get("gltf") or {}
        resolution = next((r for r in ("1k", "2k", "4k") if r in gltf), None)
        if resolution is None:
            raise AssetError(f"Poly Haven {record['provider_id']} has no glTF download")
        main = gltf[resolution]["gltf"]
        destination = staging / record["provider_id"]
        main_path = destination / safe_relative(PurePosixPath(main["url"]).name)
        asset_catalog.download(main["url"], main_path, size=main.get("size"), md5=main.get("md5"), fetch=fetch)
        paths = [main_path]
        for relative, item in sorted(main.get("include", {}).items()):
            path = destination / safe_relative(relative)
            asset_catalog.download(item["url"], path, size=item.get("size"), md5=item.get("md5"), fetch=fetch)
            paths.append(path)
        return paths


class AmbientCGProvider(Provider):
    automated = True

    def search(self, requirement: dict, fetch: Fetcher) -> list[dict]:
        query = "+".join(requirement.get("terms", [])[:3])
        data = json.loads(fetch(f"{self.spec['api']}?type=Material&q={query}&limit=12"
                                "&include=downloadData,tagData,displayData"))
        results = []
        for item in data.get("foundAssets", []):
            zips = (((item.get("downloadFolders") or {}).get("default") or {})
                    .get("downloadFiletypeCategories", {}).get("zip", {}).get("downloads", []))
            choice = next((z for z in zips if z.get("attribute") == "1K-JPG"), zips[0] if zips else None)
            if choice is None:
                continue
            results.append(self.base_record(
                item["assetId"], kind="material", title=item.get("displayName", item["assetId"]),
                tags=[t.lower() for t in item.get("tags", [])], categories=[item.get("displayCategory") or ""],
                name_tokens=tokens(item.get("displayName", "")), format="zip",
                source_url=f"https://ambientcg.com/view?id={item['assetId']}",
                thumbnail=(item.get("previewImage") or {}).get("256-PNG"),
                download={"url": choice["downloadLink"], "size": choice.get("size"), "file": choice["fileName"]},
                capabilities={"texture_px": 1024, "importable": True, "verified_by": "provider_metadata"}))
        return results

    def fetch(self, record: dict, staging: Path, fetch: Fetcher) -> list[Path]:
        download = record["download"]
        archive = staging / asset_catalog.safe_name(download["file"])
        asset_catalog.download(download["url"], archive, size=download.get("size"), fetch=fetch)
        return [archive, *asset_catalog.extract_zip(archive.read_bytes(), staging / record["provider_id"])]


def safe_relative(relative: str) -> Path:
    path = PurePosixPath(relative)
    if path.is_absolute() or ".." in path.parts:
        raise AssetError(f"unsafe provider path: {relative}")
    return Path(*path.parts)


ADAPTERS = {"local_pack": LocalPackProvider, "polyhaven": PolyHavenProvider,
            "ambientcg": AmbientCGProvider, "unavailable": UnavailableProvider}


def providers(registry: dict | None = None, base: Path | None = None) -> dict[str, Provider]:
    registry = registry or load_registry()
    return {name: ADAPTERS[spec["adapter"]](name, spec, base) for name, spec in registry["providers"].items()}
