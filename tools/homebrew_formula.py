#!/usr/bin/env python3
"""Render a Homebrew formula from verified release metadata.

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


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def render(version: str, sha256: str, license_id: str) -> str:
    if not VERSION_RE.fullmatch(version):
        raise ValueError("version must be a semantic version")
    if not SHA_RE.fullmatch(sha256):
        raise ValueError("sha256 must be the 64-character lowercase digest of that archive")
    if not re.fullmatch(r"[A-Za-z0-9.-]+", license_id):
        raise ValueError("license must be a valid SPDX identifier")
    homepage = "https://github.com/rohan-murmu/lopodev"
    archive_url = f"{homepage}/releases/download/v{version}/lopodev-{version}.tar.gz"
    return f'''# typed: strict
# frozen_string_literal: true

# Formula for the LopoDev game-development workflow toolkit.
class Lopodev < Formula
  desc "Agent-independent Blender and Godot game-development workflow toolkit"
  homepage "{homepage}"
  url "{archive_url}"
  version "{version}"
  sha256 "{sha256}"
  license "{license_id}"

  depends_on "python@3.12"

  def install
    libexec.install "AGENTS.md", "README.md", "LICENSE", "VERSION", "opencode.json",
                    "tools", "templates", "resources", "adapters", "docs"
    wrapper = bin/"lopodev"
    wrapper.write <<~SH
      #!/bin/bash
      export LOPODEV_HOME="#{{opt_prefix}}/libexec"
      exec "#{{formula_opt_bin("python@3.12")}}/python3.12" "#{{libexec}}/tools/lopodev_cli.py" "$@"
    SH
    wrapper.chmod 0755
  end

  test do
    assert_match "lopodev #{version}", shell_output("#{{bin}}/lopodev --version")
    assert_match "install", shell_output("#{{bin}}/lopodev --help")
    assert_path_exists libexec/"adapters/opencode/agents/lopodev.md"
    assert_path_exists libexec/"resources/skills/game-planner/SKILL.md"
  end
end
'''


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--version", required=True)
    parser.add_argument("--archive-file", type=Path, required=True,
                        help="downloaded exact release archive to hash")
    parser.add_argument("--license", required=True, dest="license_id")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    try:
        if not args.archive_file.is_file():
            raise ValueError(f"archive file does not exist: {args.archive_file}")
        if args.archive_file.name != f"lopodev-{args.version}.tar.gz":
            raise ValueError("archive filename must match the release asset name: lopodev-<version>.tar.gz")
        checksum = sha256_file(args.archive_file)
        formula = render(args.version, checksum, args.license_id)
    except ValueError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2
    args.output.parent.mkdir(parents=True, exist_ok=True)
    if args.output.exists():
        print(f"ERROR: refusing to overwrite {args.output}", file=sys.stderr)
        return 2
    args.output.write_text(formula, encoding="utf-8")
    print(f"FORMULA_WRITTEN={args.output}")
    print(f"ARCHIVE_SHA256={checksum}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
