# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License.

"""Unit tests for ``ComputeRouter`` (deterministic weighted-rendezvous
``auto`` resolution + capability/capacity filtering).

See spec/features/aml-compute-backend/test-plan.md UT-009..UT-012.
"""

import unittest

from hastegeo.core.models.compute import (
    BackendConfigurationError,
    CapacitySnapshot,
    CapacityState,
    CapacityUnavailableError,
    ComputeBackend,
    ComputeWorkload,
)
from hastegeo.core.runners.router import (
    ComputeRouter,
    candidates_from_env,
    weights_from_env,
)


def _snapshot(
    backend, workload=ComputeWorkload.TRAINING, state=CapacityState.AVAILABLE
):
    return CapacitySnapshot(backend=backend, workload=workload, state=state)


class TestComputeRouterResolve(unittest.TestCase):
    def setUp(self):
        self.router = ComputeRouter()

    def test_deterministic_for_same_inputs(self):
        """UT-010: auto with all candidates healthy resolves the same way
        for the same executionId every time."""
        candidates = [ComputeBackend.AZURE_BATCH, ComputeBackend.AZURE_ML]
        capacity = {
            ComputeBackend.AZURE_BATCH: _snapshot(ComputeBackend.AZURE_BATCH),
            ComputeBackend.AZURE_ML: _snapshot(ComputeBackend.AZURE_ML),
        }
        results = {
            self.router.resolve(
                execution_id="exec-fixed-1",
                workload=ComputeWorkload.TRAINING,
                candidates=candidates,
                capacity_by_backend=capacity,
            )
            for _ in range(20)
        }
        self.assertEqual(len(results), 1)

    def test_different_execution_ids_can_select_different_backends(self):
        """Sanity check that the hash actually distributes rather than
        always preferring the first candidate."""
        candidates = [ComputeBackend.AZURE_BATCH, ComputeBackend.AZURE_ML]
        capacity = {
            ComputeBackend.AZURE_BATCH: _snapshot(ComputeBackend.AZURE_BATCH),
            ComputeBackend.AZURE_ML: _snapshot(ComputeBackend.AZURE_ML),
        }
        selected_backends = set()
        for i in range(50):
            backend, _ = self.router.resolve(
                execution_id=f"exec-{i}",
                workload=ComputeWorkload.TRAINING,
                candidates=candidates,
                capacity_by_backend=capacity,
            )
            selected_backends.add(backend)
        self.assertEqual(
            selected_backends,
            {ComputeBackend.AZURE_BATCH, ComputeBackend.AZURE_ML},
        )

    def test_unavailable_candidate_is_filtered_then_next_deterministic_candidate_chosen(
        self,
    ):
        """UT-011: one candidate unavailable -> filtered out; the router
        must never choose it, and the remaining choice must still be
        deterministic."""
        candidates = [ComputeBackend.AZURE_BATCH, ComputeBackend.AZURE_ML]
        capacity = {
            ComputeBackend.AZURE_BATCH: _snapshot(
                ComputeBackend.AZURE_BATCH, state=CapacityState.UNAVAILABLE
            ),
            ComputeBackend.AZURE_ML: _snapshot(ComputeBackend.AZURE_ML),
        }
        selected, reason = self.router.resolve(
            execution_id="exec-1",
            workload=ComputeWorkload.TRAINING,
            candidates=candidates,
            capacity_by_backend=capacity,
        )
        self.assertEqual(selected, ComputeBackend.AZURE_ML)
        self.assertTrue(reason.startswith("auto:"))

    def test_all_candidates_unavailable_raises_capacity_unavailable(self):
        candidates = [ComputeBackend.AZURE_BATCH, ComputeBackend.AZURE_ML]
        capacity = {
            ComputeBackend.AZURE_BATCH: _snapshot(
                ComputeBackend.AZURE_BATCH, state=CapacityState.UNAVAILABLE
            ),
            ComputeBackend.AZURE_ML: _snapshot(
                ComputeBackend.AZURE_ML, state=CapacityState.UNAVAILABLE
            ),
        }
        with self.assertRaises(CapacityUnavailableError):
            self.router.resolve(
                execution_id="exec-1",
                workload=ComputeWorkload.TRAINING,
                candidates=candidates,
                capacity_by_backend=capacity,
            )

    def test_missing_snapshot_is_treated_as_ineligible(self):
        candidates = [ComputeBackend.AZURE_BATCH, ComputeBackend.AZURE_ML]
        capacity = {
            ComputeBackend.AZURE_ML: _snapshot(ComputeBackend.AZURE_ML)
        }
        selected, _ = self.router.resolve(
            execution_id="exec-1",
            workload=ComputeWorkload.TRAINING,
            candidates=candidates,
            capacity_by_backend=capacity,
        )
        self.assertEqual(selected, ComputeBackend.AZURE_ML)

    def test_wrong_workload_snapshot_is_treated_as_ineligible(self):
        candidates = [ComputeBackend.AZURE_BATCH, ComputeBackend.AZURE_ML]
        capacity = {
            ComputeBackend.AZURE_BATCH: _snapshot(
                ComputeBackend.AZURE_BATCH, workload=ComputeWorkload.INFERENCE
            ),
            ComputeBackend.AZURE_ML: _snapshot(ComputeBackend.AZURE_ML),
        }
        selected, _ = self.router.resolve(
            execution_id="exec-1",
            workload=ComputeWorkload.TRAINING,
            candidates=candidates,
            capacity_by_backend=capacity,
        )
        self.assertEqual(selected, ComputeBackend.AZURE_ML)

    def test_unknown_state_remains_eligible(self):
        # "unknown" is advisory/best-effort, not a rejection.
        candidates = [ComputeBackend.AZURE_ML]
        capacity = {
            ComputeBackend.AZURE_ML: _snapshot(
                ComputeBackend.AZURE_ML, state=CapacityState.UNKNOWN
            )
        }
        selected, _ = self.router.resolve(
            execution_id="exec-1",
            workload=ComputeWorkload.TRAINING,
            candidates=candidates,
            capacity_by_backend=capacity,
        )
        self.assertEqual(selected, ComputeBackend.AZURE_ML)

    def test_empty_candidates_raises_configuration_error(self):
        with self.assertRaises(BackendConfigurationError):
            self.router.resolve(
                execution_id="exec-1",
                workload=ComputeWorkload.TRAINING,
                candidates=[],
                capacity_by_backend={},
            )

    def test_auto_in_candidate_list_raises_configuration_error(self):
        with self.assertRaises(BackendConfigurationError):
            self.router.resolve(
                execution_id="exec-1",
                workload=ComputeWorkload.TRAINING,
                candidates=[ComputeBackend.AUTO, ComputeBackend.AZURE_ML],
                capacity_by_backend={
                    ComputeBackend.AZURE_ML: _snapshot(ComputeBackend.AZURE_ML)
                },
            )

    def test_duplicate_candidates_raise_configuration_error(self):
        with self.assertRaisesRegex(
            BackendConfigurationError, "duplicate backends: azure_batch"
        ):
            self.router.resolve(
                execution_id="exec-1",
                workload=ComputeWorkload.TRAINING,
                candidates=[
                    ComputeBackend.AZURE_BATCH,
                    ComputeBackend.AZURE_ML,
                    ComputeBackend.AZURE_BATCH,
                ],
                capacity_by_backend={
                    ComputeBackend.AZURE_BATCH: _snapshot(
                        ComputeBackend.AZURE_BATCH
                    ),
                    ComputeBackend.AZURE_ML: _snapshot(
                        ComputeBackend.AZURE_ML
                    ),
                },
            )

    def test_non_positive_programmatic_weight_is_rejected(self):
        capacity = {
            ComputeBackend.AZURE_BATCH: _snapshot(ComputeBackend.AZURE_BATCH)
        }
        for weight in (0, -1):
            with self.subTest(weight=weight):
                with self.assertRaisesRegex(
                    BackendConfigurationError, "positive integer"
                ):
                    self.router.resolve(
                        execution_id="exec-1",
                        workload=ComputeWorkload.TRAINING,
                        candidates=[ComputeBackend.AZURE_BATCH],
                        capacity_by_backend=capacity,
                        weights={ComputeBackend.AZURE_BATCH: weight},
                    )

    def test_non_integer_programmatic_weight_is_rejected(self):
        with self.assertRaisesRegex(
            BackendConfigurationError, "positive integer"
        ):
            self.router.resolve(
                execution_id="exec-1",
                workload=ComputeWorkload.TRAINING,
                candidates=[ComputeBackend.AZURE_BATCH],
                capacity_by_backend={
                    ComputeBackend.AZURE_BATCH: _snapshot(
                        ComputeBackend.AZURE_BATCH
                    )
                },
                weights={ComputeBackend.AZURE_BATCH: True},
            )

    def test_weight_for_non_candidate_backend_is_rejected(self):
        with self.assertRaisesRegex(
            BackendConfigurationError, "non-candidate backends: azure_ml"
        ):
            self.router.resolve(
                execution_id="exec-1",
                workload=ComputeWorkload.TRAINING,
                candidates=[ComputeBackend.AZURE_BATCH],
                capacity_by_backend={
                    ComputeBackend.AZURE_BATCH: _snapshot(
                        ComputeBackend.AZURE_BATCH
                    )
                },
                weights={ComputeBackend.AZURE_ML: 1},
            )

    def test_configured_weight_can_change_selection(self):
        """A heavily weighted candidate should win far more often than an
        even split would predict, without breaking determinism per id."""
        candidates = [ComputeBackend.AZURE_BATCH, ComputeBackend.AZURE_ML]
        capacity = {
            ComputeBackend.AZURE_BATCH: _snapshot(ComputeBackend.AZURE_BATCH),
            ComputeBackend.AZURE_ML: _snapshot(ComputeBackend.AZURE_ML),
        }
        heavy_weights = {
            ComputeBackend.AZURE_BATCH: 1,
            ComputeBackend.AZURE_ML: 1000,
        }
        batch_wins = 0
        total = 200
        for i in range(total):
            selected, _ = self.router.resolve(
                execution_id=f"exec-weighted-{i}",
                workload=ComputeWorkload.TRAINING,
                candidates=candidates,
                capacity_by_backend=capacity,
                weights=heavy_weights,
            )
            if selected == ComputeBackend.AZURE_BATCH:
                batch_wins += 1
        # With a 1:1000 weight ratio, azure_ml should win overwhelmingly.
        self.assertLess(batch_wins, total * 0.1)


