# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License.
import asyncio
import os
import unittest
from unittest.mock import AsyncMock, patch

from hastegeo.core.utils.async_cache import (
    AsyncTTLCache,
    configured_cache_value,
)


class TestConfiguredCacheValue(unittest.TestCase):
    def test_reads_bounded_integer(self) -> None:
        with patch.dict(os.environ, {"TEST_CACHE_VALUE": "12"}):
            self.assertEqual(
                configured_cache_value("TEST_CACHE_VALUE", 5, 0, 20), 12
            )

    def test_rejects_invalid_value(self) -> None:
        for value in ("invalid", "-1", "21"):
            with self.subTest(value=value):
                with patch.dict(os.environ, {"TEST_CACHE_VALUE": value}):
                    with self.assertRaises(ValueError):
                        configured_cache_value("TEST_CACHE_VALUE", 5, 0, 20)


class TestAsyncTTLCache(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.now = 0.0
        self.cache = AsyncTTLCache(
            ttl_seconds=10,
            max_entries=2,
            clock=lambda: self.now,
        )

    async def asyncTearDown(self) -> None:
        await self.cache.clear()

    async def test_reuses_value_before_expiry(self) -> None:
        factory = AsyncMock(return_value="value")

        first, first_reused = await self.cache.get_or_create("key", factory)
        second, second_reused = await self.cache.get_or_create("key", factory)

        self.assertEqual((first, second), ("value", "value"))
        self.assertFalse(first_reused)
        self.assertTrue(second_reused)
        factory.assert_awaited_once_with()

    async def test_reloads_value_after_expiry(self) -> None:
        factory = AsyncMock(side_effect=["first", "second"])
        await self.cache.get_or_create("key", factory)
        self.now = 10

        value, reused = await self.cache.get_or_create("key", factory)

        self.assertEqual(value, "second")
        self.assertFalse(reused)
        self.assertEqual(factory.await_count, 2)

    async def test_refresh_replaces_unexpired_value(self) -> None:
        factory = AsyncMock(side_effect=["first", "second"])
        await self.cache.get_or_create("key", factory)

        refreshed, reused = await self.cache.get_or_create(
            "key", factory, refresh=True
        )
        cached, cached_reused = await self.cache.get_or_create("key", factory)

        self.assertEqual((refreshed, cached), ("second", "second"))
        self.assertFalse(reused)
        self.assertTrue(cached_reused)
        self.assertEqual(factory.await_count, 2)

    async def test_refresh_supersedes_an_older_inflight_load(self) -> None:
        old_started = asyncio.Event()
        old_release = asyncio.Event()

        async def old_factory() -> str:
            old_started.set()
            await old_release.wait()
            return "old"

        old_request = asyncio.create_task(
            self.cache.get_or_create("key", old_factory)
        )
        await old_started.wait()

        refreshed, reused = await self.cache.get_or_create(
            "key", lambda: asyncio.sleep(0, result="new"), refresh=True
        )
        old_release.set()
        old_value, _ = await old_request
        cached, cached_reused = await self.cache.get_or_create(
            "key", lambda: asyncio.sleep(0, result="unexpected")
        )

        self.assertEqual((old_value, refreshed, cached), ("old", "new", "new"))
        self.assertFalse(reused)
        self.assertTrue(cached_reused)

    async def test_concurrent_requests_share_one_load(self) -> None:
        started = asyncio.Event()
        release = asyncio.Event()

        async def factory() -> str:
            started.set()
            await release.wait()
            return "value"

        first = asyncio.create_task(self.cache.get_or_create("key", factory))
        await started.wait()
        second = asyncio.create_task(self.cache.get_or_create("key", factory))
        await asyncio.sleep(0)
        release.set()

        self.assertEqual(
            await asyncio.gather(first, second),
            [("value", False), ("value", True)],
        )

    async def test_failed_load_is_not_cached(self) -> None:
        factory = AsyncMock(side_effect=[RuntimeError("failed"), "recovered"])

        with self.assertRaisesRegex(RuntimeError, "failed"):
            await self.cache.get_or_create("key", factory)
        value, reused = await self.cache.get_or_create("key", factory)

        self.assertEqual(value, "recovered")
        self.assertFalse(reused)
        self.assertEqual(factory.await_count, 2)

    async def test_evicts_least_recently_used_entry(self) -> None:
        factories = {
            key: AsyncMock(return_value=key) for key in ("a", "b", "c")
        }
        for key in ("a", "b", "a", "c"):
            await self.cache.get_or_create(key, factories[key])

        _, reused = await self.cache.get_or_create("b", factories["b"])

        self.assertFalse(reused)
        self.assertEqual(factories["a"].await_count, 1)
        self.assertEqual(factories["b"].await_count, 2)

    async def test_clear_removes_cached_values(self) -> None:
        factory = AsyncMock(return_value="value")
        await self.cache.get_or_create("key", factory)

        await self.cache.clear()
        _, reused = await self.cache.get_or_create("key", factory)

        self.assertFalse(reused)
        self.assertEqual(factory.await_count, 2)

    async def test_clear_cancels_inflight_load(self) -> None:
        started = asyncio.Event()
        release = asyncio.Event()

        async def factory() -> str:
            started.set()
            await release.wait()
            return "value"

        request = asyncio.create_task(self.cache.get_or_create("key", factory))
        await started.wait()

        await self.cache.clear()

        with self.assertRaises(asyncio.CancelledError):
            await request
        await asyncio.sleep(0)

    def test_rejects_invalid_configuration(self) -> None:
        with self.assertRaises(ValueError):
            AsyncTTLCache(ttl_seconds=-1, max_entries=1)
        with self.assertRaises(ValueError):
            AsyncTTLCache(ttl_seconds=1, max_entries=0)
