#!/usr/bin/env python3
"""Adopt an existing Godot project into an LopoDev project context.

The game files are never copied, moved, or edited. LopoDev adds only its own
context files under ``projects/<slug>/`` and points ``project.json`` at the
existing Godot directory. Refuses to overwrite an existing project context.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import pipeline_state as state  # noqa: E402

SLUG_RE = re.compile(r"^[a-z][a-z0-9_]*$")
MAIN_SCENE_RE = re.compile(r'^run/main_scene="?([^"\n]+)"?', re.MULTILINE)
NAME_RE = re.compile(r'^config/name="?([^"\n]+)"?', re.MULTILINE)
RENDERER_RE = re.compile(r'^renderer/rendering_method="?([^"\n]+)"?', re.MULTILINE)
FEATURES_RE = re.compile(r'^config/features=PackedStringArray\(([^)]*)\)', re.MULTILINE)


def read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except OSError:
        return ""


def parse_project_godot(godot_dir: Path) -> dict:
    path = godot_dir / "project.godot"
    text = read_text(path)
    if not text:
        raise ValueError(f"not a readable Godot project (missing project.godot): {godot_dir}")
    main = MAIN_SCENE_RE.search(text)
    name = NAME_RE.search(text)
    renderer = RENDERER_RE.search(text)
    features = FEATURES_RE.search(text)
    feature_values = []
    if features:
        feature_values = [part.strip().strip('"') for part in features.group(1).split(",")
                          if part.strip()]
    version = "4.6.1"
    for value in feature_values:
        if re.fullmatch(r"\d+\.\d+(?:\.\d+)?", value):
            version = value
    return {
        "name": name.group(1) if name else godot_dir.name,
        "main_scene": main.group(1) if main else "",
        "renderer": renderer.group(1) if renderer else "gl_compatibility",
        "features": feature_values,
        "engine_version": version,
    }


def scan_files(godot_dir: Path, project_dir: Path) -> dict:
    scenes = sorted(str(p.relative_to(godot_dir)) for p in godot_dir.rglob("*.tscn")
                    if ".godot" not in p.parts and ".pipeline" not in p.parts)
    scripts = sorted(str(p.relative_to(godot_dir)) for p in godot_dir.rglob("*.gd")
                     if ".godot" not in p.parts and ".pipeline" not in p.parts)
    glbs = sorted(godot_dir.rglob("*.glb"))
    models = []
    for glb in glbs:
        meta = glb.with_suffix(".meta.json")
        info = {"id": glb.stem, "path": str(glb), "bytes": glb.stat().st_size}
        if meta.is_file():
            try:
                payload = json.loads(meta.read_text())
                info["animated"] = bool(payload.get("animated", False))
                mesh = payload.get("mesh", {})
                info["triangles"] = mesh.get("triangles")
                info["license"] = payload.get("license", "recorded-in-meta")
            except (OSError, json.JSONDecodeError):
                info["meta_error"] = "unreadable meta sidecar"
        models.append(info)
    return {"scenes": scenes, "scripts": scripts, "models": models}


def assets_from_models(models: list[dict]) -> list[dict]:
    assets = []
    for model in models:
        asset_id = model["id"]
        if not asset_id.startswith("sm_"):
            asset_id = f"sm_{asset_id}"
        assets.append({
            "id": asset_id,
            "kind": "imported-existing",
            "source": "existing-project",
            "license": model.get("license", "verify-in-ASSET_LICENSES.md"),
            "budget_triangles": model.get("triangles") or 6000,
            "animated": bool(model.get("animated", False)),
            "brief": f"Existing GLB adopted in place at {model['path']}.",
        })
    return assets


def adoption_report(slug: str, title: str, godot_dir: Path, parsed: dict,
                    files: dict, project_dir: Path) -> str:
    models = files["models"]
    lines = [
        f"# Adoption Report - {title}",
        "",
        f"- Slug: `{slug}`",
        f"- Godot directory (unchanged): `{godot_dir}`",
        f"- Context directory: `{project_dir}`",
        f"- Engine from project.godot: `{parsed['engine_version']}`",
        f"- Renderer: `{parsed['renderer']}`",
        f"- Main scene: `{parsed['main_scene'] or '(not declared)'}`",
        f"- Scenes found: {len(files['scenes'])}",
        f"- GDScript files found: {len(files['scripts'])}",
        f"- GLB models found: {len(models)}",
        "",
        "## Models",
        "",
    ]
    if models:
        lines += ["| Asset | Bytes | Triangles | Animated |", "|---|---:|---:|---|"]
        for model in models:
            lines.append(f"| `{model['id']}` | {model['bytes']} | "
                         f"{model.get('triangles', '?')} | {model.get('animated', '?')} |")
    else:
        lines.append("No GLB files were found. Record scene-authored geometry manually.")
    lines += [
        "",
        "## Files created by LopoDev",
        "",
        "- `project.json` - machine-readable context and ownership",
        "- `GAME_SPEC.md` - adoption draft to complete before Gate A",
        "- `ASSET_LICENSES.md` - license registry (existing entries preserved)",
        "- `pipeline_state.json` - approval and task state",
        "- `docs/ADOPTION_REPORT.md` - this report",
        "",
        "## Safety",
        "",
        "No game source, scene, script, asset or build output was copied, moved,",
        "edited, or deleted. LopoDev references the Godot project in place.",
        "",
        "## Next safe step",
        "",
        "Run the baseline content/runtime checks, complete `GAME_SPEC.md`, then",
        "propose Gate A. Do not claim mobile readiness from desktop checks.",
        "",
    ]
    return "\n".join(lines)


def spec_draft(title: str, slug: str, parsed: dict, files: dict) -> str:
    scene = parsed["main_scene"] or "res://scenes/Main.tscn"
    return f"""# {title} - Game Specification

