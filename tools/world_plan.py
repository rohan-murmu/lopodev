#!/usr/bin/env python3
"""Plan, place and validate gameplay-aware procedural worlds.

A world plan is JSON on the ground (X/Z) plane in meters. Fixed features
(spawns, objectives, landmarks, paths, placed obstacles) are authored; scatter
rules are resolved deterministically from `seed` into explicit placements.
Validation then checks what players feel: every objective reachable from a
spawn, nothing collidable overlapping, paths and spawns kept clear, density
and repetition within budget. The resolved plan is the reproducible source
for Godot assembly (tools/godot/world_to_tscn.py).

  python3 tools/world_plan.py generate plan.json --out resolved.json
  python3 tools/world_plan.py validate resolved.json [--report report.json] [--map]

Optional plan features: `terrain` (deterministic value-noise heightfield;
placements get `y` and rules can set `max_slope_deg`), `exclusions` (circles or
boxes nothing collidable may enter), scatter `"distribution": "poisson"`
(blue-noise spacing), `enemy_spawns` + `enemy_radius` (enemies must reach the
player), `sightlines` (must stay unobstructed) and `combat_zones` (bounded
cover). Overlap queries use a spatial hash, so dense foliage stays fast.
"""

from __future__ import annotations

import argparse
import json
import math
import random
import sys
from collections import Counter, deque
from pathlib import Path

DEFAULTS = {"cell_size": 0.5, "player_radius": 0.4, "spawn_clearance": 2.0,
            "objective_clearance": 1.0, "enemy_radius": 0.5}


class SpatialHash:
    """Uniform grid of circles for fast neighbor queries."""

    def __init__(self, cell: float):
        self.cell = max(cell, 0.25)
        self.buckets: dict[tuple[int, int], list[dict]] = {}

    def key(self, x: float, z: float) -> tuple[int, int]:
        return int(math.floor(x / self.cell)), int(math.floor(z / self.cell))

    def add(self, item: dict) -> None:
        self.buckets.setdefault(self.key(*item["pos"]), []).append(item)

    def near(self, x: float, z: float, reach: float):
        span = int(math.ceil(reach / self.cell))
        cx, cz = self.key(x, z)
        for i in range(cx - span, cx + span + 1):
            for j in range(cz - span, cz + span + 1):
                yield from self.buckets.get((i, j), [])


# ---------------------------------------------------------------- terrain

def _lattice(seed: int, i: int, j: int) -> float:
    value = (i * 374761393 + j * 668265263 + seed * 2147483647) & 0xFFFFFFFF
    value = ((value ^ (value >> 13)) * 1274126177) & 0xFFFFFFFF
    return (value ^ (value >> 16)) / 0xFFFFFFFF


def height(plan: dict, x: float, z: float) -> float:
    """Deterministic terrain height in meters (0 for flat or absent terrain)."""
    terrain = plan.get("terrain") or {}
    if terrain.get("type", "flat") == "flat":
        return 0.0
    amplitude, scale = float(terrain.get("amplitude", 1.5)), float(terrain.get("scale", 16.0))
    seed = int(terrain.get("seed", plan.get("seed", 0)))
    total, weight = 0.0, 0.0
    for octave in range(int(terrain.get("octaves", 2))):
        frequency = (2 ** octave) / scale
        u, v = x * frequency, z * frequency
        i, j = math.floor(u), math.floor(v)
        fu, fv = u - i, v - j
        su, sv = fu * fu * (3 - 2 * fu), fv * fv * (3 - 2 * fv)
        a, b = _lattice(seed + octave, i, j), _lattice(seed + octave, i + 1, j)
        c, d = _lattice(seed + octave, i, j + 1), _lattice(seed + octave, i + 1, j + 1)
        sample = (a + (b - a) * su) + ((c + (d - c) * su) - (a + (b - a) * su)) * sv
        total += (sample - 0.5) * 2 * (0.5 ** octave)
        weight += 0.5 ** octave
    flatten = terrain.get("flatten", [])  # [{"pos": [x, z], "radius": r}] e.g. spawns, arenas
    factor = 1.0
    for zone in flatten:
        distance = math.hypot(x - zone["pos"][0], z - zone["pos"][1])
        factor = min(factor, max(0.0, min(1.0, (distance - zone["radius"]) / max(zone.get("falloff", 4.0), 0.01))))
    return round(amplitude * total / weight * factor, 4)


