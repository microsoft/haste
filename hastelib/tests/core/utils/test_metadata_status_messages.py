# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License.
import json
import unittest

from hastegeo.core.utils.metadata import (
    MAX_STATUS_MESSAGE_BYTES,
    STATUS_HISTORY_TRIMMED,
    MetadataUtils,
)

PROGRESS = "Training job in progress"


def _serialized_size(text: str) -> int:
    # Monitors queue records with json.dumps, which escapes non-ASCII.
    return len(json.dumps(text)) - 2


def _progress(minutes) -> str:
    return (
        f"{PROGRESS}\n"
        "trainStartTime: 2026-09-22T19:24:47+00:00\n"
        "epoch: 1\n"
        f"elapsedDurationInMinutes: {minutes}\n"
        "approxMinutesToComplete: 120"
    )


class TestUpsertStatusMessage(unittest.TestCase):
    def test_replaces_the_trailing_progress_entry(self) -> None:
        history = MetadataUtils.append_status_message(
            "",
            "Training submitted with task id trn-1",
            timestamp="2026-09-22T19:20:17.455000+00:00",
        )
        history = MetadataUtils.upsert_status_message(
            history,
            _progress(1),
            PROGRESS,
            timestamp="2026-09-22T19:25:00.000000+00:00",
        )
        history = MetadataUtils.upsert_status_message(
            history,
            _progress(2),
            PROGRESS,
            timestamp="2026-09-22T19:25:32.000000+00:00",
        )

        self.assertEqual(
            history,
            "\n2026-09-22T19:20:17.455000+00:00: "
            "Training submitted with task id trn-1"
            "\n2026-09-22T19:25:32.000000+00:00: " + _progress(2),
        )

    def test_appends_when_the_last_entry_is_something_else(self) -> None:
        history = "\n2026-09-22T19:20:17+00:00: Queued for training"

        updated = MetadataUtils.upsert_status_message(
            history,
            _progress(1),
            PROGRESS,
            timestamp="2026-09-22T19:25:00+00:00",
        )

        self.assertEqual(
            updated,
            history + "\n2026-09-22T19:25:00+00:00: " + _progress(1),
        )

    def test_only_the_trailing_entry_is_replaced(self) -> None:
        history = (
            "\n2026-09-22T19:25:00+00:00: "
            + _progress(1)
            + "\n2026-09-22T19:30:00+00:00: Epoch 1 checkpoint saved"
        )

        updated = MetadataUtils.upsert_status_message(
            history,
            _progress(9),
            PROGRESS,
            timestamp="2026-09-22T19:35:00+00:00",
        )

        self.assertEqual(
            updated,
            history + "\n2026-09-22T19:35:00+00:00: " + _progress(9),
        )

    def test_empty_history(self) -> None:
        for empty in (None, ""):
            with self.subTest(history=empty):
                self.assertEqual(
                    MetadataUtils.upsert_status_message(
                        empty,
                        _progress(1),
                        PROGRESS,
                        timestamp="2026-09-22T19:25:00+00:00",
                    ),
                    "\n2026-09-22T19:25:00+00:00: " + _progress(1),
                )

    def test_many_polls_keep_one_progress_entry(self) -> None:
        history = (
            "\n2026-09-22T19:20:17+00:00: "
            "Training submitted with task id trn-1"
        )

        for minute in range(1000):
            history = MetadataUtils.upsert_status_message(
                history, _progress(minute), PROGRESS
            )

        self.assertEqual(history.count(PROGRESS), 1)
        self.assertIn("elapsedDurationInMinutes: 999\n", history)
        self.assertIn("Training submitted with task id trn-1", history)


class TestTrimStatusMessage(unittest.TestCase):
    def test_history_within_the_limit_is_unchanged(self) -> None:
        history = "\n2026-09-22T19:20:17+00:00: Queued for training"

        self.assertEqual(
            MetadataUtils.trim_status_message(history, 1000), history
        )

    def test_keeps_the_newest_whole_entries_and_says_so(self) -> None:
        entries = [
            f"\n2026-09-22T19:{minute:02d}:00+00:00: event {minute}"
            for minute in range(60)
        ]
        history = "".join(entries)

        trimmed = MetadataUtils.trim_status_message(history, 400)

        self.assertLessEqual(_serialized_size(trimmed), 400)
        marker, retained = trimmed[1:].split("\n", 1)
        retained = "\n" + retained
        self.assertTrue(marker.endswith(f": {STATUS_HISTORY_TRIMMED}"))
        # Only whole entries survive, newest last, and the marker carries
        # the oldest survivor's time so the history stays in order.
        self.assertIn(
            retained,
            ["".join(entries[first:]) for first in range(1, len(entries))],
        )
        self.assertEqual(
            marker.partition(": ")[0], retained[1:].partition(": ")[0]
        )

    def test_the_budget_counts_escaped_non_ascii_text(self) -> None:
        # Fewer characters than the budget, but each of these escapes to six
        # bytes in the queued message: measured by characters, this history
        # would pass untrimmed and overflow the 64 KiB queue limit.
        entries = [
            f"\n2026-09-22T19:{minute:02d}:00+00:00: " + "训练失败" * 75
            for minute in range(45)
        ]
        history = "".join(entries)
        self.assertLess(len(history), MAX_STATUS_MESSAGE_BYTES)
        self.assertGreater(_serialized_size(history), 64 * 1024)

        trimmed = MetadataUtils.trim_status_message(history)

        self.assertLessEqual(
            _serialized_size(trimmed), MAX_STATUS_MESSAGE_BYTES
        )
        self.assertTrue(trimmed.endswith(entries[-1]))
        self.assertIn(STATUS_HISTORY_TRIMMED, trimmed)

    def test_an_oversized_newest_entry_keeps_its_beginning(self) -> None:
        newest = "\n2026-09-22T19:21:00+00:00: " + "x" * 5000
        history = "\n2026-09-22T19:20:17+00:00: Queued for training" + newest

        trimmed = MetadataUtils.trim_status_message(history, 100)

        # The longest start of the entry that fits: the leading newline
        # serializes to two bytes, so one fewer character than the budget.
        self.assertEqual(trimmed, newest[:99])
        self.assertEqual(_serialized_size(trimmed), 100)

    def test_unstructured_text_keeps_its_tail(self) -> None:
        self.assertEqual(
            MetadataUtils.trim_status_message("a" * 50 + "b" * 50, 50),
            "b" * 50,
        )
        self.assertEqual(
            MetadataUtils.trim_status_message("a" * 50 + "é" * 50, 60),
            "é" * 10,
        )


if __name__ == "__main__":
    unittest.main()
