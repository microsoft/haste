# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License.
import unittest
from unittest.mock import Mock

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


if __name__ == "__main__":
    unittest.main()
