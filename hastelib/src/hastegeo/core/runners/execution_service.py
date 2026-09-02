# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License.
"""``ComputeExecutionService``: validate, resolve, submit, and dispatch.

Owns idempotent submission (spec validation, backend resolution, get-or-
create against the provider) and handle-based lifecycle dispatch — every
lifecycle call (``get_status``/``read_output``/``cancel``/``finalize``)
looks up the adapter by the persisted ``ComputeJobHandle.selectedBackend``,
never by the current process-global default, so a ``COMPUTE_BACKEND_DEFAULT``
change or worker restart mid-job is safe (design.md#lifecycle-dispatch).
"""

from typing import (
    Dict,
    Iterable,
    List,
    Mapping,
    Optional,
    Sequence,
    Tuple,
    Union,
)

from hastegeo.core.models.compute import (
    BackendConfigurationError,
    BackendUnavailableError,
    CapacitySnapshot,
    CapacityUnavailableError,
    ComputeBackend,
    ComputeJobHandle,
    ComputeJobSpec,
    ComputeJobState,
    SubmissionIndeterminateError,
    redact_if_credential,
)
from hastegeo.core.runners.base import ComputeRunner
from hastegeo.core.utils.logs import Logger

from .registry import DEFAULT_PROFILE, RunnerRegistry
from .router import ComputeRouter, candidates_from_env, weights_from_env

# Pre-acceptance errors: safe to try the next auto candidate, because the
# provider could not have accepted the job yet. Anything else — most
# importantly SubmissionIndeterminateError — must reconcile against the
# same backend/provider instead of risking a duplicate submission
# (design.md#idempotent-submission).
_PRE_ACCEPTANCE_ERRORS = (
    BackendConfigurationError,
    BackendUnavailableError,
    CapacityUnavailableError,
)


