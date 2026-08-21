# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License.
"""Tests for the primary-label-class helpers.

The decision these drive is whether a training run enables the "No Damage"
constraint loss. Getting it wrong is quiet in both directions: leaving it off
trains a weak label as a hard visual class, and turning it on for a class
layout the pipeline can't support fails the job after submission.
"""

import unittest

from hastegeo.core.utils.label_classes import (
    DAMAGED_CLASS_INDEX,
    find_class_value,
    normalize_class_name,
    should_use_constraint_loss,
)

# The full catalog the project form offers, in ui/src/assets/json/settings.json
# order. Cloud sits between Damaged Building and No Damage.
UI_CATALOG = [
    "Background",
    "Building",
    "Damaged Building",
    "Cloud",
    "No Damage",
    "Flood Extent",
]


class TestNormalizeClassName(unittest.TestCase):
    def test_equivalent_spellings_collapse(self):
        forms = [
            "No Damage",
            "no damage",
            "NO DAMAGE",
            "no_damage",
            "No-Damage",
            "  no   damage  ",
        ]
        self.assertEqual(
            {normalize_class_name(f) for f in forms}, {"no damage"}
        )

    def test_distinct_names_stay_distinct(self):
        self.assertNotEqual(
            normalize_class_name("Damaged Building"),
            normalize_class_name("No Damage"),
        )


class TestFindClassValue(unittest.TestCase):
    def test_is_one_based(self):
        """0 is reserved for "not labeled"."""
        self.assertEqual(find_class_value(UI_CATALOG, "Background"), 1)
        self.assertEqual(find_class_value(UI_CATALOG, "No Damage"), 5)

    def test_matches_leniently(self):
        self.assertEqual(
            find_class_value(UI_CATALOG, "damaged_building"),
            DAMAGED_CLASS_INDEX,
        )

    def test_returns_none_when_absent(self):
        self.assertIsNone(find_class_value(["Background"], "No Damage"))


class TestShouldUseConstraintLoss(unittest.TestCase):
    def test_enabled_for_the_full_ui_catalog(self):
        self.assertTrue(should_use_constraint_loss(UI_CATALOG))

    def test_enabled_for_the_minimal_viable_list(self):
        classes = ["Background", "Building", "Damaged Building", "No Damage"]
        self.assertTrue(should_use_constraint_loss(classes))

    def test_enabled_regardless_of_spelling(self):
        classes = ["background", "building", "damaged_building", "no_damage"]
        self.assertTrue(should_use_constraint_loss(classes))

    def test_disabled_without_no_damage(self):
        """The default 3-class project must be unaffected."""
        classes = ["Background", "Building", "Damaged Building"]
        self.assertFalse(should_use_constraint_loss(classes))

    def test_disabled_without_damaged_building(self):
        """The loss penalizes Damaged Building probability; it must exist."""
        classes = ["Background", "Building", "No Damage"]
        self.assertFalse(should_use_constraint_loss(classes))

    def test_disabled_when_damaged_building_is_misplaced(self):
        """Enabling here would fail the job at startup, so stay off.

        Downstream steps hardcode class value 3 as damaged, so this ordering
        is already wrong for the damage reports -- but that is a pre-existing
        problem and not one to surface as a training failure.
        """
        classes = [
            "Background",
            "Cloud",
            "Building",
            "Damaged Building",
            "No Damage",
        ]
        self.assertEqual(find_class_value(classes, "Damaged Building"), 4)
        self.assertFalse(should_use_constraint_loss(classes))

    def test_disabled_for_empty_or_missing_classes(self):
        self.assertFalse(should_use_constraint_loss([]))
        self.assertFalse(should_use_constraint_loss(None))

    def test_warns_when_layout_blocks_the_loss(self):
        """A silent skip would leave no trace of why the loss was off."""
        # Damaged Building at value 4, not 3.
        classes = [
            "Background",
            "Cloud",
            "Building",
            "Damaged Building",
            "No Damage",
        ]
        with self.assertLogs(
            "hastegeo.core.utils.label_classes", level="WARNING"
        ) as captured:
            should_use_constraint_loss(classes)
        self.assertIn("Damaged Building", "".join(captured.output))

    def test_does_not_warn_for_a_project_without_no_damage(self):
        """No warning for the common case that simply doesn't use the loss."""
        classes = ["Background", "Building", "Damaged Building"]
        with self.assertNoLogs(
            "hastegeo.core.utils.label_classes", level="WARNING"
        ):
            should_use_constraint_loss(classes)


if __name__ == "__main__":
    unittest.main()
