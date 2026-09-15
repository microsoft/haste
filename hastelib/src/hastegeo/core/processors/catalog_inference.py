# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License.

"""Inference-only runs sharing HASTE's queue, runners and output pipeline."""

import hashlib
import json
import re
from copy import deepcopy
from pathlib import PurePosixPath
from tempfile import NamedTemporaryFile
from urllib.parse import urlsplit, urlunsplit

import yaml

from ..config import Config
from ..models.pretrained_inference import CatalogInferenceRequest
from ..models.projects import ImageLayer, InferenceJob, Model
from ..publishing.lease import LeaseUnavailableError
from ..runners.unified_runner import UnifiedRunner
from ..utils.catalog_lock import catalog_lock, catalog_task_id
from ..utils.logs import Logger
from ..utils.metadata import MetadataUtils
from ..utils.queues import AzureQueueHandler
from .catalog_artifacts import CatalogArtifactProcessor
from .catalog_metadata import CatalogMetadataProcessor
from .model_catalog import CatalogConflictError, ModelCatalogProcessor

WORKDIR = "AZ_BATCH_TASK_WORKING_DIR"


class CatalogInferenceOutputError(RuntimeError):
    pass


def request_fingerprint(request: CatalogInferenceRequest) -> str:
    data = request.model_dump(mode="json", exclude={"clientRequestId"})
    data["baseModelName"] = data["baseModelName"].casefold()
    return hashlib.sha256(
        json.dumps(data, sort_keys=True).encode()
    ).hexdigest()


