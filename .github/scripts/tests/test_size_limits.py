"""Dependency-free tests for operator size configuration."""

import os
from pathlib import Path
import subprocess
import sys
import unittest

SCRIPTS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SCRIPTS))

from resolve_size_limits import DEFAULTS, parse_size, resolve_limits  # noqa: E402


class TestSizeLimits(unittest.TestCase):
    def test_decimal_and_binary_units(self) -> None:
        cases = {
            "30GiB": 30 * 1024**3,
            "30GB": 30 * 1000**3,
            "030GiB": 30 * 1024**3,
            "08GiB": 8 * 1024**3,
            "1 MiB": 1024**2,
            "1t": 1024**4,
            "1_048_576": 1024**2,
            "1,048,576": 1024**2,
            "0001048576": 1024**2,
        }
        for value, expected in cases.items():
            with self.subTest(value=value):
                self.assertEqual(parse_size(value), expected)

    def test_rejects_invalid_and_out_of_range_values(self) -> None:
        for value in (
            "0", "-1", "1048575", "1099511627777", "1.5GiB", "oops",
            "16777217TiB", "18446744073710600192", "1GiB;echo bad",
        ):
            with self.subTest(value=value):
                with self.assertRaises(ValueError):
                    parse_size(value)

    def test_missing_and_blank_values_restore_defaults(self) -> None:
        self.assertEqual(resolve_limits({}), DEFAULTS)
        self.assertEqual(
            resolve_limits(dict.fromkeys(DEFAULTS, "  ")), DEFAULTS
        )

    def test_override_does_not_change_other_defaults(self) -> None:
        self.assertEqual(
            resolve_limits({"HASTE_MAX_UPLOAD_BYTES": "30GiB"}),
            {**DEFAULTS, "HASTE_MAX_UPLOAD_BYTES": 30 * 1024**3},
        )

    def test_invalid_input_emits_no_partial_configuration(self) -> None:
        environment = {**os.environ, **dict.fromkeys(DEFAULTS, "")}
        environment["PUBLISH_ASSESSMENT_MAX_TOTAL_BYTES"] = "invalid"
        result = subprocess.run(
            [sys.executable, str(SCRIPTS / "resolve_size_limits.py")],
            env=environment, capture_output=True, text=True, check=False,
        )
        self.assertEqual(result.returncode, 1)
        self.assertEqual(result.stdout, "")
        self.assertIn("PUBLISH_ASSESSMENT_MAX_TOTAL_BYTES", result.stderr)

    def test_cli_emits_shell_safe_line_endings(self) -> None:
        result = subprocess.run(
            [sys.executable, str(SCRIPTS / "resolve_size_limits.py")],
            env={**os.environ, **dict.fromkeys(DEFAULTS, "")},
            capture_output=True, check=True,
        )
        self.assertNotIn(b"\r", result.stdout)
        self.assertEqual(len(result.stdout.splitlines()), 3)


if __name__ == "__main__":
    unittest.main()