# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License.

import json
from copy import deepcopy

from ..config import Config
from ..models.projects import (
    ImageLayer,
    LabelProject,
    Model,
    ModelArtifacts,
    Project,
)
from ..models.training import ExperimentConfig
from ..runners.base import TaskMissingError
from ..runners.deferred_cleanup import DeferredCleanupRunner
from ..runners.unified_runner import UnifiedRunner
from ..utils.data import convert_json_to_geojson
from ..utils.logs import Logger
from ..utils.metadata import MetadataUtils
from ..utils.prediction_edit_lock import prediction_edit_lock
from ..utils.workflow_progress import (
    read_training_output,
    workflow_progress_updates,
)
from .artifacts import ArtifactProcessor
from .embedding import EmbeddingPostprocessor
from .imagery import ImageryPostProcessor, prepare_footprint_tiles
from .inference import InferencePostprocessor, InferencePreprocessor
from .job_state import (
    WORKFLOWS,
    JobClaimRenewal,
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
        renewal = JobClaimRenewal(self.repository, workload, baseline)
        renewal.start()
        try:
            status = baseline.get(workflow.status)
            if status in {
                self.config.get_status_types().PENDING.value,
                self.config.get_status_types().IN_PROGRESS.value,
            } or self.repository.needs_cancellation(baseline, workload):
                try:
                    output, cleanup = self._process_current(workload, baseline)
                except TaskMissingError as error:
                    output, cleanup = self._task_missing(
                        workload, baseline, error
                    )
                renewal.check()
                baseline = self._commit(workload, baseline, output, cleanup)
                if baseline is None:
                    return
                if workload == Workload.IMAGERY:
                    prepare_footprint_tiles(output, config=self.config)
            turn = self.repository.turn(baseline, workload)
            if turn.cleanup:
                renewal.check()
                runner = self._runner(workload)
                for identity in turn.cleanup:
                    runner.cleanup_task(identity.job_id, identity.task_id)
                baseline = self.repository.complete_action(
                    workload, baseline, "cleanup"
                )
                if baseline is None:
                    return
            for action, request_id in (
                self.repository.turn(baseline, workload).actions.copy().items()
            ):
                renewal.check()
                self._perform_action(baseline, action, request_id)
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
                    if self.repository.release(workload, baseline, error):
                        # Recorded with a backoff; recovery retries it, so the
                        # delivery must not be retried or poisoned as well.
                        return
                else:
                    self.repository.mark_delivery_interrupted(
                        workload, baseline
                    )
            raise
        finally:
            renewal.close()

    def _commit(
        self,
        workload: Workload,
        baseline: dict,
        output: JobRecord,
        cleanup: list[TaskIdentity],
    ) -> dict | None:
        if workload != Workload.INFERENCE:
            return self.repository.commit(workload, baseline, output, cleanup)
        # Prediction editors validate the revision under this lock before
        # publishing, so inference results never interleave with an edit.
        with prediction_edit_lock(
            self.config, baseline["projectId"], baseline["modelId"]
        ) as lease:
            if lease is not None:
                lease.renew()
            return self.repository.commit(workload, baseline, output, cleanup)

    def _runner(self, workload: Workload) -> UnifiedRunner:
        batch = self.config.get_azure_batch_config()
        training_pool = workload in {
            Workload.TRAINING,
            Workload.INFERENCE,
            Workload.EMBEDDING,
        }
        candidates = (
            "inference_pool_ids"
            if workload == Workload.INFERENCE
            else (
                "training_pool_ids"
                if training_pool
                else "imageryprep_pool_ids"
            )
        )
        return UnifiedRunner(
            runner_type=self.config.runner_type,
            config=self.config,
            pool_id=batch[
                "training_pool_id" if training_pool else "imageprep_pool_id"
            ],
            candidate_pool_ids=batch[candidates],
        )

    def _process_current(
        self, workload: Workload, baseline: dict
    ) -> tuple[JobRecord, list[TaskIdentity]]:
        workflow = WORKFLOWS[workload]
        record = workflow.model.model_validate(baseline)
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
                    if (
                        image_layer.projectId != model.projectId
                        or image_layer.imageLayerId != model.imageLayerId
                    ):
                        raise ValueError(
                            "Inference layer does not match its model"
                        )
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
        deferred = DeferredCleanupRunner(processor.runner)
        processor.runner = deferred
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
            TaskIdentity(job_id=job_id, task_id=task_id)
            for job_id, task_id in deferred.cleanup
        ]

    def _task_missing(
        self, workload: Workload, baseline: dict, error: TaskMissingError
    ) -> tuple[JobRecord, list[TaskIdentity]]:
        """End an execution whose compute task no longer exists.

        Nothing can report its outcome any more, so retrying would never
        finish. A requested cancellation stays cancelled; nothing is left to
        clean up.
        """
        workflow = WORKFLOWS[workload]
        statuses = self.config.get_status_types()
        values = deepcopy(baseline)
        status = (
            statuses.CANCELLED.value
            if values.get(workflow.status) == statuses.CANCELLED.value
            else statuses.FAILED.value
        )
        values[workflow.status] = status
        job = current_job(values, workload)
        if job:
            job["status"] = status
            job["completedDate"] = MetadataUtils.get_timestamp()
        values[workflow.message] = MetadataUtils.append_status_message(
            values.get(workflow.message),
            f"Compute task {job.get('taskId')} no longer exists; "
            f"marked {status}",
        )
        self.logger.error(
            "Compute task for %s %s no longer exists (%s); marking it %s",
            workload.value,
            values.get(workflow.key),
            error,
            status,
        )
        return workflow.model.model_validate(values), []

    def _cancel(
        self, workload: Workload, record: JobRecord
    ) -> tuple[JobRecord, list[TaskIdentity]]:
        values = record.model_dump(mode="json")
        job = current_job(values, workload)
        identity = TaskIdentity(job_id=job["jobId"], task_id=job["taskId"])
        runner = self._runner(workload)
        stopped = runner.cancel_task(identity.job_id, identity.task_id)
        job["status"] = (
            runner.get_task_status(identity.job_id, identity.task_id)
            if stopped is False
            else self.config.get_status_types().CANCELLED.value
        )
        job["completedDate"] = MetadataUtils.get_timestamp()
        workflow = WORKFLOWS[workload]
        if workload == Workload.TRAINING:
            values[
                "trainingOutputPath"
            ] = f"{MetadataUtils.hash_string(record.projectId)}/{identity.task_id}"
            values[workflow.message] = self._training_cancellation_history(
                runner, identity, values.get(workflow.message)
            )
        values[workflow.message] = MetadataUtils.append_status_message(
            values.get(workflow.message),
            (
                f"Task already reached {job['status']} before cancellation"
                if stopped is False
                else "Task cancelled"
            ),
        )
        if workload == Workload.TRAINING:
            # The final workflow records are unbounded; keep the newest
            # entries within the budget the training monitor uses.
            values[workflow.message] = MetadataUtils.trim_status_message(
                values[workflow.message]
            )
        return workflow.model.model_validate(values), [identity]

    def _training_cancellation_history(
        self,
        runner: UnifiedRunner,
        identity: TaskIdentity,
        status_message: str | None,
    ) -> str | None:
        content, _ = read_training_output(
            runner,
            job_id=identity.job_id,
            task_id=identity.task_id,
            filename="workflow_progress.log",
            logger=self.logger,
        )
        if content is None:
            return status_message
        if not isinstance(content, str):
            self.logger.warning("Workflow progress is not text")
            return status_message
        _, updates = workflow_progress_updates(
            content, status_message, logger=self.logger
        )
        for timestamp, message in updates:
            status_message = MetadataUtils.append_status_message(
                status_message, message, timestamp=timestamp
            )
        return status_message

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
        self, data: dict, action: str, request_id: str
    ) -> None:
        model = Model.model_validate(
            self.repository.processor(
                Workload.TRAINING, data["projectId"]
            ).load(data["modelId"])
        )
        if action == "inference":
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
    if config.runner_type != "local":
        return 0
    from ..runners.local import LocalRunner

    return LocalRunner(config=config).reconcile_tasks()
