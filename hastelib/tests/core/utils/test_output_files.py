# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License.

import os
import tempfile
import unittest
from contextlib import contextmanager
from io import BytesIO
from pathlib import Path, PurePosixPath
from typing import BinaryIO, Iterator, Optional
from unittest.mock import MagicMock, patch

from hastegeo.core.utils import output_files
from hastegeo.core.utils.output_files import (
    AmbiguousTaskOutputError,
    open_task_output,
)


class TaskOutputTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.workspace = Path(self.temporary.name) / "work"
        self.root = self.workspace / "job" / "task"
        self.root.mkdir(parents=True)
        self.other_task = self.workspace / "other-job" / "task"
        self.other_task.mkdir(parents=True)
        (self.other_task / "progress.log").write_bytes(b"other task private")

    def write(self, relative: str, content: bytes = b"output") -> Path:
        path = self.root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)
        return path

    def open_output(self, requested: str) -> Optional[BinaryIO]:
        return open_task_output(
            self.root, requested, workspace_root=self.workspace
        )

    def read_output(self, requested: str) -> Optional[bytes]:
        stream = self.open_output(requested)
        if stream is None:
            return None
        with stream:
            return stream.read()

    @contextmanager
    def replace_after_discovery(
        self, path: Path, replacement: Path, *, directory: bool
    ) -> Iterator[None]:
        resolve = output_files._resolve_task_output

        def replace(
            task_fd: int, relative: PurePosixPath
        ) -> Optional[output_files._TaskOutput]:
            candidate = resolve(task_fd, relative)
            self.assertIsNotNone(candidate)
            path.rename(path.with_name(path.name + ".original"))
            path.symlink_to(replacement, target_is_directory=directory)
            return candidate

        with patch.object(
            output_files, "_resolve_task_output", side_effect=replace
        ):
            yield


class TestTaskOutputValidation(TaskOutputTestCase):
    def test_unsafe_paths_are_rejected(self) -> None:
        for path in (
            "",
            ".",
            "..",
            "../secret",
            r"..\secret",
            "/tmp/x",
            r"C:\x",
            "C:x",
            "a\x00b",
        ):
            with self.subTest(path=path), self.assertRaises(ValueError):
                self.open_output(path)

    def test_only_a_job_task_beneath_the_trusted_root_is_accepted(
        self,
    ) -> None:
        for path in (
            self.workspace,
            self.root.parent,
            self.root / "nested",
            self.workspace / ".." / "job" / "task",
            Path(self.temporary.name) / "outside" / "task",
        ):
            with self.subTest(path=path), self.assertRaises(ValueError):
                open_task_output(
                    path, "progress.log", workspace_root=self.workspace
                )

    def test_no_path_fallback_when_descriptor_apis_are_missing(self) -> None:
        with (
            patch.object(os, "supports_dir_fd", set()),
            patch.object(os, "open") as opened,
            self.assertRaisesRegex(NotImplementedError, "descriptor-relative"),
        ):
            self.open_output("progress.log")
        opened.assert_not_called()

    @unittest.skipUnless(os.name == "nt", "Native Windows contract")
    def test_windows_reads_fail_explicitly_without_a_path_fallback(
        self,
    ) -> None:
        self.write("progress.log")
        with self.assertRaisesRegex(NotImplementedError, "Linux"):
            self.open_output("progress.log")


