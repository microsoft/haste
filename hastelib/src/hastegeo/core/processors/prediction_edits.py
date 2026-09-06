# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License.

"""Explicit, paired, immutable edit saves. No preparation queues or GET writes."""

import hashlib
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any

from azure.core.exceptions import ResourceExistsError

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
from ..utils.prediction_readiness import (
    artifact_api_url,
    raw_predictions_readiness,
)
from .prediction_generations import PredictionEditConflict
from .prediction_results import (
    MAX_ATTRIBUTES_BYTES,
    PredictionRequestError,
    PredictionResultsProcessor,
)
from .prediction_sources import (
    find_edited_version,
    prediction_source_url,
    prediction_versions,
    resolve_prediction_source,
    source_readiness,
)


def edit_request_fingerprint(request: SaveEditedPredictionsRequest) -> str:
    data = request.model_dump(
        mode="json", by_alias=True, exclude={"clientRequestId"}
    )
    data["overrides"] = sorted(data["overrides"], key=lambda item: item["id"])
    # JSON spellings 0 and -0.0 are the same logical threshold.
    data["threshold"] = request.threshold or 0.0
    data["unknownThreshold"] = request.unknownThreshold or 0.0
    canonical = json.dumps(
        data, sort_keys=True, separators=(",", ":"), allow_nan=False
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def download_prediction_input(
    processor: PredictionResultsProcessor, location: str, directory: str
) -> str:
    """Fetch trusted input through configured storage, supporting Local/Blob."""
    storage = processor.storage()
    relative = storage.resolve_artifact_path(location)
    if not storage.artifact_exists(relative):
        raise FileNotFoundError("Prediction source artifact is missing")
    Path(directory).mkdir(parents=True, exist_ok=True)
    if processor.config.artifact_storage_type == "local":
        storage.fetch_artifact(
            src_path=storage.get_file_path(relative), dst_path=directory
        )
        path = Path(directory, Path(relative).name)
    else:
        storage.fetch_artifact(src_path=relative, dst_path=directory)
        path = Path(directory, relative)
    if not path.is_file():
        raise FileNotFoundError("Prediction source artifact is missing")
    return str(path)


class PredictionEditsProcessor(PredictionResultsProcessor):
    def list_versions(
        self, request: PredictionVersionsRequest
    ) -> dict[str, Any]:
        model = self.repository.load(request.projectId, request.modelId)
        if request.imageLayerId and request.imageLayerId != model.imageLayerId:
            raise PredictionRequestError(
                "Model does not belong to the requested layer"
            )
        layer = self.layer(request.projectId, model.imageLayerId)
        return {
            "modelId": model.modelId,
            "currentPredictionRevision": model.predictionRevision,
            "versions": prediction_versions(model, layer),
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
                detail="This version belongs to an older or unknown raw generation.",
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
        if (
            not entry.predictionAttrsUrl
            or entry.buildingCount is None
            or not source.predictionRevision
        ):
            raise RuntimeError(
                "Confirmed edit receipt has incomplete version metadata"
            )
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
        request_id = str(request.clientRequestId)
        try:
            with self.repository.lock(
                request.projectId, request.modelId, wait_timeout_seconds=2
            ) as lease:
                model = self.repository.load(
                    request.projectId, request.modelId
                )
                if model.imageLayerId != request.imageLayerId:
                    raise PredictionRequestError(
                        "Model does not belong to the requested layer"
                    )
                previous = model.predictionEditReceipts.get(request_id)
                if previous:
                    if previous.fingerprint != fingerprint:
                        raise PredictionEditConflict(
                            "request_conflict",
                            "Request ID was used for a different save.",
                        )
                    if previous.state == "committed":
                        # Replay is not a new edit, even after raw regeneration.
                        return self.saved_response(model, previous.version)
                elif any(
                    str(item.clientRequestId) == request_id
                    for item in model.editedPredictions or []
                ):
                    raise RuntimeError("Confirmed edit has no request receipt")
                if (
                    model.predictionRevision != request.predictionRevision
                    or not raw_predictions_readiness(model)["ready"]
                ):
                    raise PredictionEditConflict(
                        "source_changed",
                        "Raw predictions changed; reopen the edit session.",
                    )
                source = resolve_prediction_source(model, request.baseVersion)
                if source.predictionRevision != request.predictionRevision:
                    raise PredictionEditConflict(
                        "source_changed",
                        "The base version belongs to another raw generation.",
                    )
                if request.baseVersion and (
                    request.threshold != source.threshold
                    or request.unknownThreshold != source.unknownThreshold
                ):
                    raise PredictionRequestError(
                        "Select raw predictions before changing thresholds"
                    )
                if source.flavor == "embedding" and (
                    request.threshold != 0 or request.unknownThreshold != 0
                ):
                    raise PredictionRequestError(
                        "Embedding predictions do not support score thresholds"
                    )
                if model.predictedBuildingCount is not None and any(
                    row.id >= model.predictedBuildingCount
                    for row in request.overrides
                ):
                    raise PredictionRequestError(
                        "Override row ID is outside the raw prediction source"
                    )
                layer = self.layer(request.projectId, request.imageLayerId)
                if not layer.buildingFootprintsUrl:
                    raise FileNotFoundError(
                        "Cached building footprints are missing"
                    )
                receipt = self.repository.reserve_edit_locked(
                    model, request_id, fingerprint, created_by, lease
                )
                with TemporaryDirectory(dir=self.config.TEMP_DIR) as directory:
                    raw_path = download_prediction_input(
                        self, model.gpkgUrl, str(Path(directory, "raw"))
                    )
                    footprints_path = download_prediction_input(
                        self,
                        layer.buildingFootprintsUrl,
                        str(Path(directory, "footprints")),
                    )
                    # GIS owns all class/geometry processing. Import lazily so
                    # read-only metadata paths do not initialize geospatial I/O.
                    from ..utils.prediction_edits import (
                        PredictionOverride,
                        apply_prediction_edits,
                    )

                    gpkg_name = (
                        self.config.get_artifact_types().EDITED_PREDICTIONS_GPKG.value.substitute(
                            modelId=model.modelId, version=receipt.version
                        )
                        + ".gpkg"
                    )
                    attrs_name = (
                        self.config.get_artifact_types().PREDICTION_ATTRS_VERSION.value.substitute(
                            modelId=model.modelId, version=receipt.version
                        )
                        + ".json"
                    )
                    try:
                        artifacts = apply_prediction_edits(
                            raw_path,
                            footprints_path,
                            str(Path(directory, gpkg_name)),
                            str(Path(directory, attrs_name)),
                            prediction_revision=request.predictionRevision,
                            version=receipt.version,
                            flavor=source.flavor,
                            threshold=request.threshold,
                            unknown_threshold=request.unknownThreshold,
                            overrides=[
                                PredictionOverride(row.id, row.edited_class)
                                for row in request.overrides
                            ],
                        )
                    except ValueError:
                        raise PredictionRequestError(
                            "Edits do not match the raw prediction source"
                        ) from None
                    self.repository.renew_edit_lease(lease)
                    namespace = [
                        "prediction_edits",
                        model.modelId,
                        request.predictionRevision,
                        f"v{receipt.version}",
                    ]
                    storage = self.storage(model.projectId)
                    gpkg_path = storage.store_artifact(
                        artifact_name=gpkg_name,
                        src_path=artifacts.gpkg_path,
                        namespace=namespace,
                        overwrite=False,
                    )
                    attrs_path = storage.store_artifact(
                        artifact_name=attrs_name,
                        src_path=artifacts.attrs_path,
                        namespace=namespace,
                        overwrite=False,
                    )
                    if (
                        not storage.artifact_exists(gpkg_path)
                        or storage.get_artifact_size(gpkg_path) <= 0
                    ):
                        raise RuntimeError(
                            "Edited GeoPackage upload is missing"
                        )
                    attrs = EditedPredictionAttributes.model_validate_json(
                        storage.read_artifact_bytes(
                            attrs_path, MAX_ATTRIBUTES_BYTES
                        )
                    )
                    assignments = {
                        row.id: row.edited_class for row in request.overrides
                    }
                    if (
                        attrs.predictionRevision != request.predictionRevision
                        or attrs.predictionVersion != receipt.version
                        or attrs.flavor != source.flavor
                        or attrs.n != artifacts.count
                        or attrs.n != artifacts.summary.total_rows
                        or attrs.threshold != request.threshold
                        or attrs.unknownThreshold != request.unknownThreshold
                        or artifacts.summary.changed_from_model
                        != sum(
                            effective != baseline
                            for effective, baseline in zip(
                                attrs.classes, attrs.modelClasses
                            )
                        )
                        or artifacts.summary.overrides_applied
                        != sum(
                            value is not None
                            for value in attrs.overrideClasses
                        )
                        or not assignments.keys() <= set(attrs.ids)
                        or any(
                            override != assignments.get(row_id)
                            for row_id, override in zip(
                                attrs.ids, attrs.overrideClasses
                            )
                        )
                    ):
                        raise RuntimeError(
                            "Uploaded edit attributes do not match the save"
                        )
                    entry = EditedPredictionVersion(
                        version=receipt.version,
                        gpkgUrl=storage.get_download_url(
                            identifier=gpkg_name,
                            extra_partition_keys=namespace,
                        ),
                        predictionAttrsUrl=storage.get_download_url(
                            identifier=attrs_name,
                            extra_partition_keys=namespace,
                        ),
                        sourcePredictionRevision=request.predictionRevision,
                        sourceGpkgUrl=model.gpkgUrl,
                        baseVersion=request.baseVersion,
                        clientRequestId=request.clientRequestId,
                        createdAt=MetadataUtils.get_timestamp(),
                        createdBy=receipt.createdBy,
                        threshold=request.threshold,
                        unknownThreshold=request.unknownThreshold,
                        buildingCount=attrs.n,
                        editedCount=artifacts.summary.changed_from_model,
                        overridesApplied=artifacts.summary.overrides_applied,
                        flavor=source.flavor,
                    )
                    committed = self.repository.commit_edit_locked(
                        model.projectId,
                        model.modelId,
                        request_id,
                        receipt,
                        entry,
                        lease,
                    )
                    return self.saved_response(committed, entry.version)
        except (
            LeaseUnavailableError,
            LeaseRenewalError,
            ResourceExistsError,
            FileExistsError,
        ):
            raise PredictionEditConflict(
                "save_conflict",
                "The save is busy or its artifact path is already occupied.",
            ) from None
