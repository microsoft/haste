# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License.
"""Helpers for interpreting a project's primary label classes.

``PrimaryClass.name`` is an unconstrained string and the UI lets a project
pick any subset of the catalog in any order (see
``ui/src/assets/json/settings.json``), so the training pipeline can't assume
a fixed class layout. These helpers turn the configured names into the mask
values the training scripts reason about.

Mask values are ``index + 1`` because 0 is reserved for "not labeled".

.. note::
   ``docker/training/code/bda/config.py`` carries an equivalent
   implementation. It is deliberately duplicated rather than imported: the
   ``bda`` package is a vendored fork of
   https://github.com/microsoft/building-damage-assessment and has to keep
   running standalone, outside this image. Keep the two in sync.
"""
import logging
import re
from typing import List, Optional, Sequence

logger = logging.getLogger(__name__)

# Class names the "No Damage" constraint loss operates on. These match the
# UI's catalog entries, but names are matched leniently (see
# ``normalize_class_name``) because nothing enforces that spelling.
NO_DAMAGE_CLASS = "No Damage"
DAMAGED_BUILDING_CLASS = "Damaged Building"

# Mask value the rest of the pipeline treats as the damaged class.
# ``merge_with_building_footprints.py`` derives the damage fraction from this
# raster value and ``inference.py`` gives it the red palette entry.
DAMAGED_CLASS_INDEX = 3


def normalize_class_name(name: str) -> str:
    """Fold a class name so casing and separator style don't matter.

    "No Damage", "no_damage", "NO-DAMAGE" and "no  damage" all normalize to
    the same string. This matches the case-insensitive duplicate check the
    project form already applies (``validatePrimaryClasses`` in
    ``ui/src/util/validation.js``).

    Args:
        name (str): A class name.

    Returns:
        str: The normalized name.
    """
    return re.sub(r"[\s_\-]+", " ", str(name).strip().casefold())


def find_class_value(classes: Sequence[str], target: str) -> Optional[int]:
    """Return the mask value of ``target`` in ``classes``, or None.

    Args:
        classes (Sequence[str]): The project's label class names, in order.
        target (str): The class name to look for.

    Returns:
        Optional[int]: The mask value (``index + 1``), or None if absent.
    """
    wanted = normalize_class_name(target)
    for idx, name in enumerate(classes):
        if normalize_class_name(name) == wanted:
            return idx + 1
    return None


def should_use_constraint_loss(classes: Optional[List[str]]) -> bool:
    """Whether a project's class list calls for the "No Damage" loss.

    "No Damage" is a weak label: it says a building is *not damaged*, not
    what the pixels look like. Training it as an ordinary hard class asks the
    model to learn a visual category that doesn't exist. The constraint loss
    is the correct treatment, so enable it whenever the project defines that
    class.

    Two conditions must hold, and both are checked here rather than left to
    fail inside the training container:

    * "Damaged Building" must also be present -- the loss penalizes *its*
      predicted probability at "No Damage" pixels.
    * "Damaged Building" must sit at :data:`DAMAGED_CLASS_INDEX`, because the
      merge and visualization steps hardcode that value.

    When "No Damage" is present but the layout can't support the loss, this
    logs why and returns False rather than submitting a job that would fail
    at startup. That case also means the class ordering is already wrong for
    the damage reports, which the warning surfaces.

    Args:
        classes (Optional[List[str]]): The project's label class names.

    Returns:
        bool: True when the constraint loss should be enabled.
    """
    if not classes:
        return False

    no_damage_value = find_class_value(classes, NO_DAMAGE_CLASS)
    if no_damage_value is None:
        return False

    damaged_value = find_class_value(classes, DAMAGED_BUILDING_CLASS)
    if damaged_value is None:
        logger.warning(
            "Label classes include '%s' but not '%s', so the constraint "
            "loss cannot be enabled and '%s' will be trained as an ordinary "
            "class. Classes: %s",
            NO_DAMAGE_CLASS,
            DAMAGED_BUILDING_CLASS,
            NO_DAMAGE_CLASS,
            classes,
        )
        return False

    if no_damage_value != len(classes):
        logger.warning(
            "Label classes include '%s', but it is entry %d of %d rather than "
            "the last. It is a weak label and is given no output channel, "
            "which requires it to be the final class. Leaving the constraint "
            "loss off; move '%s' to the end of the project's classes to use "
            "it. Classes: %s",
            NO_DAMAGE_CLASS,
            no_damage_value,
            len(classes),
            NO_DAMAGE_CLASS,
            classes,
        )
        return False

    if damaged_value != DAMAGED_CLASS_INDEX:
        logger.warning(
            "Label classes include '%s', but '%s' is class value %d rather "
            "than %d, which the merge and visualization steps require. "
            "Leaving the constraint loss off; note this ordering also means "
            "the damage reports will read class %d. Classes: %s",
            NO_DAMAGE_CLASS,
            DAMAGED_BUILDING_CLASS,
            damaged_value,
            DAMAGED_CLASS_INDEX,
            DAMAGED_CLASS_INDEX,
            classes,
        )
        return False

    logger.info(
        "Label classes include '%s' (value %d); enabling the constraint "
        "loss so it is treated as a weak label rather than a hard class.",
        NO_DAMAGE_CLASS,
        no_damage_value,
    )
    return True
