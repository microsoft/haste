# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License.

"""Tests for Overture Maps dynamic release resolution in footprints.py."""

import unittest
from unittest.mock import MagicMock, patch

from bda.footprints import FALLBACK_RELEASE, _dataset_path, get_latest_release


class TestGetLatestRelease(unittest.TestCase):
    """Tests for get_latest_release()."""

    def setUp(self):
        # Clear the lru_cache before each test so mocks take effect
        get_latest_release.cache_clear()

    def tearDown(self):
        get_latest_release.cache_clear()

    @patch("bda.footprints.fsspec.filesystem")
    def test_returns_latest_release(self, mock_filesystem):
        """Should return the most recent release by lexicographic sort."""
        mock_fs = MagicMock()
        mock_fs.ls.return_value = [
            "release/2025-03-01.0",
            "release/2025-06-15.0",
            "release/2026-01-10.0",
            "release/2026-02-18.0",
        ]
        mock_filesystem.return_value = mock_fs

        result = get_latest_release()

        self.assertEqual(result, "2026-02-18.0")
        mock_filesystem.assert_called_once_with(
            "az", account_name="overturemapswestus2", anon=True
        )
        mock_fs.ls.assert_called_once_with("release/")

    @patch("bda.footprints.fsspec.filesystem")
    def test_returns_latest_when_unordered(self, mock_filesystem):
        """Should sort correctly even if blob listing is unordered."""
        mock_fs = MagicMock()
        mock_fs.ls.return_value = [
            "release/2026-02-18.0",
            "release/2025-03-01.0",
            "release/2026-06-01.0",
            "release/2025-12-15.1",
        ]
        mock_filesystem.return_value = mock_fs

        result = get_latest_release()

        self.assertEqual(result, "2026-06-01.0")

    @patch("bda.footprints.fsspec.filesystem")
    def test_filters_invalid_entries(self, mock_filesystem):
        """Should ignore entries that don't match the release name pattern."""
        mock_fs = MagicMock()
        mock_fs.ls.return_value = [
            "release/2025-06-15.0",
            "release/readme.txt",
            "release/.metadata",
            "release/2026-02-18.0",
        ]
        mock_filesystem.return_value = mock_fs

        result = get_latest_release()

        self.assertEqual(result, "2026-02-18.0")

    @patch("bda.footprints.fsspec.filesystem")
    def test_fallback_on_empty_listing(self, mock_filesystem):
        """Should return FALLBACK_RELEASE when no valid releases are found."""
        mock_fs = MagicMock()
        mock_fs.ls.return_value = []
        mock_filesystem.return_value = mock_fs

        result = get_latest_release()

        self.assertEqual(result, FALLBACK_RELEASE)

    @patch("bda.footprints.fsspec.filesystem")
    def test_fallback_on_exception(self, mock_filesystem):
        """Should return FALLBACK_RELEASE when blob listing raises."""
        mock_filesystem.side_effect = Exception("Network error")

        result = get_latest_release()

        self.assertEqual(result, FALLBACK_RELEASE)

    @patch("bda.footprints.fsspec.filesystem")
    def test_handles_trailing_slashes(self, mock_filesystem):
        """Should handle entries with trailing slashes from blob listing."""
        mock_fs = MagicMock()
        mock_fs.ls.return_value = [
            "release/2025-06-15.0/",
            "release/2026-02-18.0/",
        ]
        mock_filesystem.return_value = mock_fs

        result = get_latest_release()

        self.assertEqual(result, "2026-02-18.0")


class TestDatasetPath(unittest.TestCase):
    """Tests for _dataset_path()."""

    def setUp(self):
        get_latest_release.cache_clear()

    def tearDown(self):
        get_latest_release.cache_clear()

    def test_explicit_release(self):
        """Should use the explicitly provided release version."""
        path = _dataset_path("building", release="2025-01-01.0")
        self.assertEqual(
            path, "release/2025-01-01.0/theme=buildings/type=building/"
        )

    @patch("bda.footprints.fsspec.filesystem")
    def test_dynamic_release(self, mock_filesystem):
        """Should resolve version dynamically when release is None."""
        mock_fs = MagicMock()
        mock_fs.ls.return_value = [
            "release/2026-03-01.0",
            "release/2026-06-15.0",
        ]
        mock_filesystem.return_value = mock_fs

        path = _dataset_path("building")

        self.assertEqual(
            path, "release/2026-06-15.0/theme=buildings/type=building/"
        )

    def test_all_type_theme_mappings(self):
        """Every type in type_theme_map should produce a valid path."""
        from bda.footprints import type_theme_map

        for overture_type, theme in type_theme_map.items():
            path = _dataset_path(overture_type, release="2026-01-01.0")
            self.assertEqual(
                path,
                f"release/2026-01-01.0/theme={theme}/type={overture_type}/",
            )


if __name__ == "__main__":
    unittest.main()
