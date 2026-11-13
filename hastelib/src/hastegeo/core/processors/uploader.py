# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License.
import os
import re

from hastegeo.core.config import Config

from ..data_layer.unified import UnifiedDataLayer
from ..models.uploader import FileUploadRequest
from ..utils.gdal_security import (
    assert_matches_declared,
    assert_matches_declared_bytes,
    max_upload_bytes,
)
from ..utils.logs import Logger
from ..utils.metadata import MetadataUtils


class FileUploader:
    _IDENTIFIER = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")

    def __init__(self, project_id: str, config: Config = None):
        if config is None:
            config = Config()
        self._validate_identifier(project_id)
        self.use_blob_staging = config.storage_type == "blob"
        if not self.use_blob_staging and not config.DATA_DIR:
            raise ValueError("DATA_DIR is not set in the config.")
        self.storage = UnifiedDataLayer(
            storage_type=config.storage_type,
            partition_key=project_id,
            **config.storage_config,
        )
        self.logger = Logger.get_logger(__name__)
        self.config = config
        self.temp_dir = os.path.join(
            config.DATA_DIR or config.TEMP_DIR, project_id, "file-chunks"
        )
        self.default_name_prefix = f"{project_id}_uploaded"
        self.project_id = project_id

    def save_chunk(
        self,
        chunk_number,
        chunk_data,
        file_id,
        total_chunks,
        action: str = "add",
        data_format: str = None,
    ):
        self._validate_identifier(file_id)
        chunk_number, total_chunks = int(chunk_number), int(total_chunks)
        if (
            not 0 < total_chunks <= 2048
            or not 0 <= chunk_number < total_chunks
        ):
            raise ValueError("Invalid upload chunk range.")
        self.logger.info(
            f"processing request for project_id: {self.project_id}, file_id: {file_id}, file chunk {chunk_number} and action {action}."
        )
        data_format = self._resolve_data_format(data_format)
        # if action equals cancel clean up the chunks and return
        if action and action.lower() == "cancel":
            if self.use_blob_staging:
                self.storage.discard_chunk_upload(
                    identifier=f"{self.default_name_prefix}_{file_id}",
                    data_type=self.config.get_metadata_types().RAW_IMAGERY.value,
                    data_format=data_format,
                    total_chunks=total_chunks,
                )
            else:
                for i in range(total_chunks):
                    self.delete_chunk(f"{file_id}_chunk_{i}")
            return FileUploadRequest(
                projectId=self.project_id,
                fileId=file_id,
                totalChunks=str(total_chunks),
                chunkNumber=str(chunk_number),
                status=self.config.get_status_types().CANCELLED.value,
                statusMessage=f"File chunk {chunk_number} of {total_chunks} upload cancelled.",
                outputUrl=None,
                updatedDate=MetadataUtils.get_timestamp(),
            )
        # Save chunk to local disk. NOTE: eliminate this read and see how the stream can be saved directly to the storage
        chunk_path = os.path.join(
            self.temp_dir, f"{file_id}_chunk_{chunk_number}"
        )
        # Size cap at the upload boundary: reject an oversized single chunk
        # outright, then reject once the cumulative upload exceeds the cap,
        # so a hostile/accidental multi-GB upload can't fill disk or OOM
        # downstream GDAL parsing (GDAL CVE compensating control —
        # docs/known-vulnerabilities.md Root Cause C).
        max_bytes = max_upload_bytes()
        data = chunk_data.read(max_bytes + 1)
        if len(data) > max_bytes:
            raise ValueError(
                f"Upload chunk exceeds the max upload size of "
                f"{max_bytes} bytes."
            )
        if chunk_number == 0:
            assert_matches_declared_bytes(data, data_format)
        if self.use_blob_staging:
            return self._save_blob_chunk(
                file_id,
                chunk_number,
                total_chunks,
                data,
                data_format,
                max_bytes,
            )
        os.makedirs(self.temp_dir, exist_ok=True)
        with open(chunk_path, "wb") as chunk_file:
            chunk_file.write(data)

        self._enforce_cumulative_size_limit(file_id, max_bytes)

        # Save chunk from local to storage
        self.storage.save_chunk(
            identifier=f"{self.default_name_prefix}_{file_id}",
            data_type=self.config.get_metadata_types().RAW_IMAGERY.value,
            data_file_path=chunk_path,
            chunk_id=chunk_number,
            data_format=data_format,
        )

        # Check if all chunks are saved
        all_chunks_saved = total_chunks - 1
        if chunk_number == all_chunks_saved:
            output_url = self.finalize(
                file_id, total_chunks, data_format=data_format
            )
            self.logger.info(f"uploaded {total_chunks} successfully.")
            return FileUploadRequest(
                projectId=self.project_id,
                fileId=file_id,
                totalChunks=str(total_chunks),
                chunkNumber=str(chunk_number),
                status=self.config.get_status_types().COMPLETED.value,
                statusMessage=f"File chunk {chunk_number} of {total_chunks} uploaded successfully.",
                outputUrl=output_url,
                updatedDate=MetadataUtils.get_timestamp(),
            )
        self.logger.info(
            f"uploaded {chunk_number} of {total_chunks} successfully."
        )
        return FileUploadRequest(
            projectId=self.project_id,
            fileId=file_id,
            totalChunks=str(total_chunks),
            chunkNumber=str(chunk_number),
            status=self.config.get_status_types().IN_PROGRESS.value,
            statusMessage=f"File chunk {chunk_number} of {total_chunks} uploaded successfully.",
            outputUrl=None,
            updatedDate=MetadataUtils.get_timestamp(),
        )

    @classmethod
    def _validate_identifier(cls, value: str) -> None:
        if not isinstance(value, str) or not cls._IDENTIFIER.fullmatch(value):
            raise ValueError("Upload identifier contains invalid characters.")

    def _save_blob_chunk(
        self,
        file_id: str,
        chunk_number: int,
        total_chunks: int,
        data: bytes,
        data_format: str,
        max_bytes: int,
    ) -> FileUploadRequest:
        kwargs = {
            "identifier": f"{self.default_name_prefix}_{file_id}",
            "data_type": self.config.get_metadata_types().RAW_IMAGERY.value,
            "data_format": data_format,
            "total_chunks": total_chunks,
        }
        state = self.storage.get_chunk_upload_state(**kwargs)
        if not state["complete"]:
            self.storage.save_chunk(
                identifier=kwargs["identifier"],
                data_type=kwargs["data_type"],
                data_format=data_format,
                data=data,
                chunk_id=chunk_number,
            )
            state = self.storage.get_chunk_upload_state(**kwargs)
            if state["total_size"] > max_bytes or state["unexpected"]:
                self.storage.discard_chunk_upload(**kwargs)
                raise ValueError("Upload exceeds size or chunk limits.")
            if not state["missing"]:
                state["output_url"] = self.storage.finalize_save(**kwargs)
                state["complete"] = True
        statuses = self.config.get_status_types()
        return FileUploadRequest(
            projectId=self.project_id,
            fileId=file_id,
            totalChunks=str(total_chunks),
            chunkNumber=str(chunk_number),
            status=(
                statuses.COMPLETED.value
                if state["complete"]
                else statuses.IN_PROGRESS.value
            ),
            statusMessage=(
                "Upload completed." if state["complete"] else "Chunk staged."
            ),
            outputUrl=state["output_url"],
            updatedDate=MetadataUtils.get_timestamp(),
        )

    def finalize(self, file_id, total_chunks, data_format: str = None):
        data_format = self._resolve_data_format(data_format)
        # Content/type check at the upload boundary: the assembled file
        # must actually be the declared format, so a hostile client cannot
        # upload e.g. an HDF4 file as ".tif" and have GDAL parse it (GDAL
        # CVE compensating control — docs/known-vulnerabilities.md C).
        self._assert_content_matches_declared(file_id, data_format)
        identifier = f"{self.default_name_prefix}_{file_id}"
        output_remote_path = self.storage.finalize_save(
            identifier=identifier,
            data_type=self.config.get_metadata_types().RAW_IMAGERY.value,
            data_format=data_format,
            total_chunks=total_chunks,
        )
        # Clean up local chunks after upload
        for i in range(total_chunks):
            self.delete_chunk(f"{file_id}_chunk_{i}")
        return output_remote_path

    def _resolve_data_format(self, data_format):
        """Normalize and validate the chunked-upload data format.

        Accepts ``None`` (back-compat default of ``tif``), ``tif``,
        ``tiff``, ``geotiff`` (all normalize to ``tif``), and ``gpkg``.
        Raises ValueError for anything else so a hostile client cannot
        smuggle arbitrary extensions through the blob-path construction.
        """
        formats = self.config.get_data_formats()
        if data_format is None:
            return formats.TIF.value
        normalized = data_format.strip().lower()
        if normalized in ("tif", "tiff", "geotiff"):
            return formats.TIF.value
        if normalized == "gpkg":
            return formats.GPKG.value
        raise ValueError(
            f"Unsupported chunked-upload data_format: {data_format!r}"
        )

    def _local_chunk_paths(self, file_id):
        """Return the locally-staged chunk paths for ``file_id``, sorted."""
        import glob

        pattern = os.path.join(self.temp_dir, f"{file_id}_chunk_*")
        return sorted(glob.glob(pattern))

    def _enforce_cumulative_size_limit(self, file_id, max_bytes):
        """Reject (and clean up) once the staged chunks exceed ``max_bytes``.

        Bounds total upload size so a hostile/accidental multi-GB upload
        can't fill disk or OOM downstream GDAL parsing.
        """
        total = 0
        for path in self._local_chunk_paths(file_id):
            try:
                total += os.path.getsize(path)
            except OSError:
                continue
        if total > max_bytes:
            for path in self._local_chunk_paths(file_id):
                try:
                    os.remove(path)
                except OSError:
                    pass
            raise ValueError(
                f"Upload exceeds the max upload size of {max_bytes} bytes."
            )

    def _assert_content_matches_declared(self, file_id, data_format):
        """Verify the assembled file's magic bytes match ``data_format``.

        Reads the head of the first staged chunk (the start of the file).
        Skips silently if no local chunk is present (e.g. a finalize with
        no local staging) rather than blocking a legitimate finalize.
        """
        chunk0 = os.path.join(self.temp_dir, f"{file_id}_chunk_0")
        if not os.path.exists(chunk0):
            return
        assert_matches_declared(chunk0, data_format)

    def get_chunk(self, chunk_key):
        chunk_path = os.path.join(self.temp_dir, chunk_key)
        if os.path.exists(chunk_path):
            with open(chunk_path, "rb") as chunk_file:
                return chunk_file.read()
        return None

    def delete_chunk(self, chunk_key):
        chunk_path = os.path.join(self.temp_dir, chunk_key)
        if os.path.exists(chunk_path):
            os.remove(chunk_path)