@unittest.skipUnless(os.name == "posix", "POSIX descriptor APIs required")
class TestTaskOutputReads(TaskOutputTestCase):
    def test_exact_path_wins_over_nested_matches(self) -> None:
        self.write("events.out.tfevents", b"exact")
        self.write("logs/events.out.tfevents", b"nested")
        self.assertEqual(self.read_output("events.out.tfevents"), b"exact")

    def test_nested_file_and_generated_basename_are_found(self) -> None:
        self.write(
            "logs/model_42/version_0/events.out.tfevents.123.host.0",
            b"\x00binary\xff",
        )
        self.assertEqual(
            self.read_output("events.out.tfevents"), b"\x00binary\xff"
        )

    def test_nested_exact_suffix_precedes_basename_prefix(self) -> None:
        self.write("outputs/logs/progress.log", b"suffix")
        self.write("elsewhere/progress.log.extra", b"prefix")
        self.assertEqual(self.read_output("logs/progress.log"), b"suffix")

    def test_backslash_separators_are_normalized(self) -> None:
        self.write("logs/progress.log")
        self.assertEqual(self.read_output(r"logs\progress.log"), b"output")

    def test_multiple_prefix_matches_are_not_selected_arbitrarily(
        self,
    ) -> None:
        self.write("logs/version_0/events.out.tfevents.123")
        self.write("logs/version_1/events.out.tfevents.456")
        with self.assertRaises(AmbiguousTaskOutputError):
            self.open_output("events.out.tfevents")

    def test_multiple_nested_exact_matches_are_ambiguous(self) -> None:
        self.write("one/progress.log")
        self.write("two/progress.log")
        with self.assertRaises(AmbiguousTaskOutputError):
            self.open_output("progress.log")

    def test_missing_output_never_searches_another_task(self) -> None:
        self.assertIsNone(self.open_output("progress.log"))
        self.assertIsNone(
            open_task_output(
                self.workspace / "job" / "missing",
                "progress.log",
                workspace_root=self.workspace,
            )
        )

    def test_missing_workspace_is_unavailable(self) -> None:
        missing = Path(self.temporary.name) / "missing"
        self.assertIsNone(
            open_task_output(
                missing / "job" / "task",
                "progress.log",
                workspace_root=missing,
            )
        )

    def test_directory_is_not_an_output_file(self) -> None:
        (self.root / "progress.log").mkdir()
        self.assertIsNone(self.open_output("progress.log"))

    def test_workspace_root_symlink_is_rejected(self) -> None:
        original = self.workspace.with_name("original-work")
        self.workspace.rename(original)
        self.workspace.symlink_to(original, target_is_directory=True)
        with self.assertRaises(ValueError):
            self.open_output("progress.log")

    def test_job_parent_symlink_cannot_redirect_to_another_job(self) -> None:
        self.root.rmdir()
        self.root.parent.rmdir()
        self.root.parent.symlink_to(
            self.other_task.parent, target_is_directory=True
        )
        with self.assertRaises(ValueError):
            self.open_output("progress.log")

    def test_task_root_symlink_cannot_redirect_to_another_task(self) -> None:
        self.root.rmdir()
        self.root.symlink_to(self.other_task, target_is_directory=True)
        with self.assertRaises(ValueError):
            self.open_output("progress.log")

    def test_exact_file_symlink_cannot_escape_task(self) -> None:
        (self.root / "progress.log").symlink_to(
            self.other_task / "progress.log"
        )
        with self.assertRaises(ValueError):
            self.open_output("progress.log")

    def test_exact_file_symlink_is_rejected_even_within_task(self) -> None:
        target = self.write("logs/original.log")
        (self.root / "progress.log").symlink_to(target)
        with self.assertRaises(ValueError):
            self.open_output("progress.log")

    def test_generated_candidate_symlink_is_rejected(self) -> None:
        logs = self.root / "logs"
        logs.mkdir()
        (logs / "events.out.tfevents.123").symlink_to(
            self.other_task / "progress.log"
        )
        with self.assertRaises(ValueError):
            self.open_output("events.out.tfevents")

    def test_exact_parent_symlink_is_rejected(self) -> None:
        (self.root / "logs").symlink_to(
            self.other_task, target_is_directory=True
        )
        with self.assertRaises(ValueError):
            self.open_output("logs/progress.log")

    def test_discovery_does_not_descend_into_symlink_directories(self) -> None:
        (self.root / "linked").symlink_to(
            self.other_task, target_is_directory=True
        )
        self.write("logs/progress.log", b"own task")
        self.assertEqual(self.read_output("progress.log"), b"own task")

    def test_task_replaced_after_discovery_keeps_the_original_task(
        self,
    ) -> None:
        self.write("logs/progress.log", b"own task")
        with self.replace_after_discovery(
            self.root, self.other_task, directory=True
        ):
            self.assertEqual(self.read_output("progress.log"), b"own task")

    def test_job_replaced_after_discovery_keeps_the_original_task(
        self,
    ) -> None:
        self.write("logs/progress.log", b"own task")
        with self.replace_after_discovery(
            self.root.parent, self.other_task.parent, directory=True
        ):
            self.assertEqual(self.read_output("progress.log"), b"own task")

    def test_workspace_replaced_after_discovery_keeps_the_original_task(
        self,
    ) -> None:
        self.write("logs/progress.log", b"own task")
        replacement = self.workspace.with_name("replacement-work")
        (replacement / "job" / "task" / "logs").mkdir(parents=True)
        (replacement / "job" / "task" / "logs" / "progress.log").write_bytes(
            b"other task private"
        )
        with self.replace_after_discovery(
            self.workspace, replacement, directory=True
        ):
            self.assertEqual(self.read_output("progress.log"), b"own task")

    def test_candidate_directory_replaced_before_open_is_rejected(
        self,
    ) -> None:
        self.write("logs/progress.log", b"own task")
        with self.replace_after_discovery(
            self.root / "logs", self.other_task, directory=True
        ), self.assertRaises(ValueError):
            self.open_output("progress.log")

    def test_candidate_file_replaced_before_open_is_rejected(self) -> None:
        path = self.write("logs/progress.log", b"own task")
        with self.replace_after_discovery(
            path, self.other_task / "progress.log", directory=False
        ), self.assertRaises(ValueError):
            self.open_output("progress.log")

    def test_different_regular_inode_after_discovery_is_rejected(
        self,
    ) -> None:
        path = self.write("logs/progress.log", b"own task")
        resolve = output_files._resolve_task_output

        def replace(
            task_fd: int, relative: PurePosixPath
        ) -> Optional[output_files._TaskOutput]:
            candidate = resolve(task_fd, relative)
            path.rename(path.with_name("original.log"))
            path.write_bytes(b"replacement")
            return candidate

        with patch.object(
            output_files, "_resolve_task_output", side_effect=replace
        ), self.assertRaisesRegex(ValueError, "changed during discovery"):
            self.open_output("progress.log")

    def test_path_replacement_after_final_open_cannot_redirect_read(
        self,
    ) -> None:
        path = self.write("progress.log", b"own task")
        with self.open_output("progress.log") as stream:
            path.unlink()
            path.symlink_to(self.other_task / "progress.log")
            self.assertEqual(stream.read(), b"own task")