def slope_deg(plan: dict, x: float, z: float, step: float = 0.5) -> float:
    dx = (height(plan, x + step, z) - height(plan, x - step, z)) / (2 * step)
    dz = (height(plan, x, z + step) - height(plan, x, z - step)) / (2 * step)
    return math.degrees(math.atan(math.hypot(dx, dz)))


def in_exclusion(plan: dict, x: float, z: float, radius: float) -> str | None:
    for zone in plan.get("exclusions", []):
        if "circle" in zone:
            cx, cz, r = zone["circle"]
            if math.hypot(x - cx, z - cz) < r + radius:
                return zone.get("id", "exclusion")
        else:
            (x0, z0), (x1, z1) = zone["min"], zone["max"]
            if x0 - radius <= x <= x1 + radius and z0 - radius <= z <= z1 + radius:
                return zone.get("id", "exclusion")
    return None


def poisson_points(rng: random.Random, region: tuple, spacing: float, limit: int, k: int = 20):
    """Bridson-style blue-noise sample stream inside a rectangle."""
    rx0, rz0, rx1, rz1 = region
    cell = spacing / math.sqrt(2)
    grid: dict[tuple[int, int], tuple[float, float]] = {}

    def fits(x: float, z: float) -> bool:
        gx, gz = int(x / cell), int(z / cell)
        for i in range(gx - 2, gx + 3):
            for j in range(gz - 2, gz + 3):
                other = grid.get((i, j))
                if other and math.hypot(other[0] - x, other[1] - z) < spacing:
                    return False
        return True

    first = (rng.uniform(rx0, rx1), rng.uniform(rz0, rz1))
    grid[(int(first[0] / cell), int(first[1] / cell))] = first
    active, produced = [first], 0
    yield first
    while active and produced < limit:
        index = rng.randrange(len(active))
        ox, oz = active[index]
        for _ in range(k):
            angle, distance = rng.uniform(0, 2 * math.pi), rng.uniform(spacing, 2 * spacing)
            x, z = ox + math.cos(angle) * distance, oz + math.sin(angle) * distance
            if rx0 <= x <= rx1 and rz0 <= z <= rz1 and fits(x, z):
                grid[(int(x / cell), int(z / cell))] = (x, z)
                active.append((x, z))
                produced += 1
                yield (x, z)
                break
        else:
            active.pop(index)


def load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def bounds(plan: dict) -> tuple[float, float, float, float]:
    (x0, z0), (x1, z1) = plan["bounds"]["min"], plan["bounds"]["max"]
    return float(x0), float(z0), float(x1), float(z1)


def setting(plan: dict, key: str) -> float:
    return float(plan.get(key, DEFAULTS[key]))


def segment_distance(px: float, pz: float, a: list, b: list) -> float:
    ax, az, bx, bz = float(a[0]), float(a[1]), float(b[0]), float(b[1])
    dx, dz = bx - ax, bz - az
    length = dx * dx + dz * dz
    t = 0.0 if length == 0 else max(0.0, min(1.0, ((px - ax) * dx + (pz - az) * dz) / length))
    return math.hypot(px - (ax + t * dx), pz - (az + t * dz))


def path_distance(px: float, pz: float, path: dict) -> float:
    points = path["points"]
    if len(points) == 1:
        return math.hypot(px - points[0][0], pz - points[0][1])
    return min(segment_distance(px, pz, points[i], points[i + 1]) for i in range(len(points) - 1))


def keepouts(plan: dict, avoid: list[str]) -> list[tuple[float, float, float]]:
    """Circles (x, z, radius) that scattered collidable props must not enter."""
    zones = []
    if "spawns" in avoid:
        for spawn in plan.get("spawns", []):
            zones.append((spawn["pos"][0], spawn["pos"][1], setting(plan, "spawn_clearance")))
    if "objectives" in avoid:
        for item in plan.get("objectives", []):
            zones.append((item["pos"][0], item["pos"][1],
                          item.get("radius", 0.5) + setting(plan, "objective_clearance")))
    if "landmarks" in avoid:
        for item in plan.get("landmarks", []):
            zones.append((item["pos"][0], item["pos"][1], item.get("radius", 1.0)))
    return zones


