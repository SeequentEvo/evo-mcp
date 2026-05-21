# SPDX-FileCopyrightText: 2026 Bentley Systems, Incorporated
#
# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

import re
import sys
from pathlib import Path

PYPI = "https://pypi.org/simple"

_EXCLUDED_DIR_NAMES = frozenset(
    {
        ".git",
        ".tox",
        "__pycache__",
        "build",
        "dist",
        "node_modules",
        "venv",
    }
)

_SOURCE = re.compile(
    r"""
    ^\s*
    source \s* = \s*
    \{ \s* (?P<body>.*?) \s* }
    \s*$
""",
    re.VERBOSE,
)

_ALLOWED = re.compile(
    r"""
    registry \s* = \s* "(?P<registry>[^"]+)"
    | (?:editable|virtual) \s* = \s* "[^"]+"
""",
    re.VERBOSE,
)


def _is_excluded_dir(name: str) -> bool:
    if name in _EXCLUDED_DIR_NAMES:
        return True
    return name.startswith(".") and name not in {".", ".."}


def find_uv_lock_files(root: Path) -> list[Path]:
    """Return all ``uv.lock`` files under ``root``, excluding noise directories.

    Excluded directory names: anything in ``_EXCLUDED_DIR_NAMES`` plus any
    directory whose name starts with ``.`` (e.g. ``.venv``, ``.git``, ``.tox``).
    Results are sorted for deterministic ordering.
    """

    root = root.resolve()
    matches: list[Path] = []

    def walk(directory: Path) -> None:
        try:
            entries = list(directory.iterdir())
        except (PermissionError, FileNotFoundError):
            return
        for entry in entries:
            if entry.is_dir():
                if _is_excluded_dir(entry.name):
                    continue
                walk(entry)
            elif entry.is_file() and entry.name == "uv.lock":
                matches.append(entry)

    walk(root)
    return sorted(matches)


def validate_lock_file(lockfile: Path) -> bool:
    for line in lockfile.read_text(encoding="utf-8").splitlines():
        match = _SOURCE.match(line)
        if match is None:
            continue
        body = match.group("body").strip()
        allowed_match = _ALLOWED.fullmatch(body)
        if allowed_match and (allowed_match.group("registry") is None or allowed_match.group("registry") == PYPI):
            continue
        return False
    return True


def main() -> int:
    lockfiles = find_uv_lock_files(Path.cwd())
    bad_files = [f for f in lockfiles if not validate_lock_file(f)]
    if bad_files:
        print("uv.lock validation failed:", file=sys.stderr)
        for f in bad_files:
            print(f"  {f}", file=sys.stderr)
        return 1
    print(f"Validated {len(lockfiles)} uv.lock file(s).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
