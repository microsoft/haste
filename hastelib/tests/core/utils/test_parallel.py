# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License.
import os
import unittest
from concurrent.futures import ThreadPoolExecutor
from threading import Event, Lock
from unittest.mock import patch

from hastegeo.core.utils.parallel import (
    BoundedExecutor,
    configured_worker_count,
)


class TestConfiguredWorkerCount(unittest.TestCase):
    def test_uses_default_when_environment_is_missing(self) -> None:
        with patch.dict(os.environ, {}, clear=True):
            self.assertEqual(configured_worker_count("TEST_WORKERS", 4), 4)

    def test_reads_valid_environment_value(self) -> None:
        with patch.dict(os.environ, {"TEST_WORKERS": "7"}):
            self.assertEqual(configured_worker_count("TEST_WORKERS", 4), 7)

    def test_rejects_invalid_environment_values(self) -> None:
        for value in ("not-an-int", "0", "65"):
            with self.subTest(value=value):
                with patch.dict(os.environ, {"TEST_WORKERS": value}):
                    with self.assertRaises(ValueError):
                        configured_worker_count("TEST_WORKERS", 4)

    def test_rejects_non_integer_direct_value(self) -> None:
        for value in (True, "4"):
            with self.subTest(value=value):
                with self.assertRaisesRegex(ValueError, "integer"):
                    BoundedExecutor(max_workers=value)


class TestBoundedExecutor(unittest.TestCase):
    def setUp(self) -> None:
        self.executor = BoundedExecutor(max_workers=2)

    def tearDown(self) -> None:
        self.executor.shutdown()

    def test_preserves_input_order(self) -> None:
        result = self.executor.map(lambda value: value * 2, [3, 1, 2])

        self.assertEqual(result, [6, 2, 4])

    def test_propagates_worker_exceptions(self) -> None:
        def fail_on_two(value: int) -> int:
            if value == 2:
                raise RuntimeError("failed")
            return value

        with self.assertRaisesRegex(RuntimeError, "failed"):
            self.executor.map(fail_on_two, [1, 2, 3])

    def test_cancels_queued_work_after_failure(self) -> None:
        release = Event()

        def fail_with_pending_work(value: int) -> int:
            if value == 1:
                raise RuntimeError("failed")
            release.wait(timeout=1)
            return value

        try:
            with self.assertRaisesRegex(RuntimeError, "failed"):
                self.executor.map(fail_with_pending_work, [1, 2, 3, 4])
        finally:
            release.set()

    def test_rejects_invalid_per_call_limit(self) -> None:
        with self.assertRaises(ValueError):
            self.executor.map(str, [1], max_workers=0)

    def test_nested_map_does_not_deadlock(self) -> None:
        single_worker = BoundedExecutor(max_workers=1)
        self.addCleanup(single_worker.shutdown)

        result = single_worker.map(
            lambda value: single_worker.map(lambda item: item, [value])[0],
            [1],
        )

        self.assertEqual(result, [1])

    def test_concurrent_maps_share_the_process_budget(self) -> None:
        active = 0
        peak = 0
        lock = Lock()
        two_workers_started = Event()

        def work(value: int) -> int:
            nonlocal active, peak
            with lock:
                active += 1
                peak = max(peak, active)
                if active == 2:
                    two_workers_started.set()
            self.assertTrue(two_workers_started.wait(timeout=1))
            with lock:
                active -= 1
            return value

        with ThreadPoolExecutor(max_workers=2) as callers:
            first = callers.submit(self.executor.map, work, [1, 2, 3])
            second = callers.submit(self.executor.map, work, [4, 5, 6])
            self.assertEqual(first.result(), [1, 2, 3])
            self.assertEqual(second.result(), [4, 5, 6])

        self.assertEqual(peak, 2)
