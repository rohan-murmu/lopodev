#!/usr/bin/env python3
"""Game Brief: a structured first prompt that gives the planner a complete head start.

  lopodev brief template                      print the fill-in form
  lopodev brief check <brief.md>              missing essentials and contradictions
  lopodev brief scaffold <brief.md> --project projects/<slug> [--force]
                                              seed project.json, world plan and tasks

A brief is `Key: value` lines; a key with an empty value followed by `- item`
lines is a list. Headings, blank lines and `<!-- comments -->` are ignored.
Blank fields are allowed: scaffold fills them from genre defaults and lists
each guess under `assumptions`, so Gate A shows exactly what was invented.
The scaffold is a draft for `game-planner`; it never approves anything.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import asset_requirements  # noqa: E402
import asset_sources  # noqa: E402
import validate_spec  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
TEMPLATE = ROOT / "templates/GAME_BRIEF.md"
REQUIRED = ("genre", "core_loop", "controls", "platform", "win")

ALIASES = {
    "name": "title", "one_line_pitch": "pitch", "pitch": "pitch", "logline": "pitch",
    "reference_games": "references", "references": "references",
    "art_style": "art_style", "style": "art_style", "look": "art_style",
    "theme": "theme", "setting": "theme", "theme_setting": "theme",
    "mood": "mood", "palette": "palette", "camera": "camera", "perspective": "camera",
    "story": "premise", "premise": "premise", "protagonist": "protagonist", "hero": "protagonist",
    "goal": "goal", "antagonist": "antagonist", "villain": "antagonist", "ending": "ending", "tone": "tone",
    "core_loop": "core_loop", "loop": "core_loop",
    "win": "win", "win_condition": "win", "lose": "lose", "lose_condition": "lose", "win_lose": "win_lose",
    "mechanics": "mechanics_must", "must": "mechanics_must", "mechanics_must": "mechanics_must",
    "should": "mechanics_should", "mechanics_should": "mechanics_should",
    "could": "mechanics_could", "mechanics_could": "mechanics_could",
    "progression": "progression", "session_length": "session_length", "session": "session_length",
    "platform": "platform", "platforms": "platform", "orientation": "orientation",
    "controls": "controls", "control_type": "controls", "control": "controls", "actions": "actions",
    "levels": "levels", "areas": "levels", "levels_areas": "levels", "world": "world",
    "environment": "world", "world_size": "world_size", "size": "world_size", "landmarks": "landmarks",
    "enemy_placement": "enemy_placement", "enemies_placement": "enemy_placement",
    "characters": "characters",
    "assets": "assets", "must_have_assets": "assets", "must_have": "assets",
    "asset_edits": "asset_edits", "edits": "asset_edits", "edit_existing": "asset_edits",
    "custom_models": "custom_models", "custom": "custom_models", "asset_sources": "asset_sources",
    "sources": "asset_sources",
    "screens": "screens", "menus": "screens", "music": "music", "sfx": "sfx", "sound_effects": "sfx",
    "scope_v1": "scope_in", "v1_includes": "scope_in", "scope": "scope_in", "includes": "scope_in",
    "v1_excludes": "scope_out", "out_of_scope": "scope_out", "excludes": "scope_out",
    "performance": "performance", "performance_target": "performance", "constraints": "constraints",
    "budget_profile": "budget_profile",
}
LIST_KEYS = {"references", "mechanics_must", "mechanics_should", "mechanics_could", "actions", "landmarks",
             "characters", "assets", "asset_edits", "custom_models", "asset_sources", "screens",
             "scope_in", "scope_out", "constraints", "sfx"}
LINE_RE = re.compile(r"^\s*([A-Za-z][A-Za-z0-9 /&()_-]{0,40}?)\s*:\s*(.*)$")
FIRST_PERSON = ("fps", "first-person", "first person")


def key_of(label: str) -> str:
    normalized = re.sub(r"[^a-z0-9]+", "_", label.lower()).strip("_")
    normalized = re.sub(r"_\(.*", "", normalized)
    return ALIASES.get(normalized, normalized)


def split_items(value: str) -> list[str]:
    parts = re.split(r"\s*[;,]\s*(?![^()]*\))", value)
    return [part.strip() for part in parts if part.strip()]


def parse(text: str) -> dict:
    """Brief text -> dict of canonical keys. Unknown keys are kept under `extra`."""
    text = re.sub(r"<!--.*?-->", "", text, flags=re.DOTALL)
    brief: dict = {}
    current: str | None = None
    for raw in text.splitlines():
        line = raw.rstrip()
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        item = re.match(r"^\s*[-*]\s+(.*)$", line)
        if item and current:
            brief.setdefault(current, [])
            if not isinstance(brief[current], list):
                brief[current] = [brief[current]]
            brief[current].append(item.group(1).strip())
            continue
        match = LINE_RE.match(line)
        if not match:
            continue
        key, value = key_of(match.group(1)), match.group(2).strip()
        current = key
        if not value:
            continue
        brief[key] = split_items(value) if key in LIST_KEYS else value
    if "win_lose" in brief and "win" not in brief:
        win, _, lose = str(brief.pop("win_lose")).partition("/")
        brief["win"], brief["lose"] = win.strip(), lose.strip() or brief.get("lose", "")
    return brief


def lower(brief: dict, key: str) -> str:
    value = brief.get(key, "")
    return " ".join(value).lower() if isinstance(value, list) else str(value).lower()


def platform_of(brief: dict) -> tuple[bool, bool]:
    """(mobile, desktop) targets."""
    text = lower(brief, "platform")
    mobile = any(word in text for word in ("android", "mobile", "phone", "tablet", "ios", "both"))
    desktop = any(word in text for word in ("desktop", "pc", "linux", "windows", "mac", "both", "steam"))
    return mobile, desktop or not mobile


def check(brief: dict) -> dict:
    missing = [key for key in REQUIRED if not brief.get(key)]
    problems = []
    genre, camera, controls = lower(brief, "genre"), lower(brief, "camera"), lower(brief, "controls")
    orientation = lower(brief, "orientation")
    mobile, desktop = platform_of(brief)
    first_person = any(word in f"{genre} {camera}" for word in FIRST_PERSON)
    if first_person and "portrait" in orientation:
        problems.append("first-person games need landscape; portrait leaves no room for move + look")
    if first_person and any(view in camera for view in ("top-down", "isometric", "side")):
        problems.append(f"genre says first-person but camera is {camera!r}")
    if not mobile and any(word in controls for word in ("tilt", "joystick", "touch", "swipe", "tap")):
        problems.append(f"controls {controls!r} are touch/tilt controls but the platform is desktop-only")
    if mobile and not desktop and controls and all(word in controls for word in ("keyboard",)) \
            and not any(word in controls for word in ("joystick", "tap", "swipe", "touch", "tilt", "drag", "button")):
        problems.append("platform is mobile but controls are keyboard-only")
    if brief.get("core_loop") and len(str(brief["core_loop"])) < 12:
        problems.append("core_loop is too short to plan from; describe the repeated actions")
    if brief.get("lose") in (None, "") and brief.get("win"):
        problems.append("no lose condition: say how the player fails, or write `Lose: none` for a relaxing game")
    return {"missing": missing, "contradictions": problems,
            "status": "PASS" if not missing and not problems else "FAIL"}


# ---------------------------------------------------------------- scaffold helpers

def slugify(text: str, prefix: str = "sm_") -> str:
    words = asset_sources.tokens(text)[:4] or ["asset"]
    return prefix + "_".join(words)


def parse_character(text: str) -> dict:
    """'witch (player, idle/run/cast)' or 'spirit: enemy, float, attack, die'."""
    match = re.match(r"^\s*([^(:]+?)\s*[(:]\s*(.*?)\)?\s*$", text)
    name, rest = (match.group(1), match.group(2)) if match else (text, "")
    words = [w.strip().lower() for w in re.split(r"[,/;]", rest) if w.strip()]
    role = next((w for w in words if w in ("player", "enemy", "npc", "boss", "ally", "companion")), "npc")
    actions = []
    for word in words:
        for action in word.replace("animations", "").replace("anims", "").split():
            for canonical, aliases in {"idle": ["idle"], "walk": ["walk"], "run": ["run"],
                                       "jump": ["jump"], "attack": ["attack", "cast", "melee", "slash"],
                                       "shoot": ["shoot", "fire"], "hit": ["hit", "hurt"],
                                       "death": ["death", "die", "dies"], "interact": ["interact", "use"],
                                       "float": ["float", "fly", "hover"]}.items():
                if action in aliases and canonical not in actions:
                    actions.append(canonical)
    if "idle" not in actions:
        actions.insert(0, "idle")
    if role == "enemy" and "death" not in actions:
        actions.append("death")
    return {"name": name.strip(), "role": role, "animations": actions}


def control_plan(brief: dict, mobile: bool, first_person_or_3d: bool) -> tuple[dict, list[str]]:
    controls = lower(brief, "controls")
    actions = [a for a in (brief.get("actions") or []) if a]
    assumed = []
    if not actions:
        named = re.findall(r"\(([^)]*)\)", str(brief.get("controls", "")))
        actions = split_items(named[0]) if named else []
    if not actions:
        actions = ["jump"] if "platform" in lower(brief, "genre") else ["attack"]
        assumed.append(f"actions: {actions} (from genre)")
    plan: dict = {"scheme": str(brief.get("controls") or "virtual-joystick+buttons"), "keyboard_fallback": True}
    if not mobile:
        plan["keyboard"] = [{"key": "WASD", "action": "move"}, {"key": "mouse", "action": "camera_look"}] + \
            [{"key": key, "action": action} for key, action in zip(("Space", "E", "Q", "R", "F"), actions)] + \
            [{"key": "Escape", "action": "pause"}]
        return plan, assumed
    touch: list[dict] = []
    if any(word in controls for word in ("joystick", "stick", "dpad", "move")) or not controls:
        touch.append({"id": "move_stick", "type": "joystick", "action": "move", "zone": "bottom-left"})
        if first_person_or_3d:
            touch.append({"id": "look", "type": "look-drag", "action": "camera_look", "zone": "right"})
    if "swipe" in controls:
        touch.append({"id": "swipe", "type": "swipe", "action": actions[0], "zone": "screen"})
    elif "tap" in controls and not touch:
        touch.append({"id": "tap", "type": "tap", "action": actions[0], "zone": "screen"})
    if "drag" in controls and not any(c["type"] in ("drag", "look-drag") for c in touch):
        touch.append({"id": "drag", "type": "drag", "action": "move", "zone": "left"})
    if "tilt" in controls:
        plan["sensors"] = ["accelerometer"]
    zones = ["bottom-right", "right-middle", "right-upper", "bottom-center", "top-left"]
    used = {c["action"] for c in touch}
    for index, action in enumerate(a for a in actions if a not in used):
        slug = re.sub(r"[^a-z0-9]+", "_", action.lower()).strip("_") or f"action_{index}"
        touch.append({"id": f"{slug}_button", "type": "button", "action": slug,
                      "zone": zones[index % len(zones)], "min_size_dp": 64})
    touch.append({"id": "pause_button", "type": "button", "action": "pause", "zone": "top-right", "min_size_dp": 48})
    plan["touch"] = touch
    plan["knowledge"] = ["godot-mobile-touch-controls", "godot-safe-area"]
    return plan, assumed


def screen_plan(brief: dict) -> tuple[list[dict], dict]:
    extra = [s.lower() for s in (brief.get("screens") or [])]
    screens = [{"id": "main_menu", "kind": "menu", "scene": "res://scenes/ui/MainMenu.tscn",
                "controls": ["play", "settings", "credits", "quit"]},
               {"id": "settings", "kind": "settings", "scene": "res://scenes/ui/Settings.tscn", "controls": ["back"]},
               {"id": "credits", "kind": "settings", "scene": "res://scenes/ui/Credits.tscn", "controls": ["back"]},
               {"id": "game", "kind": "gameplay", "scene": "res://scenes/Main.tscn", "controls": ["pause_button"]},
               {"id": "pause", "kind": "overlay", "scene": "res://scenes/ui/Pause.tscn",
                "controls": ["resume", "restart", "menu"]},
               {"id": "victory", "kind": "result", "scene": "res://scenes/ui/Victory.tscn", "controls": ["retry", "menu"]}]
    transitions = [{"from": "main_menu", "on": "play", "to": "game"},
                   {"from": "main_menu", "on": "settings", "to": "settings"},
                   {"from": "main_menu", "on": "credits", "to": "credits"},
                   {"from": "main_menu", "on": "quit", "to": "@quit"},
                   {"from": "settings", "on": "back", "to": "@back"},
                   {"from": "credits", "on": "back", "to": "@back"},
                   {"from": "game", "on": "pause_button", "to": "pause"},
                   {"from": "game", "on": "goal_complete", "to": "victory"},
                   {"from": "pause", "on": "resume", "to": "@back"},
                   {"from": "pause", "on": "restart", "to": "game"},
                   {"from": "pause", "on": "menu", "to": "main_menu"},
                   {"from": "victory", "on": "retry", "to": "game"},
                   {"from": "victory", "on": "menu", "to": "main_menu"}]
    if lower(brief, "lose") not in ("", "none", "no", "n/a"):
        screens.append({"id": "game_over", "kind": "result", "scene": "res://scenes/ui/GameOver.tscn",
                        "controls": ["retry", "menu"]})
        transitions += [{"from": "game", "on": "player_defeated", "to": "game_over"},
                        {"from": "game_over", "on": "retry", "to": "game"},
                        {"from": "game_over", "on": "menu", "to": "main_menu"}]
    if any("level" in s or "select" in s for s in extra):
        screens.append({"id": "level_select", "kind": "select", "scene": "res://scenes/ui/LevelSelect.tscn",
                        "controls": ["start_level", "back"]})
        transitions += [{"from": "main_menu", "on": "levels", "to": "level_select"},
                        {"from": "level_select", "on": "start_level", "to": "game"},
                        {"from": "level_select", "on": "back", "to": "@back"}]
        screens[0]["controls"].append("levels")
    if any(word in s for s in extra for word in ("shop", "upgrade", "store")):
        screens.append({"id": "upgrades", "kind": "select", "scene": "res://scenes/ui/Upgrades.tscn",
                        "controls": ["back"]})
        transitions += [{"from": "main_menu", "on": "upgrades", "to": "upgrades"},
                        {"from": "upgrades", "on": "back", "to": "@back"}]
        screens[0]["controls"].append("upgrades")
    return screens, {"entry": "main_menu", "router": "godot-screen-router", "transitions": transitions}


def asset_plan(brief: dict, style: list[str]) -> tuple[list[dict], list[dict], list[str]]:
    """(assets, derive edits, assumptions)."""
    assets: dict[str, dict] = {}
    assumed = []
    for text in brief.get("characters") or []:
        character = parse_character(text)
        asset_id = slugify(character["name"])
        # Proper names ("Mira") find nothing; the protagonist line says what she is.
        described = brief.get("protagonist", "") if character["role"] == "player" else ""
        terms = list(dict.fromkeys(t for t in asset_sources.tokens(f"{character['name']} {described}")
                                   if t not in ("a", "an", "the", "young", "old")))[:4] + ["character"]
        assets[asset_id] = {"id": asset_id, "class": "skeletal_character", "source": "discover",
                            "role": f"{character['role']} {character['name']}",
                            "terms": terms,
                            "animations": [a for a in character["animations"]
                                           if a in asset_requirements_actions()],
                            "style": style, "mandatory": character["role"] in ("player", "enemy", "boss")}
    for text in brief.get("assets") or []:
        asset_id = slugify(text)
        assets.setdefault(asset_id, {"id": asset_id, "class": "static_prop", "source": "discover",
                                     "role": text, "terms": asset_sources.tokens(text)[:3], "style": style,
                                     "fallbacks": ["procedural:box"]})
    for text in brief.get("custom_models") or []:
        asset_id = slugify(text)
        assets[asset_id] = {"id": asset_id, "class": "static_prop", "source": "custom", "role": text,
                            "terms": asset_sources.tokens(text)[:3], "style": style, "brief": text}
    edits = []
    for text in brief.get("asset_edits") or []:
        parts = re.split(r"\s*(?:->|→|=>|\binto\b|\bto\b)\s*", text, maxsplit=1)
        source_text, target_text = (parts[0], parts[1]) if len(parts) == 2 else (text, text)
        target_name = re.split(r"\s+(?:with|and|that|which)\s+|,", target_text, maxsplit=1)[0]
        source_id, target_id = slugify(source_text), slugify(target_name)
        if source_id == target_id:
            target_id = f"{source_id}_edited"
        assets.setdefault(source_id, {"id": source_id, "class": "static_prop", "source": "discover",
                                      "role": source_text, "terms": asset_sources.tokens(source_text)[:3],
                                      "style": style, "mandatory": True})
        assets[target_id] = {"id": target_id, "class": "static_prop", "source": "derived",
                             "derive_from": source_id, "role": target_text, "edit_brief": text,
                             "terms": asset_sources.tokens(target_text)[:3], "style": style}
        edits.append({"source": source_id, "target": target_id, "brief": text})
    world_text = " ".join(str(brief.get(key, "")) for key in ("genre", "theme", "world"))
    for suggestion in asset_requirements.suggest(world_text, style):
        if suggestion["id"] not in assets and suggestion["class"] != "skeletal_character":
            suggestion["source"] = "discover"
            suggestion.setdefault("mandatory", False)
            assets[suggestion["id"]] = suggestion
            assumed.append(f"asset {suggestion['id']} suggested from theme/world")
    if not assets:
        assets["sm_goal_marker"] = {"id": "sm_goal_marker", "class": "static_prop", "source": "discover",
                                    "role": "goal marker", "terms": ["flag", "marker"], "style": style,
                                    "fallbacks": ["procedural:cylinder"]}
        assumed.append("asset sm_goal_marker (no assets named in the brief)")
    return list(assets.values()), edits, assumed


def asset_requirements_actions() -> set[str]:
    import asset_rank
    return set(asset_rank.ANIMATION_ALIASES) | {"float"}


def world_seed(brief: dict, assets: list[dict], seed: int) -> dict:
    size = {"small": 30, "medium": 60, "large": 120}.get(lower(brief, "world_size").split(" ")[0], 60)
    half = size / 2
    scatter = []
    for asset in assets:
        if asset["class"] == "procedural_element":
            scatter.append({"asset": asset["id"], "count": int(size * 1.5), "radius": 0.3, "collision": "none",
                            "distribution": "poisson", "avoid": ["spawns", "objectives"]})
        elif asset["class"] == "static_prop" and asset.get("source") == "discover" and \
                any(t in asset["terms"] for t in ("tree", "rock", "bush", "log", "palm", "stone")):
            scatter.append({"asset": asset["id"], "count": int(size * 0.6), "radius": 0.6, "min_spacing": 1.0,
                            "distribution": "poisson", "max_slope_deg": 30})
    enemies = [a for a in assets if a["class"] == "skeletal_character" and "enemy" in a.get("role", "")]
    plan = {"schema_version": 1, "seed": seed, "bounds": {"min": [-half, -half], "max": [half, half]},
            "terrain": {"type": "noise", "amplitude": 1.0, "scale": 16, "max_walkable_slope_deg": 35,
                        "flatten": [{"pos": [0, -half + 4], "radius": 4}]},
            "spawns": [{"id": "player", "pos": [0, -half + 4]}],
            "objectives": [{"id": "goal", "pos": [0, half - 4], "radius": 1.0}],
            "paths": [{"id": "main_path", "points": [[0, -half + 4], [0, half - 4]], "width": 3.0}],
            "scatter": scatter, "budgets": {"max_instances": int(size * 6)},
            "art_direction": " ".join(str(brief.get(k, "")) for k in ("theme", "mood", "palette")).strip()}
    if enemies:
        plan["enemy_spawns"] = [{"id": f"enemy_{i + 1}", "pos": [x, half / 3]}
                                for i, x in enumerate((-half / 2, half / 2))]
    return plan


def scaffold(brief: dict, base: dict, slug: str) -> tuple[dict, dict, list[str]]:
    """Merge the brief into a bootstrap draft. Returns (spec, world plan, assumptions)."""
    assumptions: list[str] = []

    def take(key: str, default, why: str):
        value = brief.get(key)
        if value:
            return value
        assumptions.append(f"{key}: {default!r} ({why})")
        return default

    spec = json.loads(json.dumps(base))
    title = take("title", spec.get("title", slug), "bootstrap title")
    genre = take("genre", "action adventure", "no genre given")
    style_text = take("art_style", "stylized", "no art style given")
    style = [style_text] if isinstance(style_text, str) else list(style_text)
    camera = take("camera", "first-person" if any(w in str(genre).lower() for w in FIRST_PERSON)
                  else "third-person", "from genre")
    mobile, desktop = platform_of(brief)
    if not brief.get("platform"):
        assumptions.append("platform: 'android' (LopoDev default)")
        mobile, desktop = True, False
    orientation = brief.get("orientation") or ("portrait" if any(
        w in str(genre).lower() for w in ("puzzle", "match", "endless", "card")) and "person" not in camera
        else "landscape")
    if not brief.get("orientation") and mobile:
        assumptions.append(f"orientation: {orientation!r} (from genre/camera)")
    win = take("win", "reach the goal", "no win condition given")
    lose = brief.get("lose") or ""
    loop = take("core_loop", f"explore the level, overcome obstacles and {win}", "no core loop given")
    loop_text = loop if isinstance(loop, str) else " -> ".join(loop)
    core_loop = loop_text if len(loop_text) >= 20 else f"The player repeats: {loop_text}; to win, {win}."
    first_person_or_3d = "person" in camera or "3d" in str(genre).lower()
    controls, assumed = control_plan(brief, mobile, first_person_or_3d)
    assumptions += assumed
    screens, navigation = screen_plan(brief)
    assets, edits, assumed = asset_plan(brief, style)
    assumptions += assumed
    seed = int(hashlib.sha256(slug.encode()).hexdigest()[:6], 16)

    spec.update({
        "title": title, "summary": brief.get("pitch") or f"A {style_text} {genre} game.",
        "status": "draft", "genre": genre, "art_style": style_text, "camera": camera,
        "theme": brief.get("theme", ""), "mood": brief.get("mood", ""), "palette": brief.get("palette", ""),
        "story": {key: brief.get(key, "") for key in ("premise", "protagonist", "goal", "antagonist",
                                                    "ending", "tone")},
        "core_loop": core_loop, "win_condition": win, "lose_condition": lose or "none",
        "mechanics": {"must": brief.get("mechanics_must", []), "should": brief.get("mechanics_should", []),
                      "could": brief.get("mechanics_could", [])},
        "progression": brief.get("progression", ""), "session_length": brief.get("session_length", ""),
        "controls": controls, "screens": screens, "navigation": navigation,
        "assets": assets, "audio": {"music": brief.get("music", ""), "sfx": brief.get("sfx", [])},
        "scope": {"v1_includes": brief.get("scope_in", []), "v1_excludes": brief.get("scope_out", []),
                  "performance": brief.get("performance", ""), "constraints": brief.get("constraints", [])},
        "world_plan": f"projects/{slug}/docs/world_plan.json",
        "assumptions": assumptions,
    })
    if brief.get("budget_profile"):
        spec["budget_profile"] = brief["budget_profile"]
    if mobile:
        spec["target_platform"] = "android"
        spec["platforms"] = {"primary": "android", "mobile": "android", "ios": "unverified-path",
                             "desktop_dev": "linux-x86_64", "desktop": desktop}
        spec.setdefault("mobile", {}).update({"orientation": orientation, "touch_input": True,
                                              "renderer": "gl_compatibility"})
        spec["mobile"]["budget"] = {"draw_calls": 150, "triangles_visible": 300000, "texture_max_px": 2048}
    else:
        spec["target_platform"] = "linux-x86_64"
        spec["platforms"] = {"primary": "linux-x86_64", "desktop": True}
        spec.pop("mobile", None)
        spec["engine"] = {**spec.get("engine", {}), "renderer": "forward_plus"}

    godot = f"projects/{slug}/godot"
    t = lambda tid, title, owner, skills, deps, verify: {  # noqa: E731
        "id": tid, "title": title, "owner": owner, "skills": skills, "depends_on": deps,
        "verify": verify, "status": "planned"}
    tasks = [t("T1", "Refine the brief into GAME_SPEC.md and confirm assumptions", "game-design",
               ["game-planner"], [], f"python3 tools/validate_spec.py projects/{slug}/project.json --no-file-checks"),
             t("T2", "Resolve, cache and import the asset list", "modeling", ["asset-intelligence"], ["T1"],
               f"lopodev assets validate --project projects/{slug}")]
    next_id = 3
    for edit in edits:
        tasks.append(t(f"T{next_id}", f"Derive {edit['target']} from {edit['source']}: {edit['brief']}",
                       "modeling", ["asset-intelligence", "blender-modeling"], ["T2"],
                       f"lopodev assets validate --project projects/{slug}"))
        next_id += 1
    asset_tasks = [task["id"] for task in tasks[1:]]
    if any(a["class"] == "skeletal_character" for a in assets):
        tasks.append(t(f"T{next_id}", "Map character animations and prove playback", "animation",
                       ["asset-intelligence", "blender-animation"], ["T2"],
                       f"lopodev assets validate --project projects/{slug} --strict"))
        asset_tasks.append(f"T{next_id}")
        next_id += 1
    world = f"T{next_id}"
    tasks.append(t(world, "Generate and validate the procedural world plan", "level-design", ["game-world"],
                   ["T1"], f"lopodev world validate projects/{slug}/docs/world_plan.resolved.json"))
    scene = f"T{next_id + 1}"
    tasks.append(t(scene, "Assemble the world scene and prove navigation", "level-design", ["game-world"],
                   [world, *asset_tasks], f"TARGET_NODE=Props tools/godot/validate.sh {godot}"))
    loop_task = f"T{next_id + 2}"
    tasks.append(t(loop_task, "Implement the core loop, win and lose", "gameplay", ["godot-gameplay"], [scene],
                   f"tools/godot/smoke.sh {godot}"))
    ui = f"T{next_id + 3}"
    tasks.append(t(ui, "Screens, HUD and controls", "ui", ["mobile-game"] if mobile else ["godot-gameplay"],
                   [loop_task], f"tools/godot/smoke.sh {godot}"))
    tasks.append(t(f"T{next_id + 4}", "QA, export and emulator test", "qa-release", ["game-qa"], [ui],
                   f"python3 tools/qa_report.py validate --project projects/{slug}"))
    spec["tasks"] = tasks
    spec["acceptance"] = [
        {"id": "A1", "criterion": "Every mandatory asset requirement is selected, licensed, imported and validated.",
         "gate": "asset", "evidence": f"projects/{slug}/artifacts/asset_validation.json"},
        {"id": "A2", "criterion": "The world plan validates: objectives reachable, no overlaps, enemies can reach the player.",
         "gate": "content", "evidence": f"projects/{slug}/artifacts/world_plan.report.json"},
        {"id": "A3", "criterion": f"The core loop works at runtime: {core_loop}", "gate": "runtime",
         "evidence": f"projects/{slug}/artifacts/logs/core_loop_test.log"},
        {"id": "A4", "criterion": f"Winning ({win}) shows victory; " + (f"losing ({lose}) shows game over; "
                                                                        if lose and lose.lower() != "none" else "")
         + "retry and menu work.", "gate": "runtime", "evidence": f"projects/{slug}/artifacts/logs/navigation_test.log"},
        {"id": "A5", "criterion": "A graphical screenshot shows the world, characters and HUD in the requested style.",
         "gate": "visual", "evidence": f"projects/{slug}/artifacts/screenshots/main.png"},
    ]
    if mobile:
        spec["acceptance"].append({"id": "A6", "criterion": "The debug APK installs and runs on the Android emulator "
                                   "without crashes; screenshots before and after a tap differ.",
                                   "gate": "android", "evidence": f"projects/{slug}/artifacts/android/"})
    spec["known_limitations"] = ["Draft from the game brief; game-planner refines it before Gate A."]
    return spec, world_seed(brief, assets, seed), assumptions


def write_scaffold(brief_path: Path, project: Path, force: bool = False) -> dict:
    brief = parse(brief_path.read_text(encoding="utf-8"))
    spec_path = project / "project.json"
    base = json.loads(spec_path.read_text(encoding="utf-8"))
    if base.get("status") != "draft" and not force:
        raise ValueError(f"{spec_path} is not a draft (status={base.get('status')!r}); pass --force to overwrite")
    spec, world, assumptions = scaffold(brief, base, base["slug"])
    errors = validate_spec.validate(spec)
    (project / "docs").mkdir(parents=True, exist_ok=True)
    (project / "docs/GAME_BRIEF.md").write_text(brief_path.read_text(encoding="utf-8"), encoding="utf-8")
    world_path = project / "docs/world_plan.json"
    if not world_path.exists() or force:
        world_path.write_text(json.dumps(world, indent=2) + "\n", encoding="utf-8")
    spec_path.write_text(json.dumps(spec, indent=2) + "\n", encoding="utf-8")
    orientation = (spec.get("mobile") or {}).get("orientation")
    godot_file = validate_spec._godot_dir(spec.get("godot_dir", ""), project.resolve()) / "project.godot"
    if orientation and godot_file.is_file():
        text = godot_file.read_text(encoding="utf-8")
        value = {"landscape": "0", "portrait": "1", "sensor": "6"}[orientation]
        updated = re.sub(r"^window/handheld/orientation=\d+", f"window/handheld/orientation={value}", text,
                         flags=re.MULTILINE)
        if updated != text:
            godot_file.write_text(updated, encoding="utf-8")
    return {"project": str(spec_path), "errors": errors, "assumptions": assumptions,
            "assets": len(spec["assets"]), "tasks": len(spec["tasks"]), "world_plan": str(world_path)}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="lopodev brief", description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("template", help="print the fill-in form")
    checker = sub.add_parser("check", help="report missing essentials and contradictions")
    checker.add_argument("brief", type=Path)
    builder = sub.add_parser("scaffold", help="seed project.json and the world plan from a brief")
    builder.add_argument("brief", type=Path)
    builder.add_argument("--project", type=Path, required=True)
    builder.add_argument("--force", action="store_true", help="overwrite a non-draft spec")
    args = parser.parse_args(argv)
    if args.command == "template":
        print(TEMPLATE.read_text(encoding="utf-8"), end="")
        return 0
    try:
        brief = parse(args.brief.read_text(encoding="utf-8"))
        if args.command == "check":
            result = check(brief)
            for key in result["missing"]:
                print(f"MISSING {key}")
            for problem in result["contradictions"]:
                print(f"CONTRADICTION {problem}")
            print(f"BRIEF_CHECK={result['status']} fields={len(brief)}")
            return 0 if result["status"] == "PASS" else 1
        result = check(brief)
        for problem in result["contradictions"]:
            print(f"CONTRADICTION {problem}")
        outcome = write_scaffold(args.brief, args.project, args.force)
    except (OSError, ValueError, KeyError, json.JSONDecodeError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2
    for item in outcome["assumptions"]:
        print(f"ASSUMED {item}")
    for error in outcome["errors"]:
        print(f"SPEC_ERROR {error}")
    print(f"BRIEF_SCAFFOLD={'PASS' if not outcome['errors'] else 'FAIL'} assets={outcome['assets']} "
          f"tasks={outcome['tasks']} world_plan={outcome['world_plan']}")
    return 0 if not outcome["errors"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
