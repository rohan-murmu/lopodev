#!/usr/bin/env python3
"""Validate a pipeline project.json specification without third-party deps."""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

KNOWN_SKILLS = {
    # First-draft skills, still the domain procedures used by LopoDev.
    "game-planner",
    "blender-modeling",
    "blender-animation",
    "game-world",
    "godot-gameplay",
    "game-qa",
    # LopoDev shared procedures.
    "mobile-game",
    "mobile-low-poly",  # pre-0.3 name of mobile-game, kept for old specs
    "lopodev-workflow",
    "asset-intelligence",
}
try:
    # Vendored skills installed by `lopodev setup` are valid task skills too.
    KNOWN_SKILLS |= {skill for pack in json.loads(
        (Path(__file__).resolve().parent.parent / "resources/integrations.json").read_text()
    )["skill_packs"].values() for skill in pack["skills"]}
except (OSError, json.JSONDecodeError, KeyError):
    pass
KNOWN_GATES = {"generation", "asset", "import", "content", "runtime", "visual", "build",
               "android", "manual"}
SCREEN_KINDS = {"menu", "select", "settings", "gameplay", "overlay", "result", "loading"}
CONTROL_TYPES = {"joystick", "dpad", "button", "look-drag", "tap", "swipe", "drag", "pinch", "hold"}
CONTINUOUS_CONTROLS = {"joystick", "dpad", "look-drag", "drag", "pinch"}
NAV_SPECIAL = {"@back", "@quit"}
ORIENTATIONS = {"portrait", "landscape", "sensor"}
TASK_STATUS = {
    "planned", "in_progress", "blocked", "needs_approval", "verified", "failed",
    # Legacy first-draft values kept for existing projects such as crystal_test.
    "pending", "complete",
}
SLUG_RE = re.compile(r"^[a-z][a-z0-9_]*$")
ASSET_ID_RE = re.compile(r"^(sm_|mat_|rig_|anim_|sfx_|tex_)[a-z0-9_]+$")


def check(condition: bool, message: str, errors: list[str]) -> None:
    if not condition:
        errors.append(message)


