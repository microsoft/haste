# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License.

"""GetEffectiveLimits must report what the worker would actually enforce.

The Update Size Limits workflow polls this route to tell a *stored* app
setting apart from a *live* one, so the values have to come from the running
process rather than from a constant.
"""

import json
import os
import unittest
from unittest.mock import patch

import azure.functions as func
from hastegeo.core.config import Config

from api.hastefuncapi import function_app
from api.hastefuncqueues import function_app as queues_function_app


def _call(app_module=function_app):
    handler = app_module.GetEffectiveLimits.build().get_user_function()
    response = handler(
        func.HttpRequest("GET", "/api/GetEffectiveLimits", body=b"", params={})
    )
    return response, json.loads(response.get_body())


class TestGetEffectiveLimits(unittest.TestCase):
    def test_reports_code_defaults_when_nothing_is_overridden(self):
        env = dict(os.environ)
        env.pop("HASTE_MAX_UPLOAD_BYTES", None)
        env.pop("HASTE_MAX_IMAGERY_DOWNLOAD_BYTES", None)
        with patch.dict(os.environ, env, clear=True):
            response, body = _call()

        self.assertEqual(response.status_code, 200)
        self.assertEqual(body["maxUploadBytes"], 5 * 1024**3)
        self.assertEqual(body["maxImageryDownloadBytes"], 8 * 1024**3)

    def test_tracks_the_process_environment_not_a_cached_snapshot(self):
        with patch.dict(
            os.environ,
            {
                "HASTE_MAX_UPLOAD_BYTES": "10737418240",
                "HASTE_MAX_IMAGERY_DOWNLOAD_BYTES": "32212254720",
            },
        ):
            _, body = _call()

        self.assertEqual(body["maxUploadBytes"], 10737418240)
        self.assertEqual(body["maxImageryDownloadBytes"], 32212254720)

    def test_reports_the_instance_so_callers_can_spot_a_stale_worker(self):
        with patch.dict(os.environ, {"WEBSITE_INSTANCE_ID": "abc123"}):
            _, body = _call()

        self.assertEqual(body["instanceId"], "abc123")

    def test_includes_the_publish_assessment_cap(self):
        _, body = _call()
        self.assertEqual(
            body["publishAssessmentMaxTotalBytes"],
            function_app.config.publishing_config[
                "assessment_max_total_bytes"
            ],
        )

    def test_missing_assessment_cap_reports_bounded_default(self) -> None:
        for app_module in (function_app, queues_function_app):
            with self.subTest(app=app_module.__name__):
                with patch.object(app_module.config, "publishing_config", {}):
                    response, body = _call(app_module)
                self.assertEqual(response.status_code, 200)
                self.assertEqual(
                    body["publishAssessmentMaxTotalBytes"], 512 * 1024**2
                )

    def test_reports_configured_assessment_input_cap(self):
        with patch.dict(
            os.environ,
            {"PUBLISH_ASSESSMENT_MAX_TOTAL_BYTES": "1073741824"},
        ):
            configured = Config()
        for app_module in (function_app, queues_function_app):
            with self.subTest(app=app_module.__name__):
                with patch.object(app_module, "config", configured):
                    _, body = _call(app_module)
                self.assertEqual(
                    body["publishAssessmentMaxTotalBytes"], 1073741824
                )

    def test_queue_diagnostic_reports_its_http_process_environment(self):
        with patch.dict(
            os.environ,
            {
                "HASTE_MAX_IMAGERY_DOWNLOAD_BYTES": "32212254720",
                "WEBSITE_INSTANCE_ID": "queue-app-http-instance",
            },
        ):
            response, body = _call(queues_function_app)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(body["maxImageryDownloadBytes"], 32212254720)
        self.assertEqual(body["instanceId"], "queue-app-http-instance")


if __name__ == "__main__":
    unittest.main()
