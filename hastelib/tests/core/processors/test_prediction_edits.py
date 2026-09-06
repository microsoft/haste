# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License.

import json
from concurrent.futures import ThreadPoolExecutor
from contextlib import nullcontext
from typing import Any
from unittest.mock import MagicMock, patch
from urllib.parse import parse_qs, urlsplit
from uuid import uuid4

from hastegeo.core.artifact_storage.unified_artifact_storage import (
    UnifiedArtifactStorage,
)
from hastegeo.core.models.prediction_edits import (
    EditedPredictionVersion,
    PredictionEditSessionRequest,
    SavedPredictionResponse,
    SaveEditedPredictionsRequest,
)
from hastegeo.core.models.prediction_results import ModelArtifactRequest
from hastegeo.core.processors.prediction_edits import (
    PredictionEditsProcessor,
    edit_request_fingerprint,
)
from hastegeo.core.processors.prediction_generations import (
    PredictionEditConflict,
)
from hastegeo.core.processors.prediction_sources import (
    resolve_prediction_source,
)

from .test_prediction_results import (
    LAYER_ID,
    MODEL_ID,
    PROJECT_ID,
    ResultsTestCase,
)


class EditTestCase(ResultsTestCase):
    def setUp(self) -> None:
        super().setUp()
        self.save_predictions()
        self.editor = PredictionEditsProcessor(self.config)

    def edit_request(self, **changes: Any) -> SaveEditedPredictionsRequest:
        body = {
            "projectId": PROJECT_ID,
            "imageLayerId": LAYER_ID,
            "modelId": MODEL_ID,
            "predictionRevision": self.current().predictionRevision,
            "baseVersion": 0,
            "clientRequestId": str(uuid4()),
            "threshold": 0.0,
            "unknownThreshold": 0.0,
            "overrides": [{"id": 0, "class": "NotDamaged"}],
        }
        body.update(changes)
        return SaveEditedPredictionsRequest.model_validate(body)

    def edit(self, **changes: Any) -> SavedPredictionResponse:
        return self.editor.save(
            self.edit_request(**changes), "analyst@example.test"
        )

    def attrs(self, version: int) -> dict:
        entry = next(
            item
            for item in self.current().editedPredictions
            if item.version == version
        )
        return json.loads(
            self.storage.read_artifact_bytes(
                self.storage.resolve_artifact_path(entry.predictionAttrsUrl),
                1_000_000,
            )
        )