def validate(data: dict, project_dir: Path | None = None) -> list[str]:
    errors: list[str] = []

    for key in ("schema_version", "slug", "title", "summary", "status", "target_platform"):
        check(key in data, f"missing top-level field: {key}", errors)
    check(data.get("schema_version") == 1, "schema_version must be 1", errors)
    slug = data.get("slug", "")
    check(isinstance(slug, str) and bool(SLUG_RE.match(slug)),
          "slug must be lowercase snake_case starting with a letter", errors)
    check(isinstance(data.get("title"), str) and bool(data.get("title", "").strip()),
          "title must be non-empty", errors)
    check(isinstance(data.get("summary"), str) and bool(data.get("summary", "").strip()),
          "summary must be non-empty", errors)

    engine = data.get("engine")
    check(isinstance(engine, dict), "engine must be an object", errors)
    if isinstance(engine, dict):
        check(engine.get("name") == "godot", "engine.name must be 'godot'", errors)
        check(isinstance(engine.get("version"), str) and bool(engine.get("version")),
              "engine.version must be non-empty", errors)

    blender = data.get("blender")
    check(isinstance(blender, dict) and isinstance(blender.get("version"), str),
          "blender.version must be a non-empty object field", errors)

    main_scene = data.get("main_scene", "")
    check(isinstance(main_scene, str) and main_scene.startswith("res://")
          and main_scene.endswith(".tscn"),
          "main_scene must be a res:// path ending in .tscn", errors)

    assets = data.get("assets")
    adoption = data.get("adoption")
    if isinstance(adoption, dict):
        check(isinstance(assets, list), "assets must be a list", errors)
    else:
        check(isinstance(assets, list) and len(assets) > 0,
              "assets must be a non-empty list", errors)
    asset_ids: set[str] = set()
    if isinstance(assets, list):
        for index, asset in enumerate(assets):
            prefix = f"assets[{index}]"
            if not isinstance(asset, dict):
                errors.append(f"{prefix} must be an object")
                continue
            asset_id = asset.get("id")
            check(isinstance(asset_id, str) and bool(ASSET_ID_RE.match(asset_id)),
                  f"{prefix}.id must match sm_/mat_/rig_/anim_/sfx_/tex_ naming", errors)
            if isinstance(asset_id, str):
                check(asset_id not in asset_ids, f"duplicate asset id: {asset_id}", errors)
                asset_ids.add(asset_id)
            if asset.get("source") in ("discover", "custom", "derived") or ("class" in asset and "source" not in asset):
                # Discovery entries are requirements; license and budgets are resolved by
                # `lopodev assets` and recorded in the asset manifest, not guessed here.
                sys.path.insert(0, str(Path(__file__).resolve().parent))
                import asset_requirements
                for error in asset_requirements.validate_requirement(asset_requirements.normalize(asset)):
                    errors.append(f"{prefix}: {error}")
                continue
            for key in ("kind", "source", "license"):
                check(isinstance(asset.get(key), str) and bool(asset.get(key)),
                      f"{prefix}.{key} must be non-empty", errors)
            budget = asset.get("budget_triangles")
            check(isinstance(budget, int) and 1 <= budget <= 500000,
                  f"{prefix}.budget_triangles must be 1..500000", errors)
            check(isinstance(asset.get("animated"), bool),
                  f"{prefix}.animated must be boolean", errors)
            if asset.get("source") not in ("procedural", "generated-in-repo"):
                check(bool(asset.get("license")) and asset.get("license") != "unknown",
                      f"{prefix} external asset needs a real license", errors)

    tasks = data.get("tasks")
    check(isinstance(tasks, list) and len(tasks) > 0, "tasks must be a non-empty list", errors)
    task_ids: set[str] = set()
    dependencies: dict[str, list[str]] = {}
    if isinstance(tasks, list):
        for index, task in enumerate(tasks):
            prefix = f"tasks[{index}]"
            if not isinstance(task, dict):
                errors.append(f"{prefix} must be an object")
                continue
            task_id = task.get("id")
            check(isinstance(task_id, str) and bool(task_id), f"{prefix}.id required", errors)
            if isinstance(task_id, str):
                check(task_id not in task_ids, f"duplicate task id: {task_id}", errors)
                task_ids.add(task_id)
            check(isinstance(task.get("title"), str) and bool(task.get("title")),
                  f"{prefix}.title must be non-empty", errors)
            skills = task.get("skills")
            check(isinstance(skills, list) and len(skills) > 0,
                  f"{prefix}.skills must be a non-empty list", errors)
            if isinstance(skills, list):
                for skill in skills:
                    check(skill in KNOWN_SKILLS, f"{prefix} unknown skill: {skill}", errors)
            deps = task.get("depends_on")
            check(isinstance(deps, list), f"{prefix}.depends_on must be a list", errors)
            if isinstance(deps, list) and isinstance(task_id, str):
                dependencies[task_id] = [d for d in deps if isinstance(d, str)]
            check(isinstance(task.get("verify"), str) and bool(task.get("verify")),
                  f"{prefix}.verify must name a command or check", errors)
            check(task.get("status") in TASK_STATUS,
                  f"{prefix}.status must be one of {sorted(TASK_STATUS)}", errors)

    for task_id, deps in dependencies.items():
        for dep in deps:
            check(dep in task_ids, f"task {task_id} depends on unknown task {dep}", errors)

    visiting: set[str] = set()
    visited: set[str] = set()

    def visit(node: str) -> None:
        if node in visited:
            return
        if node in visiting:
            errors.append(f"dependency cycle involving task {node}")
            return
        visiting.add(node)
        for dep in dependencies.get(node, []):
            visit(dep)
        visiting.discard(node)
        visited.add(node)

    for task_id in dependencies:
        visit(task_id)

    acceptance = data.get("acceptance")
    check(isinstance(acceptance, list) and len(acceptance) > 0,
          "acceptance must be a non-empty list", errors)
    acceptance_ids: set[str] = set()
    if isinstance(acceptance, list):
        for index, item in enumerate(acceptance):
            prefix = f"acceptance[{index}]"
            if not isinstance(item, dict):
                errors.append(f"{prefix} must be an object")
                continue
            item_id = item.get("id")
            check(isinstance(item_id, str) and bool(item_id), f"{prefix}.id required", errors)
            if isinstance(item_id, str):
                check(item_id not in acceptance_ids, f"duplicate acceptance id: {item_id}", errors)
                acceptance_ids.add(item_id)
            check(isinstance(item.get("criterion"), str) and bool(item.get("criterion")),
                  f"{prefix}.criterion must be non-empty", errors)
            check(item.get("gate") in KNOWN_GATES,
                  f"{prefix}.gate must be one of {sorted(KNOWN_GATES)}", errors)
            check(isinstance(item.get("evidence"), str) and bool(item.get("evidence")),
                  f"{prefix}.evidence must be a path or description", errors)

    check(isinstance(data.get("known_limitations"), list),
          "known_limitations must be a list", errors)

    errors.extend(validate_design(data))

    if project_dir is not None:
        godot_setting = data.get("godot_dir")
        if isinstance(godot_setting, str) and isinstance(main_scene, str):
            scene_rel = main_scene.removeprefix("res://")
            scene_path = Path(godot_setting) / scene_rel
            if not scene_path.is_absolute():
                scene_path = project_dir.parent.parent / scene_path
            check(scene_path.exists(), f"main_scene file not found: {scene_path}", errors)
            errors.extend(check_engine_orientation(data, _godot_dir(godot_setting, project_dir)))

    return errors


