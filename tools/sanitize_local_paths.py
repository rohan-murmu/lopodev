#!/usr/bin/env python3
"""Check or redact absolute developer-local paths in tracked text files."""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
from pathlib import Path

LOCAL_PATH = re.compile(r'''(?<![A-Za-z0-9_])(?:/home/[^\s"'`]+|/Users/[^\s"'`]+|/media/[^\s"'`]+|/tmp/opencode(?:/[^\s"'`]*)?|[A-Za-z]:\\(?:Users|Documents and Settings)\\[^\s"'`]+)''')
LOCAL_PATH_BYTES = re.compile(rb"(?:/home/[^\x00\s\"'`]+|/Users/[^\x00\s\"'`]+|/media/[^\x00\s\"'`]+|/tmp/opencode(?:/[^\x00\s\"'`]*)?|[A-Za-z]:\\(?:Users|Documents and Settings)\\[^\x00\s\"'`]+)")
PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"


def sanitize_text(text: str) -> str:
    return LOCAL_PATH.sub("<LOCAL_PATH>", text)


def sanitize_png(data: bytes) -> tuple[bytes, bool]:
    """Drop PNG text metadata chunks containing local paths; pixel chunks stay byte-identical."""
    if not data.startswith(PNG_SIGNATURE):
        return data, False
    output = bytearray(PNG_SIGNATURE)
    position = len(PNG_SIGNATURE)
    changed = False
    text_chunks = {b"tEXt", b"zTXt", b"iTXt"}
    while position < len(data):
        if position + 12 > len(data):
            raise ValueError("malformed PNG chunk header")
        length = int.from_bytes(data[position:position + 4], "big")
        end = position + 12 + length
        if end > len(data):
            raise ValueError("malformed PNG chunk length")
        chunk_type = data[position + 4:position + 8]
        chunk = data[position:end]
        chunk_data = data[position + 8:position + 8 + length]
        if chunk_type in text_chunks and LOCAL_PATH_BYTES.search(chunk_data):
            changed = True
        else:
            if LOCAL_PATH_BYTES.search(chunk_data):
                raise ValueError(f"local path found in non-text PNG chunk {chunk_type!r}; refusing pixel-data rewrite")
            output.extend(chunk)
        position = end
        if chunk_type == b"IEND":
            output.extend(data[position:])
            break
    return bytes(output), changed


def tracked_files(root: Path) -> list[Path]:
    result = subprocess.run(["git", "-C", str(root), "ls-files", "-z"],
                            capture_output=True, check=True)
    return [root / item.decode("utf-8") for item in result.stdout.split(b"\0") if item]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--check", action="store_true", help="check only (default)")
    parser.add_argument("--apply", action="store_true", help="replace matching paths with <LOCAL_PATH>")
    args = parser.parse_args()
    root = args.root.expanduser().resolve()
    changed: list[Path] = []
    try:
        for path in tracked_files(root):
            try:
                raw = path.read_bytes()
            except OSError:
                continue
            try:
                source = raw.decode("utf-8")
            except UnicodeDecodeError:
                if path.suffix.lower() == ".png":
                    sanitized_png, png_changed = sanitize_png(raw)
                    if png_changed:
                        changed.append(path)
                        if args.apply:
                            path.write_bytes(sanitized_png)
                continue
            sanitized = sanitize_text(source)
            if sanitized != source:
                changed.append(path)
                if args.apply:
                    path.write_text(sanitized, encoding="utf-8")
    except (OSError, ValueError, subprocess.CalledProcessError) as exc:
        print(f"PATH_SANITIZE=ERROR {exc}", file=sys.stderr)
        return 2
    if changed and not args.apply:
        for path in changed:
            print(f"LOCAL_PATH_FOUND={path.relative_to(root)}")
        print("PATH_SANITIZE=FAIL; rerun with --apply to redact tracked text paths")
        return 1
    print(f"PATH_SANITIZE={'APPLIED' if args.apply else 'PASS'} files={len(changed)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
