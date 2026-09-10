# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License.

import json

from ..config import Config
from ..models.compute import ComputeBackend, ComputeJobHandle
from ..models.projects import (
    ImageLayer,
    LabelProject,
    Model,
    ModelArtifacts,
    Project,
)
from ..models.training import ExperimentConfig
from ..runners.deferred_cleanup import DeferredCleanupService
from ..utils.compute_jobs import resolve_compute_job_handle
from ..utils.compute_specs import (
    build_execution_service,
    follow_on_backend,
    follow_on_backend_for_record,
    handle_log_fields,
    output_prefix,
    output_uri,
)
from ..utils.data import convert_json_to_geojson
from ..utils.logs import Logger
from ..utils.metadata import MetadataUtils
from .artifacts import ArtifactProcessor
from .embedding import EmbeddingPostprocessor
from .imagery import ImageryPostProcessor
from .inference import InferencePostprocessor, InferencePreprocessor
from .job_state import (
    COMPUTE_WORKLOADS,
    WORKFLOWS,
    JobRecord,
    JobStateRepository,
    TaskIdentity,
    Workload,
    current_job,
)
from .labels import LabelTaskGenerator
from .metadata import MetadataProcessor
from .train import TrainPostprocessor


class JobQueueProcessor:
    """Drive one current execution turn; queue messages only wake it up."""

    def __init__(
        self,
        config: Config = None,
        repository: JobStateRepository | None = None,
    ) -> None:
        self.config = config or Config()
        self.repository = repository or JobStateRepository(self.config)
        self.logger = Logger.get_logger(__name__)
        self.execution_service = build_execution_service(self.config)

    def process_message(
        self, workload: Workload | str, body: bytes, *, poison: bool = False
    ) -> None:
        try:
            payload = json.loads(body)
            if poison:
                self.mark_poisoned(workload, payload)
            else:
                self.process(workload, payload)
        except Exception as error:
            self.logger.error(
                "Job queue dispatch failed with %s", type(error).__name__
            )
            raise RuntimeError(
                f"Job queue dispatch failed: {type(error).__name__}"
            ) from None

    def process(self, workload: Workload | str, payload: dict) -> None:
        workload = Workload(workload)
        workflow = WORKFLOWS[workload]
        message = workflow.model.model_validate(payload).model_dump(
            mode="json"
        )
        if workload == Workload.ZIP:
            try:
                self.repository.processor(
                    Workload.TRAINING, message["projectId"]
                ).load(message["modelId"])
            except FileNotFoundError:
                self.logger.info("Ignoring artifacts for a removed model")
                return
        baseline = self.repository.claim(workload, message)
        if baseline is None:
            return
        handle = current_job(baseline, workload).get("computeJob")
        self.logger.info(
            "Processing %s project=%s record=%s compute=%s",
            workload.value,
            baseline["projectId"],
            baseline[workflow.key],
            handle_log_fields(
                ComputeJobHandle.model_validate(handle) if handle else None
            ),
        )
        try:
            status = baseline.get(workflow.status)
            cancelled = self.config.get_status_types().CANCELLED.value
            if status in {
                self.config.get_status_types().PENDING.value,
                self.config.get_status_types().IN_PROGRESS.value,
            } or (
                status == cancelled
                and current_job(baseline, workload).get("status") != cancelled
            ):
                output, cleanup = self._process_current(workload, baseline)
                baseline = self.repository.commit(
                    workload, baseline, output, cleanup
                )
                if baseline is None:
                    return
            turn = self.repository.turn(baseline, workload)
            if turn.cleanup:
                for identity in turn.cleanup:
                    if identity.handle is None:
                        raise ValueError(
                            "Cleanup requires its persisted compute handle"
                        )
                    self.execution_service.finalize(identity.handle)
                baseline = self.repository.complete_action(
                    workload, baseline, "cleanup"
                )
                if baseline is None:
                    return
            for action, request_id in (
                self.repository.turn(baseline, workload).actions.copy().items()
            ):
                self._perform_action(
                    baseline, action, request_id, source_workload=workload
                )
                baseline = self.repository.complete_action(
                    workload, baseline, action
                )
                if baseline is None:
                    return
            baseline = self.repository.release(workload, baseline)
            if baseline is not None and self.repository.needs_processing(
                baseline, workload
            ):
                self.repository.enqueue(workload, baseline)
        except Exception as error:
            self.logger.error(
                "Job queue turn failed for %s (%s)",
                workload.value,
                type(error).__name__,
            )
            if baseline is not None:
                if self.repository.turn(baseline, workload).claim:
                    self.repository.release(workload, baseline, error)
                else:
                    self.repository.mark_delivery_interrupted(
                        workload, baseline
                    )
            raise

    def _process_current(
        self, workload: Workload, baseline: dict
    ) -> tuple[JobRecord, list[TaskIdentity]]:
        workflow = WORKFLOWS[workload]
        record = workflow.model.model_validate(baseline)
        record.computeBackend = ComputeBackend(
            self.repository.turn(baseline, workload).backend
        )
        if (
            baseline.get(workflow.status)
            == self.config.get_status_types().CANCELLED.value
        ):
            return self._cancel(workload, record)
        if workload == Workload.IMAGERY:
            processor = ImageryPostProcessor(record, config=self.config)
        else:
            model = (
                Model.model_validate(
                    self.repository.processor(
                        Workload.TRAINING, record.projectId
                    ).load(record.modelId)
                )
                if workload == Workload.ZIP
                else record
            )
            if workload == Workload.ZIP:
                processor = ArtifactProcessor(
                    partition_key=record.projectId,
                    config=self.config,
                    model=model,
                    model_artifacts=record,
                )
            else:
                image_layer = ImageLayer.model_validate(
                    self.repository.processor(
                        Workload.IMAGERY, model.projectId
                    ).load(model.imageLayerId)
                )
                if workload == Workload.TRAINING:
                    label_processor = MetadataProcessor(
                        data_type=self.config.get_metadata_types().LABELS.value,
                        partition_key=model.projectId,
                        config=self.config,
                    )
                    labels = next(
                        (
                            item
                            for item in label_processor.load_all_from_partition()
                            if item["imageLayerId"] == model.imageLayerId
                        ),
                        None,
                    )
                    if labels is None:
                        raise FileNotFoundError(
                            "Training label project is missing"
                        )
                    project = MetadataProcessor(
                        data_type=self.config.get_metadata_types().PROJECT.value,
                        partition_key=model.projectId,
                        config=self.config,
                    ).load(model.projectId)
                    processor = TrainPostprocessor(
                        model,
                        image_layer,
                        LabelProject.model_validate(labels),
                        Project.model_validate(project),
                        config=self.config,
                    )
                elif workload == Workload.EMBEDDING:
                    processor = EmbeddingPostprocessor(
                        model, image_layer, config=self.config
                    )
                else:
                    experiment = MetadataProcessor(
                        data_type=self.config.get_metadata_types().EXPERIMENT_CONFIG.value,
                        partition_key=model.projectId,
                        config=self.config,
                    ).load(model.modelId, data_format="yaml")
                    processor = InferencePostprocessor(
                        model,
                        image_layer,
                        ExperimentConfig.model_validate(experiment),
                        config=self.config,
                    )
        deferred = DeferredCleanupService(
            processor.execution_service,
            before_submit=lambda spec: self.repository.require_current_submission(
                workload, baseline
            ),
            record_submission=lambda handle: self.repository.record_submission(
                workload, baseline, handle
            ),
        )
        processor.execution_service = deferred
        output = (
            processor.process_zip()
            if workload == Workload.ZIP
            else processor.process()
        )
        if (
            workload == Workload.IMAGERY
            and output.status == self.config.get_status_types().COMPLETED.value
        ):
            self._complete_imagery(output)
        return output, [
            TaskIdentity(
                job_id=handle.providerJobId,
                task_id=handle.providerTaskId or handle.executionId,
                handle=handle,
            )
            for handle in deferred.cleanup
        ]

    def _cancel(
        self, workload: Workload, record: JobRecord
    ) -> tuple[JobRecord, list[TaskIdentity]]:
        values = record.model_dump(mode="json")
        job = current_job(values, workload)
        job_record = (
            getattr(record, WORKFLOWS[workload].job)
            if WORKFLOWS[workload].current_task is None
            else next(
                item
                for item in getattr(record, WORKFLOWS[workload].job)
                if item.taskId == job["taskId"]
            )
        )
        runtime = self.config.get_compute_runtime_config(
            COMPUTE_WORKLOADS[workload]
        )
        handle = resolve_compute_job_handle(
            job_record,
            output_uri=output_uri(
                runtime["output_container_url"],
                output_prefix(record.projectId, job["taskId"]),
            ),
        )
        cleanup = []
        if handle is not None:
            self.execution_service.cancel(handle)
            cleanup.append(
                TaskIdentity(
                    job_id=handle.providerJobId,
                    task_id=handle.providerTaskId or handle.executionId,
                    handle=handle,
                )
            )
        job["status"] = self.config.get_status_types().CANCELLED.value
        job["completedDate"] = MetadataUtils.get_timestamp()
        if handle is not None and workload == Workload.TRAINING:
            values["trainingOutputPath"] = output_prefix(
                record.projectId, job["taskId"]
            )
        workflow = WORKFLOWS[workload]
        values[workflow.message] = MetadataUtils.append_status_message(
            values.get(workflow.message), "Task cancelled"
        )
        return workflow.model.model_validate(values), cleanup

    def _complete_imagery(self, output: ImageLayer) -> None:
        label_id = MetadataUtils.generate_deterministic_id(
            "local-lifecycle-labels",
            output.projectId,
            output.preprocessJob.taskId,
        )
        metadata = MetadataProcessor(
            data_type=self.config.get_metadata_types().LABELS.value,
            partition_key=output.projectId,
            config=self.config,
        )
        try:
            labels = metadata.load(label_id)
        except FileNotFoundError:
            label_project = LabelTaskGenerator(
                output, config=self.config
            ).generate_task_files()
            label_project.labelprojectId = label_id
            labels = metadata.mutate(
                label_id,
                lambda current: (
                    current
                    if current is not None
                    else label_project.model_dump(mode="json")
                ),
            )
        label_project = LabelProject.model_validate(labels)
        output.labelProjectId = label_project.labelprojectId
        geojson = convert_json_to_geojson(
            label_project.model_dump(by_alias=True)
        )
        artifacts = ArtifactProcessor(
            partition_key=output.projectId, config=self.config
        )
        filename = f"{self.config.get_metadata_types().LABELS.value}_{output.labelProjectId}.geojson"
        artifacts.store_artifact(
            artifact_name=filename, data=geojson, namespace="artifacts"
        )
        output.labelsUrl = artifacts.get_download_url(
            identifier=filename, extra_partition_keys="artifacts"
        )

    def _perform_action(
        self,
        data: dict,
        action: str,
        request_id: str,
        *,
        source_workload: Workload,
    ) -> None:
        model = Model.model_validate(
            self.repository.processor(
                Workload.TRAINING, data["projectId"]
            ).load(data["modelId"])
        )
        origin = current_job(data, source_workload).get("computeJob")
        inherited = (
            follow_on_backend(
                ComputeJobHandle.model_validate(origin).selectedBackend,
                config=self.config,
            )
            if origin
            else follow_on_backend_for_record(
                Model.model_validate(data), config=self.config
            )
        )
        if action == "inference":
            model.computeBackend = inherited
            InferencePreprocessor(model, config=self.config).send_to_queue(
                request_id=request_id
            )
        elif action == "zip":
            try:
                artifacts = ModelArtifacts.model_validate(
                    self.repository.processor(
                        Workload.ZIP, model.projectId
                    ).load(model.modelId)
                )
            except FileNotFoundError:
                artifacts = ModelArtifacts(
                    projectId=model.projectId,
                    modelId=model.modelId,
                    imageLayerId=model.imageLayerId,
                )
            artifacts.computeBackend = inherited
            ArtifactProcessor(
                partition_key=model.projectId,
                config=self.config,
                model_artifacts=artifacts,
            ).send_to_zip_queue(request_id=request_id)
        else:
            raise ValueError("Unknown job follow-on action")

    def mark_poisoned(self, workload: Workload | str, payload: dict) -> None:
        workload = Workload(workload)
        message = (
            WORKFLOWS[workload]
            .model.model_validate(payload)
            .model_dump(mode="json")
        )
        self.repository.mark_delivery_interrupted(workload, message)


def reconcile_local_tasks(config: Config) -> int:
    from ..runners.local import TASK_WORK_DIR, LocalRunner

    if not (TASK_WORK_DIR / ".lifecycle").is_dir():
        return 0
    return LocalRunner(config=config).reconcile_tasks()
