# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License.

"""Native paired versions on Model; no shadow-store or reservation fixtures."""

import json
import unittest
from concurrent.futures import ThreadPoolExecutor
from contextlib import nullcontext
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any
from unittest.mock import MagicMock, patch
from urllib.parse import parse_qs, urlsplit
from uuid import uuid4

from hastegeo.core.artifact_storage.unified_artifact_storage import (
    UnifiedArtifactStorage,
)
from hastegeo.core.config import Config
from hastegeo.core.models.prediction_edits import (
    EditedPredictionVersion,
    PredictionSelectionRequest,
    SavedPredictionResponse,
    SaveEditedPredictionsRequest,
)
from hastegeo.core.models.prediction_results import (
    BuildingPredictionsRequest,
    ModelArtifactRequest,
)
from hastegeo.core.models.projects import ImageLayer, Model, Project
from hastegeo.core.processors import prediction_edits
from hastegeo.core.processors.metadata import MetadataProcessor
from hastegeo.core.processors.prediction_edits import (
    PredictionEditConflict,
    PredictionEditsProcessor,
    edit_request_fingerprint,
)
from hastegeo.core.processors.prediction_results import (
    PredictionResultsProcessor,
)
from hastegeo.core.processors.prediction_sources import (
    resolve_prediction_source,
)
from hastegeo.core.processors.visualizer import VisualizerProcessor
from hastegeo.core.publishing.lease import LeaseRenewalError

from ..prediction_fixtures import write_gpkg
from .test_prediction_results import LAYER_ID, MODEL_ID, PROJECT_ID


class EditTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self.directory = self.enterContext(TemporaryDirectory())
        self.config = Config()
        self.config.storage_type = self.config.artifact_storage_type = "local"
        self.config.storage_config = {
            "directory": str(Path(self.directory, "meta"))
        }
        self.config.artifact_storage_config = {
            "directory": str(Path(self.directory, "artifacts"))
        }
        self.config.TEMP_DIR = self.directory
        self.storage = UnifiedArtifactStorage(
            "local", **self.config.artifact_storage_config
        )
        footprints = write_gpkg(
            Path(self.directory, "footprints.gpkg"),
            [{"id": "building-0"}, {"id": "building-1"}],
            fields={"id": "str"},
        )
        self.storage.store_artifact("cached.gpkg", src_path=footprints)
        self.model = Model(
            projectId=PROJECT_ID,
            imageLayerId=LAYER_ID,
            modelId=MODEL_ID,
            name="Test",
            modelType="embedding",
            status="Processed",
        )
        self.layer = ImageLayer(
            projectId=PROJECT_ID,
            imageLayerId=LAYER_ID,
            buildingFootprintsUrl=self.storage.get_download_url(
                identifier="cached.gpkg"
            ),
            footprintPmtilesUrl="https://storage/tiles.pmtiles",
        )
        self.save_record("model", MODEL_ID, self.model.model_dump())
        self.save_record("imagelayer", LAYER_ID, self.layer.model_dump())
        self.save_record(
            "project", PROJECT_ID, Project(projectId=PROJECT_ID).model_dump()
        )
        self.processor = PredictionResultsProcessor(self.config)
        self.editor = PredictionEditsProcessor(self.config)
        self.save_predictions()

    def save_record(
        self, kind: str, key: str, fields: dict, data_format: str = "json"
    ) -> None:
        MetadataProcessor(kind, PROJECT_ID, self.config).save(
            key, fields, data_format
        )

    def current(self) -> Model:
        return self.processor.model(PROJECT_ID, MODEL_ID)

    def save_predictions(self, **changes: Any) -> dict:
        return self.processor.save_building_predictions(
            BuildingPredictionsRequest.model_validate(
                {
                    "projectId": PROJECT_ID,
                    "imageLayerId": LAYER_ID,
                    "modelId": MODEL_ID,
                    "predictions": [
                        {"id": 0, "damaged": 1},
                        {"id": 1, "damaged": 0},
                    ],
                    **changes,
                }
            )
        )

    def edit_request(self, **changes: Any) -> SaveEditedPredictionsRequest:
        return SaveEditedPredictionsRequest.model_validate(
            {
                "projectId": PROJECT_ID,
                "imageLayerId": LAYER_ID,
                "modelId": MODEL_ID,
                "predictionRevision": self.current().predictionRevision,
                "baseVersion": 0,
                "clientRequestId": str(uuid4()),
                "threshold": 0.0,
                "unknownThreshold": 0.0,
                "overrides": [{"id": 0, "class": "NotDamaged"}],
                **changes,
            }
        )

    def edit(self, **changes: Any) -> SavedPredictionResponse:
        return self.editor.save(
            self.edit_request(**changes), "analyst@example.test"
        )

    def attrs(self, version: int) -> dict:
        source = resolve_prediction_source(self.current(), version)
        return json.loads(
            self.local_path(source.predictionAttrsUrl).read_text()
        )

    def local_path(self, location: str) -> Path:
        return Path(
            self.storage.get_file_path(
                self.storage.resolve_artifact_path(location)
            )
        )


