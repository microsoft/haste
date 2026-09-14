# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License.

import json
import time
from dataclasses import dataclass
from enum import Enum
from threading import Event, Thread
from typing import Callable

from pydantic import BaseModel, Field

from ..config import Config
from ..data_layer.conditional import JsonDocument
from ..models.compute import ComputeBackend, ComputeJobHandle, ComputeWorkload
from ..models.projects import (
    ImageLayer,
    ImageryPreprocessJob,
    InferenceJob,
    Model,
    ModelArtifacts,
    TrainingJob,
    ZipJob,
)
from ..utils.compute_specs import output_prefix, resolve_backend_preference
from ..utils.logs import Logger
from ..utils.metadata import MetadataUtils
from ..utils.queues import AzureQueueHandler
from .metadata import MetadataProcessor

JobRecord = ImageLayer | Model | ModelArtifacts
RUNTIME_KEY = "_jobRuntime"


class Workload(str, Enum):
    IMAGERY = "imagery"
    TRAINING = "training"
    INFERENCE = "inference"
    EMBEDDING = "embedding"
    ZIP = "zip"


COMPUTE_WORKLOADS = {
    Workload.IMAGERY: ComputeWorkload.IMAGERY_PREPARATION,
    Workload.TRAINING: ComputeWorkload.TRAINING,
    Workload.INFERENCE: ComputeWorkload.INFERENCE,
    Workload.EMBEDDING: ComputeWorkload.EMBEDDING,
    Workload.ZIP: ComputeWorkload.ARTIFACT_PACKAGING,
}


@dataclass(frozen=True)
class Workflow:
    model: type[ImageLayer] | type[Model] | type[ModelArtifacts]
    metadata_type: str
    key: str
    status: str
    message: str
    job: str
    queue: str
    batch_job: str
    prefix: str
    fields: frozenset[str]
    current_task: str | None = None


PROGRESS_FIELDS = {
    "status",
    "statusMessage",
    "currentStep",
    "totalSteps",
    "progressPct",
    "computeBackend",
}
WORKFLOWS = {
    Workload.IMAGERY: Workflow(
        ImageLayer,
        "IMAGELAYER",
        "imageLayerId",
        "status",
        "statusMessage",
        "preprocessJob",
        "image_queue_name",
        "imageryprep_batch_job_id",
        "img",
        frozenset(
            PROGRESS_FIELDS
            | {
                "preprocessJob",
                "imageryPath",
                "preEventPreviewUrls",
                "preEventMosaicCogImageryUrl",
                "preEventProcessedImageryUrl",
                "postEventPreviewUrls",
                "postEventMosaicCogImageryUrl",
                "postEventProcessedImageryUrl",
                "processedImageryUrls",
                "rawImageryUrls",
                "previewSourceImageryUrls",
                "normalizationMeans",
                "normalizationStds",
                "normalizationFactor",
                "buildingFootprintsUrl",
                "validAreaMaskUrl",
                "labelProjectId",
                "labelsUrl",
            }
        ),
    ),
    Workload.TRAINING: Workflow(
        Model,
        "MODEL",
        "modelId",
        "status",
        "statusMessage",
        "trainingJob",
        "train_queue_name",
        "training_batch_job_id",
        "trn",
        frozenset(
            PROGRESS_FIELDS
            | {
                "trainingJob",
                "trainDate",
                "checkpointPath",
                "trainingOutputPath",
                "labelsUrl",
            }
        ),
    ),
    Workload.INFERENCE: Workflow(
        Model,
        "MODEL",
        "modelId",
        "inferenceStatus",
        "inferenceStatusMessage",
        "inferenceJobs",
        "inference_queue_name",
        "inference_batch_job_id",
        "inf",
        frozenset(
            {
                "inferenceJobs",
                "currentInferenceTaskId",
                "inferenceStatus",
                "inferenceStatusMessage",
                "inferenceCurrentStep",
                "inferenceTotalSteps",
                "inferenceProgressPct",
                "inferenceOutputPath",
                "predictedDamageLayerUrl",
                "gpkgUrl",
                "computeBackend",
            }
        ),
        "currentInferenceTaskId",
    ),
    Workload.EMBEDDING: Workflow(
        Model,
        "MODEL",
        "modelId",
        "status",
        "statusMessage",
        "embeddingJob",
        "embedding_queue_name",
        "training_batch_job_id",
        "emb",
        frozenset(
            PROGRESS_FIELDS
            | {
                "embeddingJob",
                "embeddingsGeoJSONUrl",
                "pmtilesUrl",
                "featuresSidecarUrl",
            }
        ),
    ),
    Workload.ZIP: Workflow(
        ModelArtifacts,
        "MODEL_ARTIFACTS",
        "modelId",
        "zipStatus",
        "zipStatusMessage",
        "zipJobs",
        "zip_queue_name",
        "artifact_batch_job_id",
        "zip",
        frozenset(
            {
                "zipJobs",
                "currentZipJobUid",
                "zipStatus",
                "zipStatusMessage",
                "zipUrl",
                "trainingZipUrl",
                "trainingZipSize",
                "inferenceZipUrl",
                "inferenceZipSize",
                "computeBackend",
            }
        ),
        "currentZipJobUid",
    ),
}