class CatalogInferenceProcessor:
    def __init__(self, config: Config | None = None) -> None:
        self.config = config or Config()
        self.catalog = ModelCatalogProcessor(self.config)
        self.artifacts = self.catalog.artifacts
        self.logger = Logger.get_logger(__name__)

    def metadata(self, project_id: str) -> CatalogMetadataProcessor:
        return CatalogMetadataProcessor(
            self.config.get_metadata_types().MODEL.value,
            project_id,
            self.config,
        )

    def _queue(self, model: Model, delay: int = 0) -> None:
        queue = self.config.queue_config
        AzureQueueHandler(
            queue["queue_connection_string"],
            queue["inference_queue_name"],
            queue["queue_account_url"],
        ).put_message(
            json.dumps(
                {
                    "projectId": model.projectId,
                    "modelId": model.modelId,
                    "inferenceRequestId": model.inferenceRequestId,
                }
            ),
            visibility_timeout=delay,
        )

    def start(self, request: CatalogInferenceRequest, user_id: str) -> Model:
        metadata = self.metadata(request.projectId)
        fingerprint = request_fingerprint(request)
        with catalog_lock(self.config, request.projectId, "create-inference"):
            records = metadata.load_all_from_partition()
            for record in records:
                if record.get("inferenceRequestId") == str(
                    request.clientRequestId
                ):
                    model = Model.model_validate(record)
                    if model.inferenceRequestFingerprint != fingerprint:
                        raise CatalogConflictError(
                            "Request ID was used for different inference inputs"
                        )
                    if model.inferenceStatus == "Queued":
                        self._queue(model)
                    return model
            layer = self.catalog.layer(request.projectId, request.imageLayerId)
            project = CatalogMetadataProcessor(
                self.config.get_metadata_types().PROJECT.value,
                request.projectId,
                self.config,
            ).load(request.projectId)
            if not project or project.get("projectId") != request.projectId:
                raise FileNotFoundError("Project not found")
            entry = self.catalog.find(request.baseModelName)
            try:
                spec = self.catalog.resolve_spec(entry)
                image_name = self.catalog.inference_image(spec)
                self.catalog.compatible_layer(spec, layer)
            except ValueError as error:
                raise CatalogConflictError(str(error)) from error
            image = (
                layer.postEventProcessedImageryUrl
                if spec.inputKind == "rgb"
                else layer.postEventMosaicCogImageryUrl
            )
            inputs = {
                "imagery": self.artifacts.resolve_artifact_path(image),
                "footprints": self.artifacts.resolve_artifact_path(
                    layer.buildingFootprintsUrl
                ),
            }
            used = {record.get("modelId") for record in records}
            for _ in range(100):
                model_id = MetadataUtils.generate_short_int_id()
                if model_id not in used:
                    break
            else:
                raise CatalogConflictError("Unable to allocate a model ID")
            name = re.sub(
                r"[^A-Za-z0-9_.-]+", "-", request.name or entry.baseModelName
            ).strip(".-")
            name = (name[:75] or "catalog-inference") + f"-{model_id}"
            model = Model(
                modelId=model_id,
                projectId=request.projectId,
                imageLayerId=request.imageLayerId,
                name=name,
                modelType="pretrained",
                catalogModelName=entry.baseModelName,
                inferenceRequestId=str(request.clientRequestId),
                inferenceRequestFingerprint=fingerprint,
                pretrainedInference=spec,
                inferenceImage=image_name,
                autoRunInference=False,
                inferenceInputs=inputs,
                userId=user_id,
                creationDate=MetadataUtils.get_timestamp(),
                inferenceStatus="Queued",
                inferenceTotalSteps=7,
                inferenceStatusMessage=MetadataUtils.append_status_message(
                    "", "Queued for catalog inference"
                ),
            )
            metadata.save(model_id, model.model_dump(mode="json"))
            try:
                self._queue(model)
            except Exception:
                metadata.save(
                    model_id,
                    {
                        "inferenceStatusMessage": MetadataUtils.append_status_message(
                            model.inferenceStatusMessage,
                            "Queue publication failed; retry this request to dispatch the same run",
                        ),
                    },
                )
                raise
            return model

    def _asset(self, location: str, target: str) -> dict[str, str]:
        relative = self.artifacts.resolve_artifact_path(location)
        url = self.artifacts.get_download_url(identifier=relative)
        parsed = urlsplit(url)
        # The runners supply their configured storage credentials themselves.
        clean = urlunsplit((parsed.scheme, parsed.netloc, parsed.path, "", ""))
        return {"http_url": clean, "file_path": target}

    def _configuration(
        self, model: Model, layer: ImageLayer
    ) -> tuple[dict[str, dict[str, str]], dict[str, str]]:
        spec = model.pretrainedInference
        if spec is None:
            raise ValueError("The run has no inference recipe")
        if not model.inferenceImage:
            raise ValueError("The run has no pinned inference image")
        if not model.inferenceInputs:
            raise ValueError("The run has no immutable input snapshot")
        if (
            spec.checkpointEtag
            and self.artifacts.get_artifact_etag(spec.checkpointFilePath)
            != spec.checkpointEtag
        ):
            raise ValueError("The catalog checkpoint changed after submission")
        output_stem = (
            self.config.get_artifact_types()
            .VISUALIZER.value.substitute(
                projectId=model.projectId, imageLayerId=model.imageLayerId
            )
            .removesuffix("_visualizer")
        )
        names = {
            "predictions": output_stem + "_predictions.tif",
            "visualizer": output_stem + "_visualizer.tif",
            "gpkg": self.config.get_artifact_types().INFERENCE_GPKG.value.substitute(
                modelName=model.name
            )
            + ".gpkg",
        }
        image_path = f"inputs/{output_stem}.tif"
        resources = {
            "image": self._asset(model.inferenceInputs["imagery"], image_path),
            "checkpoint": self._asset(
                spec.checkpointFilePath, "inputs/checkpoint/model.ckpt"
            ),
            "footprints": self._asset(
                model.inferenceInputs["footprints"],
                "inputs/building_footprints.gpkg",
            ),
        }
        if spec.backboneConfigPath:
            resources["backbone_config"] = self._asset(
                spec.backboneConfigPath, "inputs/backbone_config.json"
            )
        config = deepcopy(spec.experimentConfig or {})
        config.update(
            experiment_dir=WORKDIR, experiment_name=f"catalog_{model.modelId}"
        )
        config["imagery"] = {
            **(config.get("imagery") or {}),
            "raw_fn": f"{WORKDIR}/{image_path}",
            "rgb_fn": f"{WORKDIR}/{image_path}",
            "num_channels": spec.numChannels,
            "normalization_means": spec.normalizationMeans,
            "normalization_stds": spec.normalizationStds,
        }
        config["inference"] = {
            **(config.get("inference") or {}),
            "adapter": spec.adapter,
            "output_subdir": "inference",
            "checkpoint_fn": f"{WORKDIR}/inputs/checkpoint/model.ckpt",
            "checkpoint_sha256": spec.checkpointSha256,
            "backbone_config_fn": (
                f"{WORKDIR}/inputs/backbone_config.json"
                if spec.backboneConfigPath
                else None
            ),
            "backbone_config_sha256": spec.backboneConfigSha256,
            "gpu_id": 0,
            "patch_size": spec.patchSize,
            "padding": spec.padding,
            "batch_size": spec.batchSize,
            "num_workers": spec.numWorkers,
            "prefetch_factor": spec.prefetchFactor,
            "predictions_filename": names["predictions"],
            "predictions_gpkg_fileprefix": names["gpkg"].removesuffix(".gpkg"),
            "preserve_source_identity": True,
        }
        namespace = [
            MetadataUtils.hash_string(model.projectId),
            "catalog-inference",
            model.inferenceRequestId,
        ]
        with NamedTemporaryFile(mode="w+", suffix=".yaml") as temporary:
            yaml.safe_dump(config, temporary)
            temporary.flush()
            self.artifacts.store_artifact(
                "config.yaml", src_path=temporary.name, namespace=namespace
            )
        resources["config"] = self._asset(
            str(PurePosixPath(*namespace, "config.yaml")), "inputs/config.yaml"
        )
        return resources, names

    def _save(self, metadata: CatalogMetadataProcessor, model: Model) -> Model:
        with catalog_lock(
            self.config, model.projectId, f"record-{model.modelId}"
        ):
            current = Model.model_validate(metadata.load(model.modelId))
            if current.inferenceStatus in ("Processed", "Failed", "Cancelled"):
                return current
            metadata.save(model.modelId, model.model_dump(mode="json"))
        return model

    def cancel(self, project_id: str, model_id: str) -> Model:
        metadata = self.metadata(project_id)
        with catalog_lock(self.config, project_id, f"record-{model_id}"):
            model = Model.model_validate(metadata.load(model_id))
            if model.modelType != "pretrained":
                raise ValueError("Not a catalog inference run")
            if model.inferenceStatus in ("Processed", "Failed", "Cancelled"):
                return model
            model.inferenceStatus = "Cancelled"
            for job in model.inferenceJobs:
                if job.taskId == model.currentInferenceTaskId:
                    job.status = "Cancelled"
                    job.completedDate = MetadataUtils.get_timestamp()
            model.inferenceStatusMessage = MetadataUtils.append_status_message(
                model.inferenceStatusMessage, "Catalog inference cancelled"
            )
            metadata.save(model_id, model.model_dump(mode="json"))
        if model.currentInferenceTaskId:
            runner = UnifiedRunner(
                runner_type=self.config.runner_type,
                config=self.config,
                pool_id=self.config.get_azure_batch_config()[
                    "training_pool_id"
                ],
                candidate_pool_ids=self.config.get_azure_batch_config()[
                    "inference_pool_ids"
                ],
            )
            runner.cancel_task(
                model.inferenceJobs[-1].jobId, model.currentInferenceTaskId
            )
        return model

    def _cleanup_task(self, runner: UnifiedRunner, task_id: str) -> None:
        try:
            runner.cleanup_task(task_id, task_id)
        except Exception as error:
            self.logger.warning(
                "Catalog task cleanup failed (%s)", type(error).__name__
            )

    def process(
        self, project_id: str, model_id: str, request_id: str | None = None
    ) -> Model | None:
        metadata = self.metadata(project_id)
        try:
            with catalog_lock(
                self.config, project_id, f"inference-{model_id}"
            ):
                try:
                    model = Model.model_validate(metadata.load(model_id))
                except FileNotFoundError:
                    return None
                if (
                    request_id is not None
                    and model.inferenceRequestId != request_id
                ):
                    self.logger.info(
                        "Ignoring stale catalog inference request"
                    )
                    return None
                if (
                    model.modelType != "pretrained"
                    or model.projectId != project_id
                    or model.modelId != model_id
                ):
                    raise ValueError("Not a catalog inference run")
                if model.inferenceStatus == "Processed":
                    CatalogArtifactProcessor(self.config).process(
                        model, self._queue
                    )
                    return model
                if model.inferenceStatus == "Failed":
                    return model
                runner = UnifiedRunner(
                    runner_type=self.config.runner_type,
                    config=self.config,
                    pool_id=self.config.get_azure_batch_config()[
                        "training_pool_id"
                    ],
                    candidate_pool_ids=self.config.get_azure_batch_config()[
                        "inference_pool_ids"
                    ],
                )
                if model.inferenceStatus == "Cancelled":
                    if model.currentInferenceTaskId:
                        runner.cancel_task(
                            model.inferenceJobs[-1].jobId,
                            model.currentInferenceTaskId,
                        )
                        if self.config.runner_type == "local":
                            self._cleanup_task(
                                runner, model.currentInferenceTaskId
                            )
                    return model
                layer = self.catalog.layer(project_id, model.imageLayerId)
                resources, names = self._configuration(model, layer)
                task_id = model.currentInferenceTaskId or catalog_task_id(
                    project_id, model.inferenceRequestId
                )
                if not model.inferenceJobs:
                    model.inferenceJobs = [
                        InferenceJob(
                            jobId=task_id,
                            taskId=task_id,
                            modelId=model_id,
                            projectId=project_id,
                            status="InProgress",
                            creationDate=MetadataUtils.get_timestamp(),
                        )
                    ]
                    model.inferenceCurrentStep = 1
                    model.inferenceStatusMessage = (
                        MetadataUtils.append_status_message(
                            model.inferenceStatusMessage,
                            "Running catalog inference",
                        )
                    )
                model.currentInferenceTaskId = task_id
                model.inferenceStatus = "InProgress"
                model = self._save(metadata, model)
                if model.inferenceStatus in (
                    "Processed",
                    "Failed",
                    "Cancelled",
                ):
                    return model
                # Leave a future poll before external work, including an
                # accepted submission whose worker never returns.
                self._queue(model, delay=30)
                runner.add_task(
                    job_id=task_id,
                    task_id=task_id,
                    idempotent=True,
                    output_prefix=f"{MetadataUtils.hash_string(project_id)}/{task_id}",
                    resource_files_for_upload=resources,
                    file_pattern=[
                        f"${WORKDIR}/inference/**/*",
                        f"${WORKDIR}/logs/**/*",
                        f"${WORKDIR}/inputs/*.yaml",
                    ],
                    command=(
                        f'"cd /app && export TORCHINDUCTOR_CACHE_DIR=${WORKDIR}/torchinductor-cache '
                        f"&& source scripts/set_dirs.sh ${WORKDIR}/inputs/config.yaml "
                        f'&& python run_workflow.py --config ${WORKDIR}/inputs/config.yaml --step inference"'
                    ),
                    env_vars={
                        "GDAL_TRANSLATE_PARAMS": self.config.gdal_translate_params,
                        "USER": "haste-inference",
                        "LOGNAME": "haste-inference",
                    },
                    image_name=model.inferenceImage,
                )
                current = Model.model_validate(metadata.load(model_id))
                if current.inferenceStatus == "Cancelled":
                    runner.cancel_task(task_id, task_id)
                    if self.config.runner_type == "local":
                        self._cleanup_task(runner, task_id)
                    return current
                status = runner.get_task_status(task_id, task_id)
                progress = runner.get_filecontent_from_task(
                    task_id,
                    task_id,
                    (
                        "logs/workflow_progress.log"
                        if self.config.runner_type == "local"
                        else "workflow_progress.log"
                    ),
                )
                if progress:
                    for line in progress.splitlines():
                        if "|" not in line:
                            continue
                        timestamp, message = line.split("|", 1)
                        if (
                            message
                            and message not in model.inferenceStatusMessage
                        ):
                            model.inferenceStatusMessage = (
                                MetadataUtils.append_status_message(
                                    model.inferenceStatusMessage,
                                    message,
                                    timestamp=timestamp,
                                )
                            )
                            model.inferenceCurrentStep = min(
                                model.inferenceCurrentStep + 1,
                                model.inferenceTotalSteps - 1,
                            )
                    model.inferenceJobs[-1].logs = model.inferenceStatusMessage
                    model.inferenceProgressPct = round(
                        100
                        * model.inferenceCurrentStep
                        / model.inferenceTotalSteps,
                        2,
                    )
                if status not in ("Processed", "Failed"):
                    model.inferenceFailures = 0
                    return self._save(metadata, model)
                job = model.inferenceJobs[-1]
                model.inferenceStatus = job.status = status
                job.completedDate = MetadataUtils.get_timestamp()
                if status == "Processed":
                    prefix = [MetadataUtils.hash_string(project_id), task_id]
                    if self.config.runner_type == "local":
                        prefix.append("inference")
                    paths = {
                        key: str(PurePosixPath(*prefix, name))
                        for key, name in names.items()
                    }
                    for path in paths.values():
                        if (
                            not self.artifacts.artifact_exists(path)
                            or self.artifacts.get_artifact_size(path) <= 0
                        ):
                            raise CatalogInferenceOutputError(
                                "Inference task completed without its expected artifacts"
                            )
                    model.inferenceOutputPath = str(PurePosixPath(*prefix[:2]))
                    model.predictedDamageLayerUrl = (
                        self.artifacts.get_download_url(
                            identifier=paths["visualizer"]
                        )
                    )
                    model.gpkgUrl = self.artifacts.get_download_url(
                        identifier=paths["gpkg"]
                    )
                    model.inferenceCurrentStep = model.inferenceTotalSteps
                    model.inferenceProgressPct = 100
                model.inferenceStatusMessage = (
                    MetadataUtils.append_status_message(
                        model.inferenceStatusMessage,
                        (
                            "Inference completed"
                            if status == "Processed"
                            else "Inference failed; inspect task logs"
                        ),
                    )
                )
                model = self._save(metadata, model)
                if model.inferenceStatus == "Processed":
                    CatalogArtifactProcessor(self.config).process(
                        model, self._queue
                    )
                self._cleanup_task(runner, task_id)
                return model
        except LeaseUnavailableError:
            try:
                model = Model.model_validate(metadata.load(model_id))
            except FileNotFoundError:
                return None
            self._queue(model, delay=30)
            return model
        except Exception as error:
            self.logger.error(
                "Catalog inference failed (%s)", type(error).__name__
            )
            try:
                model = Model.model_validate(metadata.load(model_id))
            except FileNotFoundError:
                return None
            if model.inferenceStatus in ("Processed", "Failed", "Cancelled"):
                return model
            model.inferenceFailures += 1
            terminal = (
                isinstance(
                    error,
                    (
                        ValueError,
                        FileNotFoundError,
                        CatalogInferenceOutputError,
                    ),
                )
                or model.inferenceFailures >= 5
            )
            model.inferenceStatus = (
                "Failed" if terminal else model.inferenceStatus
            )
            detail = (
                str(error)
                if isinstance(error, (ValueError, CatalogInferenceOutputError))
                else f"Catalog inference encountered {type(error).__name__}"
            )
            model.inferenceStatusMessage = MetadataUtils.append_status_message(
                model.inferenceStatusMessage,
                detail if terminal else f"{detail}; retrying",
            )
            model = self._save(metadata, model)
            if model.inferenceStatus not in (
                "Processed",
                "Failed",
                "Cancelled",
            ):
                self._queue(model, delay=30)
            return model
