# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License.

"""Tests for hastegeo.core.utils.validation_config."""

import unittest

from hastegeo.core.utils.validation_config import (
    DEFAULT_VALIDATION_SAMPLE,
    MAX_VALIDATION_SAMPLE,
    MIN_VALIDATION_SAMPLE,
    OUTCOME_BLOCKED,
    OUTCOME_EXTEND,
    OUTCOME_INVALID,
    OUTCOME_NOOP,
    OUTCOME_RESAMPLE,
    check_sample_size_change,
    clamp_validation_sample,
    resolve_sample_size,
)


class TestResolveSampleSize(unittest.TestCase):
    """Tests for resolve_sample_size()."""

    def test_missing_document_uses_the_default(self):
        """A layer nobody has validated behaves as it always did."""
        self.assertEqual(resolve_sample_size(None), DEFAULT_VALIDATION_SAMPLE)
        self.assertEqual(resolve_sample_size({}), DEFAULT_VALIDATION_SAMPLE)

    def test_document_written_before_the_setting_existed(self):
        """No migration: an old document reads back as the default."""
        stored = {"imageLayerId": "layer", "labels": {}}

        self.assertEqual(
            resolve_sample_size(stored), DEFAULT_VALIDATION_SAMPLE
        )

    def test_reads_a_configured_value(self):
        self.assertEqual(resolve_sample_size({"sampleSize": 500}), 500)

    def test_clamps_a_stored_value_out_of_range(self):
        self.assertEqual(
            resolve_sample_size({"sampleSize": 99_999}),
            MAX_VALIDATION_SAMPLE,
        )
        self.assertEqual(
            resolve_sample_size({"sampleSize": 0}), MIN_VALIDATION_SAMPLE
        )

    def test_ignores_a_non_integer_value(self):
        for bad in ["300", 12.5, None, True]:
            with self.subTest(bad=bad):
                self.assertEqual(
                    resolve_sample_size({"sampleSize": bad}),
                    DEFAULT_VALIDATION_SAMPLE,
                )


class TestCheckSampleSizeChange(unittest.TestCase):
    """Tests for check_sample_size_change()."""

    def test_same_value_is_a_noop(self):
        result = check_sample_size_change(200, 200, label_count=40)

        self.assertEqual(result.outcome, OUTCOME_NOOP)
        self.assertTrue(result.allowed)
        self.assertFalse(result.writes)

    def test_growing_is_allowed_even_with_labels(self):
        """The point of the feature: more never destroys work.

        The draw is a permutation prefix, so the existing 200 buildings stay
        in the set and 100 new ones are added.
        """
        result = check_sample_size_change(200, 300, label_count=40)

        self.assertEqual(result.outcome, OUTCOME_EXTEND)
        self.assertTrue(result.allowed)
        self.assertTrue(result.writes)

    def test_growing_is_allowed_with_no_labels(self):
        result = check_sample_size_change(200, 300, label_count=0)

        self.assertEqual(result.outcome, OUTCOME_EXTEND)

    def test_shrinking_is_allowed_when_nothing_is_labeled(self):
        result = check_sample_size_change(300, 100, label_count=0)

        self.assertEqual(result.outcome, OUTCOME_RESAMPLE)
        self.assertTrue(result.allowed)
        self.assertTrue(result.writes)

    def test_shrinking_is_blocked_when_labels_exist(self):
        """Shrinking truncates the prefix, dropping labeled buildings."""
        result = check_sample_size_change(300, 100, label_count=40)

        self.assertEqual(result.outcome, OUTCOME_BLOCKED)
        self.assertFalse(result.allowed)
        self.assertFalse(result.writes)

    def test_blocked_message_names_the_numbers(self):
        """The user needs to know what is at stake and what to do."""
        result = check_sample_size_change(300, 100, label_count=40)

        self.assertIn("40", result.message)
        self.assertIn("300", result.message)
        self.assertIn("100", result.message)
        self.assertIn("Clear the validation labels first", result.message)

    def test_one_label_is_enough_to_block(self):
        result = check_sample_size_change(300, 299, label_count=1)

        self.assertEqual(result.outcome, OUTCOME_BLOCKED)

    def test_rejects_values_out_of_range(self):
        for bad in [0, -1, MAX_VALIDATION_SAMPLE + 1]:
            with self.subTest(bad=bad):
                result = check_sample_size_change(200, bad, label_count=0)
                self.assertEqual(result.outcome, OUTCOME_INVALID)
                self.assertFalse(result.allowed)

    def test_accepts_the_range_boundaries(self):
        low = check_sample_size_change(200, MIN_VALIDATION_SAMPLE, 0)
        high = check_sample_size_change(200, MAX_VALIDATION_SAMPLE, 0)

        self.assertEqual(low.outcome, OUTCOME_RESAMPLE)
        self.assertEqual(high.outcome, OUTCOME_EXTEND)

    def test_rejects_non_integers(self):
        for bad in ["300", 12.5, None, True]:
            with self.subTest(bad=bad):
                result = check_sample_size_change(200, bad, label_count=0)
                self.assertEqual(result.outcome, OUTCOME_INVALID)


class TestClampValidationSample(unittest.TestCase):
    """Tests for clamp_validation_sample()."""

    def test_passes_through_in_range_values(self):
        self.assertEqual(clamp_validation_sample(200), 200)

    def test_clamps_both_ends(self):
        self.assertEqual(clamp_validation_sample(-5), MIN_VALIDATION_SAMPLE)
        self.assertEqual(
            clamp_validation_sample(99_999), MAX_VALIDATION_SAMPLE
        )


if __name__ == "__main__":
    unittest.main()