class TaskIdentity(BaseModel):
    job_id: str
    task_id: str
    handle: ComputeJobHandle | None = None


class RuntimeTurn(BaseModel):
    attempt: str
    backend: str
    revision: int = 0
    claim: str | None = None
    lease_until: float = 0
    next_poll: float = 0
    request_id: str | None = None
    error: str | None = None
    cleanup: list[TaskIdentity] = Field(default_factory=list)
    actions: dict[str, str] = Field(default_factory=dict)


def current_job(data: dict, workload: Workload) -> dict:
    workflow = WORKFLOWS[workload]
    if workflow.current_task:
        task_id = data.get(workflow.current_task)
        return next(
            (
                job
                for job in (data.get(workflow.job) or [])
                if job.get("taskId") == task_id
            ),
            {},
        )
    return data.get(workflow.job) or {}


def attempt_id(data: dict, workload: Workload) -> str | None:
    return current_job(data, workload).get("taskId")


def ensure_pending_identity(
    data: dict, workload: Workload, config: Config
) -> None:
    workflow = WORKFLOWS[workload]
    existing = current_job(data, workload)
    if existing.get("taskId"):
        return
    values = {
        "taskId": existing.get("taskId")
        or f"{workflow.prefix}-{MetadataUtils.generate_id()}",
        "projectId": data["projectId"],
        "status": config.get_status_types().PENDING.value,
        "creationDate": MetadataUtils.get_timestamp(),
    }
    if workload == Workload.IMAGERY:
        job = ImageryPreprocessJob(imageLayerId=data["imageLayerId"], **values)
    elif workload == Workload.INFERENCE:
        job = InferenceJob(modelId=data["modelId"], **values)
    elif workload == Workload.ZIP:
        job = ZipJob(
            modelId=data["modelId"],
            imageLayerId=data.get("imageLayerId"),
            dstZipPath=output_prefix(data["projectId"], values["taskId"]),
            **values,
        )
    else:
        job = TrainingJob(modelId=data["modelId"], **values)
    if workflow.current_task:
        jobs = data.get(workflow.job) or []
        data[workflow.job] = [
            item for item in jobs if item.get("taskId") != job.taskId
        ] + [job.model_dump(mode="json")]
        data[workflow.current_task] = job.taskId
    else:
        data[workflow.job] = job.model_dump(mode="json")


