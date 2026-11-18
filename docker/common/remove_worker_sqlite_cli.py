#!/usr/bin/env python3
"""Remove known unused SQLite shell executables from worker images."""

import argparse
import shutil
from pathlib import Path

CLI_PATHS = (
    "opt/miniconda/bin/sqlite3",
    "opt/conda/envs/bda/bin/sqlite3",
    "usr/bin/sqlite3",
    "usr/local/bin/sqlite3",
)


def remove_worker_sqlite_cli(root: Path) -> list[str]:
    if not root.is_absolute():
        raise ValueError("Image root must be absolute")
    root = root.resolve(strict=True)
    removed = []
    for relative in CLI_PATHS:
        path = root / relative
        if not path.parent.resolve().is_relative_to(root):
            raise ValueError(
                f"SQLite shell path escapes image root: {relative}"
            )
        if path.is_symlink() or path.is_file():
            path.unlink()
            removed.append(relative)
        elif path.exists():
            raise ValueError(f"SQLite shell path is not a file: {relative}")
    unexpected = shutil.which("sqlite3")
    if unexpected:
        raise RuntimeError(
            f"An unexpected sqlite3 executable remains on PATH: {unexpected}"
        )
    return removed


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--image-root", type=Path, required=True)
    args = parser.parse_args()
    removed = remove_worker_sqlite_cli(args.image_root)
    print(f"Removed {len(removed)} known SQLite shell executable(s)")


if __name__ == "__main__":
    main()