Status: adoption-draft
Slug: `{slug}`
Target: existing Godot project, engine {parsed['engine_version']}, renderer {parsed['renderer']}
First milestone: verified baseline without modifying existing gameplay

## Existing project

- Godot directory (outside LopoDev context): `{parsed.get('godot_dir', '')}`
- Main scene: `{scene}`
- Scenes found: {len(files['scenes'])}
- Scripts found: {len(files['scripts'])}
- GLB models found: {len(files['models'])}

## Player fantasy and core loop

<Capture the current loop from the project and owner confirmation. Do not invent
one from file names.>

## Scope

Must have for the adoption baseline:

- Content gate passes on the existing main scene.
- Runtime smoke processes real frames with an observed game-specific assertion.
- Graphical screenshot is produced and inspected.
- Existing release workflow is re-run or explicitly recorded as NOT RUN.

Explicit non-goals:

- No unrelated refactor, art replacement, or mechanic change during adoption.
- No mobile readiness claim unless an Android export and device check ran.

## Controls

<Record the actual input actions parsed from project.godot or scripts.>

## Scene and flow

- Main scene: `{scene}`
- Start state: <record>
- Win condition: <record>
- Lose/restart condition: <record>

## Assets

| ID | Kind | Source | Triangles | Animated | Notes |
|---|---|---|---|---|---|
{chr(10).join(f"| `{m['id']}` | imported-existing | existing-project | {m.get('triangles', '?')} | {'yes' if m.get('animated') else 'no'} | {m['path']} |" for m in files['models']) or '| none found | - | - | - | - | - |'}

## Technical constraints

- Preserve the existing engine version and renderer unless an approved task changes them.
- Existing asset licenses must be verified in `ASSET_LICENSES.md`.
- One script per system; do not merge systems during adoption.

## Milestones and tasks

| ID | Task | Owner | Verification | Status |
|---|---|---|---|---|
| T1 | Inventory scenes, scripts, assets, input actions and owners | level-design | adoption report reviewed | planned |
| T2 | Run content and runtime baseline without changing game code | qa-release | validate.sh, smoke.sh | planned |
| T3 | Produce and inspect a real screenshot | qa-release | screenshot.sh + image inspection | planned |
| T4 | Re-run release export or record it NOT RUN with a reason | qa-release | export_build.sh | planned |
| T5 | Define the first approved feature or fix | game-design | GAME_SPEC.md reviewed | planned |

## Acceptance criteria

