# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License.
"""``ComputeRouter``: deterministic resolution of ``ComputeBackend.AUTO``.

Filters adapter-reported capacity/capability snapshots and ranks the
remainder with weighted rendezvous hashing (HRW) on ``executionId``, so the
same job always resolves to the same backend given the same configured
candidate set and weights — no shared/durable routing state needed across
retries (design.md#auto-routing).
"""

import hashlib
import math
import os
from typing import Dict, List, Mapping, Optional, Sequence, Tuple

from hastegeo.core.models.compute import (
    BackendConfigurationError,
    CapacitySnapshot,
    CapacityState,
    CapacityUnavailableError,
    ComputeBackend,
    ComputeWorkload,
)

# Env-var suffixes for COMPUTE_AUTO_CANDIDATES_<WORKLOAD> /
# COMPUTE_AUTO_WEIGHTS_<WORKLOAD> (data-model.md#configuration-changes).
_WORKLOAD_ENV_SUFFIX: Dict[ComputeWorkload, str] = {
    ComputeWorkload.TRAINING: "TRAINING",
    ComputeWorkload.INFERENCE: "INFERENCE",
    ComputeWorkload.EMBEDDING: "EMBEDDING",
    ComputeWorkload.IMAGERY_PREPARATION: "IMAGERYPREP",
    ComputeWorkload.ARTIFACT_PACKAGING: "ARTIFACTS",
}

# Capacity states that remove a candidate from auto-routing consideration.
# ``unknown`` is deliberately still eligible (advisory/best-effort per
# data-model.md) rather than treated as a rejection.
_INELIGIBLE_STATES = frozenset({CapacityState.UNAVAILABLE})

# Keeps the rendezvous hash strictly inside (0, 1) so -log() never sees 0.
_EPSILON = 1e-12


def candidates_from_env(
    workload: ComputeWorkload,
) -> Optional[List[ComputeBackend]]:
    """Read ``COMPUTE_AUTO_CANDIDATES_<WORKLOAD>`` (comma-separated backend
    names, e.g. ``"azure_batch,azure_ml"``).

    Returns ``None`` when unset so callers can fall back to an explicitly
    supplied candidate list instead of an empty one. Raises
    ``BackendConfigurationError`` for an unrecognized backend token or a
    duplicate entry, rather than letting an invalid enum value surface as
    an unclassified ``ValueError`` or silently double-weighting a repeated
    candidate in the router.
    """
    suffix = _WORKLOAD_ENV_SUFFIX[workload]
    raw = os.environ.get(f"COMPUTE_AUTO_CANDIDATES_{suffix}")
    if raw is None or not raw.strip():
        return None
    backends: List[ComputeBackend] = []
    seen = set()
    for token in raw.split(","):
        token = token.strip()
        if not token:
            continue
        try:
            backend = ComputeBackend(token)
        except ValueError as exc:
            raise BackendConfigurationError(
                f"COMPUTE_AUTO_CANDIDATES_{suffix} contains an "
                f"unrecognized backend {token!r}"
            ) from exc
        if backend in seen:
            raise BackendConfigurationError(
                f"COMPUTE_AUTO_CANDIDATES_{suffix} lists {backend.value!r} "
                "more than once"
            )
        seen.add(backend)
        backends.append(backend)
    return backends


def weights_from_env(
    workload: ComputeWorkload,
) -> Optional[Dict[ComputeBackend, int]]:
    """Read ``COMPUTE_AUTO_WEIGHTS_<WORKLOAD>`` (comma-separated positive
    integers, positionally aligned with
    ``COMPUTE_AUTO_CANDIDATES_<WORKLOAD>``).

    Returns ``None`` when unset (equal weighting). Raises
    ``BackendConfigurationError`` for any malformed configuration (weights
    without candidates, mismatched counts, non-positive/non-integer
    entries) rather than silently ignoring it.
    """
    suffix = _WORKLOAD_ENV_SUFFIX[workload]
    raw = os.environ.get(f"COMPUTE_AUTO_WEIGHTS_{suffix}")
    if raw is None or not raw.strip():
        return None
    candidates = candidates_from_env(workload)
    if not candidates:
        raise BackendConfigurationError(
            f"COMPUTE_AUTO_WEIGHTS_{suffix} is set but "
            f"COMPUTE_AUTO_CANDIDATES_{suffix} is not"
        )
    weight_tokens = [
        token.strip() for token in raw.split(",") if token.strip()
    ]
    if len(weight_tokens) != len(candidates):
        raise BackendConfigurationError(
            f"COMPUTE_AUTO_WEIGHTS_{suffix} must have the same number of "
            f"entries as COMPUTE_AUTO_CANDIDATES_{suffix}"
        )
    weights: Dict[ComputeBackend, int] = {}
    for backend, token in zip(candidates, weight_tokens):
        try:
            weight = int(token)
        except ValueError as exc:
            raise BackendConfigurationError(
                f"COMPUTE_AUTO_WEIGHTS_{suffix} entry {token!r} is not an "
                "integer"
            ) from exc
        if weight <= 0:
            raise BackendConfigurationError(
                f"COMPUTE_AUTO_WEIGHTS_{suffix} entry for "
                f"{backend.value!r} must be a positive integer"
            )
        weights[backend] = weight
    return weights


