# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License.

"""Resolve logical output names without searching outside one task."""

import os
from pathlib import Path, PurePosixPath, PureWindowsPath
from typing import Optional


class AmbiguousTaskOutputError(ValueError):
    """More than one file matches a logical task output."""


def resolve_task_output(
    task_directory: Path, requested_path: str
) -> Optional[Path]:
    normalized = requested_path.replace("\\", "/")
    relative = PurePosixPath(normalized)
    if (
        not normalized
        or "\x00" in normalized
        or relative.is_absolute()
        or PureWindowsPath(requested_path).drive
        or ".." in relative.parts
        or relative == PurePosixPath(".")
    ):
        raise ValueError("Task output must be a safe relative path")
    root = task_directory.resolve()
    if not root.is_dir():
        return None

    def checked_file(path: Path) -> Optional[Path]:
        resolved = path.resolve()
        if not resolved.is_relative_to(root):
            raise ValueError("Task output resolves outside its workspace")
        return resolved if resolved.is_file() else None

    exact = checked_file(root.joinpath(*relative.parts))
    if exact is not None:
        return exact

    suffix_matches = set()
    prefix_matches = set()
    suffix = "/" + relative.as_posix()
    for directory, subdirectories, filenames in os.walk(
        root, followlinks=False
    ):
        subdirectories[:] = [
            name
            for name in subdirectories
            if not (Path(directory) / name).is_symlink()
        ]
        for filename in filenames:
            path = Path(directory) / filename
            name = path.relative_to(root).as_posix()
            is_suffix = name.endswith(suffix)
            is_prefix = filename.startswith(relative.name)
            if not is_suffix and not is_prefix:
                continue
            candidate = checked_file(path)
            if candidate is not None:
                if is_suffix:
                    suffix_matches.add(candidate)
                if is_prefix:
                    prefix_matches.add(candidate)
    matches = suffix_matches or prefix_matches
    if len(matches) > 1:
        raise AmbiguousTaskOutputError(
            f"Multiple task outputs match {requested_path!r}"
        )
    return next(iter(matches), None)
