#!/usr/bin/env python3
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License.
"""Reject configuration that weakens HASTE GDAL runtime protections."""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
SCAN_ROOTS = ("infra", ".github/workflows", ".github/scripts", "api", "docker")
# This checker contains inert GDAL setting names in an environment drift allowlist.
POLICY_ONLY_FILES = {
    REPO_ROOT / ".github" / "scripts" / "check_env_drift.py",
}
SCAN_SUFFIXES = {
    "",
    ".bicep",
    ".env",
    ".ini",
    ".json",
    ".py",
    ".sh",
    ".toml",
    ".yml",
    ".yaml",
}

_ASSIGNMENT = r"""(?ix)
    (?:
        (?:export|ENV)\s+
        |
        os\.environ(?:\.get)?\s*\[\s*
    )?
    ["']?{key}["']?
    \s*\]?\s*[:=]\s*["']?{value}\b
"""
_CALL = r"""(?ix)
    SetConfigOption\s*\(\s*["']{key}["']\s*,\s*["']?{value}\b
"""
FORBIDDEN_VALUES = {
    "GDAL_VRT_ENABLE_RAWRASTERBAND": r"(?:YES|TRUE|ON|1)",
    "GDAL_VRT_ENABLE_PYTHON": r"(?:YES|TRUE|ON|1)",
    "GDAL_VRT_RAWRASTERBAND_ALLOWED_SOURCE": r"ALL",
    "GDAL_VRT_PYTHON_TRUSTED_MODULES": r"[^'\"\s][^)]*",
    "GDAL_PYTHON_DRIVER_PATH": r"[^'\"\s][^)]*",
    "GDAL_DRIVER_PATH": r"(?!disable\b)[^'\"\s][^)]*",
    "CPL_VSIL_CURL_HEADER_FILE_KVP_ENABLED": (
        r"(?:YES|TRUE|ON|1|ONLY_IN_TEMP)"
    ),
    "CPL_ENABLE_PATH_TRAVERSAL_DETECTION": r"(?:NO|FALSE|OFF|0)",
    "GDAL_HTTP_UNSAFESSL": r"(?:YES|TRUE|ON|1)",
}


def _patterns() -> list[tuple[str, re.Pattern[str]]]:
    patterns = []
    for key, value in FORBIDDEN_VALUES.items():
        patterns.append(
            (key, re.compile(_ASSIGNMENT.format(key=key, value=value)))
        )
        patterns.append((key, re.compile(_CALL.format(key=key, value=value))))
    return patterns


PATTERNS = _patterns()


def _candidate_files(root: Path) -> list[Path]:
    files = []
    for relative_root in SCAN_ROOTS:
        directory = root / relative_root
        if not directory.exists():
            continue
        for path in directory.rglob("*"):
            if not path.is_file() or (
                path.suffix.lower() not in SCAN_SUFFIXES
                and not path.name.startswith("Dockerfile")
            ):
                continue
            if path == Path(__file__).resolve() or path in POLICY_ONLY_FILES:
                continue
            if (
                any(
                    part == "tests" or part.startswith("test_")
                    for part in path.parts
                )
                or "__pycache__" in path.parts
            ):
                continue
            files.append(path)
    return sorted(set(files))


def find_violations(paths: list[Path]) -> list[str]:
    violations = []
    for path in paths:
        try:
            content = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue
        for line_number, line in enumerate(content.splitlines(), start=1):
            for key, pattern in PATTERNS:
                if pattern.search(line):
                    violations.append(
                        f"{path}:{line_number}: forbidden {key} override"
                    )
    return violations


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "paths",
        nargs="*",
        type=Path,
        help="specific files to scan (default: protected configuration roots)",
    )
    args = parser.parse_args(argv)
    paths = args.paths or _candidate_files(REPO_ROOT)
    violations = find_violations(
        [path if path.is_absolute() else REPO_ROOT / path for path in paths]
    )
    if violations:
        print("\n".join(violations), file=sys.stderr)
        return 1
    print(
        f"GDAL hardening configuration is valid ({len(paths)} files scanned)"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
