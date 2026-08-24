# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License.
"""Tests for the canonical source-type key normalizer.

These lock in the Maxar -> Vantor alias that keeps image layers and
catalogued models written before the rename interoperable with ones
written after it.
"""

import unittest

from hastegeo.core.utils.source_types import normalize_source_type


class TestNormalizeSourceType(unittest.TestCase):
    def test_maps_legacy_maxar_to_vantor(self):
        self.assertEqual(normalize_source_type("maxar"), "vantor")

    def test_vantor_is_already_canonical(self):
        self.assertEqual(normalize_source_type("vantor"), "vantor")

    def test_legacy_and_canonical_keys_agree(self):
        # This is the property the model-catalog filter depends on: a
        # legacy layer and a renamed layer must land in the same pool.
        self.assertEqual(
            normalize_source_type("maxar"),
            normalize_source_type("vantor"),
        )

    def test_normalizes_case_and_surrounding_whitespace(self):
        self.assertEqual(normalize_source_type("  MAXAR "), "vantor")
        self.assertEqual(normalize_source_type("Vantor"), "vantor")

    def test_passes_through_unrelated_keys(self):
        for key in ("planet_scope", "planet_skysat", "sentinel_2", "n/a"):
            self.assertEqual(normalize_source_type(key), key)

    def test_does_not_discard_unknown_keys(self):
        self.assertEqual(
            normalize_source_type("some_new_provider"), "some_new_provider"
        )

    def test_non_string_input_passes_through(self):
        self.assertIsNone(normalize_source_type(None))
        self.assertEqual(normalize_source_type(7), 7)


if __name__ == "__main__":
    unittest.main()