class TestLocalOutputPlatformContract(TaskOutputTestCase):
    def setUp(self) -> None:
        super().setUp()
        from hastegeo.core.runners.local import LocalRunner

        self.runner = LocalRunner.__new__(LocalRunner)
        self.runner.work_dir = self.workspace
        self.runner.logger = MagicMock()

    def test_unsupported_reads_are_logged_and_not_silently_downgraded(
        self,
    ) -> None:
        with patch.object(os, "supports_dir_fd", set()):
            for as_chunk in (False, True):
                with self.subTest(as_chunk=as_chunk):
                    with self.assertRaises(NotImplementedError):
                        self.runner.get_filecontent_from_task(
                            "job", "task", "progress.log", as_chunk=as_chunk
                        )
        self.assertEqual(self.runner.logger.warning.call_count, 2)

    def test_text_uses_and_closes_the_owned_stream(self) -> None:
        stream = BytesIO("caf\u00e9\r\nnext\rline".encode("utf-8"))
        self.addCleanup(stream.close)
        with patch(
            "hastegeo.core.runners.local.open_task_output",
            return_value=stream,
        ) as opened:
            self.assertEqual(
                self.runner.get_filecontent_from_task(
                    "job", "task", "progress.log"
                ),
                "caf\u00e9\nnext\nline",
            )
        opened.assert_called_once_with(
            self.root, "progress.log", workspace_root=self.workspace
        )
        self.assertTrue(stream.closed)

    def test_binary_chunks_retain_bytes_and_close_on_exhaustion(self) -> None:
        content = b"\x00binary\xff" * 2049
        stream = BytesIO(content)
        self.addCleanup(stream.close)
        with patch(
            "hastegeo.core.runners.local.open_task_output",
            return_value=stream,
        ):
            chunks = self.runner.get_filecontent_from_task(
                "job", "task", "events.out.tfevents", as_chunk=True
            )
        self.addCleanup(chunks.close)
        self.assertEqual(next(chunks), content[:8192])
        self.assertEqual(next(chunks), content[8192:16384])
        self.assertEqual(b"".join(chunks), content[16384:])
        self.assertTrue(stream.closed)

    def test_partial_chunk_read_closes_the_owned_stream(self) -> None:
        stream = BytesIO(b"x" * 16384)
        self.addCleanup(stream.close)
        with patch(
            "hastegeo.core.runners.local.open_task_output",
            return_value=stream,
        ):
            chunks = self.runner.get_filecontent_from_task(
                "job", "task", "events.out.tfevents", as_chunk=True
            )
        self.addCleanup(chunks.close)
        self.assertEqual(len(next(chunks)), 8192)
        chunks.close()
        self.assertTrue(stream.closed)

    def test_ambiguous_or_missing_stream_retains_none_and_a_diagnostic(
        self,
    ) -> None:
        for as_chunk in (False, True):
            for failure in (None, AmbiguousTaskOutputError("ambiguous")):
                with self.subTest(as_chunk=as_chunk, failure=failure):
                    with patch(
                        "hastegeo.core.runners.local.open_task_output",
                        return_value=None,
                        side_effect=failure,
                    ):
                        self.assertIsNone(
                            self.runner.get_filecontent_from_task(
                                "job",
                                "task",
                                "progress.log",
                                as_chunk=as_chunk,
                            )
                        )
        self.assertEqual(self.runner.logger.warning.call_count, 4)


