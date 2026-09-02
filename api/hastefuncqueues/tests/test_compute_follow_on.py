# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License.

"""Queue-handler tests for compute follow-on propagation and safe logging.

Two guarantees are pinned here:

* an automatic follow-on (training → inference, training/inference →
  artifact packaging) carries the backend the originating job actually ran
  on when ``COMPUTE_FOLLOW_ON_INHERITS_BACKEND`` is enabled, and pins
  nothing when it is disabled;
* no queue trigger logs a raw message body — those payloads carry whole
  ``Model``/``ImageLayer``/``ModelArtifacts`` records, which can include
  signed artifact URLs and the server-owned compute handle.
"""

import io
import json
import os
import pathlib
import re
import tempfile
import unittest
from contextlib import redirect_stderr
from unittest.mock import MagicMock, patch

os.environ.setdefault("DEVELOPMENT_MODE", "true")
os.environ.setdefault("METADATA_STORAGE_TYPE", "local")
os.environ.setdefault("ARTIFACT_STORAGE_TYPE", "local")
os.environ.setdefault(
    "DATA_PATH",
    os.path.join(tempfile.gettempdir(), "haste-compute-queue-tests"),
)
os.environ.setdefault(
    "TEMP_DATA_PATH",
    os.path.join(tempfile.gettempdir(), "haste-compute-queue-tests"),
)

with redirect_stderr(io.StringIO()):
    from api.hastefuncqueues import function_app

from hastegeo.core.models.compute import ComputeBackend  # noqa: E402
from hastegeo.core.models.projects import Model  # noqa: E402

PROJECT_ID = "123e4567-e89b-12d3-a456-426614174000"


class _Message:
    """Minimal stand-in for ``func.QueueMessage``."""

    def __init__(self, payload: dict, message_id: str = "msg-1"):
        self._body = json.dumps(payload).encode("utf-8")
        self.id = message_id

    def get_body(self) -> bytes:
        return self._body


def _model(**overrides):
    values = {
        "modelId": "42",
        "projectId": PROJECT_ID,
        "imageLayerId": "layer-1",
        "name": "damage-model",
        "status": "Queued",
        "autoRunInference": True,
        "maxEpochs": "2",
    }
    values.update(overrides)
    return Model(**values)


class TestFollowOnBackendInheritance(unittest.TestCase):
    def test_inherits_the_originating_backend_when_enabled(self):
        model = _model(computeBackend=ComputeBackend.AZURE_ML)
        with patch.dict(
            os.environ,
            {"COMPUTE_FOLLOW_ON_INHERITS_BACKEND": "true"},
            clear=False,
        ):
            self.assertEqual(
                function_app.follow_on_backend_for_record(
                    model, config=function_app.config
                ),
                ComputeBackend.AZURE_ML,
            )

    def test_pins_nothing_when_inheritance_is_disabled(self):
        model = _model(computeBackend=ComputeBackend.AZURE_ML)
        with patch.dict(
            os.environ,
            {"COMPUTE_FOLLOW_ON_INHERITS_BACKEND": "false"},
            clear=False,
        ):
            self.assertIsNone(
                function_app.follow_on_backend_for_record(
                    model, config=function_app.config
                )
            )

    def test_unset_backend_stays_unset(self):
        self.assertIsNone(
            function_app.follow_on_backend_for_record(
                _model(), config=function_app.config
            )
        )


