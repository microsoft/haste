# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License.

"""Building-embedding job: queue + execute the MOSAIKS embedding workflow.

Mirrors the imagery preprocessing pipeline (``processors/imagery.py``): a
``Model`` with ``modelType="embedding"`` is the unit of work. The preprocessor
enqueues it; the postprocessor submits a task to the *training* docker image
running ``embed-buildings`` (the workflow module ``embed_buildings.py``), polls
it, and on completion records the embeddings GeoJSON + PMTiles artifact URLs on
the model so the interactive labeler can load them.
"""

import json
import os

from ..config import ArtifactTypes, Config
from ..data_layer.unified import UnifiedDataLayer
from ..models.projects import ImageLayer, Model, TrainingJob
from ..runners.unified_runner import UnifiedRunner
from ..utils.data import extract_from_url
from ..utils.logs import Logger
from ..utils.metadata import MetadataUtils
from ..utils.queues import AzureQueueHandler

# Do not prefix with '$'. Replaced at runtime with the task working directory.
BATCH_JOB_WORKDIR = "AZ_BATCH_TASK_WORKING_DIR"
EMBEDDING_PREFIX = "emb"


class EmbeddingPreprocessor:
    def __init__(self, model: Model, config: Config = None):
        if config is None:
            config = Config()
        self.queue_client = AzureQueueHandler(
            config.queue_config["queue_connection_string"],
            config.queue_config["embedding_queue_name"],
            config.queue_config["queue_account_url"],
        )
        self.model_data = model
        self.config = config

    def send_to_queue(self):
        self.model_data.status = self.config.get_status_types().PENDING.value
        self.model_data.currentStep = 0
        self.model_data.progressPct = 0.0
        # 3 friendly steps: submit -> embedding -> tiling/finalize.
        self.model_data.totalSteps = 3
        self.queue_client.put_message(json.dumps(self.model_data.dict()))
        self.model_data.statusMessage = MetadataUtils.append_status_message(
            self.model_data.statusMessage, "Queued for embedding"
        )
        return self.model_data


