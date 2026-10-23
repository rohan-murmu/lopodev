#!/usr/bin/env python3
"""Validate a pipeline project.json specification without third-party deps."""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

KNOWN_SKILLS = {
    "game-planner",
    "blender-modeling",
    "blender-animation",
    "game-world",
    "godot-gameplay",
    "game-qa",
}
KNOWN_GATES = {"generation", "asset", "import", "content", "runtime", "visual", "build", "manual"}
TASK_STATUS = {"pending", "in_progress", "complete", "blocked"}
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
    check(isinstance(assets, list) and len(assets) > 0, "assets must be a non-empty list", errors)
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
            for key in ("kind", "source", "license"):
                check(isinstance(asset.get(key), str) and bool(asset.get(key)),
                      f"{prefix}.{key} must be non-empty", errors)
            budget = asset.get("budget_triangles")
            check(isinstance(budget, int) and 1 <= budget <= 100000,
                  f"{prefix}.budget_triangles must be 1..100000", errors)
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

    if project_dir is not None:
        godot_setting = data.get("godot_dir")
        if isinstance(godot_setting, str) and isinstance(main_scene, str):
            scene_rel = main_scene.removeprefix("res://")
            scene_path = Path(godot_setting) / scene_rel
            if not scene_path.is_absolute():
                scene_path = project_dir.parent.parent / scene_path
            check(scene_path.exists(), f"main_scene file not found: {scene_path}", errors)

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