# project.godot window/handheld/orientation (DisplayServer.ScreenOrientation).
GODOT_ORIENTATION = {"0": "landscape", "1": "portrait", "2": "landscape", "3": "portrait",
                     "4": "landscape", "5": "portrait", "6": "sensor"}


def _godot_dir(setting: str, project_dir: Path) -> Path:
    path = Path(setting)
    return path if path.is_absolute() else project_dir.parent.parent / path


def check_engine_orientation(data: dict, godot_dir: Path) -> list[str]:
    """The orientation the game ships with must match the spec."""
    wanted = (data.get("mobile") or {}).get("orientation")
    try:
        text = (godot_dir / "project.godot").read_text(encoding="utf-8")
    except OSError:
        return []
    match = re.search(r"^window/handheld/orientation=(\d+)", text, re.MULTILINE)
    actual = GODOT_ORIENTATION.get(match.group(1) if match else "0", "landscape")
    if wanted in ("landscape", "portrait") and actual != wanted:
        return [f"mobile.orientation is {wanted!r} but project.godot window/handheld/orientation "
                f"ships {actual!r}"]
    return []


def validate_design(data: dict) -> list[str]:
    """Screens, navigation and touch controls.

    Required from design_version 2 (new projects); validated whenever present
    so older specs keep passing until they opt in.
    """
    errors: list[str] = []
    required = data.get("design_version", 1) >= 2
    mobile = data.get("mobile") if isinstance(data.get("mobile"), dict) else {}
    if required:
        for key in ("core_loop", "screens", "navigation"):
            check(key in data, f"design_version 2 requires `{key}`", errors)
        check(isinstance(data.get("core_loop"), str) and len(data.get("core_loop", "")) >= 20,
              "core_loop must describe the repeated player loop in a sentence", errors)
        if mobile.get("touch_input"):
            check("controls" in data, "touch_input projects require a `controls` plan", errors)
            check(mobile.get("orientation") in ORIENTATIONS,
                  f"mobile.orientation must be one of {sorted(ORIENTATIONS)}", errors)

    screens = data.get("screens")
    by_id: dict[str, dict] = {}
    if screens is not None:
        check(isinstance(screens, list) and screens, "screens must be a non-empty list", errors)
        for index, screen in enumerate(screens if isinstance(screens, list) else []):
            prefix = f"screens[{index}]"
            if not isinstance(screen, dict) or not isinstance(screen.get("id"), str):
                errors.append(f"{prefix} must be an object with an id")
                continue
            check(screen["id"] not in by_id, f"duplicate screen id: {screen['id']}", errors)
            check(screen.get("kind") in SCREEN_KINDS,
                  f"{prefix}.kind must be one of {sorted(SCREEN_KINDS)}", errors)
            by_id[screen["id"]] = screen

    navigation = data.get("navigation")
    if navigation is not None and by_id:
        if not isinstance(navigation, dict):
            return errors + ["navigation must be an object"]
        entry = navigation.get("entry")
        check(entry in by_id, f"navigation.entry must be a declared screen (got {entry!r})", errors)
        if entry in by_id and by_id[entry].get("kind") != "menu":
            check(bool(navigation.get("entry_reason")),
                  "entry screen is not a menu; add navigation.entry_reason (the developer asked for it)",
                  errors)
        transitions = navigation.get("transitions")
        check(isinstance(transitions, list) and transitions, "navigation.transitions must be a non-empty list",
              errors)
        outgoing: dict[str, list[dict]] = {screen: [] for screen in by_id}
        for index, edge in enumerate(transitions if isinstance(transitions, list) else []):
            prefix = f"navigation.transitions[{index}]"
            if not isinstance(edge, dict):
                errors.append(f"{prefix} must be an object")
                continue
            source, target = edge.get("from"), edge.get("to")
            check(source in by_id, f"{prefix}.from unknown screen {source!r}", errors)
            check(target in by_id or target in NAV_SPECIAL, f"{prefix}.to unknown screen {target!r}", errors)
            check(isinstance(edge.get("on"), str) and bool(edge.get("on")),
                  f"{prefix}.on must name the control or event that triggers it", errors)
            if source in outgoing:
                outgoing[source].append(edge)
        reachable, frontier = set(), [entry] if entry in by_id else []
        while frontier:
            screen = frontier.pop()
            if screen in reachable:
                continue
            reachable.add(screen)
            frontier.extend(edge["to"] for edge in outgoing.get(screen, []) if edge.get("to") in by_id)
        for screen_id, screen in by_id.items():
            check(screen_id in reachable, f"screen {screen_id} is unreachable from {entry}", errors)
            if screen_id != entry:
                check(bool(outgoing[screen_id]), f"screen {screen_id} is a dead end (no way out)", errors)
            triggers = {edge.get("on") for edge in outgoing[screen_id]}
            for control in screen.get("controls", []):
                check(control in triggers,
                      f"screen {screen_id} control {control!r} has no transition or action", errors)
            if screen.get("kind") == "gameplay" and mobile.get("touch_input"):
                check(any(by_id.get(edge.get("to"), {}).get("kind") == "overlay"
                          for edge in outgoing[screen_id]),
                      f"gameplay screen {screen_id} needs a pause overlay transition", errors)
            if screen.get("kind") == "result":
                check(any(by_id.get(edge.get("to"), {}).get("kind") in {"gameplay", "menu", "select"}
                          for edge in outgoing[screen_id]),
                      f"result screen {screen_id} needs retry or return-to-menu", errors)

    controls = data.get("controls")
    if controls is not None:
        if not isinstance(controls, dict):
            return errors + ["controls must be an object"]
        check(isinstance(controls.get("scheme"), str) and bool(controls.get("scheme")),
              "controls.scheme must name the control layout (e.g. twin-stick, tap, drag)", errors)
        touch = controls.get("touch")
        if mobile.get("touch_input") or touch is not None:
            check(isinstance(touch, list) and touch, "controls.touch must list the touch controls", errors)
        else:
            check(bool(controls.get("keyboard") or controls.get("gamepad")),
                  "desktop controls must list `keyboard` or `gamepad` bindings", errors)
        seen: set[str] = set()
        zones: dict[str, str] = {}
        for index, control in enumerate(touch if isinstance(touch, list) else []):
            prefix = f"controls.touch[{index}]"
            if not isinstance(control, dict):
                errors.append(f"{prefix} must be an object")
                continue
            control_id = control.get("id")
            check(isinstance(control_id, str) and control_id not in seen,
                  f"{prefix}.id must be unique", errors)
            seen.add(str(control_id))
            kind = control.get("type")
            check(kind in CONTROL_TYPES, f"{prefix}.type must be one of {sorted(CONTROL_TYPES)}", errors)
            check(isinstance(control.get("action"), str) and bool(control.get("action")),
                  f"{prefix}.action must name the gameplay action it drives", errors)
            zone = control.get("zone")
            if kind in CONTINUOUS_CONTROLS and isinstance(zone, str):
                check(zone not in zones,
                      f"{prefix} shares zone {zone!r} with {zones.get(zone)}; continuous touch "
                      "controls need separate zones to avoid finger conflicts", errors)
                zones[zone] = str(control_id)
            if kind == "button":
                size = control.get("min_size_dp", 48)
                check(isinstance(size, (int, float)) and size >= 44,
                      f"{prefix}.min_size_dp must be >= 44 for reliable touch", errors)
    return errors


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("project_json", type=Path)
    parser.add_argument("--report", type=Path, help="write JSON validation report")
    parser.add_argument("--no-file-checks", action="store_true",
                        help="skip checking that main_scene exists")
    args = parser.parse_args()

    try:
        data = json.loads(args.project_json.read_text())
    except (OSError, json.JSONDecodeError) as exc:
        print(f"FAIL: cannot read {args.project_json}: {exc}")
        return 2

    project_dir = args.project_json.parent
    errors = validate(data, None if args.no_file_checks else project_dir)
    result = {
        "project": str(args.project_json),
        "slug": data.get("slug"),
        "status": "PASS" if not errors else "FAIL",
        "errors": errors,
        "task_count": len(data.get("tasks", [])) if isinstance(data.get("tasks"), list) else 0,
        "asset_count": len(data.get("assets", [])) if isinstance(data.get("assets"), list) else 0,
        "acceptance_count": len(data.get("acceptance", [])) if isinstance(data.get("acceptance"), list) else 0,
    }
    if args.report:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(json.dumps(result, indent=2) + "\n")

    print(f"SPEC_CHECK={result['status']}")
    print(f"project={result['project']} assets={result['asset_count']} "
          f"tasks={result['task_count']} acceptance={result['acceptance_count']}")
    for error in errors:
        print(f"ERROR: {error}")
    return 0 if not errors else 1


if __name__ == "__main__":
    sys.exit(main())