class ComputeExecutionService:
    """Validates specs, resolves the backend, submits idempotently, and
    dispatches lifecycle operations by persisted handle."""

    def __init__(
        self,
        registry: Optional[RunnerRegistry] = None,
        router: Optional[ComputeRouter] = None,
        *,
        max_indeterminate_retries: int = 2,
    ):
        if max_indeterminate_retries < 0:
            raise ValueError("max_indeterminate_retries must be >= 0")
        self._registry = registry or RunnerRegistry()
        self._router = router or ComputeRouter()
        self._max_indeterminate_retries = max_indeterminate_retries
        self._logger = Logger.get_logger(__name__)

    # -- submission ---------------------------------------------------

    def submit(
        self,
        spec: ComputeJobSpec,
        *,
        profile: str = DEFAULT_PROFILE,
        auto_candidates: Optional[Sequence[ComputeBackend]] = None,
        auto_weights: Optional[Mapping[ComputeBackend, int]] = None,
    ) -> ComputeJobHandle:
        """Resolve ``spec.backendPreference`` and submit idempotently.

        For an explicit (non-``auto``) preference, resolves directly to
        that backend — no capacity/weight logic is invoked, and any
        configuration/availability failure is raised immediately with no
        silent reroute (design.md's "Explicit backend disabled or
        incompatible" edge case).

        For ``auto``, evaluates ``auto_candidates``/``auto_weights`` if
        given, else falls back to ``COMPUTE_AUTO_CANDIDATES_<WORKLOAD>``/
        ``COMPUTE_AUTO_WEIGHTS_<WORKLOAD>``.
        """
        if spec.backendPreference != ComputeBackend.AUTO:
            return self._submit_explicit(
                spec,
                spec.backendPreference,
                profile,
                routing_reason="explicit",
            )

        candidates = list(
            auto_candidates or candidates_from_env(spec.workload) or []
        )
        weights = dict(auto_weights or weights_from_env(spec.workload) or {})
        return self._submit_auto(spec, profile, candidates, weights)

    def _submit_explicit(
        self,
        spec: ComputeJobSpec,
        backend: ComputeBackend,
        profile: str,
        *,
        routing_reason: str,
    ) -> ComputeJobHandle:
        runner = self._registry.get(backend, profile=profile)
        runner.validate(spec)
        return self._submit_with_reconciliation(
            runner, spec, profile=profile, routing_reason=routing_reason
        )

    def _submit_auto(
        self,
        spec: ComputeJobSpec,
        profile: str,
        candidates: Sequence[ComputeBackend],
        weights: Mapping[ComputeBackend, int],
    ) -> ComputeJobHandle:
        if not candidates:
            raise BackendConfigurationError(
                f"'auto' requested for workload {spec.workload.value!r} but "
                "no candidate backends are configured"
            )

        remaining = list(candidates)
        last_error: Optional[Exception] = None
        while remaining:
            (
                runners,
                snapshots,
                remaining,
                gather_error,
            ) = self._gather_capacity(remaining, profile, spec)
            if gather_error is not None:
                last_error = gather_error
            if not remaining:
                break

            try:
                selected, reason = self._router.resolve(
                    execution_id=spec.executionId,
                    workload=spec.workload,
                    candidates=remaining,
                    capacity_by_backend=snapshots,
                    weights=weights,
                )
            except CapacityUnavailableError as exc:
                # The router itself found every remaining candidate
                # ineligible (unavailable/wrong-workload/missing
                # snapshot) — nothing left to try.
                last_error = exc
                break

            runner = runners[selected]
            try:
                runner.validate(spec)
                return self._submit_with_reconciliation(
                    runner, spec, profile=profile, routing_reason=reason
                )
            except _PRE_ACCEPTANCE_ERRORS as exc:
                last_error = exc
                self._logger.warning(
                    "auto routing: backend %s rejected before acceptance "
                    "(%s); trying next candidate",
                    selected.value,
                    redact_if_credential(str(exc)),
                )
                remaining = [b for b in remaining if b != selected]
                continue

        raise BackendUnavailableError(
            f"all auto candidates for workload {spec.workload.value!r} were "
            "rejected before acceptance; last error: "
            f"{redact_if_credential(str(last_error))}"
        )

    def _gather_capacity(
        self,
        candidates: Sequence[ComputeBackend],
        profile: str,
        spec: ComputeJobSpec,
    ) -> Tuple[
        Dict[ComputeBackend, ComputeRunner],
        Dict[ComputeBackend, CapacitySnapshot],
        List[ComputeBackend],
        Optional[Exception],
    ]:
        """Resolve an adapter and fetch its capacity snapshot for each
        candidate, classifying per-candidate failures instead of letting
        one misconfigured/unavailable candidate abort routing for the
        rest.

        Returns ``(runners, snapshots, usable_candidates, last_error)``:
        ``runners``/``snapshots`` are keyed only by the candidates that
        succeeded; ``usable_candidates`` preserves the original candidate
        order; ``last_error`` is the most recent classified failure (or
        ``None`` if every candidate succeeded), surfaced only if no
        candidate is usable at all.
        """
        runners: Dict[ComputeBackend, ComputeRunner] = {}
        snapshots: Dict[ComputeBackend, CapacitySnapshot] = {}
        usable: List[ComputeBackend] = []
        last_error: Optional[Exception] = None
        for backend in candidates:
            try:
                runner = self._registry.get(backend, profile=profile)
                snapshot = runner.get_capacity(spec.workload, spec.resources)
            except _PRE_ACCEPTANCE_ERRORS as exc:
                last_error = exc
                self._logger.warning(
                    "auto routing: backend %s unusable while gathering "
                    "capacity (%s); excluding it from this resolution",
                    backend.value,
                    redact_if_credential(str(exc)),
                )
                continue
            runners[backend] = runner
            snapshots[backend] = snapshot
            usable.append(backend)
        return runners, snapshots, usable, last_error

    def _submit_with_reconciliation(
        self,
        runner: ComputeRunner,
        spec: ComputeJobSpec,
        *,
        profile: str,
        routing_reason: str,
    ) -> ComputeJobHandle:
        attempts = 0
        handle: Optional[ComputeJobHandle] = None
        while handle is None:
            attempts += 1
            try:
                handle = runner.submit(spec)
            except SubmissionIndeterminateError:
                if attempts > self._max_indeterminate_retries:
                    raise
                self._logger.warning(
                    "submission outcome indeterminate for executionId=%s "
                    "(attempt %d); reconciling against the same backend, "
                    "not re-routing",
                    spec.executionId,
                    attempts,
                )
                continue

        # The adapter knows the provider-facing identifiers; the service is
        # authoritative for *why*/*at what profile* this backend was used,
        # since the adapter itself has no notion of "auto" or profile
        # selection. It is likewise authoritative for how many submit()
        # calls it actually took (including indeterminate-outcome
        # retries) — the adapter has no visibility into retries the
        # service performs around it, so ``attempts`` (not whatever
        # ``attempt`` the adapter itself set) is the accurate count. In
        # the common single-call case this is 1, matching what adapters
        # already stamp on their own.
        return handle.model_copy(
            update={
                "requestedBackend": spec.backendPreference,
                "backendProfile": profile,
                "routingReason": routing_reason,
                "attempt": attempts,
            }
        )

    # -- lifecycle dispatch --------------------------------------------
    #
    # Every method below resolves the adapter strictly from
    # ``handle.selectedBackend``/``handle.backendProfile`` — never from any
    # current default — so lifecycle calls remain correct across restarts
    # and configuration changes (design.md#lifecycle-dispatch, UT-015).

    def get_status(self, handle: ComputeJobHandle) -> ComputeJobState:
        runner = self._runner_for(handle)
        return runner.get_status(handle)

    def read_output(
        self,
        handle: ComputeJobHandle,
        relative_path: str,
        *,
        as_chunks: bool = False,
    ) -> Optional[Union[str, Iterable[bytes]]]:
        runner = self._runner_for(handle)
        return runner.read_output(handle, relative_path, as_chunks=as_chunks)

    def cancel(self, handle: ComputeJobHandle) -> None:
        runner = self._runner_for(handle)
        runner.cancel(handle)

    def finalize(self, handle: ComputeJobHandle) -> None:
        runner = self._runner_for(handle)
        runner.finalize(handle)

    def _runner_for(self, handle: ComputeJobHandle) -> ComputeRunner:
        return self._registry.get(
            handle.selectedBackend, profile=handle.backendProfile
        )
