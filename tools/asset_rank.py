#!/usr/bin/env python3
"""Rank asset candidates against a requirement, transparently.

License eligibility, kind, rig and budget limits are hard filters: a rejected
candidate never wins on looks. Survivors get a weighted score whose parts and
reasons are recorded, so a selection can be explained and audited.

Also provides the animation capability map (required action -> clip) and the
skeleton comparison used to decide whether animations can be shared or need
retargeting. Matching bone names alone never counts as proven compatibility.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import asset_sources  # noqa: E402

# Clip-name aliases for common gameplay actions (compared on normalized tokens).
ANIMATION_ALIASES = {
    "idle": ["idle", "stand", "breathe", "rest"],
    "walk": ["walk", "walking"],
    "run": ["run", "running", "sprint", "jog"],
    "aim": ["aim", "aiming"],
    "shoot": ["shoot", "shooting", "fire", "firing", "attack", "gun"],
    "reload": ["reload", "reloading"],
    "hit": ["hit", "hitreact", "hurt", "damage", "receivehit", "impact"],
    "death": ["death", "die", "dying", "dead", "defeat"],
    "jump": ["jump", "jumping", "leap"],
    "attack": ["attack", "punch", "slash", "swing", "kick", "melee"],
    "interact": ["interact", "pickup", "use", "open"],
}
SYNONYMS = {
    "tree": ["palm", "pine", "oak", "trunk", "birch"], "bush": ["shrub", "plant", "fern", "foliage"],
    "grass": ["tuft", "weed", "foliage"], "rock": ["stone", "boulder", "cliff"], "log": ["trunk", "stump", "wood"],
    "soldier": ["character", "human", "man", "enemy", "military"], "enemy": ["character", "monster", "soldier"],
    "ruin": ["ruins", "wall", "pillar", "column", "broken"], "wall": ["fence", "barrier"],
    "weapon": ["gun", "rifle", "pistol", "sword"], "gun": ["rifle", "pistol", "blaster", "weapon"],
    "building": ["house", "hut", "cabin", "structure"], "crate": ["box", "chest", "barrel"],
}
PREFIX_RE = re.compile(r"^(mixamorig\d*[:_]|def[-_]|org[-_]|armature[|_:]|bip\d*[ _]?)", re.IGNORECASE)


def norm_bone(name: str) -> str:
    return re.sub(r"[^a-z0-9]", "", PREFIX_RE.sub("", name).lower())


def animation_map(required: list[str], clips: list[str]) -> dict[str, str | None]:
    """Required action -> best clip name, or None. Exact token match beats substring."""
    result: dict[str, str | None] = {}
    clip_tokens = {clip: set(asset_sources.tokens(clip)) | {clip.lower()} for clip in clips}
    for action in required:
        aliases = ANIMATION_ALIASES.get(action, [action])
        exact = [clip for clip, words in clip_tokens.items() if words & set(aliases)]
        loose = [clip for clip in clips if any(alias in clip.lower() for alias in aliases)]
        # Prefer the plainest clip: "Run" over "Run_Shoot" for "run".
        pool = exact or loose
        result[action] = min(pool, key=lambda c: (len(asset_sources.tokens(c)), len(c))) if pool else None
    return result


def compare_skeletons(source: list[dict], target: list[dict]) -> dict:
    """Classify how animations from `source` could apply to `target`.

    identical       same normalized names and parents: shareable, still verify playback
    name_compatible most bones and parents match: retarget candidate, needs runtime check
    incompatible    otherwise: pick another character or animation set
    """
    if not source or not target:
        return {"relation": "incompatible", "matched": 0, "reason": "missing skeleton"}
    src = {norm_bone(j["name"]): norm_bone(j["parent"]) if j.get("parent") else None for j in source}
    dst = {norm_bone(j["name"]): norm_bone(j["parent"]) if j.get("parent") else None for j in target}
    shared = set(src) & set(dst)
    same_parent = sum(1 for bone in shared if src[bone] == dst[bone])
    coverage = len(shared) / max(len(src), len(dst))
    hierarchy = same_parent / len(shared) if shared else 0.0
    detail = {"matched": len(shared), "source_bones": len(src), "target_bones": len(dst),
              "name_coverage": round(coverage, 3), "hierarchy_agreement": round(hierarchy, 3)}
    if shared == set(src) == set(dst) and hierarchy == 1.0:
        return {"relation": "identical", **detail,
                "reason": "same bone names and hierarchy; rest poses still need a playback check"}
    if coverage >= 0.7 and hierarchy >= 0.9:
        return {"relation": "name_compatible", **detail,
                "reason": "names/hierarchy mostly match; rest pose and orientation unverified (retarget + runtime check)"}
    return {"relation": "incompatible", **detail, "reason": "bone names or hierarchy differ"}


def expand(terms: list[str]) -> set[str]:
    words = set(terms)
    for term in terms:
        words |= set(SYNONYMS.get(term, []))
    return words


def score(requirement: dict, candidate: dict, policy: dict, weights: dict) -> dict:
    """Return {eligible, score, parts, reasons, rejection} for one candidate."""
    reasons: list[str] = []
    caps = candidate.get("capabilities") or {}
    license_id = (candidate.get("license") or {}).get("id", "unknown")
    decision = asset_sources.license_decision(license_id, policy)

    def reject(reason: str) -> dict:
        return {"eligible": False, "score": 0.0, "parts": {}, "reasons": reasons, "rejection": reason,
                "license_decision": decision["decision"]}

    if decision["decision"] not in ("allowed", "attribution"):
        return reject(f"license {license_id}: {decision.get('reason', decision['decision'])}")
    req_class = requirement["class"]
    kind = candidate.get("kind", "model")
    if (req_class == "material") != (kind == "material") or (req_class == "hdri") != (kind == "hdri"):
        return reject(f"kind {kind} does not fit {req_class}")
    if requirement.get("rig") == "required" and caps.get("skinned") is False:
        return reject("requirement needs a rigged model; candidate has no skin")
    budget = requirement.get("budget_triangles")
    triangles = caps.get("triangles")
    if budget and triangles and triangles > budget * 2:
        return reject(f"{triangles} triangles is more than twice the budget {budget}")
    if caps.get("importable") is False:
        return reject("inspection found missing files or errors")

    # semantic: tags/categories count fully, title tokens partly, folder/file names least.
    wanted = set(requirement.get("terms", []))
    related = expand(requirement.get("terms", [])) - wanted
    tags = {t.lower() for t in candidate.get("tags", [])} | {c.lower() for c in candidate.get("categories", [])}
    names = set(candidate.get("name_tokens", []))
    hits = []
    semantic = 0.0
    for term in wanted:
        if term in tags:
            semantic += 1.0
            hits.append(f"tag:{term}")
        elif term in names:
            semantic += 0.6
            hits.append(f"name:{term}")
    for term in related:
        if term in tags or term in names:
            semantic += 0.3
            hits.append(f"related:{term}")
    semantic = min(1.0, semantic / max(1, min(len(wanted), 3)))
    if not hits:
        return reject("no semantic match")
    reasons.append("matches " + ", ".join(sorted(hits)[:6]))

    style_wanted = set(requirement.get("style", []))
    style_have = set(candidate.get("style", []))
    style = 1.0 if not style_wanted else len(style_wanted & style_have) / len(style_wanted)
    if style_wanted and style < 1.0:
        reasons.append(f"style {sorted(style_have)} vs wanted {sorted(style_wanted)}")

    fmt = candidate.get("format")
    technical = {"glb": 1.0, "gltf": 0.9, "zip": 0.8}.get(fmt, 0.3)
    if technical < 0.8:
        reasons.append(f"{fmt} needs conversion before Godot import")

    rig = 1.0
    animation = 1.0
    anim_map: dict = {}
    if requirement.get("rig") == "required":
        rig = 1.0 if caps.get("skinned") else 0.3
        if caps.get("skinned") is None:
            reasons.append("rig unknown until inspected")
    elif caps.get("skinned"):
        rig = 0.7  # static need served by a skinned mesh: works, costs more
    needed = requirement.get("animations", [])
    if needed:
        anim_map = animation_map(needed, caps.get("animations", []))
        covered = sum(1 for clip in anim_map.values() if clip)
        animation = covered / len(needed)
        missing = [action for action, clip in anim_map.items() if not clip]
        reasons.append(f"animations {covered}/{len(needed)}" + (f", missing {missing}" if missing else ""))

    budget_score = 1.0
    if budget and triangles:
        budget_score = 1.0 if triangles <= budget else max(0.0, 1 - (triangles - budget) / budget)
        reasons.append(f"{triangles} tris (budget {budget})")
    elif budget:
        budget_score = 0.6
        reasons.append("triangle count unknown")

    collision = 1.0
    size = caps.get("size_m")
    target_size = requirement.get("size_m")
    if size and target_size:
        ratio = max(s for s in size) / max(max(target_size), 1e-6)
        collision = 1.0 if 0.5 <= ratio <= 2.0 else 0.5
        if collision < 1.0:
            reasons.append(f"size {size} m needs scaling toward {target_size} m")

    parts = {"semantic": semantic, "style": style, "technical": technical, "rig": rig,
             "animation": animation, "budget": budget_score, "collision": collision}
    total = sum(weights.get(name, 0) * value for name, value in parts.items())
    total /= max(1e-6, sum(weights.get(name, 0) for name in parts))
    if decision["decision"] == "attribution":
        reasons.append(f"{license_id}: attribution required")
    return {"eligible": True, "score": round(total, 4), "parts": {k: round(v, 3) for k, v in parts.items()},
            "reasons": reasons, "rejection": None, "license_decision": decision["decision"],
            "animation_map": anim_map}


def rank(requirement: dict, candidates: list[dict], policy: dict, weights: dict) -> tuple[list, list]:
    """Return (eligible sorted best first, rejected) as (candidate, result) pairs."""
    eligible, rejected = [], []
    for candidate in candidates:
        result = score(requirement, candidate, policy, weights)
        (eligible if result["eligible"] else rejected).append((candidate, result))
    eligible.sort(key=lambda pair: (-pair[1]["score"], pair[0]["asset_id"]))
    return eligible, rejected