class TestPairedEditPublication(EditTestCase):
    def test_pair_matches_selected_version_without_overwriting_raw(
        self,
    ) -> None:
        raw = self.current()
        saved = self.edit()
        self.assertEqual(saved.version, 1)
        self.assertEqual(saved.editedCount, 1)
        self.assertEqual(self.current().gpkgUrl, raw.gpkgUrl)
        self.assertEqual(
            self.current().predictionAttrsUrl, raw.predictionAttrsUrl
        )
        attrs = self.attrs(1)
        self.assertEqual(attrs["classes"], ["NotDamaged", "NotDamaged"])
        self.assertEqual(attrs["modelClasses"], ["Damaged", "NotDamaged"])
        self.assertEqual(attrs["overrideClasses"], ["NotDamaged", None])
        row = self.processor.list_models(PROJECT_ID, LAYER_ID)[0]
        query = {
            k: v[0]
            for k, v in parse_qs(
                urlsplit(row["predictionAttrsUrl"]).query
            ).items()
        }
        path, _ = self.processor.resolve_artifact(
            ModelArtifactRequest.model_validate(query)
        )
        self.assertEqual(
            json.loads(self.local_path(path).read_text())["predictionVersion"],
            row["predictionVersion"],
        )

    def test_complete_pins_and_older_current_base_are_preserved(self) -> None:
        self.edit()
        self.edit(overrides=[{"id": 1, "class": "Unknown"}])
        saved = self.edit(
            baseVersion=1,
            overrides=[
                {"id": 0, "class": "Damaged"},
                {"id": 1, "class": "Unknown"},
            ],
        )
        self.assertEqual(saved.version, 3)
        self.assertEqual(saved.editedCount, 1)
        self.assertEqual(saved.overridesApplied, 2)
        self.assertEqual(
            self.attrs(3)["overrideClasses"], ["Damaged", "Unknown"]
        )

    def test_confirmed_replay_survives_new_raw_predictions(self) -> None:
        request = self.edit_request()
        first = self.editor.save(request, "analyst")
        self.save_predictions()
        with patch.object(UnifiedArtifactStorage, "store_artifact") as upload:
            self.assertEqual(self.editor.save(request, "analyst"), first)
        upload.assert_not_called()
        self.assertEqual(
            resolve_prediction_source(
                self.current(), default="latest_current"
            ).predictionVersion,
            0,
        )
        view = VisualizerProcessor(self.config).load(
            PredictionSelectionRequest(
                projectId=PROJECT_ID,
                imageLayerId=LAYER_ID,
                modelId=MODEL_ID,
                version=1,
            )
        )
        self.assertFalse(view.editReadiness["ready"])
        self.assertTrue(view.predictionsReady)

    def test_conflicting_request_and_stale_source_do_not_append(self) -> None:
        request = self.edit_request()
        self.editor.save(request, "analyst")
        with self.assertRaises(PredictionEditConflict) as error:
            self.edit(clientRequestId=request.clientRequestId, overrides=[])
        self.assertEqual(error.exception.code, "request_conflict")
        self.save_predictions()
        with self.assertRaises(PredictionEditConflict) as error:
            self.edit(
                predictionRevision=request.predictionRevision, baseVersion=1
            )
        self.assertEqual(error.exception.code, "source_changed")
        self.assertEqual(len(self.current().editedPredictions), 1)

    def test_failed_upload_is_invisible_and_retry_uses_new_files(self) -> None:
        request = self.edit_request()
        original = UnifiedArtifactStorage.store_artifact
        orphans = []

        def store(
            storage: UnifiedArtifactStorage, *args: Any, **kwargs: Any
        ) -> str:
            self.assertFalse(kwargs["overwrite"])
            if args[0].endswith(".json"):
                raise RuntimeError("Upload failed")
            path = original(storage, *args, **kwargs)
            orphans.append(path)
            return path

        with patch.object(UnifiedArtifactStorage, "store_artifact", store):
            with self.assertRaises(RuntimeError):
                self.editor.save(request, "analyst")
        self.assertEqual(self.current().editedPredictions, [])
        before = Path(orphans[0]).read_bytes()
        saved = self.editor.save(request, "analyst")
        self.assertEqual(saved.version, 1)
        self.assertNotEqual(
            self.current().editedPredictions[0].gpkgUrl, orphans[0]
        )
        self.assertEqual(Path(orphans[0]).read_bytes(), before)
        self.assertEqual(self.editor.save(request, "analyst"), saved)

    def test_concurrent_duplicate_and_distinct_saves(self) -> None:
        request = self.edit_request()
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(
                pool.map(
                    lambda req: PredictionEditsProcessor(self.config).save(
                        req, "analyst"
                    ),
                    [request, request],
                )
            )
        self.assertEqual([r.version for r in results], [1, 1])
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(
                pool.map(
                    lambda req: PredictionEditsProcessor(self.config).save(
                        req, "analyst"
                    ),
                    [self.edit_request(), self.edit_request()],
                )
            )
        self.assertEqual(sorted(r.version for r in results), [2, 3])

    def test_lease_loss_never_advertises_the_new_version(self) -> None:
        lease = MagicMock()
        lease.renew.side_effect = LeaseRenewalError("Lease lost")
        with patch.object(
            prediction_edits,
            "prediction_edit_lock",
            return_value=nullcontext(lease),
        ):
            with self.assertRaises(PredictionEditConflict):
                self.edit()
        self.assertEqual(self.current().editedPredictions, [])

    def test_clear_preserves_history_and_missing_attrs_still_download(
        self,
    ) -> None:
        saved = self.edit()
        self.save_predictions(predictions=[])
        current = self.current()
        current.editedPredictions[0].predictionAttrsUrl = None
        self.save_record(
            "model",
            MODEL_ID,
            {
                "editedPredictions": [
                    v.model_dump(mode="json")
                    for v in current.editedPredictions
                ],
            },
        )
        path, _ = self.processor.resolve_artifact(
            ModelArtifactRequest(
                projectId=PROJECT_ID,
                modelId=MODEL_ID,
                kind="gpkg",
                version=saved.version,
            )
        )
        self.assertTrue(self.local_path(path).is_file())
        with self.assertRaises(FileNotFoundError):
            self.processor.resolve_artifact(
                ModelArtifactRequest(
                    projectId=PROJECT_ID,
                    modelId=MODEL_ID,
                    kind="prediction_attrs",
                    version=1,
                )
            )

    def test_fingerprint_normalizes_override_order_and_numeric_zero(
        self,
    ) -> None:
        first = self.edit_request(
            overrides=[
                {"id": 0, "class": "Damaged"},
                {"id": 1, "class": "Unknown"},
            ]
        )
        second = first.model_copy(
            update={
                "overrides": list(reversed(first.overrides)),
                "threshold": -0.0,
            }
        )
        self.assertEqual(
            edit_request_fingerprint(first), edit_request_fingerprint(second)
        )

    def test_legacy_unbound_history_is_readable_but_not_selected_by_default(
        self,
    ) -> None:
        raw = self.current()
        self.save_record(
            "model",
            MODEL_ID,
            {
                "editedPredictions": [
                    EditedPredictionVersion(
                        version=3, gpkgUrl=raw.gpkgUrl
                    ).model_dump(),
                ]
            },
        )
        self.assertEqual(
            resolve_prediction_source(
                self.current(), default="latest_current"
            ).predictionVersion,
            0,
        )
        self.assertEqual(
            resolve_prediction_source(self.current(), 3).gpkgUrl, raw.gpkgUrl
        )