class TestPairedEditPublication(EditTestCase):
    def test_model_list_artifacts_match_the_advertised_saved_version(
        self,
    ) -> None:
        raw = self.current()
        saved = self.edit()
        row = self.processor.list_models(PROJECT_ID, LAYER_ID)[0]
        self.assertEqual(row["predictionVersion"], saved.version)
        expected = self.current().editedPredictions[0]

        for kind, field in (
            ("gpkg", "gpkgUrl"),
            ("prediction_attrs", "predictionAttrsUrl"),
        ):
            with self.subTest(kind=kind):
                url = urlsplit(row[field])
                self.assertEqual(url.path, "/api/GetModelArtifact")
                query = {
                    key: values[0]
                    for key, values in parse_qs(url.query).items()
                }
                self.assertEqual(query["version"], str(saved.version))
                self.assertEqual(
                    query["predictionRevision"], row["predictionRevision"]
                )
                location, _ = self.processor.resolve_artifact(
                    ModelArtifactRequest.model_validate(query)
                )
                self.assertEqual(location, getattr(expected, field))
                if kind == "prediction_attrs":
                    attrs = json.loads(
                        self.storage.read_artifact_bytes(
                            self.storage.resolve_artifact_path(location),
                            1_000_000,
                        )
                    )
                    self.assertEqual(
                        attrs["predictionVersion"], row["predictionVersion"]
                    )
                    self.assertEqual(
                        attrs["classes"], ["NotDamaged", "NotDamaged"]
                    )

        self.assertEqual(self.current().gpkgUrl, raw.gpkgUrl)
        self.assertEqual(
            self.current().predictionAttrsUrl, raw.predictionAttrsUrl
        )

    def test_real_gis_save_publishes_pair_without_changing_raw(self) -> None:
        raw = self.current()
        response = self.edit()
        current = self.current()
        self.assertEqual(response.version, 1)
        self.assertEqual(response.predictionRevision, raw.predictionRevision)
        self.assertEqual(response.editedCount, 1)
        self.assertEqual(response.overridesApplied, 1)
        self.assertEqual(response.buildingCount, 2)
        self.assertIn("version=1", response.gpkgUrl)
        self.assertIn("predictionRevision=", response.predictionAttrsUrl)
        self.assertEqual(current.gpkgUrl, raw.gpkgUrl)
        self.assertEqual(current.predictionAttrsUrl, raw.predictionAttrsUrl)
        attrs = self.attrs(1)
        self.assertTrue(attrs["isEdited"])
        self.assertEqual(attrs["predictionVersion"], 1)
        self.assertEqual(attrs["classes"], ["NotDamaged", "NotDamaged"])
        self.assertEqual(attrs["modelClasses"], ["Damaged", "NotDamaged"])
        self.assertEqual(attrs["overrideClasses"], ["NotDamaged", None])
        self.assertEqual(
            current.editedPredictions[0].createdBy, "analyst@example.test"
        )

    def test_older_current_generation_base_and_complete_pins_are_preserved(
        self,
    ) -> None:
        first = self.edit()
        self.edit(overrides=[{"id": 1, "class": "Unknown"}])
        third = self.edit(
            baseVersion=first.version,
            overrides=[
                {"id": 0, "class": "Damaged"},
                {"id": 1, "class": "Unknown"},
            ],
        )
        self.assertEqual(third.version, 3)
        attrs = self.attrs(3)
        self.assertEqual(attrs["overrideClasses"], ["Damaged", "Unknown"])
        self.assertEqual(third.editedCount, 1)
        self.assertEqual(third.overridesApplied, 2)

    def test_committed_request_replays_after_regeneration(self) -> None:
        request = self.edit_request()
        first = self.editor.save(request, "first@example.test")
        self.save_predictions()
        with patch.object(UnifiedArtifactStorage, "store_artifact") as upload:
            replay = self.editor.save(request, "first@example.test")
        self.assertEqual(replay, first)
        upload.assert_not_called()
        self.assertEqual(len(self.current().editedPredictions), 1)
        self.assertEqual(
            resolve_prediction_source(
                self.current(), default="latest_current"
            ).predictionVersion,
            0,
        )
        source = resolve_prediction_source(self.current(), first.version)
        self.assertEqual(source.predictionRevision, first.predictionRevision)
        session = self.editor.get_session(
            PredictionEditSessionRequest(
                projectId=PROJECT_ID,
                imageLayerId=LAYER_ID,
                modelId=MODEL_ID,
                version=1,
            )
        )
        self.assertFalse(session["editReadiness"]["ready"])
        self.assertEqual(session["editReadiness"]["reason"], "source_changed")
        self.assertTrue(session["predictionsReady"])

    def test_conflicting_request_id_has_no_side_effects(self) -> None:
        request = self.edit_request()
        self.editor.save(request, "analyst")
        changed = self.edit_request(
            clientRequestId=request.clientRequestId, overrides=[]
        )
        with self.assertRaises(PredictionEditConflict) as error:
            self.editor.save(changed, "analyst")
        self.assertEqual(error.exception.code, "request_conflict")
        self.assertEqual(len(self.current().editedPredictions), 1)

    def test_unconfirmed_old_generation_and_wrong_base_generation_are_rejected(
        self,
    ) -> None:
        old = self.edit()
        self.save_predictions()
        for changes in (
            {
                "predictionRevision": old.predictionRevision,
                "baseVersion": old.version,
            },
            {"baseVersion": old.version},
        ):
            with self.assertRaises(PredictionEditConflict) as error:
                self.edit(**changes)
            self.assertEqual(error.exception.code, "source_changed")
        self.assertEqual(self.current().predictionEditVersionCounter, 1)

    def test_partial_upload_is_invisible_and_retry_does_not_overwrite(
        self,
    ) -> None:
        request = self.edit_request()
        raw = self.current().gpkgUrl
        original = UnifiedArtifactStorage.store_artifact
        paths = []

        def fail_attrs(storage: UnifiedArtifactStorage, **kwargs: Any) -> str:
            self.assertIs(kwargs["overwrite"], False)
            if kwargs["artifact_name"].endswith(".json"):
                raise RuntimeError("upload unavailable")
            path = original(storage, **kwargs)
            paths.append(path)
            return path

        with patch.object(
            UnifiedArtifactStorage, "store_artifact", fail_attrs
        ):
            with self.assertRaises(RuntimeError):
                self.editor.save(request, "analyst")
        self.assertEqual(self.current().editedPredictions, [])
        self.assertEqual(self.current().gpkgUrl, raw)
        self.assertEqual(self.current().predictionEditVersionCounter, 1)
        with self.assertRaises(FileNotFoundError):
            resolve_prediction_source(self.current(), 1)
        etag = self.storage.get_artifact_etag(paths[0])
        response = self.editor.save(request, "analyst")
        self.assertEqual(response.version, 2)
        self.assertEqual(self.storage.get_artifact_etag(paths[0]), etag)
        self.assertEqual(
            [item.version for item in self.current().editedPredictions], [2]
        )
        self.assertEqual(self.editor.save(request, "analyst").version, 2)

    def test_concurrent_duplicate_requests_publish_only_one_version(
        self,
    ) -> None:
        request = self.edit_request()
        with ThreadPoolExecutor(max_workers=2) as executor:
            results = list(
                executor.map(
                    lambda _: PredictionEditsProcessor(self.config).save(
                        request, "analyst"
                    ),
                    range(2),
                )
            )
        self.assertEqual([result.version for result in results], [1, 1])
        self.assertEqual(len(self.current().editedPredictions), 1)

    def test_concurrent_distinct_requests_allocate_distinct_versions(
        self,
    ) -> None:
        requests = [self.edit_request(), self.edit_request()]
        with ThreadPoolExecutor(max_workers=2) as executor:
            results = list(
                executor.map(
                    lambda req: PredictionEditsProcessor(self.config).save(
                        req, "analyst"
                    ),
                    requests,
                )
            )
        self.assertEqual(sorted(result.version for result in results), [1, 2])

    def test_lease_loss_after_upload_does_not_advertise_version(self) -> None:
        lease = MagicMock()
        lease.renew.side_effect = [None, None, None, RuntimeError("lost")]
        with patch.object(
            self.editor.repository, "lock", return_value=nullcontext(lease)
        ):
            with self.assertRaises(PredictionEditConflict) as error:
                self.edit()
        self.assertEqual(error.exception.code, "save_conflict")
        self.assertEqual(self.current().editedPredictions, [])
        self.assertEqual(self.current().predictionEditVersionCounter, 1)

    def test_receipt_ownership_is_checked_before_append(self) -> None:
        original = self.editor.repository.commit_edit_locked

        def stolen(
            project: str,
            model_id: str,
            request_id: str,
            receipt: Any,
            entry: Any,
            lease: Any,
        ) -> Any:
            model = self.current()
            model.predictionEditReceipts[
                request_id
            ].attemptId = "another-owner"
            self.editor.repository.save_locked(model, None)
            return original(
                project, model_id, request_id, receipt, entry, lease
            )

        with patch.object(
            self.editor.repository, "commit_edit_locked", side_effect=stolen
        ):
            with self.assertRaises(PredictionEditConflict) as error:
                self.edit()
        self.assertEqual(error.exception.code, "save_conflict")
        self.assertEqual(self.current().editedPredictions, [])

    def test_clear_preserves_history_but_delete_removes_private_versions(
        self,
    ) -> None:
        saved = self.edit()
        stale = self.current()
        self.save_predictions(predictions=[])
        self.save_record("model", MODEL_ID, stale.model_dump(mode="json"))
        current = self.current()
        self.assertEqual(len(current.editedPredictions), 1)
        self.assertEqual(
            resolve_prediction_source(
                current, default="latest_current"
            ).predictionVersion,
            0,
        )
        url, _ = self.processor.resolve_artifact(
            ModelArtifactRequest(
                projectId=PROJECT_ID,
                modelId=MODEL_ID,
                kind="gpkg",
                version=saved.version,
                predictionRevision=saved.predictionRevision,
            )
        )
        self.assertTrue(url)
        self.repository.delete_model_metadata(PROJECT_ID, MODEL_ID)
        self.save_record("model", MODEL_ID, stale.model_dump(mode="json"))
        self.assertEqual(self.current().editedPredictions, [])
        self.assertEqual(self.current().predictionEditReceipts, {})
        with self.assertRaises(FileNotFoundError):
            resolve_prediction_source(self.current(), saved.version)

    def test_fingerprint_is_order_and_numeric_zero_independent(self) -> None:
        request = self.edit_request(
            overrides=[
                {"id": 1, "class": "Damaged"},
                {"id": 0, "class": "Unknown"},
            ]
        )
        reordered = self.edit_request(
            clientRequestId=request.clientRequestId,
            overrides=[
                {"id": 0, "class": "Unknown"},
                {"id": 1, "class": "Damaged"},
            ],
            threshold=-0.0,
        )
        self.assertEqual(
            edit_request_fingerprint(request),
            edit_request_fingerprint(reordered),
        )

    def test_legacy_model_serializers_remain_json_compatible_after_edits(
        self,
    ) -> None:
        self.edit()
        encoded = json.dumps(self.current().model_dump())
        self.assertIn("clientRequestId", encoded)

    def test_busy_local_save_has_bounded_conflict_without_reservation(
        self,
    ) -> None:
        with self.repository.lock(PROJECT_ID, MODEL_ID):
            with self.assertRaises(PredictionEditConflict) as error:
                self.edit()
        self.assertEqual(error.exception.code, "save_conflict")
        self.assertEqual(self.current().predictionEditVersionCounter, 0)

    def test_missing_historical_attrs_does_not_disable_its_download(
        self,
    ) -> None:
        saved = self.edit()
        with self.repository.lock(PROJECT_ID, MODEL_ID) as lease:
            model = self.current()
            model.editedPredictions[0].predictionAttrsUrl = None
            self.repository.save_locked(model, lease)
        session = self.editor.get_session(
            PredictionEditSessionRequest(
                projectId=PROJECT_ID,
                imageLayerId=LAYER_ID,
                modelId=MODEL_ID,
                version=1,
            )
        )
        self.assertFalse(session["predictionsReady"])
        self.assertFalse(session["editReadiness"]["ready"])
        url, _ = self.processor.resolve_artifact(
            ModelArtifactRequest(
                projectId=PROJECT_ID,
                modelId=MODEL_ID,
                kind="gpkg",
                version=saved.version,
            )
        )
        self.assertTrue(url)
        with self.assertRaises(FileNotFoundError):
            self.processor.resolve_artifact(
                ModelArtifactRequest(
                    projectId=PROJECT_ID,
                    modelId=MODEL_ID,
                    kind="prediction_attrs",
                    version=1,
                )
            )

    def test_legacy_136_metadata_is_readable_but_unbound_versions_are_not_default(
        self,
    ) -> None:
        current = self.current()
        current.editedPredictions = [
            EditedPredictionVersion(
                version=7,
                gpkgUrl=current.gpkgUrl,
                createdAt="2026-01-01",
                createdBy="legacy",
                editedCount=1,
                sourceGpkgUrl=current.gpkgUrl,
            )
        ]
        with self.repository.lock(PROJECT_ID, MODEL_ID) as lease:
            self.repository.save_locked(current, lease)
        self.assertEqual(
            resolve_prediction_source(
                self.current(), default="latest_current"
            ).predictionVersion,
            0,
        )
        self.assertTrue(resolve_prediction_source(self.current(), 7).gpkgUrl)
        saved = self.edit()
        self.assertEqual(saved.version, 8)

    def test_receipts_and_failed_reservation_counter_survive_raw_regeneration(
        self,
    ) -> None:
        request = self.edit_request()
        with patch.object(
            UnifiedArtifactStorage,
            "store_artifact",
            side_effect=RuntimeError("upload failed"),
        ):
            with self.assertRaises(RuntimeError):
                self.editor.save(request, "analyst")
        self.save_predictions()
        self.assertEqual(self.current().predictionEditVersionCounter, 1)
        self.assertIn(
            str(request.clientRequestId), self.current().predictionEditReceipts
        )
        self.assertEqual(self.edit().version, 2)

    def test_source_change_before_append_is_fenced(self) -> None:
        original = self.editor.repository.commit_edit_locked

        def change_source(
            project: str,
            model_id: str,
            request_id: str,
            receipt: Any,
            entry: Any,
            lease: Any,
        ) -> Any:
            model = self.current()
            self.repository.initialize(model, str(uuid4()), clear=True)
            self.editor.repository.save_locked(model, None)
            return original(
                project, model_id, request_id, receipt, entry, lease
            )

        with patch.object(
            self.editor.repository,
            "commit_edit_locked",
            side_effect=change_source,
        ):
            with self.assertRaises(PredictionEditConflict) as error:
                self.edit()
        self.assertEqual(error.exception.code, "source_changed")
        self.assertEqual(self.current().editedPredictions, [])
        self.assertEqual(self.current().predictedBuildingCount, 0)

    def test_existing_version_path_is_a_conflict_not_an_overwrite(
        self,
    ) -> None:
        revision = self.current().predictionRevision
        path = self.storage.store_artifact(
            f"edited_predictions_{MODEL_ID}_v1.gpkg",
            data=b"existing artifact",
            namespace=["prediction_edits", MODEL_ID, revision, "v1"],
            overwrite=False,
        )
        with self.assertRaises(PredictionEditConflict) as error:
            self.edit()
        self.assertEqual(error.exception.code, "save_conflict")
        self.assertEqual(
            self.storage.read_artifact_bytes(path, 100), b"existing artifact"
        )
        self.assertEqual(self.current().editedPredictions, [])

    def test_invalid_uploaded_attrs_never_advertise_a_version(self) -> None:
        raw = self.current().gpkgUrl
        with patch.object(
            UnifiedArtifactStorage, "read_artifact_bytes", return_value=b"{}"
        ):
            with self.assertRaises(ValueError):
                self.edit()
        self.assertEqual(self.current().gpkgUrl, raw)
        self.assertEqual(self.current().editedPredictions, [])

    def test_uploaded_assignments_must_match_the_complete_request_snapshot(
        self,
    ) -> None:
        original = UnifiedArtifactStorage.read_artifact_bytes

        def altered(
            storage: UnifiedArtifactStorage, path: str, limit: int
        ) -> bytes:
            payload = json.loads(original(storage, path, limit))
            payload["classes"][0] = "Unknown"
            payload["overrideClasses"][0] = "Unknown"
            return json.dumps(payload).encode()

        with patch.object(
            UnifiedArtifactStorage, "read_artifact_bytes", altered
        ):
            with self.assertRaises(RuntimeError):
                self.edit()
        self.assertEqual(self.current().editedPredictions, [])
