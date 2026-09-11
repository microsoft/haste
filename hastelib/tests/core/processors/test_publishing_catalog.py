import asyncio
import json
import unittest
from unittest.mock import Mock

from hastegeo.core.processors.publishing_catalog import (
    CatalogQuery,
    PublishingCatalogProcessor,
)
from hastegeo.core.utils.async_cache import AsyncTTLCache


class TestPublishingCatalog(unittest.IsolatedAsyncioTestCase):
    async def test_cache_hits_do_not_construct_repository_and_keys_isolate_callers(
        self,
    ) -> None:
        cache = AsyncTTLCache(ttl_seconds=5, max_entries=8)
        factory = Mock()
        factory.return_value.list_page.return_value = ([], 0)
        processor = PublishingCatalogProcessor(factory, cache)
        first, reused = await processor.load("Alice", CatalogQuery())
        self.assertFalse(reused)
        await asyncio.sleep(0)
        second, reused = await processor.load("alice", CatalogQuery())
        self.assertTrue(reused)
        self.assertEqual(first, second)
        factory.assert_called_once_with()
        self.assertEqual(
            json.loads(first["payload"])["pagination"]["totalCount"], 0
        )
        await processor.load("bob", CatalogQuery())
        self.assertEqual(factory.call_count, 2)
        await cache.clear()
