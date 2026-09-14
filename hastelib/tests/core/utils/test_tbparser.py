# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License.

import json
import math
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from hastegeo.core.utils.tbparser import calculate_metrics, parse_tb_event_logs
from tensorboard.compat.proto.event_pb2 import Event
from tensorboard.compat.proto.summary_pb2 import Summary
from tensorboard.summary.writer.event_file_writer import EventFileWriter


class TestTensorBoardProgress(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.writer = EventFileWriter(self.temporary.name)
        self.addCleanup(self.writer.close)
        self.writer.flush()
        self.path = next(
            Path(self.temporary.name).glob("events.out.tfevents.*")
        )

    def write_event(
        self, step: int, wall_time: float, **values: float
    ) -> None:
        self.writer.add_event(
            Event(
                step=step,
                wall_time=wall_time,
                summary=Summary(
                    value=[
                        Summary.Value(tag=tag, simple_value=value)
                        for tag, value in values.items()
                    ]
                ),
            )
        )
        self.writer.flush()

    def test_empty_event_file_is_not_a_failure(self) -> None:
        start, records = parse_tb_event_logs(str(self.path))
        self.assertIsNone(start)
        self.assertEqual(json.loads(records), [])
        self.assertIsNone(calculate_metrics(records, "1"))

    def test_growing_epoch_zero_reports_real_elapsed_time(self) -> None:
        self.write_event(0, 100, epoch=0, train_loss=0.8)
        _, initial = parse_tb_event_logs(str(self.path))
        first = calculate_metrics(initial, "2")
        self.assertEqual(first["completed_epochs"], 0)
        self.assertEqual(first["total_elapsed_time"], 0)
        self.assertIsNone(first["approx_time_to_complete"])

        self.write_event(50, 160, epoch=0, train_loss=0.5)
        _, updated = parse_tb_event_logs(str(self.path))
        current = calculate_metrics(updated, "2")
        self.assertEqual(current["completed_epochs"], 0)
        self.assertEqual(current["total_elapsed_time"], 1)
        self.assertIsNone(current["approx_time_to_complete"])
        self.assertEqual(json.loads(updated)[0]["loss"], 0.5)

    def test_nonfinite_metrics_are_unavailable_not_zero(self) -> None:
        self.write_event(
            0,
            100,
            epoch=0,
            train_loss=math.nan,
            train_MulticlassAccuracy=math.inf,
        )
        with patch("hastegeo.core.utils.tbparser.logger") as logger:
            _, records = parse_tb_event_logs(str(self.path))
        record = json.loads(records)[0]
        self.assertIsNone(record["loss"])
        self.assertIsNone(record["multiclassAccuracy"])
        self.assertNotIn("NaN", records)
        self.assertNotIn("Infinity", records)
        self.assertEqual(logger.warning.call_count, 2)

    def test_invalid_epoch_is_ignored_with_diagnostic(self) -> None:
        self.write_event(0, 100, epoch=math.nan, train_loss=0.5)
        with patch("hastegeo.core.utils.tbparser.logger") as logger:
            _, records = parse_tb_event_logs(str(self.path))
        self.assertEqual(json.loads(records), [])
        logger.warning.assert_called_once()

    def test_partial_trailing_event_does_not_erase_valid_events(self) -> None:
        self.write_event(0, 100, epoch=0, train_loss=0.5)
        self.writer.close()
        with self.path.open("ab") as stream:
            stream.write(b"\x01\x02\x03")
        _, records = parse_tb_event_logs(str(self.path))
        self.assertEqual(json.loads(records)[0]["loss"], 0.5)


class TestCalculateMetrics(unittest.TestCase):
    def records(self, *durations: float, start_epoch: int = 0) -> str:
        return json.dumps(
            [
                {
                    "epoch": start_epoch + index,
                    "elapsedDurationInMinutes": value,
                }
                for index, value in enumerate(durations)
            ]
        )

    def test_zero_duration_is_valid_progress(self) -> None:
        metrics = calculate_metrics(self.records(0), "1")
        self.assertEqual(metrics["completed_epochs"], 0)
        self.assertEqual(metrics["total_elapsed_time"], 0)
        self.assertIsNone(metrics["time_per_epoch"])

    def test_eta_uses_completed_not_partial_epoch_duration(self) -> None:
        metrics = calculate_metrics(self.records(10, 2), "3")
        self.assertEqual(metrics["completed_epochs"], 1)
        self.assertEqual(metrics["time_per_epoch"], 10)
        self.assertEqual(metrics["total_elapsed_time"], 12)
        self.assertEqual(metrics["approx_time_to_complete"], 18)

    def test_completed_run_counts_the_final_epoch(self) -> None:
        metrics = calculate_metrics(self.records(10), "1", job_completed=True)
        self.assertEqual(metrics["completed_epochs"], 1)
        self.assertEqual(metrics["approx_time_to_complete"], 0)
        self.assertEqual(metrics["time_per_epoch"], 10)

    def test_completed_run_does_not_claim_unobserved_target_epochs(
        self,
    ) -> None:
        metrics = calculate_metrics(self.records(10), "20", job_completed=True)
        self.assertEqual(metrics["completed_epochs"], 1)
        self.assertEqual(metrics["approx_time_to_complete"], 0)

    def test_resumed_epoch_counter_does_not_restart_at_zero(self) -> None:
        metrics = calculate_metrics(self.records(10, 2, start_epoch=5), "10")
        self.assertEqual(metrics["completed_epochs"], 6)
        self.assertEqual(metrics["approx_time_to_complete"], 38)

    def test_invalid_records_do_not_produce_fabricated_progress(self) -> None:
        for logs in (
            "not-json",
            "{}",
            "[null]",
            self.records(math.nan),
            self.records(-1),
            '[{"epoch":0}]',
        ):
            with self.subTest(logs=logs):
                self.assertIsNone(calculate_metrics(logs, "2"))

    def test_missing_target_has_no_eta(self) -> None:
        metrics = calculate_metrics(self.records(10, 2), None)
        self.assertEqual(metrics["completed_epochs"], 1)
        self.assertIsNone(metrics["approx_time_to_complete"])

    def test_numeric_overflow_cannot_escape_as_invalid_json_numbers(
        self,
    ) -> None:
        self.assertIsNone(calculate_metrics(self.records(1e308, 1e308), "3"))
        metrics = calculate_metrics(self.records(10, 2), str(10**400))
        self.assertIsNone(metrics["approx_time_to_complete"])
        json.dumps(metrics, allow_nan=False)