class TestCandidatesAndWeightsFromEnv(unittest.TestCase):
    def test_candidates_from_env_parses_csv(self):
        os_environ_backup = {}
        try:
            import os

            os_environ_backup[
                "COMPUTE_AUTO_CANDIDATES_TRAINING"
            ] = os.environ.get("COMPUTE_AUTO_CANDIDATES_TRAINING")
            os.environ[
                "COMPUTE_AUTO_CANDIDATES_TRAINING"
            ] = "azure_batch, azure_ml"
            candidates = candidates_from_env(ComputeWorkload.TRAINING)
            self.assertEqual(
                candidates,
                [ComputeBackend.AZURE_BATCH, ComputeBackend.AZURE_ML],
            )
        finally:
            self._restore(os_environ_backup)

    def test_candidates_from_env_returns_none_when_unset(self):
        import os

        backup = os.environ.pop("COMPUTE_AUTO_CANDIDATES_INFERENCE", None)
        try:
            self.assertIsNone(candidates_from_env(ComputeWorkload.INFERENCE))
        finally:
            if backup is not None:
                os.environ["COMPUTE_AUTO_CANDIDATES_INFERENCE"] = backup

    def test_candidates_from_env_rejects_unrecognized_backend_token(self):
        import os

        backup = os.environ.get("COMPUTE_AUTO_CANDIDATES_TRAINING")
        os.environ[
            "COMPUTE_AUTO_CANDIDATES_TRAINING"
        ] = "azure_batch,not_a_backend"
        try:
            with self.assertRaises(BackendConfigurationError):
                candidates_from_env(ComputeWorkload.TRAINING)
        finally:
            if backup is None:
                os.environ.pop("COMPUTE_AUTO_CANDIDATES_TRAINING", None)
            else:
                os.environ["COMPUTE_AUTO_CANDIDATES_TRAINING"] = backup

    def test_candidates_from_env_rejects_duplicate_candidate(self):
        import os

        backup = os.environ.get("COMPUTE_AUTO_CANDIDATES_TRAINING")
        os.environ[
            "COMPUTE_AUTO_CANDIDATES_TRAINING"
        ] = "azure_batch,azure_ml,azure_batch"
        try:
            with self.assertRaises(BackendConfigurationError):
                candidates_from_env(ComputeWorkload.TRAINING)
        finally:
            if backup is None:
                os.environ.pop("COMPUTE_AUTO_CANDIDATES_TRAINING", None)
            else:
                os.environ["COMPUTE_AUTO_CANDIDATES_TRAINING"] = backup

    def test_weights_from_env_requires_candidates(self):
        import os

        backup = os.environ.get("COMPUTE_AUTO_CANDIDATES_EMBEDDING")
        os.environ.pop("COMPUTE_AUTO_CANDIDATES_EMBEDDING", None)
        os.environ["COMPUTE_AUTO_WEIGHTS_EMBEDDING"] = "1,2"
        try:
            with self.assertRaises(BackendConfigurationError):
                weights_from_env(ComputeWorkload.EMBEDDING)
        finally:
            os.environ.pop("COMPUTE_AUTO_WEIGHTS_EMBEDDING", None)
            if backup is not None:
                os.environ["COMPUTE_AUTO_CANDIDATES_EMBEDDING"] = backup

    def test_weights_from_env_mismatched_length_raises(self):
        import os

        os.environ[
            "COMPUTE_AUTO_CANDIDATES_ARTIFACTS"
        ] = "azure_batch,azure_ml"
        os.environ["COMPUTE_AUTO_WEIGHTS_ARTIFACTS"] = "1"
        try:
            with self.assertRaises(BackendConfigurationError):
                weights_from_env(ComputeWorkload.ARTIFACT_PACKAGING)
        finally:
            os.environ.pop("COMPUTE_AUTO_CANDIDATES_ARTIFACTS", None)
            os.environ.pop("COMPUTE_AUTO_WEIGHTS_ARTIFACTS", None)

    def test_weights_from_env_parses_valid_pairs(self):
        import os

        os.environ[
            "COMPUTE_AUTO_CANDIDATES_IMAGERYPREP"
        ] = "azure_batch,azure_ml"
        os.environ["COMPUTE_AUTO_WEIGHTS_IMAGERYPREP"] = "3,7"
        try:
            weights = weights_from_env(ComputeWorkload.IMAGERY_PREPARATION)
            self.assertEqual(
                weights,
                {ComputeBackend.AZURE_BATCH: 3, ComputeBackend.AZURE_ML: 7},
            )
        finally:
            os.environ.pop("COMPUTE_AUTO_CANDIDATES_IMAGERYPREP", None)
            os.environ.pop("COMPUTE_AUTO_WEIGHTS_IMAGERYPREP", None)

    def _restore(self, backup):
        import os

        for key, value in backup.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value


if __name__ == "__main__":
    unittest.main()
