# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License.

"""Imagery persists before handing footprint-owned state to the consumer."""

from copy import deepcopy
from typing import Any
from unittest.mock import MagicMock, patch

from hastegeo.core.models.footprint_tiles import FootprintTilesRequest
from hastegeo.core.models.projects import ImageLayer
from hastegeo.core.processors import footprint_tiles, imagery, job_state
from hastegeo.core.processors.job_state import JobStateRepository, Workload

from .test_footprint_tiles import (
    SECRET_URL,
    STATUSES,
    FootprintTestCase,
    _job,
    _layer,
)


class _MemoryMetadata:
    def __init__(self, test_case: FootprintTestCase) -> None:
        self.test_case = test_case

    def load(self, key: str, data_format: str = "json") -> dict:
        return deepcopy(self.test_case.record)

    def mutate(self, key: str, mutation: Any) -> dict | None:
        updated = mutation(deepcopy(self.test_case.record))
        if updated is not None:
            self.test_case.record = deepcopy(updated)
            return deepcopy(self.test_case.record)
        return deepcopy(self.test_case.record)


class TestImageryHandoff(FootprintTestCase):
    def _repository(self) -> JobStateRepository:
        return JobStateRepository(
            self.config,
            processor_factory=lambda **kwargs: _MemoryMetadata(self),
        )

    def _persist_and_enqueue(self, layer: ImageLayer) -> ImageLayer:
        repository = self._repository()
        with patch.object(
            job_state, "JobStateRepository", return_value=repository
        ):
            return job_state.persist_and_enqueue(
                layer, Workload.IMAGERY, self.config, MagicMock()
            )

    def test_standard_and_building_workflows_persist_before_enqueue(
        self,
    ) -> None:
        for workflow in ("standard", "building"):
            with self.subTest(workflow=workflow):
                self.record = _layer(
                    workflowType=workflow,
                    status=STATUSES.COMPLETED.value,
                    labelsUrl="https://acct/new-labels",
                ).model_dump()
                output = _layer(
                    workflowType=workflow,
                    status=STATUSES.COMPLETED.value,
                    buildingFootprintsUrl=None,
                    labelsUrl="stale-before-commit",
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
                imagery.prepare_footprint_tiles(output, config=self.config)
        self.assertEqual(self.queue.put_message.call_count, 2)

    def test_fast_consumer_transitions_survive_the_imagery_handoff(
        self,
    ) -> None:
        self.record["status"] = STATUSES.COMPLETED.value
        output = _layer(status=STATUSES.COMPLETED.value)

        def consume(message: str, **kwargs: Any) -> None:
            request = FootprintTilesRequest.model_validate_json(message)
            if request.taskId:
                self.complete_task()
            footprint_tiles.process_tiles_request(request, config=self.config)

        self.queue.put_message.side_effect = consume
        imagery.prepare_footprint_tiles(output, config=self.config)
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
        stale = _layer(status=STATUSES.COMPLETED.value)
        self._repository().begin(Workload.IMAGERY, stale)
        self._persist_and_enqueue(stale)
        imagery.prepare_footprint_tiles(output, config=self.config)
        self.assertEqual(
            self.record["footprintPmtilesUrl"], "https://acct/tiles.pmtiles"
        )
        self.assertEqual(self.queue.put_message.call_count, 2)

    def test_duplicate_imagery_does_not_reset_an_active_footprint_job(
        self,
    ) -> None:
        for status in (STATUSES.PENDING.value, STATUSES.IN_PROGRESS.value):
            self.record = _layer(
                status=STATUSES.COMPLETED.value,
                footprintTilesStatus=status,
                footprintTilesJob=_job(),
                footprintTilesRequestId="active-request",
            ).model_dump()
            stale = _layer(status=STATUSES.COMPLETED.value)
            self._repository().begin(Workload.IMAGERY, stale)
            imagery.prepare_footprint_tiles(stale, config=self.config)
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
        self.record["status"] = STATUSES.COMPLETED.value
        self.queue.put_message.side_effect = RuntimeError(SECRET_URL)
        with patch.object(imagery.Logger, "get_logger") as get_logger:
            imagery.prepare_footprint_tiles(output, config=self.config)
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
        for layer in (
            _layer(status=STATUSES.FAILED.value),
            (
                _layer(
                    status=STATUSES.COMPLETED.value,
                    buildingFootprintsUrl=None,
                )
            ),
        ):
            self.record = layer.model_dump()
            imagery.prepare_footprint_tiles(layer, config=self.config)
        self.queue.put_message.assert_not_called()

    def test_failed_imagery_persistence_does_not_publish(self) -> None:
        self.record["status"] = STATUSES.COMPLETED.value
        self.storage.save.side_effect = RuntimeError("storage unavailable")
        imagery.prepare_footprint_tiles(
            _layer(status=STATUSES.COMPLETED.value), config=self.config
        )
        self.queue.put_message.assert_not_called()
