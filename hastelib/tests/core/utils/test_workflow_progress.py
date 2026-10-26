# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License.

import unittest
from unittest.mock import MagicMock

from hastegeo.core.utils.metadata import STATUS_HISTORY_TRIMMED
from hastegeo.core.utils.workflow_progress import workflow_progress_updates

LOG = (
    "2026-01-01T00:00:00+00:00|Starting create_masks.py\n"
    "2026-01-01T00:01:00+00:00|Completed create_masks.py\n"
    "2026-01-01T00:02:00+00:00|Starting fine_tune.py\n"
    "2026-01-01T00:03:00+00:00|Completed fine_tune.py\n"
)


class TestWorkflowProgressUpdates(unittest.TestCase):
    def test_untrimmed_history_skips_only_recorded_entries(self) -> None:
        have_progress, updates = workflow_progress_updates(
            LOG,
            "\n2026-01-01T00:00:00+00:00: Starting create_masks.py",
            logger=MagicMock(),
        )

        self.assertTrue(have_progress)
        self.assertEqual(
            [message for _, message in updates],
            [
                "Completed create_masks.py",
                "Starting fine_tune.py",
                "Completed fine_tune.py",
            ],
        )

    def test_records_dropped_by_history_trimming_are_not_reappended(
        self,
    ) -> None:
        history = (
            f"\n2026-01-01T00:02:00+00:00: {STATUS_HISTORY_TRIMMED}"
            "\n2026-01-01T00:02:00+00:00: Starting fine_tune.py"
        )

        have_progress, updates = workflow_progress_updates(
            LOG, history, logger=MagicMock()
        )

        self.assertTrue(have_progress)
        self.assertEqual(
            updates, [("2026-01-01T00:03:00+00:00", "Completed fine_tune.py")]
        )

    def test_trim_marker_and_records_compare_as_utc_instants(self) -> None:
        history = f"\n2026-01-01T00:01:00Z: {STATUS_HISTORY_TRIMMED}"
        content = (
            "2026-01-01T01:00:59+01:00|Dropped before the marker\n"
            "2026-01-01T01:01:01+01:00|Recorded after the marker\n"
        )

        _, updates = workflow_progress_updates(
            content, history, logger=MagicMock()
        )

        self.assertEqual(
            updates,
            [("2026-01-01T01:01:01+01:00", "Recorded after the marker")],
        )


if __name__ == "__main__":
    unittest.main()
