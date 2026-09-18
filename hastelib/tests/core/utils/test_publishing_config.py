"""Assessment caps remain bounded when publishing configuration is incomplete."""

import unittest

from hastegeo.core.config import Config


class TestAssessmentMaxTotalBytes(unittest.TestCase):
    def setUp(self) -> None:
        self.config = Config.__new__(Config)
        self.config.publishing_config = {}

    def test_missing_key_returns_default_without_mutating_config(self) -> None:
        self.assertEqual(
            self.config.get_assessment_max_total_bytes(), 512 * 1024**2
        )
        self.assertEqual(self.config.publishing_config, {})

    def test_configured_positive_integer_is_preserved(self) -> None:
        for value in (1, 1024**3):
            with self.subTest(value=value):
                self.config.publishing_config = {
                    "assessment_max_total_bytes": value
                }
                self.assertEqual(
                    self.config.get_assessment_max_total_bytes(), value
                )

    def test_explicit_invalid_value_is_rejected(self) -> None:
        for value in (None, True, False, 0, -1, "1024", 1024.0):
            with self.subTest(value=value):
                self.config.publishing_config = {
                    "assessment_max_total_bytes": value
                }
                with self.assertRaisesRegex(ValueError, "positive integer"):
                    self.config.get_assessment_max_total_bytes()


if __name__ == "__main__":
    unittest.main()
