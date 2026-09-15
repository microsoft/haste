# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License.

"""Drive the existing zip workflow with a catalog run's stable task identity."""

from collections.abc import Callable
from pathlib import PurePosixPath

from ..artifact_storage.unified_artifact_storage import UnifiedArtifactStorage
from ..config import Config
from ..models.projects import Model, ModelArtifacts, ZipJob
from ..runners.unified_runner import UnifiedRunner
from ..utils.catalog_lock import catalog_task_id
from ..utils.logs import Logger
from ..utils.metadata import MetadataUtils
from .catalog_metadata import CatalogMetadataProcessor


class CatalogArtifactProcessor:
    def __init__(self, config: Config) -> None:
        self.config = config
        self.storage = UnifiedArtifactStorage(
            config.artifact_storage_type, **config.artifact_storage_config
        )

    def process(
        self, model: Model, poll: Callable[[Model, int], None]
    ) -> ModelArtifacts:
        metadata = CatalogMetadataProcessor(
            self.config.get_metadata_types().MODEL_ARTIFACTS.value,
            model.projectId,
            self.config,
        )
        try:
            artifacts = ModelArtifacts.model_validate(
                metadata.load(model.modelId)
            )
        except FileNotFoundError:
            artifacts = ModelArtifacts(
                modelId=model.modelId,
                projectId=model.projectId,
                imageLayerId=model.imageLayerId,
                zipStatus="Queued",
            )
        if artifacts.zipStatus in ("Processed", "Failed"):
            return artifacts
        task_id = artifacts.currentZipJobUid or catalog_task_id(
            model.projectId, model.inferenceRequestId, "zip"
        )
        prefix = f"{MetadataUtils.hash_string(model.projectId)}/{task_id}"
        name = (
            self.config.get_artifact_types().INFERENCE_ARTIFACTS_ZIP.value.substitute(
                modelName=model.name
            )
            + ".zip"
        )
        try:
            if not artifacts.zipJobs:
                artifacts.zipJobs = [
                    ZipJob(
                        projectId=model.projectId,
                        modelId=model.modelId,
                        imageLayerId=model.imageLayerId,
                        jobId=task_id,
                        taskId=task_id,
                        status="InProgress",
                        srcArtifactPaths=[model.inferenceOutputPath],
                        dstZipPath=prefix,
                        creationDate=MetadataUtils.get_timestamp(),
                    )
                ]
            artifacts.currentZipJobUid = task_id
            artifacts.zipStatus = "InProgress"
            artifacts.zipStatusMessage = "Packaging inference artifacts"
            metadata.save(model.modelId, artifacts.model_dump(mode="json"))
            poll(model, 30)
            runner = UnifiedRunner(
                runner_type=self.config.runner_type,
                config=self.config,
                pool_id=self.config.get_azure_batch_config()[
                    "imageprep_pool_id"
                ],
                candidate_pool_ids=self.config.get_azure_batch_config()[
                    "imageryprep_pool_ids"
                ],
            )
            runner.add_task(
                job_id=task_id,
                task_id=task_id,
                idempotent=True,
                output_prefix=prefix,
                resource_files_for_upload={
                    "inference": {
                        "storage_container_url": self.storage.get_base_url(),
                        "blob_prefix": model.inferenceOutputPath,
                        "file_path": "inputs/",
                    }
                },
                file_pattern="$AZ_BATCH_TASK_WORKING_DIR/outputs/*.*",
                command='"python -m hastegeo.workflows.zip_artifacts"',
                image_name=self.config.get_azure_batch_config()[
                    "imageprep_docker_image"
                ],
                env_vars={
                    "INPUT_DIR": f"inputs/{MetadataUtils.hash_string(model.projectId)}",
                    "OUTPUT_INFERENCE_ZIP_NAME": name,
                },
            )
            status = runner.get_task_status(task_id, task_id)
            artifacts.zipJobs[-1].status = status
            if status == "Processed":
                path = str(PurePosixPath(prefix, name))
                if (
                    not self.storage.artifact_exists(path)
                    or self.storage.get_artifact_size(path) <= 0
                ):
                    raise ValueError(
                        "Archive task completed without its expected zip"
                    )
                artifacts.inferenceZipUrl = self.storage.get_download_url(
                    identifier=path
                )
                artifacts.inferenceZipSize = self.storage.get_artifact_size(
                    path
                )
                artifacts.zipUrl = artifacts.inferenceZipUrl
                artifacts.zipStatus = "Processed"
                artifacts.zipStatusMessage = "Inference artifacts ready"
            elif status == "Failed":
                artifacts.zipStatus = "Failed"
                artifacts.zipStatusMessage = (
                    "Inference artifact packaging failed"
                )
            artifacts.zipFailures = 0
            if artifacts.zipStatus in ("Processed", "Failed"):
                artifacts.zipJobs[
                    -1
                ].completedDate = MetadataUtils.get_timestamp()
            metadata.save(model.modelId, artifacts.model_dump(mode="json"))
            if artifacts.zipStatus in ("Processed", "Failed"):
                runner.cleanup_task(task_id, task_id)
        except Exception as error:
            Logger.get_logger(__name__).error(
                "Catalog archive processing failed (%s)", type(error).__name__
            )
            if artifacts.zipStatus in ("Processed", "Failed"):
                return artifacts
            artifacts.zipFailures += 1
            if isinstance(error, ValueError) or artifacts.zipFailures >= 5:
                artifacts.zipStatus = "Failed"
            artifacts.zipStatusMessage = (
                f"Artifact packaging encountered {type(error).__name__}"
            )
            metadata.save(model.modelId, artifacts.model_dump(mode="json"))
            if artifacts.zipStatus != "Failed":
                poll(model, 30)
        return artifacts
