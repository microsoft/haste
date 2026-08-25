# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License.

"""Rules for the Building Validation sample-size setting.

Kept free of geospatial dependencies on purpose: ``footprints`` imports
geopandas at module scope, and the API needs these rules at import time
without paying for that. ``footprints.sample_indices`` does the drawing;
this module decides whether a requested change is allowed.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Optional

# How many footprints a layer validates when nobody has chosen. Matches the
# value the workflow hardcoded before the setting existed, so layers created
# earlier behave identically.
DEFAULT_VALIDATION_SAMPLE = 200
MIN_VALIDATION_SAMPLE = 1
# Also bounds the GetBuildingFootprintsGeoJSON response: a layer can hold
# millions of footprints.
MAX_VALIDATION_SAMPLE = 2000

# Outcomes of check_sample_size_change. The names match the UI's
# canApplySampleSize so the two rule tables read the same way.
OUTCOME_NOOP = "noop"
OUTCOME_EXTEND = "extend"
OUTCOME_RESAMPLE = "resample"
OUTCOME_BLOCKED = "blocked"
OUTCOME_INVALID = "invalid"


@dataclass(frozen=True)
class SampleSizeChange:
    """What should happen to a requested sample-size change."""

    outcome: str
    message: str = ""

    @property
    def allowed(self) -> bool:
        return self.outcome in (
            OUTCOME_NOOP,
            OUTCOME_EXTEND,
            OUTCOME_RESAMPLE,
        )

    @property
    def writes(self) -> bool:
        """Whether the change needs to be persisted."""
        return self.outcome in (OUTCOME_EXTEND, OUTCOME_RESAMPLE)


def clamp_validation_sample(sample_size: int) -> int:
    """Clamp a requested sample size to the supported range."""
    return max(
        MIN_VALIDATION_SAMPLE,
        min(int(sample_size), MAX_VALIDATION_SAMPLE),
    )


def resolve_sample_size(stored: Optional[dict]) -> int:
    """Read the configured sample size out of a stored validation document.

    Documents written before this setting existed have no ``sampleSize``,
    and neither does a layer that has never been validated. Both resolve to
    the default, which is what those layers already used.
    """
    if not stored:
        return DEFAULT_VALIDATION_SAMPLE

    value = stored.get("sampleSize")
    if not isinstance(value, int) or isinstance(value, bool):
        return DEFAULT_VALIDATION_SAMPLE

    return clamp_validation_sample(value)


def check_sample_size_change(
    current: int,
    requested: Any,
    label_count: int,
) -> SampleSizeChange:
    """Decide whether a sample-size change may be applied.

    Growing is always safe: the draw is a permutation prefix, so a larger
    sample keeps every building already in the set and adds only the
    difference (see ``footprints.sample_indices``). Shrinking drops
    buildings off the end of that prefix, which is fine while nothing is
    labeled and destroys work once something is.

    Args:
        current: The layer's stored sample size.
        requested: The requested sample size, unvalidated.
        label_count: How many validation labels the layer already holds.

    Returns:
        A SampleSizeChange describing the outcome. ``blocked`` and
        ``invalid`` carry a message meant to be shown to the user.
    """
    if isinstance(requested, bool) or not isinstance(requested, int):
        return SampleSizeChange(
            OUTCOME_INVALID,
            "sampleSize must be an integer.",
        )

    if requested < MIN_VALIDATION_SAMPLE or requested > MAX_VALIDATION_SAMPLE:
        return SampleSizeChange(
            OUTCOME_INVALID,
            f"sampleSize must be between {MIN_VALIDATION_SAMPLE} and "
            f"{MAX_VALIDATION_SAMPLE}.",
        )

    if requested == current:
        return SampleSizeChange(OUTCOME_NOOP)

    if requested > current:
        return SampleSizeChange(OUTCOME_EXTEND)

    if label_count > 0:
        return SampleSizeChange(
            OUTCOME_BLOCKED,
            f"This layer has {label_count} validation label(s). Lowering "
            f"the count from {current} to {requested} would drop labeled "
            "buildings from the set. Clear the validation labels first.",
        )

    return SampleSizeChange(OUTCOME_RESAMPLE)
