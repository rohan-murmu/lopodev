#!/usr/bin/env python3
"""Render the LopoDev Homebrew formula.

Two modes, both deterministic and free of machine-specific paths:

  --head-only                       formula with only `head` (works before any
                                    release: `brew install --HEAD ...`)
  --version V --archive-file F      stable formula for an exact release archive;
                                    the SHA-256 is computed from F, never typed

`--url` overrides the release URL (local validation with file:// archives).
No version, URL, checksum, or project license is assumed by this helper.
"""

from __future__ import annotations

import argparse
import hashlib
import re
import sys
from pathlib import Path

SHA_RE = re.compile(r"^[0-9a-f]{64}$")
VERSION_RE = re.compile(r"^\d+\.\d+\.\d+(?:[-+][A-Za-z0-9.-]+)?$")
HOMEPAGE = "https://github.com/rohan-murmu/lopodev"
PYTHON = "python@3.13"
LIBEXEC_FILES = ('"AGENTS.md", "README.md", "LICENSE", "VERSION", "opencode.json",\n'
                 '                    "bin", "tools", "templates", "resources", "adapters", "docs"')


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def release_url(version: str) -> str:
    return f"{HOMEPAGE}/releases/download/v{version}/lopodev-{version}.tar.gz"


def render(version: str | None, sha256: str | None, license_id: str, url: str | None = None) -> str:
    """A stable formula when version/sha256 are given, else a HEAD-only one."""
    if not re.fullmatch(r"[A-Za-z0-9.-]+", license_id):
        raise ValueError("license must be a valid SPDX identifier")
    if version is not None:
        if not VERSION_RE.fullmatch(version):
            raise ValueError("version must be a semantic version")
        if not sha256 or not SHA_RE.fullmatch(sha256):
            raise ValueError("sha256 must be the 64-character lowercase digest of that archive")
        source = (f'  url "{url or release_url(version)}"\n'
                  f'  version "{version}"\n'
                  f'  sha256 "{sha256}"\n')
    else:
        source = ""
    return f'''# typed: strict
# frozen_string_literal: true

# Formula for the LopoDev game-development workflow toolkit.
class Lopodev < Formula
  desc "Agent workflow toolkit for building mobile games with Blender and Godot"
  homepage "{HOMEPAGE}"
{source}  license "{license_id}"
  head "{HOMEPAGE}.git", branch: "main"

  depends_on "{PYTHON}"

  def install
    libexec.install {LIBEXEC_FILES}
    # Stable opt/ paths keep workspaces and agent configs valid across upgrades.
    (bin/"lopodev").write <<~SH
      #!/bin/bash
      export LOPODEV_HOME="#{{opt_libexec}}"
      export LOPODEV_LAUNCHER="#{{opt_bin}}/lopodev"
      exec "#{{formula_opt_bin("{PYTHON}")}}/python{PYTHON.split("@")[1]}" "#{{opt_libexec}}/tools/lopodev_cli.py" "$@"
    SH
  end

  def caveats
    <<~EOS
      Install the pinned Blender MCP, Godot MCP, Code Map and vendored skills
      for your user, then wire LopoDev into a workspace:
        lopodev setup
        lopodev install opencode --project /path/to/workspace
        lopodev doctor --project /path/to/workspace

      Your knowledge base and integrations live in ${{XDG_DATA_HOME:-~/.local/share}}/lopodev
      and your games live in your workspaces; upgrading or uninstalling
      LopoDev never deletes either.
    EOS
  end

  test do
    assert_match "lopodev", shell_output("#{{bin}}/lopodev --version")
    assert_match "install", shell_output("#{{bin}}/lopodev --help")
    ENV["LOPODEV_DATA"] = testpath/"data"
    ENV["LOPODEV_NO_INTEGRATIONS"] = "1"
    assert_match "KNOWLEDGE_VALIDATE=PASS", shell_output("#{{bin}}/lopodev knowledge validate")
    plan = libexec/"templates/world_plan.json"
    assert_match "WORLD_PLAN_CHECK=PASS", shell_output("#{{bin}}/lopodev world validate #{{plan}}")
    system bin/"lopodev", "new", "--workspace", testpath/"ws", "--slug", "brew_test", "--title", "Brew Test"
    assert_path_exists testpath/"ws/projects/brew_test/pipeline_state.json"
    assert_path_exists testpath/"ws/.opencode/agents/lopodev.md"
  end
end
'''


def check(path: Path, license_id: str) -> list[str]:
    """Compare a committed formula with what this generator renders for it."""
    text = path.read_text(encoding="utf-8")
    version = re.search(r'^  version "([^"]+)"', text, re.MULTILINE)
    sha = re.search(r'^  sha256 "([0-9a-f]{64})"', text, re.MULTILINE)
    url = re.search(r'^  url "([^"]+)"', text, re.MULTILINE)
    if version and sha:
        expected = render(version.group(1), sha.group(1), license_id,
                          None if url and url.group(1) == release_url(version.group(1)) else
                          (url.group(1) if url else None))
    else:
        expected = render(None, None, license_id)
    if text == expected:
        return []
    import difflib
    return list(difflib.unified_diff(expected.splitlines(), text.splitlines(),
                                     "generated", str(path), lineterm=""))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--head-only", action="store_true", help="render a HEAD-only formula")
    mode.add_argument("--version", help="release version (with --archive-file)")
    mode.add_argument("--check", type=Path, metavar="FORMULA",
                      help="fail if FORMULA differs from the generator's output")
    parser.add_argument("--archive-file", type=Path, help="downloaded exact release archive to hash")
    parser.add_argument("--url", help="override the release URL (e.g. file:// for local validation)")
    parser.add_argument("--license", required=True, dest="license_id")
    parser.add_argument("--output", type=Path)
    parser.add_argument("--force", action="store_true", help="replace an existing formula file")
    args = parser.parse_args(argv)
    if args.check:
        problems = check(args.check, args.license_id)
        for line in problems:
            print(line)
        print(f"FORMULA_CHECK={'FAIL' if problems else 'PASS'} {args.check}")
        return 1 if problems else 0
    if args.output is None:
        parser.error("--output is required")
    checksum = None
    try:
        if args.version:
            if args.archive_file is None or not args.archive_file.is_file():
                raise ValueError(f"archive file does not exist: {args.archive_file}")
            if args.archive_file.name != f"lopodev-{args.version}.tar.gz":
                raise ValueError("archive filename must match the release asset name: lopodev-<version>.tar.gz")
            checksum = sha256_file(args.archive_file)
        formula = render(args.version, checksum, args.license_id, args.url)
    except ValueError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2
    if args.output.exists() and not args.force:
        print(f"ERROR: refusing to overwrite {args.output} (pass --force for a release update)",
              file=sys.stderr)
        return 2
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(formula, encoding="utf-8")
    print(f"FORMULA_WRITTEN={args.output}")
    if checksum:
        print(f"ARCHIVE_SHA256={checksum}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