class JobStateRepository:
    """Atomic, current-attempt runtime updates shared by queue consumers."""

    def __init__(
        self,
        config: Config,
        processor_factory: Callable[
            ..., MetadataProcessor
        ] = MetadataProcessor,
        clock: Callable[[], float] = time.time,
        claim_seconds: float = 300,
        renewal_interval_seconds: float = 60,
    ) -> None:
        self.config = config
        self.processor_factory = processor_factory
        self.clock = clock
        self.claim_seconds = claim_seconds
        if not 0 < renewal_interval_seconds < claim_seconds:
            raise ValueError(
                "Claim renewal interval must be below its lease duration"
            )
        self.renewal_interval_seconds = renewal_interval_seconds
        self.logger = Logger.get_logger(__name__)
        self.statuses = config.get_status_types()

    def processor(
        self, workload: Workload, project_id: str | None
    ) -> MetadataProcessor:
        workflow = WORKFLOWS[workload]
        return self.processor_factory(
            data_type=getattr(
                self.config.get_metadata_types(), workflow.metadata_type
            ).value,
            partition_key=project_id,
            config=self.config,
        )

    def _identity(self, data: dict, workload: Workload) -> tuple[str, str]:
        project_id, record_id = data.get("projectId"), data.get(
            WORKFLOWS[workload].key
        )
        if not all(
            isinstance(value, str)
            and value
            and all(char.isalnum() or char in "-_." for char in value)
            and value not in {".", ".."}
            for value in (project_id, record_id)
        ):
            raise ValueError(
                "Job messages require valid project and record identifiers"
            )
        return project_id, record_id

    def turn(self, data: dict, workload: Workload) -> RuntimeTurn:
        raw = data.get(RUNTIME_KEY, {}).get(workload.value)
        if raw:
            return RuntimeTurn.model_validate(raw)
        attempt = attempt_id(data, workload)
        if not attempt:
            raise ValueError("Job record has no pending execution identity")
        return RuntimeTurn(
            attempt=attempt, backend=self._backend(data, workload)
        )

    def _backend(self, data: dict, workload: Workload) -> str:
        handle = current_job(data, workload).get("computeJob")
        if handle:
            return ComputeJobHandle.model_validate(
                handle
            ).selectedBackend.value
        requested = data.get("computeBackend")
        return resolve_backend_preference(
            requested=ComputeBackend(requested) if requested else None,
            workload=COMPUTE_WORKLOADS[workload],
            config=self.config,
        ).value

    @staticmethod
    def _set_turn(data: dict, workload: Workload, turn: RuntimeTurn) -> None:
        data.setdefault(RUNTIME_KEY, {})[workload.value] = turn.model_dump(
            mode="json"
        )

    def needs_processing(self, data: dict, workload: Workload) -> bool:
        workflow = WORKFLOWS[workload]
        status = data.get(workflow.status)
        if status in {
            self.statuses.PENDING.value,
            self.statuses.IN_PROGRESS.value,
        }:
            return True
        if self.needs_cancellation(data, workload):
            return True
        raw = data.get(RUNTIME_KEY, {}).get(workload.value)
        return bool(raw and (raw.get("actions") or raw.get("cleanup")))

    def needs_cancellation(self, data: dict, workload: Workload) -> bool:
        return data.get(
            WORKFLOWS[workload].status
        ) == self.statuses.CANCELLED.value and current_job(data, workload).get(
            "status"
        ) not in {
            self.statuses.CANCELLED.value,
            self.statuses.COMPLETED.value,
            self.statuses.FAILED.value,
        }

    def renew_claim(self, workload: Workload, baseline: dict) -> bool:
        project_id, record_id = self._identity(baseline, workload)
        expected = self.turn(baseline, workload)
        renewed = False

        def change(raw: JsonDocument | None) -> dict | None:
            nonlocal renewed
            renewed = False
            if (
                not isinstance(raw, dict)
                or attempt_id(raw, workload) != expected.attempt
            ):
                return None
            current = self.turn(raw, workload)
            if (
                current.claim != expected.claim
                or current.claim is None
                or current.lease_until <= self.clock()
            ):
                return None
            current.lease_until = self.clock() + self.claim_seconds
            self._set_turn(raw, workload, current)
            renewed = True
            return raw

        self.processor(workload, project_id).mutate(record_id, change)
        return renewed

    def begin(
        self,
        workload: Workload,
        record: JobRecord,
        *,
        cancel: bool = False,
        request_id: str | None = None,
    ) -> JobRecord:
        incoming = record.model_dump(mode="json")
        project_id, record_id = self._identity(incoming, workload)
        workflow = WORKFLOWS[workload]

        def change(raw: JsonDocument | None) -> dict | None:
            if raw is not None and not isinstance(raw, dict):
                raise ValueError("Job metadata must be an object")
            data = raw
            if cancel:
                if data is None:
                    raise FileNotFoundError(
                        "Job was removed before cancellation"
                    )
                if attempt_id(incoming, workload) != attempt_id(
                    data, workload
                ):
                    raise ValueError(
                        "Cancellation refers to an older execution"
                    )
                if data.get(workflow.status) not in {
                    self.statuses.PENDING.value,
                    self.statuses.IN_PROGRESS.value,
                    self.statuses.CANCELLED.value,
                }:
                    return None
                ensure_pending_identity(data, workload, self.config)
                turn = self.turn(data, workload)
                data[workflow.status] = self.statuses.CANCELLED.value
                data[workflow.message] = MetadataUtils.append_status_message(
                    data.get(workflow.message), "Cancellation requested"
                )
            else:
                if data is not None:
                    old_turn = data.get(RUNTIME_KEY, {}).get(
                        workload.value, {}
                    )
                    if request_id and old_turn.get("request_id") == request_id:
                        return None
                    if attempt_id(data, workload) and self.needs_processing(
                        data, workload
                    ):
                        if request_id:
                            raise RuntimeError(
                                "Another execution is active; follow-on work "
                                "must wait rather than losing its request"
                            )
                        return None
                    if attempt_id(incoming, workload) and attempt_id(
                        incoming, workload
                    ) != attempt_id(data, workload):
                        raise ValueError(
                            "Submission refers to an older execution"
                        )
                data = data or incoming.copy()
                protected = set().union(
                    *(
                        item.fields
                        for item in WORKFLOWS.values()
                        if item.metadata_type == workflow.metadata_type
                    )
                )
                data.update(
                    {
                        key: value
                        for key, value in incoming.items()
                        if key not in protected and key != RUNTIME_KEY
                    }
                )
                data.update(
                    {
                        key: incoming[key]
                        for key in workflow.fields
                        if key in incoming
                        and key not in {workflow.job, workflow.current_task}
                    }
                )
                existing = current_job(data, workload)
                if existing.get("status") not in {
                    self.statuses.PENDING.value,
                    self.statuses.IN_PROGRESS.value,
                }:
                    if workflow.current_task:
                        data[workflow.current_task] = None
                    else:
                        data[workflow.job] = None
                data[workflow.status] = self.statuses.PENDING.value
                ensure_pending_identity(data, workload, self.config)
                turn = RuntimeTurn(
                    attempt=attempt_id(data, workload),
                    backend=self._backend(data, workload),
                    request_id=request_id,
                )
            turn.revision += 1
            turn.claim = None
            turn.lease_until = 0
            turn.next_poll = self.clock()
            self._set_turn(data, workload, turn)
            return data

        result = self.processor(workload, project_id).mutate(record_id, change)
        if not isinstance(result, dict):
            raise RuntimeError(
                "Job submission did not produce a durable record"
            )
        return workflow.model.model_validate(result)

    def claim(self, workload: Workload, message: dict) -> dict | None:
        project_id, record_id = self._identity(message, workload)
        claim = MetadataUtils.generate_id()
        accepted = False

        def change(raw: JsonDocument | None) -> dict | None:
            nonlocal accepted
            accepted = False
            if raw is None:
                return None
            if not isinstance(raw, dict):
                raise ValueError("Job metadata must be an object")
            if attempt_id(raw, workload) != attempt_id(message, workload):
                return None
            if not self.needs_processing(raw, workload):
                return None
            ensure_pending_identity(raw, workload, self.config)
            turn = self.turn(raw, workload)
            if turn.claim and turn.lease_until > self.clock():
                return None
            turn.revision += 1
            turn.claim = claim
            turn.lease_until = self.clock() + self.claim_seconds
            self._set_turn(raw, workload, turn)
            accepted = True
            return raw

        result = self.processor(workload, project_id).mutate(record_id, change)
        if not accepted:
            self.logger.info(
                "Ignoring removed, stale, terminal, or already claimed %s job %s",
                workload.value,
                record_id,
            )
            return None
        return result

    def require_current_submission(
        self, workload: Workload, baseline: dict
    ) -> None:
        project_id, record_id = self._identity(baseline, workload)
        current = self.processor(workload, project_id).load(record_id)
        expected = self.turn(baseline, workload)
        turn = self.turn(current, workload)
        if (
            turn.attempt != expected.attempt
            or turn.claim != expected.claim
            or turn.revision != expected.revision
            or turn.lease_until <= self.clock()
            or current.get(WORKFLOWS[workload].status)
            != self.statuses.PENDING.value
        ):
            raise ValueError(
                "Submission is no longer the current pending turn"
            )

    def record_submission(
        self,
        workload: Workload,
        baseline: dict,
        handle: ComputeJobHandle,
    ) -> bool:
        project_id, record_id = self._identity(baseline, workload)
        expected = self.turn(baseline, workload)
        if handle.executionId != expected.attempt:
            raise ValueError(
                "Provider changed the accepted execution identity"
            )
        accepted = False

        def change(raw: JsonDocument | None) -> dict | None:
            nonlocal accepted
            accepted = False
            if (
                not isinstance(raw, dict)
                or attempt_id(raw, workload) != expected.attempt
            ):
                return None
            job = current_job(raw, workload)
            stored = job.get("computeJob")
            if stored:
                previous = ComputeJobHandle.model_validate(stored)
                if (
                    previous.selectedBackend != handle.selectedBackend
                    or previous.providerJobId != handle.providerJobId
                    or previous.providerTaskId != handle.providerTaskId
                ):
                    raise ValueError(
                        "Execution already belongs to another provider"
                    )
                if job.get("status") in {
                    self.statuses.COMPLETED.value,
                    self.statuses.FAILED.value,
                    self.statuses.CANCELLED.value,
                }:
                    accepted = True
                    return None
            elif raw.get(WORKFLOWS[workload].status) in {
                self.statuses.COMPLETED.value,
                self.statuses.FAILED.value,
            }:
                return None
            job.update(
                jobId=handle.providerJobId,
                computeJob=handle.model_dump(mode="json"),
                status=self.statuses.IN_PROGRESS.value,
            )
            turn = self.turn(raw, workload)
            turn.backend = handle.selectedBackend.value
            self._set_turn(raw, workload, turn)
            accepted = True
            return raw

        self.processor(workload, project_id).mutate(record_id, change)
        return accepted

    def _update_claim(
        self,
        workload: Workload,
        baseline: dict,
        update: Callable[[dict, RuntimeTurn], None],
    ) -> dict | None:
        project_id, record_id = self._identity(baseline, workload)
        expected = self.turn(baseline, workload)
        accepted = False

        def change(raw: JsonDocument | None) -> dict | None:
            nonlocal accepted
            accepted = False
            if (
                not isinstance(raw, dict)
                or attempt_id(raw, workload) != expected.attempt
            ):
                return None
            turn = self.turn(raw, workload)
            if (
                turn.claim != expected.claim
                or turn.revision != expected.revision
                or turn.lease_until <= self.clock()
            ):
                return None
            status_field = WORKFLOWS[workload].status
            if raw.get(status_field) != baseline.get(status_field) and raw.get(
                status_field
            ) in {
                self.statuses.COMPLETED.value,
                self.statuses.FAILED.value,
                self.statuses.CANCELLED.value,
            }:
                return None
            update(raw, turn)
            turn.revision += 1
            self._set_turn(raw, workload, turn)
            accepted = True
            return raw

        result = self.processor(workload, project_id).mutate(record_id, change)
        if not accepted:
            self.logger.info(
                "Discarding fenced %s update for %s", workload.value, record_id
            )
            return None
        return result

    def commit(
        self,
        workload: Workload,
        baseline: dict,
        output: JobRecord,
        cleanup: list[TaskIdentity],
    ) -> dict | None:
        workflow = WORKFLOWS[workload]
        values = output.model_dump(mode="json")

        def update(data: dict, turn: RuntimeTurn) -> None:
            if attempt_id(values, workload) != turn.attempt:
                raise ValueError(
                    "Processor changed the current execution identity"
                )
            if data.get(workflow.status) in {
                self.statuses.COMPLETED.value,
                self.statuses.FAILED.value,
                self.statuses.CANCELLED.value,
            } and values.get(workflow.status) != data.get(workflow.status):
                raise ValueError("A terminal execution cannot change status")
            data.update(
                {
                    key: values[key]
                    for key in workflow.fields
                    if key in values
                    and values[key] != baseline.get(key)
                    and (
                        key != "computeBackend"
                        or data.get(key) == baseline.get(key)
                    )
                }
            )
            turn.cleanup = cleanup
            turn.error = None
            status = data.get(workflow.status)
            if workload == Workload.TRAINING:
                if status == self.statuses.COMPLETED.value and data.get(
                    "autoRunInference"
                ):
                    turn.actions[
                        "inference"
                    ] = f"training:{turn.attempt}:inference"
                elif status in {
                    self.statuses.FAILED.value,
                    self.statuses.CANCELLED.value,
                } and data.get("trainingOutputPath"):
                    turn.actions["zip"] = f"training:{turn.attempt}:zip"
            elif (
                workload == Workload.INFERENCE
                and status
                in {
                    self.statuses.COMPLETED.value,
                    self.statuses.FAILED.value,
                    self.statuses.CANCELLED.value,
                }
                and data.get("inferenceOutputPath")
            ):
                turn.actions["zip"] = f"inference:{turn.attempt}:zip"

        return self._update_claim(workload, baseline, update)

    def complete_action(
        self, workload: Workload, baseline: dict, action: str
    ) -> dict | None:
        def update(data: dict, turn: RuntimeTurn) -> None:
            if action == "cleanup":
                turn.cleanup = []
            else:
                turn.actions.pop(action, None)
            if turn.error:
                field = WORKFLOWS[workload].message
                data[field] = MetadataUtils.append_status_message(
                    data.get(field), f"Deferred {action} action completed"
                )
                turn.error = None

        return self._update_claim(workload, baseline, update)

    def release(
        self,
        workload: Workload,
        baseline: dict,
        error: Exception | None = None,
    ) -> dict | None:
        def update(data: dict, turn: RuntimeTurn) -> None:
            turn.claim = None
            turn.lease_until = 0
            turn.next_poll = self.clock() + 30
            if error is not None:
                turn.error = (
                    f"Job processing interrupted ({type(error).__name__}); "
                    "reconciliation pending"
                )
                field = WORKFLOWS[workload].message
                data[field] = MetadataUtils.append_status_message(
                    data.get(field), turn.error
                )

        return self._update_claim(workload, baseline, update)

    def enqueue(self, workload: Workload, data: dict) -> None:
        workflow = WORKFLOWS[workload]
        client = AzureQueueHandler(
            self.config.queue_config["queue_connection_string"],
            self.config.queue_config[workflow.queue],
            self.config.queue_config["queue_account_url"],
        )
        client.put_message(
            json.dumps(
                workflow.model.model_validate(data).model_dump(mode="json")
            )
        )

    def mark_delivery_interrupted(
        self, workload: Workload, message: dict
    ) -> None:
        project_id, record_id = self._identity(message, workload)

        def change(raw: JsonDocument | None) -> dict | None:
            if not isinstance(raw, dict) or attempt_id(
                raw, workload
            ) != attempt_id(message, workload):
                return None
            if not self.needs_processing(raw, workload):
                return None
            ensure_pending_identity(raw, workload, self.config)
            turn = self.turn(raw, workload)
            turn.error = "Queue delivery interrupted; reconciliation pending"
            turn.next_poll = 0
            self._set_turn(raw, workload, turn)
            return raw

        self.processor(workload, project_id).mutate(record_id, change)
        self.logger.warning(
            "Recorded interrupted %s queue delivery for %s",
            workload.value,
            record_id,
        )

    def reconcile_queues(self) -> int:
        count = 0
        for workload in Workload:
            records = self.processor(workload, None).load_all()
            for data in records:
                if workload in {Workload.TRAINING, Workload.EMBEDDING} and (
                    data.get("modelType") == "embedding"
                ) != (workload == Workload.EMBEDDING):
                    continue
                if not self.needs_processing(data, workload):
                    continue
                if attempt_id(data, workload):
                    turn = self.turn(data, workload)
                    if max(turn.lease_until, turn.next_poll) > self.clock():
                        continue
                self.enqueue(workload, data)
                count += 1
        return count


