# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License.
"""Canonical imagery source-type keys and their legacy aliases.

The source-type key is persisted on every image layer
(``sourceTypePreEvent`` / ``sourceTypePostEvent``) and on every catalogued
model (``imagerySource``), so a rename cannot simply replace the old value:
records written before the rename still carry it. Every comparison against
a source-type key should go through :func:`normalize_source_type` rather
than matching the literal, otherwise one provider silently splits into two
non-interoperable pools.

Keep in sync with ``normalizeSourceTypeKey`` in
``ui/src/Components/sourceTypeOptions.js``.
"""

# Keys persisted before the Maxar -> Vantor rebrand.
LEGACY_SOURCE_TYPE_ALIASES = {
    "maxar": "vantor",
}


def normalize_source_type(source_type):
    """Return the canonical, lower-cased key for ``source_type``.

    Args:
        source_type: A source-type key, e.g. ``"vantor"`` or the
            pre-rebrand ``"maxar"``. Non-string values (including
            ``None``) are returned unchanged so callers can pass an
            optional field straight through without a guard.

    Returns:
        The canonical key, lower-cased and stripped; unknown keys are
        passed through unchanged (aside from case/whitespace) so this
        never silently discards a value it does not recognize.
    """
    if not isinstance(source_type, str):
        return source_type
    key = source_type.strip().lower()
    return LEGACY_SOURCE_TYPE_ALIASES.get(key, key)