def _rendezvous_score(
    execution_id: str, backend: ComputeBackend, weight: int
) -> float:
    """Deterministic weighted-rendezvous (HRW) score for ``backend``.

    Standard weighted-HRW formula: ``score = weight / -ln(hash01)``, where
    ``hash01`` is a value uniform in ``(0, 1]`` derived from a stable digest
    of ``(execution_id, backend)``. The highest score wins. This gives
    every candidate the same score for the same inputs on every call (no
    shared state needed across retries/workers) while making selection
    probability approach each candidate's share of total weight, unlike a
    plain ``weight * hash01`` product.
    """
    digest = hashlib.sha256(
        f"{execution_id}:{backend.value}".encode("utf-8")
    ).digest()
    hash_int = int.from_bytes(digest, "big")
    max_int = (1 << (8 * len(digest))) - 1
    hash01 = hash_int / max_int
    hash01 = min(max(hash01, _EPSILON), 1.0 - _EPSILON)
    return weight / -math.log(hash01)


class ComputeRouter:
    """Stateless resolver for ``ComputeBackend.AUTO``.

    A pure function of its inputs: given the same ``execution_id``,
    ``workload``, candidate set, weights, and capacity snapshots, ``resolve``
    always returns the same backend. Callers own supplying capacity
    snapshots (typically obtained per candidate via
    ``RunnerRegistry.get(...).get_capacity(...)``) and candidate/weight
    configuration (typically via ``candidates_from_env``/
    ``weights_from_env``); this class does no I/O and reads no environment
    variables itself.
    """

    @staticmethod
    def validate_candidates(
        candidates: Sequence[ComputeBackend],
        workload: ComputeWorkload,
    ) -> None:
        """Reject malformed ``auto`` candidate lists before adapter access."""
        if not candidates:
            raise BackendConfigurationError(
                f"no auto candidates configured for workload "
                f"{workload.value!r}"
            )
        if any(candidate == ComputeBackend.AUTO for candidate in candidates):
            raise BackendConfigurationError(
                "'auto' cannot be a member of its own candidate list"
            )

        seen = set()
        duplicates = []
        for candidate in candidates:
            if candidate in seen and candidate not in duplicates:
                duplicates.append(candidate)
            seen.add(candidate)
        if duplicates:
            names = ", ".join(candidate.value for candidate in duplicates)
            raise BackendConfigurationError(
                f"auto candidate list contains duplicate backends: {names}"
            )

    @staticmethod
    def validate_weights(
        candidates: Sequence[ComputeBackend],
        weights: Optional[Mapping[ComputeBackend, int]],
    ) -> None:
        """Reject invalid programmatic weights before adapter access."""
        if weights is None:
            return
        unknown = [backend for backend in weights if backend not in candidates]
        if unknown:
            names = ", ".join(
                getattr(backend, "value", str(backend)) for backend in unknown
            )
            raise BackendConfigurationError(
                f"auto weights include non-candidate backends: {names}"
            )
        for backend, weight in weights.items():
            if (
                isinstance(weight, bool)
                or not isinstance(weight, int)
                or weight <= 0
            ):
                name = getattr(backend, "value", str(backend))
                raise BackendConfigurationError(
                    f"auto weight for {name!r} must be a positive integer"
                )

    def resolve(
        self,
        *,
        execution_id: str,
        workload: ComputeWorkload,
        candidates: Sequence[ComputeBackend],
        capacity_by_backend: Mapping[ComputeBackend, CapacitySnapshot],
        weights: Optional[Mapping[ComputeBackend, int]] = None,
    ) -> Tuple[ComputeBackend, str]:
        """Return ``(selected_backend, routing_reason)``.

        ``routing_reason`` always starts with ``"auto:"`` followed by the
        ranked candidate/weight summary (data-model.md's
        ``auto:<weight/candidate summary>``).

        Raises ``BackendConfigurationError`` if ``candidates`` is empty,
        contains ``auto`` itself, or contains duplicate backends. Raises
        ``CapacityUnavailableError`` if every candidate is filtered out (no
        snapshot, wrong workload, or a capacity state in
        ``_INELIGIBLE_STATES``).
        """
        self.validate_candidates(candidates, workload)
        self.validate_weights(candidates, weights)

        eligible: List[ComputeBackend] = []
        for backend in candidates:
            snapshot = capacity_by_backend.get(backend)
            if snapshot is None:
                continue
            if snapshot.workload != workload:
                continue
            if snapshot.state in _INELIGIBLE_STATES:
                continue
            eligible.append(backend)

        if not eligible:
            raise CapacityUnavailableError(
                "no candidate backend reports usable capacity for workload "
                f"{workload.value!r} (candidates: "
                f"{[c.value for c in candidates]})"
            )

        resolved_weights: Dict[ComputeBackend, int] = dict(weights or {})
        for backend in eligible:
            resolved_weights.setdefault(backend, 1)

        ranked = sorted(
            eligible,
            key=lambda backend: _rendezvous_score(
                execution_id, backend, resolved_weights[backend]
            ),
            reverse=True,
        )
        selected = ranked[0]
        reason = "auto:" + ",".join(
            f"{backend.value}={resolved_weights[backend]}"
            for backend in ranked
        )
        return selected, reason
