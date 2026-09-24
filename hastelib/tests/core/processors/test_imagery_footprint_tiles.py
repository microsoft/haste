# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License.

"""Imagery persists before handing footprint-owned state to the consumer."""

from typing import Any
from unittest.mock import patch

from hastegeo.core.models.footprint_tiles import FootprintTilesRequest
from hastegeo.core.processors import footprint_tiles, imagery

from .test_footprint_tiles import (
    SECRET_URL,
    STATUSES,
    FootprintTestCase,
    _job,
    _layer,
)


class TestImageryHandoff(FootprintTestCase):
    def test_standard_and_building_workflows_persist_before_enqueue(
        self,
    ) -> None:
        for workflow in ("standard", "building"):
            with self.subTest(workflow=workflow):
                self.record = _layer(buildingFootprintsUrl=None).model_dump()
                output = _layer(
                    workflowType=workflow,
                    status=STATUSES.COMPLETED.value,
                    labelsUrl="https://acct/new-labels",
                )

                def consume(message: str, **kwargs: Any) -> None:
                    self.assertEqual(
                        self.record["buildingFootprintsUrl"], SECRET_URL
                    )
                    self.assertEqual(
                        self.record["labelsUrl"], "https://acct/new-labels"
                    )
                    self.assertEqual(
                        self.record["footprintTilesStatus"],
                        STATUSES.PENDING.value,
                    )
                    self.assertNotIn("do-not-log", message)

                self.queue.put_message.side_effect = consume
                imagery.save_imagery_layer(
                    output, config=self.config, prepare_footprints=True
                )
        self.assertEqual(self.queue.put_message.call_count, 2)

    def test_fast_consumer_transitions_survive_the_imagery_handoff(
        self,
    ) -> None:
        self.record["buildingFootprintsUrl"] = None
        output = _layer(status=STATUSES.COMPLETED.value)

        def consume(message: str, **kwargs: Any) -> None:
            request = FootprintTilesRequest.model_validate_json(message)
            if request.taskId:
                self.complete_task()
            footprint_tiles.process_tiles_request(request, config=self.config)

        self.queue.put_message.side_effect = consume
        imagery.save_imagery_layer(
            output, config=self.config, prepare_footprints=True
        )
        # Both the new-request and poll consumers ran before send returned.
        self.assertEqual(
            self.record["footprintTilesStatus"], STATUSES.COMPLETED.value
        )
        self.assertEqual(
            self.record["footprintPmtilesUrl"], "https://acct/tiles.pmtiles"
        )
        self.runner.add_task.assert_called_once()

        # Late imagery/error saves and duplicate completed deliveries must
        # not restore the stale footprint fields from output.
        imagery.save_imagery_layer(output, config=self.config)
        imagery.save_imagery_layer(
            output, config=self.config, prepare_footprints=True
        )
        self.assertEqual(
            self.record["footprintPmtilesUrl"], "https://acct/tiles.pmtiles"
        )
        self.assertEqual(self.queue.put_message.call_count, 2)

    def test_duplicate_imagery_does_not_reset_an_active_footprint_job(
        self,
    ) -> None:
        for status in (STATUSES.PENDING.value, STATUSES.IN_PROGRESS.value):
            self.record = _layer(
                footprintTilesStatus=status,
                footprintTilesJob=_job(),
                footprintTilesRequestId="active-request",
            ).model_dump()
            imagery.save_imagery_layer(
                _layer(status=STATUSES.COMPLETED.value),
                config=self.config,
                prepare_footprints=True,
            )
            self.assertEqual(self.record["footprintTilesStatus"], status)
            self.assertEqual(
                self.record["footprintTilesRequestId"], "active-request"
            )
            self.assertEqual(
                self.record["footprintTilesJob"]["taskId"], "ftl-task"
            )
        self.queue.put_message.assert_not_called()

    def test_queue_failure_is_visible_without_failing_usable_imagery(
        self,
    ) -> None:
        output = _layer(status=STATUSES.COMPLETED.value)
        self.queue.put_message.side_effect = RuntimeError(SECRET_URL)
        with patch.object(imagery.Logger, "get_logger") as get_logger:
            imagery.save_imagery_layer(
                output, config=self.config, prepare_footprints=True
            )
        self.assertEqual(self.record["status"], STATUSES.COMPLETED.value)
        self.assertEqual(
            self.record["footprintTilesStatus"], STATUSES.FAILED.value
        )
        get_logger.return_value.warning.assert_called_once()
        self.assertNotIn("do-not-log", str(get_logger.return_value.mock_calls))
        self.assertNotIn(
            "do-not-log", self.record["footprintTilesStatusMessage"]
        )

    def test_only_the_final_successful_imagery_save_may_enqueue(self) -> None:
        for layer, final_save in (
            (_layer(status=STATUSES.COMPLETED.value), False),
            (_layer(status=STATUSES.FAILED.value), True),
            (
                _layer(
                    status=STATUSES.COMPLETED.value,
                    buildingFootprintsUrl=None,
                ),
                True,
            ),
        ):
            imagery.save_imagery_layer(
                layer, config=self.config, prepare_footprints=final_save
            )
        self.queue.put_message.assert_not_called()

    def test_failed_imagery_persistence_does_not_publish(self) -> None:
        self.storage.save.side_effect = RuntimeError("storage unavailable")
        with self.assertRaises(RuntimeError):
            imagery.save_imagery_layer(
                _layer(status=STATUSES.COMPLETED.value),
                config=self.config,
                prepare_footprints=True,
            )
        self.queue.put_message.assert_not_called()