| ID | Criterion | Gate | Evidence |
|---|---|---|---|
| A1 | Existing main scene loads and contains expected nodes | content | `artifacts/qa_report.json` |
| A2 | Runtime processes real frames and asserts a game-specific behavior | runtime | `artifacts/qa_report.json` |
| A3 | Graphical screenshot exists and was inspected | visual | `artifacts/screenshots/baseline.png` |
| A4 | Release workflow result is PASS or explicitly NOT RUN | build | `artifacts/qa_report.json` |
| A5 | No existing source file changed during adoption | manual | `docs/ADOPTION_REPORT.md` |

## Assumptions and open questions

- The existing project may have no GLB assets; scene-authored geometry is valid.
- Mobile tooling is checked separately; desktop success is not mobile evidence.
"""


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--godot-dir", required=True,
                        help="existing Godot project directory (read-only)")
    parser.add_argument("--project", required=True,
                        help="LopoDev context directory, e.g. projects/my_game")
    parser.add_argument("--slug", required=True)
    parser.add_argument("--title", required=True)
    parser.add_argument("--workspace", default=None)
    args = parser.parse_args(argv)

    if not SLUG_RE.match(args.slug):
        print("ERROR: slug must be lowercase snake_case starting with a letter", file=sys.stderr)
        return 2
    if not args.title.strip():
        print("ERROR: title must be non-empty", file=sys.stderr)
        return 2
    godot_dir = Path(args.godot_dir).expanduser().resolve()
    project_dir = Path(args.project).expanduser().resolve()
    state_file = project_dir / state.STATE_FILENAME
    if state_file.exists() or (project_dir / "project.json").exists():
        print(f"ERROR: LopoDev context already exists; refusing to overwrite: {project_dir}",
              file=sys.stderr)
        return 2
    try:
        parsed = parse_project_godot(godot_dir)
    except ValueError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2
    parsed["godot_dir"] = str(godot_dir)
    files = scan_files(godot_dir, project_dir)

    project_dir.mkdir(parents=True, exist_ok=True)
    (project_dir / "docs").mkdir(exist_ok=True)
    (project_dir / "artifacts").mkdir(exist_ok=True)
    (project_dir / "artifacts" / "logs").mkdir(exist_ok=True)

    if args.workspace:
        workspace = Path(args.workspace).expanduser().resolve()
    elif project_dir.parent.name == "projects":
        workspace = project_dir.parent.parent
    else:
        workspace = project_dir
    try:
        godot_setting = str(godot_dir.relative_to(workspace))
    except ValueError:
        godot_setting = str(godot_dir)

    assets = assets_from_models(files["models"])
    main_scene = parsed["main_scene"] or (
        f"res://{files['scenes'][0]}" if files["scenes"] else "res://scenes/Main.tscn")
    project_json = {
        "schema_version": 1,
        "slug": args.slug,
        "title": args.title.strip(),
        "summary": f"Adopted existing Godot project ({parsed['engine_version']}); baseline must be verified before changes.",
        "status": "adoption_pending",
        "genre": "existing-project",
        "target_platform": "linux-x86_64",
        "engine": {
            "name": "godot",
            "version": parsed["engine_version"],
            "renderer": parsed["renderer"],
        },
        "blender": {"version": "not-used-unless-assets-change"},
        "godot_dir": godot_setting,
        "main_scene": main_scene,
        "adoption": {
            "source_godot_dir": str(godot_dir),
            "adopted_at_utc": state.utc_now(),
            "source_unchanged": True,
            "scenes": files["scenes"],
            "scripts": files["scripts"],
        },
        "assets": assets,
        "tasks": [
            {
                "id": "T1",
                "title": "Inventory scenes, scripts, assets and ownership",
                "owner": "level-design",
                "skills": ["game-world"],
                "depends_on": [],
                "verify": "review docs/ADOPTION_REPORT.md",
                "status": "planned",
            },
            {
                "id": "T2",
                "title": "Run content and runtime baseline without changing game code",
                "owner": "qa-release",
                "skills": ["game-qa"],
                "depends_on": ["T1"],
                "verify": "tools/godot/validate.sh and tools/godot/smoke.sh",
                "status": "planned",
            },
            {
                "id": "T3",
                "title": "Produce and inspect a real graphical screenshot",
                "owner": "qa-release",
                "skills": ["game-qa"],
                "depends_on": ["T2"],
                "verify": "tools/godot/screenshot.sh",
                "status": "planned",
            },
            {
                "id": "T4",
                "title": "Re-run release export or record NOT RUN with a reason",
                "owner": "qa-release",
                "skills": ["game-qa"],
                "depends_on": ["T2"],
                "verify": "tools/godot/export_build.sh",
                "status": "planned",
            },
            {
                "id": "T5",
                "title": "Define the first approved feature or fix",
                "owner": "game-design",
                "skills": ["game-planner"],
                "depends_on": ["T1"],
                "verify": "GAME_SPEC.md reviewed at Gate A",
                "status": "planned",
            },
        ],
        "acceptance": [
            {"id": "A1", "criterion": "Existing main scene loads and contains expected nodes.",
             "gate": "content", "evidence": "artifacts/qa_report.json"},
            {"id": "A2", "criterion": "Runtime processes real frames and asserts a game-specific behavior.",
             "gate": "runtime", "evidence": "artifacts/qa_report.json"},
            {"id": "A3", "criterion": "Graphical screenshot exists and was inspected.",
             "gate": "visual", "evidence": "artifacts/screenshots/baseline.png"},
            {"id": "A4", "criterion": "Release workflow is PASS or explicitly NOT RUN.",
             "gate": "build", "evidence": "artifacts/qa_report.json"},
            {"id": "A5", "criterion": "No existing source file changed during adoption.",
             "gate": "manual", "evidence": "docs/ADOPTION_REPORT.md"},
        ],
        "known_limitations": [
            "Adoption baseline has not been run yet.",
            "Mobile SDK, device and performance checks are not implied by desktop checks.",
            "Existing assets require independent license verification.",
        ],
    }
    (project_dir / "project.json").write_text(
        json.dumps(project_json, indent=2) + "\n", encoding="utf-8")
    (project_dir / "GAME_SPEC.md").write_text(
        spec_draft(args.title.strip(), args.slug, {**parsed, "godot_dir": str(godot_dir)}, files),
        encoding="utf-8")
    licenses = project_dir / "ASSET_LICENSES.md"
    if not licenses.exists():
        licenses.write_text(
            "# Asset Licenses\n\n"
            "Existing-project assets are referenced in place. Verify every\n"
            "third-party asset and record source, license and attribution here\n"
            "before release. Procedural assets generated in-repo are repo-owned.\n",
            encoding="utf-8")
    (project_dir / "docs" / "ADOPTION_REPORT.md").write_text(
        adoption_report(args.slug, args.title.strip(), godot_dir, parsed, files, project_dir),
        encoding="utf-8")

    data = state.new_state(args.slug, args.title.strip(), str(workspace), str(project_dir))
    data["recovery"]["next_step"] = (
        "Review docs/ADOPTION_REPORT.md, run baseline content/runtime checks, "
        "complete GAME_SPEC.md, then propose Gate A.")
    data["tasks"] = [
        {
            "id": task["id"],
            "title": task["title"],
            "status": task["status"],
            "owner": task["owner"],
            "skills": task["skills"],
            "depends_on": task["depends_on"],
            "acceptance": task["verify"],
            "evidence": [],
            "changed_files": [],
            "issues": [],
            "note": "",
            "updated_at_utc": state.utc_now(),
        }
        for task in project_json["tasks"]
    ]
    state.save_state(str(project_dir), data)
    event_path = project_dir / "artifacts" / "events.jsonl"
    if not event_path.exists():
        event_path.write_text(json.dumps({
            "ts_utc": state.utc_now(),
            "event": "project_adopted",
            "status": "created",
            "command": "tools/adopt_project.py",
            "message": f"Adopted existing Godot project at {godot_dir}; source unchanged.",
        }, sort_keys=True) + "\n", encoding="utf-8")

    print(f"ADOPTED_PROJECT={args.slug}")
    print(f"GODOT_DIR_UNCHANGED={godot_dir}")
    print(f"PROJECT_JSON={project_dir / 'project.json'}")
    print(f"GAME_SPEC={project_dir / 'GAME_SPEC.md'}")
    print(f"REPORT={project_dir / 'docs' / 'ADOPTION_REPORT.md'}")
    print(f"STATE={state_file}")
    print("NEXT=run baseline checks, complete the spec, then propose Gate A")
    return 0


if __name__ == "__main__":
    sys.exit(main())
