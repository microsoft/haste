# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License.
import os

from hastegeo.core.config import Config

from ..data_layer.unified import UnifiedDataLayer
from ..models.uploader import FileUploadRequest
from ..utils.logs import Logger
from ..utils.metadata import MetadataUtils


class FileUploader:
    def __init__(self, project_id: str, config: Config = None):
        if config is None:
            config = Config()
        if not config.DATA_DIR:
            raise ValueError("DATA_DIR is not set in the config.")
        self.storage = UnifiedDataLayer(
            storage_type=config.storage_type,
            partition_key=project_id,
            **config.storage_config,
        )
        self.logger = Logger.get_logger(__name__)
        self.config = config
        self.temp_dir = os.path.join(
            config.DATA_DIR, project_id, "file-chunks"
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
        self.logger.info(
            f"processing request for project_id: {self.project_id}, file_id: {file_id}, file chunk {chunk_number} and action {action}."
        )
        data_format = self._resolve_data_format(data_format)
        # if action equals cancel clean up the chunks and return
        if action and action.lower() == "cancel":
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
        # Create temp directory if it doesn't exist
        os.makedirs(self.temp_dir, exist_ok=True)
        # Save chunk to local disk. NOTE: eliminate this read and see how the stream can be saved directly to the storage
        chunk_path = os.path.join(
            self.temp_dir, f"{file_id}_chunk_{chunk_number}"
        )
        with open(chunk_path, "wb") as chunk_file:
            chunk_file.write(chunk_data.read())

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

    def finalize(self, file_id, total_chunks, data_format: str = None):
        data_format = self._resolve_data_format(data_format)
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
