# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License.
import asyncio
import unittest
from unittest.mock import Mock, patch

from hastegeo.core.utils import perf


class TestPerfInstrumentation(unittest.TestCase):
    def tearDown(self) -> None:
        perf.end()

    def test_timed_records_logical_data_layer_operation(self) -> None:
        counter = perf.begin(True)

        with perf.timed("load"):
            pass

        self.assertEqual(counter.calls, 1)
        self.assertEqual(counter.by_op["load"]["calls"], 1)

    def test_headers_include_new_and_legacy_names(self) -> None:
        counter = perf.begin(True)

        headers = perf.headers(counter, 0)

        self.assertEqual(headers["X-Haste-Data-Layer-Calls"], "0")
        self.assertEqual(headers["X-Haste-Storage-Calls"], "0")
        self.assertIn("data-layer", headers["Server-Timing"])

    def test_disabled_instrumentation_emits_no_headers(self) -> None:
        counter = perf.begin(False)

        self.assertIsNone(counter)
        self.assertEqual(perf.headers(counter, 0), {})

    def test_log_summary_clears_active_counter(self) -> None:
        counter = perf.begin(True)
        logger = Mock()

        perf.log_summary(logger, "operation", counter, 0, key="value")

        self.assertIsNone(perf.get_counter())
        logger.info.assert_called_once()


class TestPerf(unittest.IsolatedAsyncioTestCase):
    def tearDown(self) -> None:
        perf.end()

    async def test_disabled_tracking(self) -> None:
        self.assertIsNone(perf.begin(False))
        with perf.timed("load"):
            pass
        self.assertIsNone(perf.get_counter())
        self.assertEqual(perf.headers(None, 0), {})

    async def test_exception_is_recorded_and_cleanup_is_explicit(self) -> None:
        counter = perf.begin()
        with self.assertRaises(ValueError):
            with perf.timed("load"):
                raise ValueError("failed")
        self.assertEqual(counter.calls, 1)
        perf.end()
        self.assertIsNone(perf.get_counter())

    async def test_threads_share_counter_and_concurrent_requests_are_isolated(
        self,
    ) -> None:
        def record() -> None:
            with perf.timed("load"):
                pass

        async def request() -> object:
            counter = perf.begin()
            try:
                await asyncio.gather(
                    *(asyncio.to_thread(record) for _ in range(50))
                )
                return counter
            finally:
                perf.end()

        first, second = await asyncio.gather(request(), request())
        self.assertIsNot(first, second)
        self.assertEqual(first.calls, 50)
        self.assertEqual(second.by_op["load"]["calls"], 50)
        self.assertIsNone(perf.get_counter())

    async def test_headers_and_summary(self) -> None:
        counter = perf.begin()
        counter.record("load", 0.25)
        with patch.object(perf.time, "perf_counter", return_value=2):
            headers = perf.headers(counter, 1)
            self.assertEqual(headers["X-Haste-Storage-Calls"], "1")
            self.assertEqual(headers["X-Haste-Storage-Ms"], "250.0")
            self.assertEqual(headers["X-Haste-Wall-Ms"], "1000.0")
            self.assertIn("Server-Timing", headers)
            logger = Mock()
            perf.log_summary(logger, "request", counter, 1)
        logger.info.assert_called_once()
        self.assertIsNone(perf.get_counter())
