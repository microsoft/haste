# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License.

"""Versioned artifacts and Model history, serialized only for edit publication."""

import hashlib
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any

from azure.core.exceptions import ResourceExistsError

from ..artifact_storage.unified_artifact_storage import UnifiedArtifactStorage
from ..models.prediction_edits import (
    EditedPredictionAttributes,
    EditedPredictionVersion,
    PredictionEditSessionRequest,
    PredictionVersionsRequest,
    SavedPredictionResponse,
    SaveEditedPredictionsRequest,
)
from ..models.projects import Model
from ..publishing.lease import LeaseRenewalError, LeaseUnavailableError
from ..utils.metadata import MetadataUtils
from ..utils.prediction_edit_lock import prediction_edit_lock
from ..utils.prediction_readiness import (
    artifact_api_url,
    raw_predictions_readiness,
)
from .prediction_results import (
    PredictionRequestError,
    PredictionResultsProcessor,
    fetch_prediction_file,
)
from .prediction_sources import (
    find_edited_version,
    prediction_source_url,
    prediction_versions,
    resolve_prediction_source,
    source_readiness,
)


class PredictionEditConflict(RuntimeError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


def edit_request_fingerprint(request: SaveEditedPredictionsRequest) -> str:
    data = request.model_dump(
        mode="json", by_alias=True, exclude={"clientRequestId"}
    )
    data["overrides"] = sorted(data["overrides"], key=lambda row: row["id"])
    data["threshold"] = request.threshold or 0.0
    data["unknownThreshold"] = request.unknownThreshold or 0.0
    return hashlib.sha256(
        json.dumps(data, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def download_prediction_input(
    processor: PredictionResultsProcessor, location: str, directory: str
) -> str:
    storage = UnifiedArtifactStorage(
        processor.config.artifact_storage_type,
        **processor.config.artifact_storage_config,
    )
    return str(fetch_prediction_file(storage, location, directory))


class PredictionEditsProcessor(PredictionResultsProcessor):
    def list_versions(
        self, request: PredictionVersionsRequest
    ) -> dict[str, Any]:
        model = self.model(request.projectId, request.modelId)
        if request.imageLayerId and request.imageLayerId != model.imageLayerId:
            raise PredictionRequestError("Model does not belong to this layer")
        return {
            "modelId": model.modelId,
            "currentPredictionRevision": model.predictionRevision,
            "versions": prediction_versions(
                model, self.layer(model.projectId, model.imageLayerId)
            ),
        }

    def get_session(
        self, request: PredictionEditSessionRequest
    ) -> dict[str, Any]:
        model, layer = self.context(request)
        source = resolve_prediction_source(
            model,
            request.version,
            prediction_revision=request.predictionRevision,
        )
        readiness = source_readiness(model, layer, source)
        edit_readiness = dict(readiness)
        if (
            source.predictionRevision is None
            or source.predictionRevision != model.predictionRevision
        ):
            edit_readiness.update(
                ready=False,
                reason="source_changed",
                detail="This version belongs to an older raw output.",
            )
        elif not raw_predictions_readiness(model)["ready"]:
            edit_readiness.update(
                ready=False,
                reason="missing_raw_source",
                detail="The raw baseline is unavailable for editing.",
            )
        return {
            "projectId": model.projectId,
            "imageLayerId": model.imageLayerId,
            "modelId": model.modelId,
            **source.descriptor(),
            "supportsThreshold": source.flavor == "inference"
            and not source.is_edited,
            "defaultThreshold": 0.0,
            "defaultUnknownThreshold": 0.0,
            "buildingCount": source.buildingCount,
            "editedCount": source.editedCount,
            "predictionsReady": readiness["ready"],
            "predictionsReadiness": readiness,
            "editReadiness": edit_readiness,
            "tilesReady": readiness["tilesReady"],
            "attrsReady": readiness["attrsReady"],
            "footprintTilesUrl": artifact_api_url(model, "footprint_pmtiles")
            if layer.footprintPmtilesUrl
            else None,
            "gpkgUrl": prediction_source_url(model, source, "gpkg")
            if source.gpkgUrl
            else None,
            "predictionAttrsUrl": prediction_source_url(
                model, source, "prediction_attrs"
            )
            if source.predictionAttrsUrl
            else None,
            "versions": prediction_versions(model, layer),
        }

    @staticmethod
    def saved_response(model: Model, version: int) -> SavedPredictionResponse:
        entry = find_edited_version(model, version)
        source = resolve_prediction_source(model, version)
        return SavedPredictionResponse(
            version=entry.version,
            predictionRevision=source.predictionRevision,
            gpkgUrl=prediction_source_url(model, source, "gpkg"),
            predictionAttrsUrl=prediction_source_url(
                model, source, "prediction_attrs"
            ),
            buildingCount=entry.buildingCount,
            editedCount=entry.editedCount,
            overridesApplied=entry.overridesApplied,
        )

    def save(
        self, request: SaveEditedPredictionsRequest, created_by: str | None
    ) -> SavedPredictionResponse:
        fingerprint = edit_request_fingerprint(request)
        try:
            with prediction_edit_lock(
                self.config, request.projectId, request.modelId
            ) as lease:
                model, layer = self.context(request)
                for entry in model.editedPredictions or []:
                    if entry.clientRequestId == str(request.clientRequestId):
                        if entry.requestFingerprint != fingerprint:
                            raise PredictionEditConflict(
                                "request_conflict",
                                "Request ID was used for a different save.",
                            )
                        return self.saved_response(model, entry.version)
                self._validate_source(model, request)
                if not layer.buildingFootprintsUrl:
                    raise FileNotFoundError("Cached footprints are missing")
                source = resolve_prediction_source(model, request.baseVersion)
                version = (
                    max(
                        (
                            entry.version
                            for entry in model.editedPredictions or []
                        ),
                        default=0,
                    )
                    + 1
                )
                storage = UnifiedArtifactStorage(
                    self.config.artifact_storage_type,
                    **self.config.artifact_storage_config,
                )
                # Each attempt has its own files. Failed attempts need neither
                # reservations nor an overwrite when the same request retries.
                namespace = [
                    MetadataUtils.hash_string(model.projectId),
                    "prediction_edits",
                    model.modelId,
                    MetadataUtils.generate_id(),
                ]
                with TemporaryDirectory(dir=self.config.TEMP_DIR) as directory:
                    raw = download_prediction_input(
                        self, model.gpkgUrl, str(Path(directory, "raw"))
                    )
                    footprints = download_prediction_input(
                        self,
                        layer.buildingFootprintsUrl,
                        str(Path(directory, "footprints")),
                    )
                    from ..utils.prediction_edits import (
                        PredictionOverride,
                        apply_prediction_edits,
                    )

                    gpkg_name = (
                        f"edited_predictions_{model.modelId}_v{version}.gpkg"
                    )
                    attrs_name = (
                        f"prediction_attrs_{model.modelId}_v{version}.json"
                    )
                    artifacts = apply_prediction_edits(
                        raw,
                        footprints,
                        str(Path(directory, gpkg_name)),
                        str(Path(directory, attrs_name)),
                        prediction_revision=request.predictionRevision,
                        version=version,
                        flavor=source.flavor,
                        threshold=request.threshold,
                        unknown_threshold=request.unknownThreshold,
                        overrides=[
                            PredictionOverride(row.id, row.edited_class)
                            for row in request.overrides
                        ],
                    )
                    attrs = EditedPredictionAttributes.model_validate(
                        artifacts.payload
                    )
                    for name, path in (
                        (gpkg_name, artifacts.gpkg_path),
                        (attrs_name, artifacts.attrs_path),
                    ):
                        stored = storage.store_artifact(
                            name,
                            src_path=path,
                            namespace=namespace,
                            overwrite=False,
                        )
                        if (
                            not storage.artifact_exists(stored)
                            or storage.get_artifact_size(stored) <= 0
                        ):
                            raise RuntimeError("Edited artifact upload failed")
                current = self.model(model.projectId, model.modelId)
                self._validate_source(current, request)
                if lease is not None:
                    lease.renew()
                entry = EditedPredictionVersion(
                    version=version,
                    gpkgUrl=storage.get_download_url(
                        identifier=gpkg_name, extra_partition_keys=namespace
                    ),
                    predictionAttrsUrl=storage.get_download_url(
                        identifier=attrs_name, extra_partition_keys=namespace
                    ),
                    sourcePredictionRevision=request.predictionRevision,
                    sourceGpkgUrl=model.gpkgUrl,
                    baseVersion=request.baseVersion,
                    clientRequestId=str(request.clientRequestId),
                    requestFingerprint=fingerprint,
                    createdAt=MetadataUtils.get_timestamp(),
                    createdBy=created_by,
                    threshold=request.threshold,
                    unknownThreshold=request.unknownThreshold,
                    buildingCount=attrs.n,
                    editedCount=artifacts.summary.changed_from_model,
                    overridesApplied=artifacts.summary.overrides_applied,
                    flavor=source.flavor,
                )
                versions = [*(current.editedPredictions or []), entry]
                self.metadata(model.projectId).save(
                    model.modelId,
                    {
                        "editedPredictions": [
                            item.model_dump(mode="json") for item in versions
                        ]
                    },
                )
                return self.saved_response(
                    current.model_copy(update={"editedPredictions": versions}),
                    version,
                )
        except (
            LeaseUnavailableError,
            LeaseRenewalError,
            ResourceExistsError,
            FileExistsError,
        ):
            raise PredictionEditConflict(
                "save_conflict", "The save is busy; please retry."
            ) from None

    @staticmethod
    def _validate_source(
        model: Model, request: SaveEditedPredictionsRequest
    ) -> None:
        if (
            model.imageLayerId != request.imageLayerId
            or model.predictionRevision != request.predictionRevision
            or not raw_predictions_readiness(model)["ready"]
        ):
            raise PredictionEditConflict(
                "source_changed", "Raw predictions changed; reopen editing."
            )
        source = resolve_prediction_source(model, request.baseVersion)
        if source.predictionRevision != request.predictionRevision:
            raise PredictionEditConflict(
                "source_changed",
                "The base version belongs to older predictions.",
            )
        if request.baseVersion and (
            request.threshold != source.threshold
            or request.unknownThreshold != source.unknownThreshold
        ):
            raise PredictionRequestError(
                "Select raw predictions before changing thresholds"
            )
        if source.flavor == "embedding" and (
            request.threshold or request.unknownThreshold
        ):
            raise PredictionRequestError("Embedding scores have no thresholds")
        if model.predictedBuildingCount is None or any(
            row.id >= model.predictedBuildingCount for row in request.overrides
        ):
            raise PredictionRequestError(
                "Override IDs must match raw predictions"
            )
