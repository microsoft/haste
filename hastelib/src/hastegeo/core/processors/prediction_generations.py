# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License.

"""Durable, guarded raw-result publication, separate from stale Model snapshots.

The generation document is authoritative for the fields below. Model fields
are mirrored best effort for older readers. Mirror failures are logged but do
not block accepted work. All new result readers overlay this document,
so a legacy full Model save cannot restore obsolete pointers or readiness.
Blob leases serialize participating writers; this is not a metadata CAS.
Local metadata uses a process-shared filesystem lock instead.
"""

from contextlib import contextmanager
from pathlib import Path
from typing import Any, Callable, Iterator

from azure.core.exceptions import ResourceNotFoundError

from ..config import Config
from ..models.projects import Model
from ..publishing.lease import BlobLeaseCoordinator
from ..utils.logs import Logger
from ..utils.metadata import MetadataUtils
from .metadata import MetadataProcessor

GENERATION_FIELDS = {
    "predictionAttrsUrl",
    "gpkgUrl",
    "predictedBuildingCount",
    "predictedAt",
    "predictionRevision",
    "predictionReadyRevision",
    "predictionState",
    "predictionOutputPrefix",
    "predictionSourceTaskId",
    "predictionGpkgFilename",
    "predictedDamageLayerUrl",
}
INFERENCE_FIELDS = {
    "inferenceJobs",
    "inferenceStatus",
    "currentInferenceTaskId",
    "inferenceOutputPath",
    "inferenceCurrentStep",
    "inferenceTotalSteps",
    "inferenceProgressPct",
    "inferenceStatusMessage",
}


class PredictionSupersededError(RuntimeError):
    """Another accepted request replaced this generation."""


