# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License.
"""Process-wide bounded execution for blocking I/O."""

import os
from collections.abc import Callable, Iterable
from concurrent.futures import (
    FIRST_COMPLETED,
    Future,
    ThreadPoolExecutor,
    wait,
)
from threading import current_thread
from typing import TypeVar

_MAX_CONFIGURED_WORKERS = 64

InputT = TypeVar("InputT")
OutputT = TypeVar("OutputT")


def validate_worker_count(value: int, name: str = "max_workers") -> int:
    """Validate a worker count before constructing or scheduling a pool."""
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f"{name} must be an integer")
    if not 1 <= value <= _MAX_CONFIGURED_WORKERS:
        raise ValueError(
            f"{name} must be between 1 and {_MAX_CONFIGURED_WORKERS}"
        )
    return value


def configured_worker_count(name: str, default: int) -> int:
    """Read and validate a worker count from the process environment."""
    raw_value = os.environ.get(name)
    if raw_value is None:
        return validate_worker_count(default, name)
    try:
        value = int(raw_value)
    except ValueError as error:
        raise ValueError(f"{name} must be an integer") from error
    return validate_worker_count(value, name)


class BoundedExecutor:
    """Share one thread budget across all concurrent map operations."""

    def __init__(self, max_workers: int) -> None:
        self.max_workers = validate_worker_count(max_workers)
        self._thread_prefix = f"haste-io-{id(self):x}"
        self._executor = ThreadPoolExecutor(
            max_workers=self.max_workers,
            thread_name_prefix=self._thread_prefix,
        )

    def map(
        self,
        function: Callable[[InputT], OutputT],
        values: Iterable[InputT],
        max_workers: int | None = None,
    ) -> list[OutputT]:
        """Run an ordered map with bounded submissions and shared workers."""
        items = list(values)
        if not items:
            return []

        requested_workers = (
            self.max_workers
            if max_workers is None
            else validate_worker_count(max_workers)
        )
        worker_count = min(requested_workers, self.max_workers, len(items))
        if worker_count == 1 or current_thread().name.startswith(
            self._thread_prefix
        ):
            return [function(item) for item in items]

        indexed_items = iter(enumerate(items))
        pending: dict[Future[OutputT], int] = {}
        results: dict[int, OutputT] = {}

        def submit_next() -> bool:
            try:
                index, item = next(indexed_items)
            except StopIteration:
                return False
            pending[self._executor.submit(function, item)] = index
            return True

        for _ in range(worker_count):
            submit_next()

        try:
            while pending:
                done, _ = wait(pending, return_when=FIRST_COMPLETED)
                for future in done:
                    index = pending.pop(future)
                    results[index] = future.result()
                for _ in done:
                    submit_next()
        except Exception:
            for future in pending:
                future.cancel()
            raise

        return [results[index] for index in range(len(items))]

    def shutdown(self) -> None:
        """Release worker threads after a non-global executor is finished."""
        self._executor.shutdown(wait=True, cancel_futures=True)


PARALLEL_IO_EXECUTOR = BoundedExecutor(
    configured_worker_count("HASTE_BLOB_DOWNLOAD_WORKERS", 16)
)


def parallel_map(
    function: Callable[[InputT], OutputT],
    values: Iterable[InputT],
    max_workers: int | None = None,
) -> list[OutputT]:
    """Map blocking I/O on the shared process-wide executor."""
    return PARALLEL_IO_EXECUTOR.map(function, values, max_workers=max_workers)