# ---------------------------------------------------------------- generation

def generate(plan: dict) -> dict:
    """Resolve scatter rules into explicit placements, deterministically."""
    rng = random.Random(plan.get("seed", 0))
    x0, z0, x1, z1 = bounds(plan)
    placed = [dict(item, source="authored", y=height(plan, *item["pos"])) for item in plan.get("obstacles", [])]
    index = SpatialHash(2.0)
    for item in placed:
        index.add(item)
    largest = max([float(item.get("radius", 0.5)) for item in placed] +
                  [float(rule.get("radius", 0.5)) for rule in plan.get("scatter", [])] + [0.5])
    report = []
    for rule_index, rule in enumerate(plan.get("scatter", [])):
        rule_rng = random.Random(rng.randrange(1 << 30) + rule_index)
        region = rule.get("region") or {"min": [x0, z0], "max": [x1, z1]}
        (rx0, rz0), (rx1, rz1) = region["min"], region["max"]
        radius, spacing = float(rule.get("radius", 0.5)), float(rule.get("min_spacing", 0.0))
        avoid = rule.get("avoid", ["paths", "spawns", "objectives", "landmarks"])
        zones = keepouts(plan, avoid)
        max_slope = rule.get("max_slope_deg")
        cluster = rule.get("cluster")
        centers = [(rule_rng.uniform(rx0, rx1), rule_rng.uniform(rz0, rz1))
                   for _ in range(int(cluster["centers"]))] if cluster else []
        count, attempts = 0, 0
        target = int(rule["count"])
        rejected: Counter = Counter()
        poisson = poisson_points(rule_rng, (rx0, rz0, rx1, rz1), max(2 * radius + spacing, 0.1), target * 60) \
            if rule.get("distribution") == "poisson" else None
        while count < target and attempts < target * 60:
            attempts += 1
            if poisson is not None:
                point = next(poisson, None)
                if point is None:
                    break
                x, z = point
            elif centers:
                cx, cz = centers[attempts % len(centers)]
                spread = float(cluster.get("spread", 5.0))
                x, z = rule_rng.gauss(cx, spread), rule_rng.gauss(cz, spread)
            else:
                x, z = rule_rng.uniform(rx0, rx1), rule_rng.uniform(rz0, rz1)
            if not (rx0 + radius <= x <= rx1 - radius and rz0 + radius <= z <= rz1 - radius):
                rejected["region"] += 1
                continue
            if not (x0 + radius <= x <= x1 - radius and z0 + radius <= z <= z1 - radius):
                rejected["bounds"] += 1
                continue
            if any(math.hypot(x - kx, z - kz) < kr + radius for kx, kz, kr in zones):
                rejected["keepout"] += 1
                continue
            if rule.get("collision", "static") != "none" or "exclusions" in avoid:
                if in_exclusion(plan, x, z, radius):
                    rejected["exclusion"] += 1
                    continue
            if "paths" in avoid and any(path_distance(x, z, path) < path.get("width", 2.0) / 2 + radius
                                        for path in plan.get("paths", [])):
                rejected["path"] += 1
                continue
            if max_slope is not None and slope_deg(plan, x, z) > float(max_slope):
                rejected["slope"] += 1
                continue
            if any(math.hypot(x - other["pos"][0], z - other["pos"][1])
                   < radius + float(other.get("radius", 0.5)) + spacing
                   for other in index.near(x, z, radius + largest + spacing)):
                rejected["spacing"] += 1
                continue
            item = {"id": f"{rule['asset']}_{count + 1:03d}", "asset": rule["asset"],
                    "pos": [round(x, 3), round(z, 3)], "y": height(plan, x, z), "radius": radius,
                    "rotation": round(rule_rng.uniform(0, 360), 1) if rule.get("random_rotation", True) else 0.0,
                    "scale": round(rule_rng.uniform(*rule.get("scale_range", [1.0, 1.0])), 3),
                    "collision": rule.get("collision", "static"), "source": f"scatter[{rule_index}]"}
            if max_slope is not None:
                item["max_slope_deg"] = float(max_slope)
            if "blocks_sight" in rule:
                item["blocks_sight"] = bool(rule["blocks_sight"])
            placed.append(item)
            index.add(item)
            count += 1
        report.append({"asset": rule["asset"], "requested": target, "placed": count, "attempts": attempts,
                       "rejected": dict(rejected)})
    resolved = {key: value for key, value in plan.items() if key not in ("obstacles", "scatter")}
    resolved.update({"resolved": True, "placements": placed, "generation": report,
                     "source_plan": {"seed": plan.get("seed", 0), "scatter": plan.get("scatter", []),
                                     "obstacles": plan.get("obstacles", [])}})
    return resolved


