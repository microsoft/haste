# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License.
import unittest

from hastegeo.core.utils.metadata import matches_metadata_type


class TestMetadataTypeMatching(unittest.TestCase):
    def test_longest_known_metadata_type_wins(self) -> None:
        self.assertTrue(matches_metadata_type("model_123.json", "model"))
        self.assertFalse(
            matches_metadata_type("model_catalog_index.json", "model")
        )
        self.assertTrue(
            matches_metadata_type(
                "partition/model_catalog_index.json", "model_catalog"
            )
        )

    def test_unknown_type_uses_requested_prefix(self) -> None:
        self.assertTrue(matches_metadata_type("custom_123.json", "custom"))
        self.assertFalse(matches_metadata_type("other_123.json", "custom"))


if __name__ == "__main__":
    unittest.main()
