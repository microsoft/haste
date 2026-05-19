# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License.
import json

from hastegeo.core.artifact_storage.unified_artifact_storage import (
    UnifiedArtifactStorage,
)
from hastegeo.core.config import Config
from hastegeo.core.models.projects import Model, ModelArtifacts, ZipJob
from hastegeo.core.runners.unified_runner import UnifiedRunner
from hastegeo.core.utils.logs import Logger
from hastegeo.core.utils.metadata import MetadataUtils
from hastegeo.core.utils.queues import AzureQueueHandler

BATCH_JOB_WORKDIR = "AZ_BATCH_TASK_WORKING_DIR"
ZIP_PREFIX = "zip"


class ArtifactProcessor:
    def __init__(
        self,
        partition_key: str = None,
        config: Config = None,
        model: Model = None,
        model_artifacts: ModelArtifacts = None,
    ):
        self.config = config or Config()
        self.storage = UnifiedArtifactStorage(
            storage_type=self.config.artifact_storage_type,
            partition_key=partition_key,
            **self.config.artifact_storage_config,
        )
        self.logger = Logger.get_logger(__name__)
        self.queue_client = AzureQueueHandler(
            self.config.queue_config["queue_connection_string"],
            self.config.queue_config["zip_queue_name"],
            self.config.queue_config["queue_account_url"],
        )
        self.model_data = model
        self.runner = UnifiedRunner(
            runner_type=self.config.runner_type,
            config=self.config,
            pool_id=self.config.get_azure_batch_config()["imageprep_pool_id"],
        )
        self.model_artifacts = model_artifacts
        if self.model_data is not None:
            safe_name = self.model_data.name.replace(" ", "-")
            self.zip_name = self.config.get_artifact_types().MODEL_ARTIFACTS_ZIP.value.substitute(
                modelName=safe_name
            )
            self.training_zip_name = self.config.get_artifact_types().TRAINING_ARTIFACTS_ZIP.value.substitute(
                modelName=safe_name
            )
            self.inference_zip_name = self.config.get_artifact_types().INFERENCE_ARTIFACTS_ZIP.value.substitute(
                modelName=safe_name
            )

    def get_download_url(
        self,
        identifier=None,
        artifact_path=None,
        extra_partition_keys=None,
    ):
        """
        Get the download URL for the artifact.
        """
        return self.storage.get_download_url(
            identifier=identifier,
            artifact_path=artifact_path,
            extra_partition_keys=extra_partition_keys,
        )

    def send_to_zip_queue(self):
        """
        Put a message to the queue.
        """
        self.model_artifacts.zipStatus = (
            self.config.get_status_types().PENDING.value
        )
        self.model_artifacts.zipStatusMessage = (
            MetadataUtils.append_status_message("", "Queued for zipping")
        )
        self.model_artifacts.zipUrl = None
        self.model_artifacts.currentZipJobUid = None
        # Setting visibility timeout to 0 to make sure the message is processed immediately
        self.queue_client.put_message(
            json.dumps(self.model_artifacts.dict()), visibility_timeout=0
        )
        return self.model_artifacts

    def process_zip(self):
        self.logger.info(
            f"{self.__class__.__name__}.process: Processing artifacts for "
            f"model {self.model_artifacts.modelId} with status "
            f"{self.model_artifacts.zipStatus}"
        )

        if (
            self.model_artifacts.zipStatus
            == self.config.get_status_types().PENDING.value
        ):
            self.logger.info(
                f"Zipping artifacts for model {self.model_artifacts.modelId}"
            )
            self._update_zip_progress("Submitting zip task")
            self.model_artifacts = self.submit_zip_job()
        elif (
            self.model_artifacts.zipStatus
            == self.config.get_status_types().IN_PROGRESS.value
        ):
            for idx, zip_job in enumerate(self.model_artifacts.zipJobs):
                if zip_job.taskId == self.model_artifacts.currentZipJobUid:
                    break
            task_status = self.runner.get_task_status(
                job_id=self.model_artifacts.zipJobs[idx].jobId,
                task_id=self.model_artifacts.zipJobs[idx].taskId,
            )

            self.logger.info(
                f"Task status of zip job for model {self.model_artifacts.modelId} is {task_status}"
            )

            if task_status == self.config.get_status_types().COMPLETED.value:
                self.model_artifacts.zipStatus = task_status
                self.model_artifacts.zipJobs[idx].status = task_status
                self.model_artifacts.zipJobs[
                    idx
                ].completedDate = MetadataUtils.get_timestamp()

                # Read the zip manifest to get individual zip URLs and sizes
                zip_task_id = self.model_artifacts.zipJobs[idx].taskId
                zip_prefix = self.model_artifacts.zipJobs[idx].dstZipPath
                try:
                    manifest_data = self._read_zip_manifest(zip_prefix)
                except Exception as e:
                    self.logger.warning(
                        f"Could not read zip manifest: {e}; "
                        "falling back to combined zip URL"
                    )
                    manifest_data = {}

                if "training_zip" in manifest_data:
                    self.model_artifacts.trainingZipUrl = (
                        self.storage.get_download_url(
                            identifier=manifest_data["training_zip"][
                                "filename"
                            ],
                            extra_partition_keys=zip_task_id,
                        )
                    )
                    self.model_artifacts.trainingZipSize = manifest_data[
                        "training_zip"
                    ]["size_bytes"]

                if "inference_zip" in manifest_data:
                    self.model_artifacts.inferenceZipUrl = (
                        self.storage.get_download_url(
                            identifier=manifest_data["inference_zip"][
                                "filename"
                            ],
                            extra_partition_keys=zip_task_id,
                        )
                    )
                    self.model_artifacts.inferenceZipSize = manifest_data[
                        "inference_zip"
                    ]["size_bytes"]

                # Keep legacy zipUrl pointing at the training zip for
                # backwards compatibility with older UI versions.
                self.model_artifacts.zipUrl = (
                    self.model_artifacts.trainingZipUrl
                    or self.model_artifacts.inferenceZipUrl
                )

                self._update_zip_progress(
                    "Zipping artifacts completed successfully"
                )
                self.model_artifacts.zipJobs[
                    idx
                ].logs = self.model_artifacts.zipStatusMessage
                # Cleanup the task on the runner
                self.runner.cleanup_task(
                    job_id=self.model_artifacts.zipJobs[idx].jobId,
                    task_id=self.model_artifacts.zipJobs[idx].taskId,
                )

            elif task_status == self.config.get_status_types().FAILED.value:
                self.model_artifacts.zipStatus = task_status
                self.model_artifacts.zipJobs[idx].status = task_status
                self.model_artifacts.zipJobs[
                    idx
                ].completedDate = MetadataUtils.get_timestamp()
                self._update_zip_progress("Zip job failed")
                self.model_artifacts.zipJobs[
                    idx
                ].logs = self.model_artifacts.zipStatusMessage
                # Cleanup the task on the runner
                self.runner.cleanup_task(
                    job_id=self.model_artifacts.zipJobs[idx].jobId,
                    task_id=self.model_artifacts.zipJobs[idx].taskId,
                )
            else:
                self.model_artifacts.zipStatus = task_status
                self.model_artifacts.zipJobs[idx].status = task_status
                self._update_zip_progress("Zipping in progress")
                self.model_artifacts.zipJobs[
                    idx
                ].logs = self.model_artifacts.zipStatusMessage
                self.queue_client.put_message(
                    json.dumps(self.model_artifacts.dict())
                )
        else:
            self.model_artifacts.zipStatus = (
                self.config.get_status_types().FAILED.value
            )
            self.logger.info(
                f"Model {self.model_artifacts.modelId} is not ready for zipping"
            )

        return self.model_artifacts

    def fetch_artifact(
        self,
        identifier: str = None,
        extra_partition_keys: list | str = None,
        src_path: str = None,
        dst_path: str = None,
    ) -> str:
        """
        Download the artifact from the storage.
        """
        return self.storage.fetch_artifact(
            identifier=identifier,
            extra_partition_keys=extra_partition_keys,
            src_path=src_path,
            dst_path=dst_path,
        )

    def store_artifact(
        self,
        artifact_name: str,
        data: str = None,
        src_path: str = None,
        namespace: str | list = None,
    ) -> str:
        """
        Store an artifact in artifact storage.
        """
        return self.storage.store_artifact(
            artifact_name=artifact_name,
            data=data,
            src_path=src_path,
            namespace=namespace,
        )

    def prepare_zip_job(self):
        zip_input_files = {}
        if self.model_data.trainingOutputPath:
            zip_input_files["training"] = {
                "storage_container_url": f"{self.storage.get_base_url()}",
                "blob_prefix": self.model_data.trainingOutputPath,
                "file_path": "inputs/",
            }

        if self.model_data.inferenceOutputPath:
            zip_input_files["inference"] = {
                "storage_container_url": f"{self.storage.get_base_url()}",
                "blob_prefix": self.model_data.inferenceOutputPath,
                "file_path": "inputs/",
            }
        return zip_input_files

    def submit_zip_job(self):
        try:
            self.logger.info(
                f"Adding task for artifact zipping {self.model_artifacts.modelId}"
            )
            zip_input_files = self.prepare_zip_job()
            command = '"python -m hastegeo.workflows.zip_artifacts"'
            job_id = self.config.get_azure_batch_config()[
                "artifact_batch_job_id"
            ]
            # Trim job_id to 64 characters to comply with Azure Batch limits
            job_id = job_id[:64]
            task_id = f"{ZIP_PREFIX}-{MetadataUtils.generate_id()}"
            zip_output_prefix = f"{MetadataUtils.hash_string(self.model_artifacts.projectId)}/{task_id}"

            self.runner.add_task(
                job_id=job_id,
                task_id=task_id,
                output_prefix=zip_output_prefix,
                resource_files_for_upload=zip_input_files,
                file_pattern=f"${BATCH_JOB_WORKDIR}/outputs/*.*",
                command=command,
                image_name=self.config.get_azure_batch_config()[
                    "imageprep_docker_image"
                ],
                env_vars={
                    "INPUT_DIR": f"inputs/{MetadataUtils.hash_string(self.model_artifacts.projectId)}",
                    "OUTPUT_TRAINING_ZIP_NAME": f"{self.training_zip_name}",
                    "OUTPUT_INFERENCE_ZIP_NAME": f"{self.inference_zip_name}",
                },
            )
            self.logger.info(
                f"Completed add task {task_id} to job id {job_id} for zipping artifacts of model {self.model_artifacts.modelId}"
            )
            srcArtifactPaths = []
            if self.model_data.trainingOutputPath:
                srcArtifactPaths.append(self.model_data.trainingOutputPath)
            if self.model_data.inferenceOutputPath:
                srcArtifactPaths.append(self.model_data.inferenceOutputPath)
            self.model_artifacts.zipJobs.append(
                ZipJob(
                    projectId=self.model_artifacts.projectId,
                    imageLayerId=self.model_artifacts.imageLayerId,
                    modelId=self.model_artifacts.modelId,
                    jobId=job_id,
                    taskId=task_id,
                    status=self.config.get_status_types().IN_PROGRESS.value,
                    srcArtifactPaths=srcArtifactPaths,
                    dstZipPath=zip_output_prefix,
                    creationDate=MetadataUtils.get_timestamp(),
                )
            )
            self.model_artifacts.currentZipJobUid = task_id
            self.model_artifacts.zipStatus = (
                self.config.get_status_types().IN_PROGRESS.value
            )
            self._update_zip_progress(
                f"Zipping submitted with task id {task_id}"
            )
            self.queue_client.put_message(
                json.dumps(self.model_artifacts.dict())
            )
            self.logger.info(
                f"InProgress message to queue sent for model {self.model_artifacts.modelId}"
            )
        except Exception as e:
            self.logger.error(
                f"Error processing model {self.model_artifacts.modelId}: {e}",
                stack_info=True,
            )
            self.model_artifacts.zipStatus = (
                self.config.get_status_types().FAILED.value
            )

        return self.model_artifacts

    def _read_zip_manifest(self, zip_prefix: str) -> dict:
        """Read the zip_manifest.json produced by zip_artifacts.py."""
        blob_path = f"{zip_prefix}/zip_manifest.json"
        blob_client = (
            self.storage.artifact_storage.container_client.get_blob_client(
                blob_path
            )
        )
        data = blob_client.download_blob().readall()
        return json.loads(data)

    def _update_zip_progress(self, message: str, timestamp: str = None):
        self.model_artifacts.zipStatusMessage = (
            MetadataUtils.append_status_message(
                self.model_artifacts.zipStatusMessage,
                message,
                timestamp=timestamp,
            )
        )