# ---------------------------------------------------------------- validation

def blocked_grid(plan: dict, placements: list[dict],
                 inflate: float | None = None) -> tuple[list[list[bool]], float]:
    x0, z0, x1, z1 = bounds(plan)
    cell = setting(plan, "cell_size")
    inflate = setting(plan, "player_radius") if inflate is None else inflate
    columns, rows = max(1, int(math.ceil((x1 - x0) / cell))), max(1, int(math.ceil((z1 - z0) / cell)))
    grid = [[False] * columns for _ in range(rows)]
    for item in placements:
        if item.get("collision", "static") not in ("static", "destructible"):
            continue
        cx, cz, reach = item["pos"][0], item["pos"][1], float(item.get("radius", 0.5)) + inflate
        for row in range(max(0, int((cz - reach - z0) / cell)), min(rows, int((cz + reach - z0) / cell) + 1)):
            for column in range(max(0, int((cx - reach - x0) / cell)), min(columns, int((cx + reach - x0) / cell) + 1)):
                if math.hypot(x0 + (column + 0.5) * cell - cx, z0 + (row + 0.5) * cell - cz) < reach:
                    grid[row][column] = True
    walkable_slope = (plan.get("terrain") or {}).get("max_walkable_slope_deg")
    if walkable_slope is not None and (plan.get("terrain") or {}).get("type", "flat") != "flat":
        for row in range(rows):
            for column in range(columns):
                if slope_deg(plan, x0 + (column + 0.5) * cell, z0 + (row + 0.5) * cell, cell) > walkable_slope:
                    grid[row][column] = True
    for blocker in plan.get("blockers", []):  # walls/water as axis-aligned boxes
        (bx0, bz0), (bx1, bz1) = blocker["min"], blocker["max"]
        for row in range(rows):
            for column in range(columns):
                x, z = x0 + (column + 0.5) * cell, z0 + (row + 0.5) * cell
                if bx0 - inflate <= x <= bx1 + inflate and bz0 - inflate <= z <= bz1 + inflate:
                    grid[row][column] = True
    return grid, cell


def to_cell(plan: dict, pos: list, cell: float) -> tuple[int, int]:
    x0, z0, _, _ = bounds(plan)
    return int((pos[1] - z0) / cell), int((pos[0] - x0) / cell)


def flood(grid: list[list[bool]], start: tuple[int, int]) -> set[tuple[int, int]]:
    rows, columns = len(grid), len(grid[0])
    if not (0 <= start[0] < rows and 0 <= start[1] < columns) or grid[start[0]][start[1]]:
        return set()
    seen, queue = {start}, deque([start])
    while queue:
        row, column = queue.popleft()
        for dr, dc in ((1, 0), (-1, 0), (0, 1), (0, -1)):
            nxt = (row + dr, column + dc)
            if 0 <= nxt[0] < rows and 0 <= nxt[1] < columns and nxt not in seen and not grid[nxt[0]][nxt[1]]:
                seen.add(nxt)
                queue.append(nxt)
    return seen


def nearest_free(grid, cell_index, reach_cells: int) -> list[tuple[int, int]]:
    row, column = cell_index
    return [(r, c) for r in range(row - reach_cells, row + reach_cells + 1)
            for c in range(column - reach_cells, column + reach_cells + 1)
            if 0 <= r < len(grid) and 0 <= c < len(grid[0]) and not grid[r][c]]


