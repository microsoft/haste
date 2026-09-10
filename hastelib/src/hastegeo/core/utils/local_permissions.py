# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License.

import argparse
import os
import stat
from pathlib import Path

from .logs import Logger

LOCAL_TASK_ROOT = Path("/shared/azurite/task_work")


def prepare_local_task_permissions(
    work_dir: Path,
    *,
    owner_uid: int,
    workspace_root: Path = LOCAL_TASK_ROOT,
) -> None:
    """Allow another local worker UID to read and remove completed outputs."""
    relative = work_dir.relative_to(workspace_root)
    if len(relative.parts) != 2 or ".." in relative.parts:
        raise ValueError("Expected one local job/task directory")
    resolved_root = workspace_root.resolve(strict=True)
    resolved_task = work_dir.resolve(strict=True)
    if resolved_task.relative_to(resolved_root) != relative:
        raise ValueError("Local task directory cannot traverse symlinks")
    if not resolved_task.is_dir():
        raise ValueError("Local task workspace must be a directory")

    def on_error(error: OSError) -> None:
        raise error

    for directory, _, filenames in os.walk(
        resolved_task, followlinks=False, onerror=on_error
    ):
        paths = [Path(directory)]
        paths.extend(Path(directory) / name for name in filenames)
        for path in paths:
            attributes = path.lstat()
            if attributes.st_uid != owner_uid:
                continue
            mode = attributes.st_mode
            if stat.S_ISDIR(mode):
                required = stat.S_IRWXG | stat.S_IRWXO
            elif stat.S_ISREG(mode):
                required = stat.S_IRGRP | stat.S_IROTH
            else:
                continue
            updated = stat.S_IMODE(mode) | required
            if updated != stat.S_IMODE(mode):
                path.chmod(updated, follow_symlinks=False)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Prepare a completed local task for cross-UID finalization"
    )
    parser.add_argument("work_dir", type=Path)
    args = parser.parse_args()
    if os.name != "posix":
        parser.error("Local container permissions require POSIX")
    try:
        prepare_local_task_permissions(args.work_dir, owner_uid=os.getuid())
    except (OSError, ValueError) as error:
        Logger.get_logger(__name__).error(
            "Local task permission preparation failed (%s)",
            type(error).__name__,
        )
        raise SystemExit(1) from None


if __name__ == "__main__":
    main()