class EmbeddingPostprocessor:
    def __init__(
        self,
        model: Model,
        image_layer: ImageLayer = None,
        config: Config = None,
    ):
        if config is None:
            config = Config()
        self.config = config
        self.model_data = model
        self.image_layer = image_layer
        self.storage = UnifiedDataLayer(
            storage_type=config.storage_type,
            partition_key=model.projectId,
            **config.storage_config,
        )
        self.logger = Logger.get_logger(__name__)
        self.runner = UnifiedRunner(
            runner_type=config.runner_type,
            config=self.config,
            pool_id=self.config.get_azure_batch_config()["training_pool_id"],
            candidate_pool_ids=self.config.get_azure_batch_config()[
                "training_pool_ids"
            ],
        )
        self.queue_client = AzureQueueHandler(
            config.queue_config["queue_connection_string"],
            config.queue_config["embedding_queue_name"],
            config.queue_config["queue_account_url"],
        )

    def process(self):
        self.logger.info(
            f"{self.__class__.__name__}.process: model "
            f"{self.model_data.modelId} status {self.model_data.status}"
        )

        if (
            self.model_data.status
            == self.config.get_status_types().PENDING.value
        ):
            self._update_progress("Submitting embedding job", step=0)
            self.model_data = self._execute_embedding()

        elif (
            self.model_data.status
            == self.config.get_status_types().IN_PROGRESS.value
        ):
            task_status = self.runner.get_task_status(
                job_id=self.model_data.embeddingJob.jobId,
                task_id=self.model_data.embeddingJob.taskId,
            )
            self.logger.info(
                f"Task status for embedding model "
                f"{self.model_data.modelId} is {task_status}"
            )

            if task_status == self.config.get_status_types().COMPLETED.value:
                self.model_data.status = task_status
                self.model_data.embeddingJob.status = task_status
                self.model_data.embeddingJob.completedDate = (
                    MetadataUtils.get_timestamp()
                )
                self._update_results_from_job()
                for log in self._get_friendly_logs():
                    if log[1] not in self.model_data.statusMessage:
                        self._update_progress(log[1], timestamp=log[0])
                self.runner.cleanup_task(
                    job_id=self.model_data.embeddingJob.jobId,
                    task_id=self.model_data.embeddingJob.taskId,
                )

            elif task_status == self.config.get_status_types().FAILED.value:
                self.model_data.status = task_status
                self.model_data.embeddingJob.status = task_status
                self.model_data.embeddingJob.completedDate = (
                    MetadataUtils.get_timestamp()
                )
                for log in self._get_friendly_logs():
                    if log[1] not in self.model_data.statusMessage:
                        self._update_progress(log[1], timestamp=log[0])
                self._update_progress(
                    "Embedding job failed", step=self.model_data.currentStep
                )
                self.runner.cleanup_task(
                    job_id=self.model_data.embeddingJob.jobId,
                    task_id=self.model_data.embeddingJob.taskId,
                )
            else:
                self.model_data.status = task_status
                self.model_data.embeddingJob.status = task_status
                self.queue_client.put_message(
                    json.dumps(self.model_data.dict())
                )

        return self.model_data

    def _execute_embedding(self):
        try:
            input_files = self._create_embedding_config()
            command = (
                f'"mkdir -p ${BATCH_JOB_WORKDIR} '
                f"&& cd ${BATCH_JOB_WORKDIR} "
                f"&& embed-buildings --config "
                f'${BATCH_JOB_WORKDIR}/{input_files["config"]["file_path"]}'
                '"'
            )
            job_id = self.config.get_azure_batch_config()[
                "training_batch_job_id"
            ][:64]
            task_id = f"{EMBEDDING_PREFIX}-{MetadataUtils.generate_id()}"
            output_prefix = (
                f"{MetadataUtils.hash_string(self.model_data.projectId)}"
                f"/{task_id}"
            )
            job_id, task_id = self.runner.add_task(
                job_id=job_id,
                task_id=task_id,
                output_prefix=output_prefix,
                resource_files_for_upload=input_files,
                file_pattern=f"${BATCH_JOB_WORKDIR}/outputs/*.*",
                command=command,
                image_name=self.config.get_azure_batch_config()[
                    "docker_image"
                ],
            )
            self.model_data.embeddingJob = TrainingJob(
                jobId=job_id,
                taskId=task_id,
                modelId=self.model_data.modelId,
                projectId=self.model_data.projectId,
                status=self.config.get_status_types().IN_PROGRESS.value,
                creationDate=MetadataUtils.get_timestamp(),
            )
            self.model_data.status = (
                self.config.get_status_types().IN_PROGRESS.value
            )
            self._update_progress(
                f"Embedding submitted with task id {task_id}", step=1
            )
            self.queue_client.put_message(json.dumps(self.model_data.dict()))
        except Exception as e:
            self.logger.error(
                f"Error executing embedding for model "
                f"{self.model_data.modelId}: {e}",
                stack_info=True,
            )
            self.model_data.status = (
                self.config.get_status_types().FAILED.value
            )
            self._update_progress(
                f"Embedding job failed: {e}", step=self.model_data.currentStep
            )
        return self.model_data

    def _create_embedding_config(self):
        filename_pattern = (
            rf"{MetadataUtils.hash_string(self.model_data.projectId)}/(.*)\?+"
        )
        plain_url_pattern = r"(.*)\?+"

        imagery_url = self.image_layer.postEventMosaicCogImageryUrl
        footprints_url = self.image_layer.buildingFootprintsUrl
        if not imagery_url:
            raise ValueError("Image layer has no post-event mosaic COG.")
        if not footprints_url:
            raise ValueError("Image layer has no building footprints.")

        imagery_fn = (
            f"inputs/{extract_from_url(imagery_url, filename_pattern)}"
        )
        footprints_fn = (
            f"inputs/{extract_from_url(footprints_url, filename_pattern)}"
        )

        embeddings_name = (
            ArtifactTypes.BUILDING_EMBEDDINGS.value.substitute(
                modelName=self.model_data.modelId
            )
            + ".geojson"
        )
        sidecar_name = (
            ArtifactTypes.BUILDING_FEATURES_SIDECAR.value.substitute(
                modelName=self.model_data.modelId
            )
            + ".bin"
        )

        embedding_config = {
            "project_id": self.model_data.projectId,
            "image_layer_id": self.model_data.imageLayerId,
            "model_id": self.model_data.modelId,
            "output_dir": "outputs",
            # Relative to the task working dir: the command cd's into
            # $AZ_BATCH_TASK_WORKING_DIR before running embed-buildings, whose
            # WORKDIR defaults to ".". No env-var substitution step needed.
            "files": {
                "imagery": imagery_fn,
                "footprints": footprints_fn,
                "embeddings": embeddings_name,
                "sidecar": sidecar_name,
            },
            "pipeline": {
                "model": self.model_data.embeddingModel or "mosaiks",
                "num_feats": self.model_data.numFeatures or 1024,
                "resize_factor": self.model_data.resizeFactor or 4,
                "batch_size": int(self.model_data.batchSize or 16),
            },
        }
        self.storage.save(
            identifier=self.model_data.modelId,
            data=embedding_config,
            data_type=self.config.get_metadata_types().EMBEDDING_CONFIG.value,
            data_format="json",
        )
        config_filepath = self.storage.get_file_remote_path(
            self.model_data.modelId,
            self.config.get_metadata_types().EMBEDDING_CONFIG.value,
            data_format="json",
        )

        input_files = {
            "config": {
                "http_url": extract_from_url(
                    config_filepath, plain_url_pattern
                ),
                "file_path": f"inputs/{extract_from_url(config_filepath, filename_pattern)}",
            },
            "imagery": {
                "http_url": extract_from_url(imagery_url, plain_url_pattern),
                "file_path": imagery_fn,
            },
            "footprints": {
                "http_url": extract_from_url(
                    footprints_url, plain_url_pattern
                ),
                "file_path": footprints_fn,
            },
        }
        return input_files

    def _update_results_from_job(self):
        content = self.runner.get_filecontent_from_task(
            job_id=self.model_data.embeddingJob.jobId,
            task_id=self.model_data.embeddingJob.taskId,
            filename="embedding_manifest.json",
        )
        if not content:
            raise FileNotFoundError(
                f"Embedding manifest not found for model "
                f"{self.model_data.modelId}"
            )
        manifest = json.loads(content)
        self.model_data.embeddingsGeoJSONUrl = self._artifact_url(
            manifest.get("embeddings_filename", "")
        )
        self.model_data.featuresSidecarUrl = self._artifact_url(
            manifest.get("sidecar_filename", "")
        )
        self._update_progress(
            f"Embedded {manifest.get('num_buildings', '?')} buildings "
            f"with {manifest.get('num_features', '?')} features",
            step=self.model_data.totalSteps,
        )

    def _artifact_url(self, filename: str) -> str:
        if not filename:
            return ""
        return self.storage.get_file_remote_path(
            identifier=filename,
            extra_partition_keys=f"{self.model_data.embeddingJob.taskId}",
            data_format=os.path.splitext(filename)[1].strip("."),
        )

    def _get_friendly_logs(self):
        content = self.runner.get_filecontent_from_task(
            job_id=self.model_data.embeddingJob.jobId,
            task_id=self.model_data.embeddingJob.taskId,
            filename="embedding_friendly.log",
        )
        logs = []
        if content:
            for record in content.splitlines():
                if not record:
                    continue
                parts = record.split("|", 1)
                if len(parts) == 2:
                    logs.append((parts[0], parts[1]))
        return logs

    def _update_progress(
        self, message: str, step: int = None, timestamp: str = None
    ):
        if step is not None:
            self.model_data.currentStep = int(step)
        else:
            self.model_data.currentStep += 1
        total = int(self.model_data.totalSteps or 1)
        self.model_data.progressPct = round(
            int(self.model_data.currentStep) / total * 100, 2
        )
        self.model_data.statusMessage = MetadataUtils.append_status_message(
            self.model_data.statusMessage, message, timestamp=timestamp
        )