def validate(plan: dict) -> dict:
    checks: list[dict] = []

    def record(name: str, ok: bool, detail: str) -> None:
        checks.append({"check": name, "status": "PASS" if ok else "FAIL", "detail": detail})

    x0, z0, x1, z1 = bounds(plan)
    # Landmarks with a mesh are solid unless marked otherwise.
    structures = [dict(item, collision=item.get("collision", "static"))
                  for item in plan.get("landmarks", []) if item.get("asset")]
    placements = plan.get("placements", []) + structures
    record("resolved", bool(plan.get("resolved")), "run `generate` first" if not plan.get("resolved") else "ok")
    record("bounds", x1 > x0 and z1 > z0, f"{x1 - x0:.1f} x {z1 - z0:.1f} m")

    outside = [p["id"] for p in placements
               if not (x0 <= p["pos"][0] <= x1 and z0 <= p["pos"][1] <= z1)]
    outside += [item["id"] for group in ("spawns", "objectives")
                for item in plan.get(group, []) if not (x0 <= item["pos"][0] <= x1 and z0 <= item["pos"][1] <= z1)]
    record("inside_bounds", not outside, f"outside: {outside[:10]}" if outside else "all inside")

    collidable = [p for p in placements if p.get("collision", "static") in ("static", "destructible")]
    overlaps = []
    index = SpatialHash(2.0)
    largest = max([float(p.get("radius", 0.5)) for p in collidable] + [0.5])
    for a in collidable:
        for b in index.near(a["pos"][0], a["pos"][1], float(a.get("radius", 0.5)) + largest):
            gap = math.hypot(a["pos"][0] - b["pos"][0], a["pos"][1] - b["pos"][1])
            if gap < float(a.get("radius", 0.5)) + float(b.get("radius", 0.5)) - 1e-6:
                overlaps.append(f"{b['id']}~{a['id']}")
        index.add(a)
    record("no_overlap", not overlaps, f"{len(overlaps)} overlaps: {overlaps[:8]}" if overlaps else "none")

    spawn_hits = [f"{p['id']}@{s['id']}" for s in plan.get("spawns", []) for p in collidable
                  if math.hypot(p["pos"][0] - s["pos"][0], p["pos"][1] - s["pos"][1])
                  < float(p.get("radius", 0.5)) + setting(plan, "spawn_clearance")]
    record("spawn_clearance", not spawn_hits, f"blocked: {spawn_hits[:8]}" if spawn_hits else "clear")

    path_hits = [f"{p['id']}@{path['id']}" for path in plan.get("paths", []) for p in collidable
                 if path_distance(p["pos"][0], p["pos"][1], path) < path.get("width", 2.0) / 2 + float(p.get("radius", 0.5))]
    record("paths_clear", not path_hits, f"blocked: {path_hits[:8]}" if path_hits else "clear")

    grid, cell = blocked_grid(plan, placements)
    spawns = plan.get("spawns", [])
    record("has_spawn", bool(spawns), f"{len(spawns)} spawn(s)")
    reachable: set[tuple[int, int]] = set()
    for spawn in spawns:
        reachable |= flood(grid, to_cell(plan, spawn["pos"], cell))
    if spawns:
        record("spawn_walkable", bool(reachable), "spawn cell is free" if reachable else "spawn is inside an obstacle")
    targets = [*plan.get("objectives", []), *[l for l in plan.get("landmarks", []) if l.get("interactive")]]
    unreachable = []
    for target in targets:
        reach = int(math.ceil((float(target.get("radius", 0.5)) + setting(plan, "player_radius")) / cell)) + 1
        if not any(cell_index in reachable for cell_index in nearest_free(grid, to_cell(plan, target["pos"], cell), reach)):
            unreachable.append(target["id"])
    record("objectives_reachable", not unreachable,
           f"unreachable: {unreachable}" if unreachable else f"{len(targets)} reachable")

    area = (x1 - x0) * (z1 - z0)
    density = len(placements) / area * 100 if area > 0 else 0
    budgets = plan.get("budgets", {})
    max_instances = budgets.get("max_instances")
    record("instance_budget", max_instances is None or len(placements) <= max_instances,
           f"{len(placements)} instances (budget {max_instances}), {density:.2f} per 100 m^2")
    per_asset = Counter(p.get("asset") for p in placements)
    max_per_asset = budgets.get("max_per_asset")
    over = {asset: n for asset, n in per_asset.items() if max_per_asset and n > max_per_asset}
    record("per_asset_budget", not over, f"over budget: {over}" if over else dict(per_asset).__repr__())

    shortfall = [g for g in plan.get("generation", []) if g["placed"] < g["requested"]]
    record("scatter_complete", not shortfall,
           "; ".join(f"{g['asset']} {g['placed']}/{g['requested']}" for g in shortfall) or "all placed")

    repetition = budgets.get("max_same_asset_within_5m")
    if repetition:
        crowded = []
        for item in placements:
            near = sum(1 for other in placements if other["asset"] == item["asset"]
                       and math.hypot(other["pos"][0] - item["pos"][0], other["pos"][1] - item["pos"][1]) <= 5.0)
            if near > repetition:
                crowded.append(item["id"])
        record("repetition", not crowded, f"{len(crowded)} crowded instances" if crowded else "varied")

    if plan.get("exclusions"):
        intruders = [f"{p['id']}@{zone}" for p in collidable
                     if (zone := in_exclusion(plan, p["pos"][0], p["pos"][1], float(p.get("radius", 0.5))))]
        record("exclusions_clear", not intruders, f"inside: {intruders[:8]}" if intruders else "clear")

    steep = [f"{p['id']}={slope_deg(plan, *p['pos']):.0f}deg" for p in plan.get("placements", [])
             if p.get("max_slope_deg") is not None and slope_deg(plan, *p["pos"]) > p["max_slope_deg"] + 1e-6]
    if plan.get("terrain") and (plan["terrain"].get("type", "flat") != "flat"):
        floating = [p["id"] for p in plan.get("placements", [])
                    if abs(float(p.get("y", 0.0)) - height(plan, *p["pos"])) > 0.05]
        record("on_terrain", not floating, f"not on ground: {floating[:8]}" if floating else "all grounded")
        record("slope", not steep, f"too steep: {steep[:8]}" if steep else "within limits")

    enemy_spawns = plan.get("enemy_spawns", [])
    if enemy_spawns:
        enemy_grid, _ = blocked_grid(plan, placements, setting(plan, "enemy_radius"))
        player_cells = set()
        for spawn in spawns:
            player_cells |= flood(enemy_grid, to_cell(plan, spawn["pos"], cell))
        stranded = []
        for enemy in enemy_spawns:
            region = flood(enemy_grid, to_cell(plan, enemy["pos"], cell))
            if not region or not (region & player_cells):
                stranded.append(enemy["id"])
        record("enemy_navigation", not stranded and bool(player_cells),
               f"cannot reach the player: {stranded}" if stranded else
               f"{len(enemy_spawns)} enemy spawn(s) connected (radius {setting(plan, 'enemy_radius')} m)")

    sight_blockers = [p for p in collidable if p.get("blocks_sight", True)]
    blocked_lines = []
    for line in plan.get("sightlines", []):
        segment = {"points": [line["from"], line["to"]]}
        hits = [p["id"] for p in sight_blockers if path_distance(p["pos"][0], p["pos"][1], segment)
                < float(p.get("radius", 0.5))]
        if hits:
            blocked_lines.append(f"{line['id']} by {hits[:3]}")
    if plan.get("sightlines"):
        record("sightlines", not blocked_lines, "; ".join(blocked_lines) or f"{len(plan['sightlines'])} clear")

    zone_problems = []
    for zone in plan.get("combat_zones", []):
        cells = [(r, c) for r in range(len(grid)) for c in range(len(grid[0]))
                 if math.hypot(x0 + (c + 0.5) * cell - zone["center"][0],
                               z0 + (r + 0.5) * cell - zone["center"][1]) <= zone["radius"]]
        covered = sum(1 for r, c in cells if grid[r][c]) / max(1, len(cells))
        if covered > zone.get("max_cover_ratio", 0.35):
            zone_problems.append(f"{zone['id']} cover {covered:.0%} > {zone.get('max_cover_ratio', 0.35):.0%}")
        if covered < zone.get("min_cover_ratio", 0.0):
            zone_problems.append(f"{zone['id']} cover {covered:.0%} < {zone['min_cover_ratio']:.0%}")
        if not any(cell_index in reachable for cell_index in cells):
            zone_problems.append(f"{zone['id']} unreachable")
    if plan.get("combat_zones"):
        record("combat_zones", not zone_problems, "; ".join(zone_problems) or
               f"{len(plan['combat_zones'])} zone(s) within cover limits and reachable")

    components = 0
    free = {(r, c) for r in range(len(grid)) for c in range(len(grid[0])) if not grid[r][c]}
    islands = []
    while free:
        region = flood(grid, next(iter(free)))
        free -= region
        components += 1
        islands.append(len(region))

    status = "PASS" if all(check["status"] == "PASS" for check in checks) else "FAIL"
    return {"status": status, "checks": checks,
            "metrics": {"instances": len(placements), "area_m2": area, "density_per_100m2": round(density, 2),
                        "walkable_cells": len(reachable), "per_asset": dict(per_asset),
                        "walkable_regions": components,
                        "largest_unreached_region_cells": max([n for n in islands if n != len(reachable)] or [0])}}