class JobClaimRenewal:
    """Renew a coordination lease; provider state remains authoritative."""

    def __init__(
        self,
        repository: JobStateRepository,
        workload: Workload,
        baseline: dict,
    ) -> None:
        self.repository = repository
        self.workload = workload
        self.baseline = baseline
        self.stop = Event()
        self.error: Exception | None = None
        self.thread = Thread(
            target=self._renew, daemon=True, name="haste-job-claim-renewal"
        )

    def start(self) -> None:
        self.thread.start()

    def _renew(self) -> None:
        while not self.stop.wait(self.repository.renewal_interval_seconds):
            try:
                if not self.repository.renew_claim(
                    self.workload, self.baseline
                ):
                    self.error = RuntimeError(
                        "Processing claim is no longer owned"
                    )
                    return
            except Exception as error:
                self.error = error
                self.repository.logger.error(
                    "Job claim renewal failed (%s)", type(error).__name__
                )
                return

    def check(self) -> None:
        if self.error is not None:
            raise RuntimeError(
                "Processing claim renewal failed"
            ) from self.error

    def close(self) -> None:
        self.stop.set()
        self.thread.join(timeout=5)


def persist_and_enqueue(
    record: JobRecord,
    workload: Workload,
    config: Config,
    queue: AzureQueueHandler,
    *,
    cancel: bool = False,
    request_id: str | None = None,
) -> JobRecord:
    repository = JobStateRepository(config)
    saved = repository.begin(
        workload, record, cancel=cancel, request_id=request_id
    )
    queue.put_message(
        json.dumps(saved.model_dump(mode="json")),
        visibility_timeout=1 if cancel else 0,
    )
    return saved
