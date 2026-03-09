#!/usr/bin/env python3

# SPDX-FileCopyrightText: 2026 Bentley Systems, Incorporated
#
# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

import sys
from pathlib import Path

COPYRIGHT_LINE = "# SPDX-FileCopyrightText: 2026 Bentley Systems, Incorporated"
LICENSE_LINE = "# SPDX-License-Identifier: Apache-2.0"
HEADER_LINES = [COPYRIGHT_LINE, "#", LICENSE_LINE]
REPO_ROOT = Path(__file__).resolve().parent.parent
EXCLUDED_PARTS = {".git", ".venv", "__pycache__"}


def iter_python_files(paths: list[str] | None = None) -> list[Path]:
    if paths:
        return [Path(path).resolve() for path in paths if Path(path).suffix == ".py"]

    return sorted(
        path.resolve() for path in REPO_ROOT.rglob("*.py") if not any(part in EXCLUDED_PARTS for part in path.parts)
    )


def has_required_license_header(path: Path) -> bool:
    lines = path.read_text(encoding="utf-8").splitlines()

    start = 0
    if lines and lines[0].startswith("#!"):
        start = 1
        while start < len(lines) and not lines[start].strip():
            start += 1

    header = lines[start : start + 3]
    return header == HEADER_LINES


def add_required_license_header(path: Path) -> bool:
    if has_required_license_header(path):
        return False

    lines = path.read_text(encoding="utf-8").splitlines(keepends=True)
    newline = "\r\n" if any(line.endswith("\r\n") for line in lines) else "\n"

    header_block = [f"{line}{newline}" for line in HEADER_LINES]
    separator = [newline]

    start = 0
    prefix: list[str] = []
    if lines and lines[0].startswith("#!"):
        prefix.append(lines[0])
        start = 1
        while start < len(lines) and not lines[start].strip():
            start += 1
        prefix.append(newline)
    else:
        while start < len(lines) and not lines[start].strip():
            start += 1

    updated = prefix + header_block + separator + lines[start:]
    path.write_text("".join(updated), encoding="utf-8")
    return True


def find_missing_license_headers(paths: list[str] | None = None) -> list[Path]:
    missing: list[Path] = []
    for path in iter_python_files(paths):
        if not path.exists() or any(part in EXCLUDED_PARTS for part in path.parts):
            continue
        if not has_required_license_header(path):
            missing.append(path)
    return missing


def parse_args(argv: list[str] | None = None) -> tuple[bool, list[str]]:
    args = list(argv or [])
    fix = False
    paths: list[str] = []
    for arg in args:
        if arg == "--fix":
            fix = True
            continue
        paths.append(arg)
    return fix, paths


def main(argv: list[str] | None = None) -> int:
    fix, paths = parse_args(argv)
    missing = find_missing_license_headers(paths)
    if not missing:
        return 0

    if fix:
        for path in missing:
            add_required_license_header(path)
        return 0 if not find_missing_license_headers(paths) else 1

    print("Missing required SPDX header in Python files:")
    for path in missing:
        try:
            display_path = path.relative_to(REPO_ROOT)
        except ValueError:
            display_path = path
        print(display_path)
    return 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