def ascii_map(plan: dict, width: int = 64) -> str:
    x0, z0, x1, z1 = bounds(plan)
    height = max(8, int(width * (z1 - z0) / (x1 - x0) / 2))
    canvas = [["." for _ in range(width)] for _ in range(height)]

    def put(pos, char):
        column = int((pos[0] - x0) / (x1 - x0) * (width - 1))
        row = int((pos[1] - z0) / (z1 - z0) * (height - 1))
        if 0 <= row < height and 0 <= column < width:
            canvas[row][column] = char

    for path in plan.get("paths", []):
        points = path["points"]
        for a, b in zip(points, points[1:]):
            for step in range(41):
                put([a[0] + (b[0] - a[0]) * step / 40, a[1] + (b[1] - a[1]) * step / 40], "=")
    for item in plan.get("placements", []):
        put(item["pos"], item.get("asset", "?").removeprefix("sm_")[:1].lower() or "#")
    for item in plan.get("landmarks", []):
        put(item["pos"], "L")
    for item in plan.get("objectives", []):
        put(item["pos"], "O")
    for item in plan.get("spawns", []):
        put(item["pos"], "S")
    legend = "S spawn, O objective, L landmark, = path, letters = first letter of asset"
    return "\n".join("".join(row) for row in canvas) + "\n" + legend


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)
    gen = sub.add_parser("generate", help="resolve scatter rules into placements")
    gen.add_argument("plan", type=Path)
    gen.add_argument("--out", type=Path, required=True)
    val = sub.add_parser("validate", help="check a resolved plan")
    val.add_argument("plan", type=Path)
    val.add_argument("--report", type=Path)
    val.add_argument("--map", action="store_true", help="print an ASCII top-down map")
    args = parser.parse_args(argv)
    try:
        plan = load(args.plan)
    except (OSError, json.JSONDecodeError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2
    if args.command == "generate":
        if args.out.exists() and args.out.resolve() == args.plan.resolve():
            print("ERROR: --out must differ from the authored plan", file=sys.stderr)
            return 2
        resolved = generate(plan)
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(json.dumps(resolved, indent=2) + "\n", encoding="utf-8")
        for item in resolved["generation"]:
            print(f"SCATTER {item['asset']} placed={item['placed']}/{item['requested']}")
        print(f"WORLD_PLAN_RESOLVED={args.out} placements={len(resolved['placements'])}")
        return 0
    if not plan.get("resolved") and plan.get("scatter"):
        plan = generate(plan)
    result = validate(plan)
    for check in result["checks"]:
        print(f"{check['status']:4} {check['check']}: {check['detail']}")
    if args.map:
        print(ascii_map(plan))
    if args.report:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(f"WORLD_PLAN_CHECK={result['status']}")
    return 0 if result["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
