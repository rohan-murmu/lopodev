#!/usr/bin/env python3
"""Validate Godot knowledge artifacts in a throwaway project.

Copies the kit's GDScript files to res://kit/, the test to res://test.gd,
imports, then runs the test headless. Passes only when the test exits 0,
prints KNOWLEDGE_CHECK=PASS, and Godot logged no SCRIPT ERROR.
"""

from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import integrations  # noqa: E402

PROJECT = """config_version=5

[application]
config/name="lopodev_knowledge_check"

[rendering]
renderer/rendering_method="gl_compatibility"
"""


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base", required=True, help="knowledge store root")
    parser.add_argument("--kit", action="append", required=True,
                        help="artifact directory relative to --base (repeatable)")
    parser.add_argument("--test", required=True, help="test script relative to --base")
    parser.add_argument("--godot", help="Godot executable (default: pinned)")
    parser.add_argument("--timeout", type=int, default=180)
    args = parser.parse_args(argv)
    base = Path(args.base)
    root = Path(__file__).resolve().parent.parent
    godot = args.godot or integrations.pinned_godot(root)
    if not godot:
        print("KNOWLEDGE_CHECK=NOT RUN reason=godot-not-found", file=sys.stderr)
        return 3
    with tempfile.TemporaryDirectory(prefix="lopodev-kcheck-") as temp:
        project = Path(temp)
        (project / "project.godot").write_text(PROJECT, encoding="utf-8")
        kit = project / "kit"
        kit.mkdir()
        for directory in args.kit:
            for script in sorted((base / directory).glob("*.gd")):
                shutil.copy2(script, kit / script.name)
        shutil.copy2(base / args.test, project / "test.gd")
        imported = subprocess.run([godot, "--headless", "--path", str(project), "--import"],
                                  text=True, capture_output=True, timeout=args.timeout, check=False)
        result = subprocess.run([godot, "--headless", "--path", str(project), "--script", "res://test.gd"],
                                text=True, capture_output=True, timeout=args.timeout, check=False)
    output = result.stdout + result.stderr
    print(output)
    errors = [line for line in (imported.stdout + imported.stderr + output).splitlines()
              if "SCRIPT ERROR" in line or line.startswith("ERROR:")]
    passed = result.returncode == 0 and "KNOWLEDGE_CHECK=PASS" in output and not errors
    for line in errors:
        print(f"GODOT_ERROR {line}", file=sys.stderr)
    print(f"GODOT={godot}")
    print(f"KNOWLEDGE_GODOT_CHECK={'PASS' if passed else 'FAIL'} exit={result.returncode}")
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
