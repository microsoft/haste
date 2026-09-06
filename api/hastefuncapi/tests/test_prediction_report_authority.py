# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License.

import json
import os
from unittest.mock import patch

import azure.functions as func

os.environ.setdefault("DEVELOPMENT_MODE", "true")
os.environ.setdefault("METADATA_STORAGE_TYPE", "local")
os.environ.setdefault("ARTIFACT_STORAGE_TYPE", "local")
os.environ.setdefault("DATA_PATH", "/tmp/haste-report-authority-tests")
os.environ.setdefault("TEMP_DATA_PATH", "/tmp/haste-report-authority-tests")

from api.hastefuncapi import function_app  # noqa: E402
from hastelib.tests.core.processors.test_assessment_authority import (  # noqa: E402
    ReportAuthorityTestCase,
)
from hastelib.tests.core.processors.test_prediction_results import (  # noqa: E402
    LAYER_ID,
    MODEL_ID,
    OTHER_LAYER,
    PROJECT_ID,
)


class TestPredictionReportAuthority(ReportAuthorityTestCase):
    def setUp(self) -> None:
        super().setUp()
        self.enterContext(patch.object(function_app, "config", self.config))
        self.enterContext(
            patch.object(
                function_app, "download_blob_to_tempfile", self.download
            )
        )

    def report_request(self, layer_id: str = LAYER_ID) -> func.HttpRequest:
        return func.HttpRequest(
            method="GET",
            url="http://localhost/api/report",
            params={
                "projectId": PROJECT_ID,
                "imageLayerId": layer_id,
                "modelId": MODEL_ID,
            },
            headers={},
            body=b"",
        )

    async def test_validation_report_rejects_clear_and_stale_mirror_before_download(
        self,
    ) -> None:
        self.clear_then_restore_stale_mirror()
        response = await function_app.GetValidationReport(
            self.report_request()
        )
        self.assertEqual(response.status_code, 404)
        self.download.assert_not_awaited()

    async def test_assessment_report_rejects_clear_and_stale_mirror_before_download(
        self,
    ) -> None:
        self.clear_then_restore_stale_mirror()
        response = await function_app.GetAssessmentReport(
            self.report_request()
        )
        self.assertEqual(response.status_code, 404)
        self.download.assert_not_awaited()

    async def test_legacy_validation_report_does_not_need_viewer_artifacts(
        self,
    ) -> None:
        gpkg_url = self.legacy_raw_source()
        response = await function_app.GetValidationReport(
            self.report_request()
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(json.loads(response.get_body())["matched"], 2)
        self.assertEqual(self.downloaded_urls[-1], gpkg_url)
        self.assertEqual(self.download.await_count, 2)

    async def test_legacy_assessment_report_does_not_need_viewer_artifacts(
        self,
    ) -> None:
        gpkg_url = self.legacy_raw_source()
        response = await function_app.GetAssessmentReport(
            self.report_request()
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(self.downloaded_urls[-1], gpkg_url)
        self.assertEqual(self.download.await_count, 2)

    async def test_report_layer_mismatch_is_rejected_before_download(
        self,
    ) -> None:
        self.save_predictions()
        for handler in (
            function_app.GetValidationReport,
            function_app.GetAssessmentReport,
        ):
            response = await handler(self.report_request(OTHER_LAYER))
            self.assertEqual(response.status_code, 400)
        self.download.assert_not_awaited()
