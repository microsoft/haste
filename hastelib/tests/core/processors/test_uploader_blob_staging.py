# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License.
import io
import unittest
from contextlib import nullcontext
from unittest.mock import Mock, patch

from hastegeo.core.config import Config
from hastegeo.core.processors.uploader import FileUploader

TIFF = b"II*\x00" + b"\x00" * 80


def state(missing, total_size=0, complete=False, output_url=None):
    return {
        "complete": complete,
        "missing": missing,
        "unexpected": [],
        "total_size": total_size,
        "output_url": output_url,
    }


class TestBlobUploadStaging(unittest.TestCase):
    def setUp(self) -> None:
        config = Config()
        config.storage_type = "blob"
        config.DATA_DIR = None
        config.TEMP_DIR = "/tmp"
        self.storage = Mock()
        self.storage.chunk_upload_lock.return_value = nullcontext("lease-id")
        with patch(
            "hastegeo.core.processors.uploader.UnifiedDataLayer",
            return_value=self.storage,
        ):
            self.uploader = FileUploader("project-1", config)

    def test_last_missing_chunk_completes_without_local_staging(self) -> None:
        self.storage.get_chunk_upload_state.side_effect = [
            state([0]),
            state([], len(TIFF)),
        ]
        self.storage.finalize_save.return_value = "https://account/result.tif"
        result = self.uploader.save_chunk(0, io.BytesIO(TIFF), "file1", 2)
        self.assertEqual(
            result.status,
            self.uploader.config.get_status_types().COMPLETED.value,
        )
        self.assertEqual(
            self.storage.save_chunk.call_args.kwargs["data"], TIFF
        )
        self.assertEqual(
            self.storage.save_chunk.call_args.kwargs["lease"], "lease-id"
        )
        self.assertEqual(
            self.storage.finalize_save.call_args.kwargs["lease"], "lease-id"
        )
        self.storage.finalize_save.assert_called_once()

    def test_final_index_arriving_first_does_not_finalize(self) -> None:
        self.storage.get_chunk_upload_state.side_effect = [
            state([0, 1]),
            state([0], 4),
        ]
        result = self.uploader.save_chunk(1, io.BytesIO(b"tail"), "file1", 2)
        self.assertEqual(
            result.status,
            self.uploader.config.get_status_types().IN_PROGRESS.value,
        )
        self.storage.finalize_save.assert_not_called()

    def test_completed_retry_does_not_stage(self) -> None:
        self.storage.get_chunk_upload_state.return_value = state(
            [], complete=True, output_url="https://account/result.tif"
        )
        result = self.uploader.save_chunk(1, io.BytesIO(b"tail"), "file1", 2)
        self.assertEqual(result.outputUrl, "https://account/result.tif")
        self.storage.save_chunk.assert_not_called()

    def test_total_limit_uses_remote_not_local_state(self) -> None:
        self.storage.get_chunk_upload_state.side_effect = [
            state([0]),
            state([], 101),
        ]
        with patch(
            "hastegeo.core.processors.uploader.max_upload_bytes",
            return_value=100,
        ), self.assertRaises(ValueError):
            self.uploader.save_chunk(0, io.BytesIO(TIFF), "file1", 2)
        self.storage.discard_chunk_upload.assert_called_once()
        self.assertEqual(
            self.storage.discard_chunk_upload.call_args.kwargs["lease"],
            "lease-id",
        )

    def test_cancel_discards_remote_upload(self) -> None:
        result = self.uploader.save_chunk(
            0, io.BytesIO(b""), "file1", 2, action="cancel"
        )
        self.assertEqual(result.status, "Cancelled")
        self.storage.discard_chunk_upload.assert_called_once()

    def test_invalid_identifier_and_first_chunk_never_stage(self) -> None:
        for file_id, data in [("../file", TIFF), ("file1", b"not a tiff")]:
            with self.subTest(file_id=file_id), self.assertRaises(ValueError):
                self.uploader.save_chunk(0, io.BytesIO(data), file_id, 2)
        self.storage.save_chunk.assert_not_called()
