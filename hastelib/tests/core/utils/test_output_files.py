# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License.

import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock

from hastegeo.core.utils.output_files import (
    AmbiguousTaskOutputError,
    resolve_task_output,
)


class TestTaskOutputResolution(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name) / "task"
        self.root.mkdir()

    def write(self, relative: str, content: bytes = b"output") -> Path:
        path = self.root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)
        return path.resolve()

    def test_exact_path_wins_over_nested_matches(self) -> None:
        exact = self.write("events.out.tfevents")
        self.write("logs/events.out.tfevents")
        self.assertEqual(
            resolve_task_output(self.root, "events.out.tfevents"), exact
        )

    def test_nested_file_and_generated_basename_are_found(self) -> None:
        event = self.write(
            "logs/model_42/version_0/events.out.tfevents.123.host.0"
        )
        self.assertEqual(
            resolve_task_output(self.root, "events.out.tfevents"), event
        )

    def test_nested_exact_suffix_precedes_basename_prefix(self) -> None:
        exact = self.write("outputs/logs/progress.log")
        self.write("elsewhere/progress.log.extra")
        self.assertEqual(
            resolve_task_output(self.root, "logs/progress.log"), exact
        )

    def test_multiple_prefix_matches_are_not_selected_arbitrarily(
        self,
    ) -> None:
        self.write("logs/version_0/events.out.tfevents.123")
        self.write("logs/version_1/events.out.tfevents.456")
        with self.assertRaises(AmbiguousTaskOutputError):
            resolve_task_output(self.root, "events.out.tfevents")

    def test_multiple_nested_exact_matches_are_ambiguous(self) -> None:
        self.write("one/progress.log")
        self.write("two/progress.log")
        with self.assertRaises(AmbiguousTaskOutputError):
            resolve_task_output(self.root, "progress.log")

    def test_missing_output_is_unavailable(self) -> None:
        self.assertIsNone(resolve_task_output(self.root, "progress.log"))
        self.assertIsNone(
            resolve_task_output(self.root / "missing", "progress.log")
        )

    def test_unsafe_paths_are_rejected(self) -> None:
        for path in (
            "",
            ".",
            "..",
            "../secret",
            r"..\secret",
            "/tmp/x",
            r"C:\x",
            "a\x00b",
        ):
            with self.subTest(path=path), self.assertRaises(ValueError):
                resolve_task_output(self.root, path)

    def test_symlink_cannot_escape_task(self) -> None:
        outside = self.root.parent / "outside"
        outside.write_text("private")
        link = self.root / "progress.log"
        try:
            link.symlink_to(outside)
        except OSError as error:
            self.skipTest(f"Symlink creation unavailable: {error}")
        with self.assertRaises(ValueError):
            resolve_task_output(self.root, "progress.log")

    def test_local_reader_returns_event_bytes_and_logs_ambiguity(self) -> None:
        from hastegeo.core.runners.local import LocalRunner

        runner = LocalRunner.__new__(LocalRunner)
        runner.work_dir = self.root
        runner.logger = MagicMock()
        self.write(
            "job/task/logs/model/version_0/events.out.tfevents.123",
            b"\x00binary\xff",
        )
        self.assertEqual(
            b"".join(
                runner.get_filecontent_from_task(
                    "job", "task", "events.out.tfevents", as_chunk=True
                )
            ),
            b"\x00binary\xff",
        )
        self.write("job/task/logs/version_1/events.out.tfevents.456")
        self.assertIsNone(
            runner.get_filecontent_from_task(
                "job", "task", "events.out.tfevents", as_chunk=True
            )
        )
        runner.logger.warning.assert_called_once()
