# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License.

import shutil
import unittest
from pathlib import Path
from unittest.mock import AsyncMock

from hastegeo.core.models.prediction_results import ResultsRequest
from hastegeo.core.processors.assessment import AssessmentReportProcessor

from .test_prediction_results import (
    LAYER_ID,
    MODEL_ID,
    OTHER_LAYER,
    PROJECT_ID,
    ResultsTestCase,
)


class ReportAuthorityTestCase(
    ResultsTestCase, unittest.IsolatedAsyncioTestCase
):
    """Native GPKG fixtures and an isolated artifact-copy downloader."""

    def setUp(self) -> None:
        super().setUp()
        self.save_record(
            "validation",
            LAYER_ID,
            {
                "projectId": PROJECT_ID,
                "imageLayerId": LAYER_ID,
                "labels": {
                    "building-0": {"label": "Damaged"},
                    "building-1": {"label": "NotDamaged"},
                },
            },
        )
        self.downloaded_urls: list[str] = []
        self.download = AsyncMock(side_effect=self.copy_artifact)

    async def copy_artifact(
        self, url: str, suffix: str = "", max_bytes: int | None = None
    ) -> str:
        self.downloaded_urls.append(url)
        storage = self.processor.storage()
        source = storage.get_file_path(storage.resolve_artifact_path(url))
        destination = Path(
            self.directory, f"report-{len(self.downloaded_urls)}{suffix}"
        )
        shutil.copyfile(source, destination)
        return str(destination)

    def clear_then_restore_stale_mirror(self) -> str:
        self.save_predictions()
        stale = self.current()
        self.save_predictions(predictions=[])
        self.save_record("model", MODEL_ID, stale.model_dump())
        self.assertEqual(self.current().predictedBuildingCount, 0)
        self.assertIsNone(self.current().gpkgUrl)
        self.assertTrue(self.storage.artifact_exists(stale.gpkgUrl))
        return stale.gpkgUrl

    def legacy_raw_source(self) -> str:
        self.save_predictions()
        gpkg_url = self.current().gpkgUrl
        self.repository.metadata(PROJECT_ID, generations=True).delete(MODEL_ID)
        self.save_record(
            "model",
            MODEL_ID,
            self.model.model_copy(update={"gpkgUrl": gpkg_url}).model_dump(),
        )
        self.save_record("imagelayer", LAYER_ID, {"footprintPmtilesUrl": None})
        self.assertIsNone(self.current().predictionAttrsUrl)
        self.assertIsNone(self.current().predictionRevision)
        return gpkg_url


class TestAssessmentAuthority(ReportAuthorityTestCase):
    async def test_shared_processor_rejects_cleared_stale_mirror_before_download(
        self,
    ) -> None:
        self.clear_then_restore_stale_mirror()
        with self.assertRaises(FileNotFoundError):
            await AssessmentReportProcessor(
                config=self.config, downloader=self.download
            ).generate(PROJECT_ID, LAYER_ID, MODEL_ID)
        self.download.assert_not_awaited()

    async def test_shared_processor_accepts_legacy_raw_without_viewer_artifacts(
        self,
    ) -> None:
        gpkg_url = self.legacy_raw_source()
        report = await AssessmentReportProcessor(
            config=self.config, downloader=self.download
        ).generate(PROJECT_ID, LAYER_ID, MODEL_ID)
        self.assertIsInstance(report, dict)
        self.assertEqual(self.download.await_count, 2)
        self.assertEqual(self.downloaded_urls[-1], gpkg_url)

    async def test_shared_processor_rejects_wrong_layer_before_download(
        self,
    ) -> None:
        self.save_predictions()
        with self.assertRaises(ValueError):
            await AssessmentReportProcessor(
                config=self.config, downloader=self.download
            ).generate(PROJECT_ID, OTHER_LAYER, MODEL_ID)
        self.download.assert_not_awaited()

    async def test_raw_context_does_not_require_sidecar_or_tiles(self) -> None:
        self.legacy_raw_source()
        model, layer = self.processor.raw_context(
            ResultsRequest(
                projectId=PROJECT_ID, imageLayerId=LAYER_ID, modelId=MODEL_ID
            )
        )
        self.assertTrue(model.gpkgUrl)
        self.assertIsNone(model.predictionAttrsUrl)
        self.assertIsNone(layer.footprintPmtilesUrl)