@unittest.skipUnless(os.name == "posix", "POSIX descriptor APIs required")
class TestLocalOutputReads(TaskOutputTestCase):
    def setUp(self) -> None:
        super().setUp()
        from hastegeo.core.runners.local import LocalRunner

        self.runner = LocalRunner.__new__(LocalRunner)
        self.runner.work_dir = self.workspace
        self.runner.logger = MagicMock()

    def test_local_reader_returns_event_bytes_and_logs_ambiguity(self) -> None:
        self.write(
            "logs/model/version_0/events.out.tfevents.123", b"\x00binary\xff"
        )
        self.assertEqual(
            b"".join(
                self.runner.get_filecontent_from_task(
                    "job", "task", "events.out.tfevents", as_chunk=True
                )
            ),
            b"\x00binary\xff",
        )
        self.write("logs/version_1/events.out.tfevents.456")
        self.assertIsNone(
            self.runner.get_filecontent_from_task(
                "job", "task", "events.out.tfevents", as_chunk=True
            )
        )
        self.runner.logger.warning.assert_called_once()

    def test_local_text_reader_retains_utf8_and_universal_newlines(
        self,
    ) -> None:
        self.write(
            "logs/progress.log", "caf\u00e9\r\nnext\rline".encode("utf-8")
        )
        self.assertEqual(
            self.runner.get_filecontent_from_task(
                "job", "task", "progress.log"
            ),
            "caf\u00e9\nnext\nline",
        )

    def test_missing_output_retains_none_for_text_and_chunks(self) -> None:
        for as_chunk in (False, True):
            with self.subTest(as_chunk=as_chunk):
                self.assertIsNone(
                    self.runner.get_filecontent_from_task(
                        "job", "task", "missing.log", as_chunk=as_chunk
                    )
                )
        self.assertEqual(self.runner.logger.warning.call_count, 2)

    def test_delayed_chunk_consumption_never_reopens_the_path(self) -> None:
        content = b"\x00binary\xff" * 2048
        path = self.write("logs/events.out.tfevents.123", content)
        chunks = self.runner.get_filecontent_from_task(
            "job", "task", "events.out.tfevents", as_chunk=True
        )
        self.addCleanup(chunks.close)
        path.unlink()
        path.symlink_to(self.other_task / "progress.log")
        self.assertEqual(next(chunks), content[:8192])
        self.assertEqual(b"".join(chunks), content[8192:])

    def test_closing_partial_chunk_read_closes_the_open_file(self) -> None:
        self.write("events.out.tfevents", b"x" * 16384)
        stream = self.open_output("events.out.tfevents")
        self.addCleanup(stream.close)
        with patch(
            "hastegeo.core.runners.local.open_task_output",
            return_value=stream,
        ):
            chunks = self.runner.get_filecontent_from_task(
                "job", "task", "events.out.tfevents", as_chunk=True
            )
        self.addCleanup(chunks.close)
        self.assertEqual(len(next(chunks)), 8192)
        chunks.close()
        self.assertTrue(stream.closed)

    def test_local_ambiguity_is_explicit_for_text_reads(self) -> None:
        self.write("one/progress.log")
        self.write("two/progress.log")
        self.assertIsNone(
            self.runner.get_filecontent_from_task(
                "job", "task", "progress.log"
            )
        )
        self.runner.logger.warning.assert_called_once()
