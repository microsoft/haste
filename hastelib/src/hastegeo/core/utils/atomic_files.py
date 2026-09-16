# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License.

import errno
import os
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

from .metadata import MetadataUtils

if os.name == "nt":
    import msvcrt
else:
    import fcntl


class LockUnavailableError(TimeoutError):
    """Another process owns the requested filesystem lock."""


@contextmanager
def file_lock(path: Path, timeout: float = 30) -> Iterator[None]:
    """Hold a kernel lock, released even if the owning worker dies."""
    path.parent.mkdir(parents=True, exist_ok=True)
    deadline = time.monotonic() + timeout
    with path.open("a+b") as handle:
        while True:
            handle.seek(0)
            try:
                if os.name == "nt":
                    msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
                else:
                    fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except OSError as error:
                if error.errno not in {
                    errno.EACCES,
                    errno.EAGAIN,
                    errno.EDEADLK,
                }:
                    raise
                if time.monotonic() >= deadline:
                    raise LockUnavailableError(
                        "Filesystem operation is already active"
                    ) from error
                time.sleep(min(0.05, max(0, deadline - time.monotonic())))
        try:
            yield
        finally:
            handle.seek(0)
            if os.name == "nt":
                msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


def atomic_write(path: Path, contents: bytes) -> None:
    """Replace a file without exposing partial contents to readers."""
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(
        f".{path.name}.{MetadataUtils.generate_id()}.tmp"
    )
    try:
        with temporary.open("xb") as handle:
            handle.write(contents)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
        if os.name != "nt":
            directory = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
            try:
                os.fsync(directory)
            finally:
                os.close(directory)
    finally:
        temporary.unlink(missing_ok=True)