class PredictionGenerationRepository:
    def __init__(
        self,
        config: Config | None = None,
        processor_factory: Callable[..., MetadataProcessor] | None = None,
    ) -> None:
        self.config = config or Config()
        self.processor_factory = processor_factory or MetadataProcessor
        self.coordinator: BlobLeaseCoordinator | None = None

    def metadata(
        self, project_id: str, generations: bool = False
    ) -> MetadataProcessor:
        return self.processor_factory(
            data_type=(
                self.config.get_metadata_types().PREDICTION_RESULTS.value
                if generations
                else self.config.get_metadata_types().MODEL.value
            ),
            partition_key=project_id,
            config=self.config,
        )

    def load(self, project_id: str, model_id: str) -> Model:
        record = self.metadata(project_id).load_strict(model_id)
        if not record:
            raise FileNotFoundError("Model not found")
        try:
            generation = self.metadata(
                project_id, generations=True
            ).load_strict(model_id)
        except FileNotFoundError:
            generation = None
        if generation:
            deleted = generation.get("predictionState") == "deleted"
            identity_fields = ("projectId", "modelId")
            if not deleted:
                identity_fields += ("imageLayerId",)
            if any(
                generation.get(key) != record.get(key)
                for key in identity_fields
            ):
                raise FileNotFoundError(
                    "Generation does not belong to this model"
                )
            if deleted:
                # A deletion barrier contains no old results or jobs. It
                # must not overwrite a recreated model's layer association.
                generation = {
                    field: generation[field]
                    for field in GENERATION_FIELDS | INFERENCE_FIELDS
                    if field in generation
                }
            record = {**record, **generation}
        elif record.get("predictionRevision"):
            # A mirror is not proof of publication. Confirmed loss of the
            # authoritative document must not resurrect a cached generation.
            record = {
                **record,
                "predictionState": "unverified",
                "predictionReadyRevision": None,
            }
        model = Model.model_validate(record)
        if model.projectId != project_id or model.modelId != model_id:
            raise FileNotFoundError("Model does not belong to this project")
        return model

    def delete_model_metadata(self, project_id: str, model_id: str) -> None:
        """Retire this model's authority under the publisher lock, then delete.

        Keep one empty barrier with a fresh revision instead of removing the
        authority outright. This fences a first prediction request that saw
        no generation before deletion and finishes after same-ID recreation.
        This is scoped metadata cleanup, not artifact garbage collection.
        """
        with self.lock(project_id, model_id) as lease:
            empty = Model(projectId=project_id, modelId=model_id)
            self.initialize(empty, MetadataUtils.generate_id(), clear=True)
            empty.predictionState = "deleted"
            authority = self.metadata(project_id, generations=True)
            if lease is not None:
                lease.renew()
            # Replace, do not merge: old authority fields must not survive,
            # and deletion must also work when the old authority is corrupt.
            authority.storage.save(
                identifier=model_id,
                data=empty.model_dump(
                    include=GENERATION_FIELDS
                    | INFERENCE_FIELDS
                    | {"projectId", "modelId"}
                ),
                data_type=authority.data_type,
                data_format="json",
            )
            self.metadata(project_id).delete(model_id)
            types = self.config.get_metadata_types()
            for data_type, data_format in (
                (types.EXPERIMENT_CONFIG.value, "yaml"),
                (types.TRAIN_LABELS.value, "geojson"),
                (types.MODEL_ARTIFACTS.value, "json"),
            ):
                try:
                    self.processor_factory(
                        data_type=data_type,
                        partition_key=project_id,
                        config=self.config,
                    ).delete(model_id, data_format)
                except (FileNotFoundError, ResourceNotFoundError):
                    pass  # These optional records may never have been created.

    @contextmanager
    def lock(self, project_id: str, model_id: str) -> Iterator[Any]:
        if self.config.storage_type == "local":
            import fcntl

            directory = Path(self.config.storage_config["directory"])
            lock_dir = (
                directory
                / MetadataUtils.hash_string(project_id)
                / ".prediction-locks"
            )
            lock_dir.mkdir(parents=True, exist_ok=True)
            with (lock_dir / f"{model_id}.lock").open("a") as handle:
                fcntl.flock(handle, fcntl.LOCK_EX)
                try:
                    yield None
                finally:
                    fcntl.flock(handle, fcntl.LOCK_UN)
            return
        if self.coordinator is None:
            publishing = self.config.publishing_config
            self.coordinator = BlobLeaseCoordinator(
                connection_string=(
                    publishing["lease_connection_string"]
                    or self.config.queue_config["queue_connection_string"]
                ),
                account_url=publishing["lease_account_url"],
                container_name=publishing["lease_container"],
            )
        with self.coordinator.acquire(
            project_id,
            f"prediction-results-{model_id}",
            wait_timeout_seconds=2,
        ) as lease:
            yield lease

    def save_locked(self, model: Model, lease: Any) -> None:
        if lease is not None:
            lease.renew()  # Fail closed before publishing if ownership was lost.
        fields = GENERATION_FIELDS | {"projectId", "imageLayerId", "modelId"}
        if model.modelType != "embedding":
            fields |= INFERENCE_FIELDS
        document = model.model_dump(include=fields)
        # Readers use this record even if a later mirror save fails.
        self.metadata(model.projectId, generations=True).save_strict(
            model.modelId, document
        )
        try:
            self.metadata(model.projectId).save_strict(model.modelId, document)
        except Exception as error:
            # The authoritative commit succeeded. A compatibility-mirror
            # failure must not prevent queue publication and strand accepted
            # work. Subsequent state transitions repair the mirror. Never
            # reacquire this model's lock from this error path.
            Logger.get_logger(__name__).warning(
                "Prediction authority committed; Model mirror update failed (%s)",
                type(error).__name__,
            )

    @staticmethod
    def initialize(
        model: Model, revision: str, *, clear: bool = False
    ) -> None:
        model.predictionRevision = revision
        model.predictionReadyRevision = None
        model.predictionState = "cleared" if clear else "pending"
        model.predictionAttrsUrl = None
        model.gpkgUrl = None
        model.predictedBuildingCount = 0 if clear else None
        model.predictedAt = None
        model.predictionOutputPrefix = None
        model.predictionSourceTaskId = None
        model.predictionGpkgFilename = None
        if model.modelType != "embedding":
            model.predictedDamageLayerUrl = None

    def fail(self, project_id: str, model_id: str, revision: str) -> None:
        with self.lock(project_id, model_id) as lease:
            model = self.load(project_id, model_id)
            if (
                model.predictionRevision == revision
                and model.predictionState == "pending"
            ):
                model.predictionState = "failed"
                if model.modelType != "embedding":
                    model.inferenceStatus = (
                        self.config.get_status_types().FAILED.value
                    )
                    model.inferenceStatusMessage = (
                        MetadataUtils.append_status_message(
                            model.inferenceStatusMessage or "",
                            "Prediction generation failed before publication.",
                        )
                    )
                self.save_locked(model, lease)
