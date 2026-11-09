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

    def prepare(path: Path) -> None:
        attributes = path.lstat()
        if attributes.st_uid != owner_uid:
            return
        mode = attributes.st_mode
        if stat.S_ISDIR(mode):
            required = stat.S_IRWXU | stat.S_IRWXG | stat.S_IRWXO
        elif stat.S_ISREG(mode):
            required = stat.S_IRUSR | stat.S_IRGRP | stat.S_IROTH
        else:
            return
        updated = stat.S_IMODE(mode) | required
        if updated == stat.S_IMODE(mode):
            return
        # O_PATH binds the inode without following a final symlink or
        # requiring read permission; procfd avoids optional lchmod support.
        descriptor = os.open(path, os.O_PATH | os.O_NOFOLLOW)
        try:
            current = os.fstat(descriptor)
            if (
                current.st_dev != attributes.st_dev
                or current.st_ino != attributes.st_ino
                or current.st_uid != owner_uid
            ):
                raise ValueError("Local task path changed during preparation")
            os.chmod(f"/proc/self/fd/{descriptor}", updated)
        finally:
            os.close(descriptor)

    prepare(resolved_task)
    for directory, directories, filenames in os.walk(
        resolved_task, followlinks=False, onerror=on_error
    ):
        for name in directories + filenames:
            prepare(Path(directory) / name)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Prepare a completed local task for cross-UID finalization"
    )
    parser.add_argument("work_dir", type=Path)
    args = parser.parse_args()
    if not hasattr(os, "O_PATH"):
        parser.error("Local container permissions require Linux")
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
