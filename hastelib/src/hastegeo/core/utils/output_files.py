# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License.

"""Open logical outputs relative to a trusted local workspace descriptor."""

import errno
import os
import stat
from contextlib import ExitStack, contextmanager
from dataclasses import dataclass
from pathlib import Path, PurePosixPath, PureWindowsPath
from typing import BinaryIO, Iterator, Optional


class AmbiguousTaskOutputError(ValueError):
    """More than one file matches a logical task output."""


@dataclass(frozen=True)
class _TaskOutput:
    path: PurePosixPath
    attributes: os.stat_result


def _relative_output_path(requested_path: str) -> PurePosixPath:
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
    return relative


def _require_descriptor_support() -> None:
    if not (
        hasattr(os, "O_NOFOLLOW")
        and hasattr(os, "O_DIRECTORY")
        and hasattr(os, "O_NONBLOCK")
        and hasattr(os, "fwalk")
        and os.open in os.supports_dir_fd
        and os.stat in os.supports_dir_fd
        and os.stat in os.supports_follow_symlinks
        and os.listdir in os.supports_fd
    ):
        raise NotImplementedError(
            "Safe local task output reads require descriptor-relative "
            "filesystem APIs; run the local worker on Linux"
        )


@contextmanager
def _directory(
    path: str | Path, *, dir_fd: Optional[int] = None
) -> Iterator[int]:
    try:
        descriptor = os.open(
            path, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=dir_fd
        )
    except OSError as error:
        if error.errno in {errno.ELOOP, errno.ENOTDIR}:
            raise ValueError(
                "Task output directories must not traverse symlinks"
            ) from error
        raise
    try:
        yield descriptor
    finally:
        os.close(descriptor)


@contextmanager
def _parent_directory(task_fd: int, relative: PurePosixPath) -> Iterator[int]:
    with ExitStack() as stack:
        descriptor = task_fd
        for part in relative.parts[:-1]:
            descriptor = stack.enter_context(
                _directory(part, dir_fd=descriptor)
            )
        yield descriptor


def _regular_file(
    directory_fd: int, filename: str
) -> Optional[os.stat_result]:
    try:
        attributes = os.stat(
            filename, dir_fd=directory_fd, follow_symlinks=False
        )
    except FileNotFoundError:
        return None
    if stat.S_ISLNK(attributes.st_mode):
        raise ValueError("Task outputs must not be symlinks")
    return attributes if stat.S_ISREG(attributes.st_mode) else None


def _raise_walk_error(error: OSError) -> None:
    raise error


def _resolve_task_output(
    task_fd: int, relative: PurePosixPath
) -> Optional[_TaskOutput]:
    try:
        with _parent_directory(task_fd, relative) as parent_fd:
            exact = _regular_file(parent_fd, relative.name)
    except FileNotFoundError:
        exact = None
    if exact is not None:
        return _TaskOutput(relative, exact)

    suffix_matches = {}
    prefix_matches = {}
    suffix = "/" + relative.as_posix()
    for directory, _, filenames, directory_fd in os.fwalk(
        ".",
        dir_fd=task_fd,
        follow_symlinks=False,
        onerror=_raise_walk_error,
    ):
        for filename in filenames:
            path = PurePosixPath(directory) / filename
            is_suffix = path.as_posix().endswith(suffix)
            is_prefix = filename.startswith(relative.name)
            if not is_suffix and not is_prefix:
                continue
            attributes = _regular_file(directory_fd, filename)
            if attributes is not None:
                candidate = _TaskOutput(path, attributes)
                if is_suffix:
                    suffix_matches[path] = candidate
                if is_prefix:
                    prefix_matches[path] = candidate
    matches = suffix_matches or prefix_matches
    if len(matches) > 1:
        raise AmbiguousTaskOutputError(
            f"Multiple task outputs match {relative.as_posix()!r}"
        )
    return next(iter(matches.values()), None)


def _open_output(task_fd: int, candidate: _TaskOutput) -> BinaryIO:
    with _parent_directory(task_fd, candidate.path) as parent_fd:
        try:
            descriptor = os.open(
                candidate.path.name,
                os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK,
                dir_fd=parent_fd,
            )
        except OSError as error:
            if error.errno == errno.ELOOP:
                raise ValueError(
                    "Task outputs must not be symlinks"
                ) from error
            raise
        with ExitStack() as ownership:
            ownership.callback(os.close, descriptor)
            current = os.fstat(descriptor)
            if not stat.S_ISREG(current.st_mode) or not os.path.samestat(
                current, candidate.attributes
            ):
                raise ValueError("Task output changed during discovery")
            stream = os.fdopen(descriptor, "rb")
            ownership.pop_all()
            return stream


def open_task_output(
    task_directory: Path, requested_path: str, *, workspace_root: Path
) -> Optional[BinaryIO]:
    """Return an owned binary stream, never a pathname to reopen.

    The configured workspace root and its parents are trusted. Job/task
    ancestry and output paths are opened without following symlinks.
    """
    relative = _relative_output_path(requested_path)
    task_parts = task_directory.relative_to(workspace_root).parts
    if len(task_parts) != 2 or ".." in task_parts:
        raise ValueError("Expected one local job/task directory")
    _require_descriptor_support()
    try:
        with ExitStack() as stack:
            descriptor = stack.enter_context(_directory(workspace_root))
            for part in task_parts:
                descriptor = stack.enter_context(
                    _directory(part, dir_fd=descriptor)
                )
            candidate = _resolve_task_output(descriptor, relative)
            if candidate is None:
                return None
            # Keep the task inode pinned through discovery and the final open.
            return _open_output(descriptor, candidate)
    except FileNotFoundError:
        return None