class TestTrainingTriggerFollowOns(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        types = function_app.config.get_metadata_types()
        self.model_payload = _model().dict()

        def _metadata_factory(*args, **kwargs):
            instance = MagicMock()
            data_type = kwargs.get("data_type")
            if data_type == types.MODEL.value:
                instance.load.return_value = self.model_payload
            elif data_type == types.IMAGELAYER.value:
                instance.load.return_value = {
                    "imageLayerId": "layer-1",
                    "projectId": PROJECT_ID,
                }
            elif data_type == types.PROJECT.value:
                instance.load.return_value = {"projectId": PROJECT_ID}
            elif data_type == types.LABELS.value:
                instance.load_all_from_partition.return_value = [
                    {
                        "labelprojectId": "lp-1",
                        "imageLayerId": "layer-1",
                        "labels": [],
                    }
                ]
            return instance

        self.meta = patch.object(
            function_app, "MetadataProcessor", side_effect=_metadata_factory
        ).start()
        self.train = patch.object(function_app, "TrainPostprocessor").start()
        self.inference = patch.object(
            function_app, "InferencePreprocessor"
        ).start()
        self.inference.side_effect = lambda record: MagicMock(
            send_to_queue=MagicMock(return_value=record)
        )
        self.artifacts = patch.object(
            function_app, "ArtifactProcessor"
        ).start()
        self.artifacts.side_effect = lambda **kwargs: MagicMock(
            send_to_zip_queue=MagicMock(return_value=kwargs["model_artifacts"])
        )
        self.addCleanup(patch.stopall)

    def _train_result(self, **overrides):
        values = {
            "status": "Processed",
            "autoRunInference": True,
            "computeBackend": ComputeBackend.LOCAL,
        }
        values.update(overrides)
        return _model(**values)

    async def test_inference_follow_on_inherits_the_training_backend(self):
        self.train.return_value.process.return_value = self._train_result()
        with patch.dict(
            os.environ,
            {"COMPUTE_FOLLOW_ON_INHERITS_BACKEND": "true"},
            clear=False,
        ):
            await function_app.GetCreateModelRunQueueMessage(
                _Message(self.model_payload)
            )

        queued = self.inference.call_args.args[0]
        self.assertEqual(queued.computeBackend, ComputeBackend.LOCAL)

    async def test_inference_follow_on_is_unpinned_when_disabled(self):
        self.train.return_value.process.return_value = self._train_result()
        with patch.dict(
            os.environ,
            {"COMPUTE_FOLLOW_ON_INHERITS_BACKEND": "false"},
            clear=False,
        ):
            await function_app.GetCreateModelRunQueueMessage(
                _Message(self.model_payload)
            )

        queued = self.inference.call_args.args[0]
        self.assertIsNone(queued.computeBackend)

    async def test_packaging_follow_on_inherits_the_training_backend(self):
        self.train.return_value.process.return_value = self._train_result(
            status="Failed",
            trainingOutputPath="hash/trn-1",
            autoRunInference=False,
        )
        with patch.dict(
            os.environ,
            {"COMPUTE_FOLLOW_ON_INHERITS_BACKEND": "true"},
            clear=False,
        ):
            await function_app.GetCreateModelRunQueueMessage(
                _Message(self.model_payload)
            )

        model_artifacts = self.artifacts.call_args.kwargs["model_artifacts"]
        self.assertEqual(model_artifacts.computeBackend, ComputeBackend.LOCAL)
        # Artifact packaging must not be skipped by the inheritance wiring.
        self.assertEqual(model_artifacts.modelId, "42")


class TestQueueLoggingIsSanitized(unittest.TestCase):
    """Raw payload logging must not come back: a queue message carries a
    whole record, including signed URLs and the compute handle."""

    def test_no_logger_call_interpolates_the_message_body(self):
        source = pathlib.Path(function_app.__file__).read_text(
            encoding="utf-8"
        )
        offenders = [
            f"{number}: {line.strip()}"
            for number, line in enumerate(source.splitlines(), start=1)
            if re.search(r"logger\.\w+\(.*get_body\(\)", line)
        ]
        self.assertEqual(offenders, [], "\n".join(offenders))

    def test_workload_triggers_log_identifiers_only(self):
        source = pathlib.Path(function_app.__file__).read_text(
            encoding="utf-8"
        )
        # The workload triggers must log through the identifier-only core
        # helpers rather than dumping the record.
        self.assertIn("backend_name(", source)
        self.assertIn("selected_backend_of(", source)

    def test_compute_helpers_live_in_core_not_the_function_app(self):
        # AGENTS.md: function_app.py holds HTTP/queue wrappers only; plain
        # data helpers belong in hastegeo.
        source = pathlib.Path(function_app.__file__).read_text(
            encoding="utf-8"
        )
        for helper in (
            "backend_name",
            "selected_backend_of",
            "follow_on_backend_for_record",
        ):
            with self.subTest(helper=helper):
                self.assertNotIn(f"def {helper}(", source)
                self.assertIn(helper, source)


if __name__ == "__main__":
    unittest.main()
