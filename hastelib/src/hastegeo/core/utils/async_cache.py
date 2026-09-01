# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License.
"""Small bounded async cache with per-key single-flight loading."""

import asyncio
import os
import time
from collections import OrderedDict
from collections.abc import Awaitable, Callable
from typing import Generic, TypeVar

KeyT = TypeVar("KeyT")
ValueT = TypeVar("ValueT")


def configured_cache_value(
    name: str, default: int, minimum: int, maximum: int
) -> int:
    """Read a bounded integer cache setting from the environment."""
    raw_value = os.environ.get(name, str(default))
    try:
        value = int(raw_value)
    except ValueError as error:
        raise ValueError(f"{name} must be an integer") from error
    if not minimum <= value <= maximum:
        raise ValueError(f"{name} must be between {minimum} and {maximum}")
    return value


class AsyncTTLCache(Generic[KeyT, ValueT]):
    """Cache successful async loads for a bounded freshness window."""

    def __init__(
        self,
        ttl_seconds: float,
        max_entries: int,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        if ttl_seconds < 0:
            raise ValueError("ttl_seconds cannot be negative")
        if max_entries < 1:
            raise ValueError("max_entries must be positive")
        self.ttl_seconds = ttl_seconds
        self.max_entries = max_entries
        self._clock = clock
        self._entries: OrderedDict[KeyT, tuple[float, ValueT]] = OrderedDict()
        self._inflight: dict[KeyT, asyncio.Task[ValueT]] = {}
        self._lock = asyncio.Lock()

    async def get_or_create(
        self,
        key: KeyT,
        factory: Callable[[], Awaitable[ValueT]],
        refresh: bool = False,
    ) -> tuple[ValueT, bool]:
        """Return ``(value, reused)`` and share one in-flight load per key."""
        async with self._lock:
            cached = None if refresh else self._entries.get(key)
            if cached is not None:
                expires_at, value = cached
                if self._clock() < expires_at:
                    self._entries.move_to_end(key)
                    return value, True
                del self._entries[key]
            elif refresh:
                self._entries.pop(key, None)

            task = None if refresh else self._inflight.get(key)
            reused = task is not None
            if task is None:
                task = asyncio.create_task(factory())
                self._inflight[key] = task
                task.add_done_callback(
                    lambda completed, cache_key=key: asyncio.create_task(
                        self._complete(cache_key, completed)
                    )
                )

        return await asyncio.shield(task), reused

    async def _complete(self, key: KeyT, task: asyncio.Task[ValueT]) -> None:
        async with self._lock:
            if self._inflight.get(key) is not task:
                return
            del self._inflight[key]
            if task.cancelled() or task.exception() is not None:
                return
            self._entries[key] = (
                self._clock() + self.ttl_seconds,
                task.result(),
            )
            self._entries.move_to_end(key)
            while len(self._entries) > self.max_entries:
                self._entries.popitem(last=False)

    async def clear(self) -> None:
        """Clear cached values and cancel unfinished loads."""
        async with self._lock:
            tasks = list(self._inflight.values())
            self._inflight.clear()
            self._entries.clear()
        for task in tasks:
            task.cancel()
