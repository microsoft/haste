# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License.

"""Tests for hastegeo.core.utils.footprints.

Originally lived in docker/training/code/bda/test_footprints.py; relocated
here when the Overture Maps client moved into hastegeo so the imageryprep
workflow could share it.
"""

import unittest
from unittest.mock import MagicMock, patch

from hastegeo.core.utils.footprints import (
    FALLBACK_RELEASE,
    _dataset_path,
    get_latest_release,
)


class TestGetLatestRelease(unittest.TestCase):
    """Tests for get_latest_release()."""

    def setUp(self):
        # Clear the lru_cache before each test so mocks take effect
        get_latest_release.cache_clear()

    def tearDown(self):
        get_latest_release.cache_clear()

    @patch("hastegeo.core.utils.footprints.fsspec.filesystem")
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

    @patch("hastegeo.core.utils.footprints.fsspec.filesystem")
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

    @patch("hastegeo.core.utils.footprints.fsspec.filesystem")
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

    @patch("hastegeo.core.utils.footprints.fsspec.filesystem")
    def test_fallback_on_empty_listing(self, mock_filesystem):
        """Should return FALLBACK_RELEASE when no valid releases are found."""
        mock_fs = MagicMock()
        mock_fs.ls.return_value = []
        mock_filesystem.return_value = mock_fs

        result = get_latest_release()

        self.assertEqual(result, FALLBACK_RELEASE)

    @patch("hastegeo.core.utils.footprints.fsspec.filesystem")
    def test_fallback_on_exception(self, mock_filesystem):
        """Should return FALLBACK_RELEASE when blob listing raises."""
        mock_filesystem.side_effect = Exception("Network error")

        result = get_latest_release()

        self.assertEqual(result, FALLBACK_RELEASE)

    @patch("hastegeo.core.utils.footprints.fsspec.filesystem")
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

    @patch("hastegeo.core.utils.footprints.fsspec.filesystem")
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
        from hastegeo.core.utils.footprints import type_theme_map

        for overture_type, theme in type_theme_map.items():
            path = _dataset_path(overture_type, release="2026-01-01.0")
            self.assertEqual(
                path,
                f"release/2026-01-01.0/theme={theme}/type={overture_type}/",
            )


class TestDownloadBuildingFootprints(unittest.TestCase):
    """Tests for download_building_footprints()."""

    def test_rejects_non_gpkg_output_path(self):
        from hastegeo.core.utils.footprints import download_building_footprints

        with self.assertRaises(ValueError):
            download_building_footprints(
                bbox=(0, 0, 1, 1),
                output_path="/tmp/foo.geojson",
            )

    @patch("hastegeo.core.utils.footprints.geodataframe")
    def test_filters_to_polygons_and_writes(self, mock_geodataframe):
        """The downloader should restrict to (id, geometry, subtype, class)
        and Polygon/MultiPolygon rows, set EPSG:4326, and write a .gpkg."""
        import os
        import tempfile

        # Build a tiny geodataframe stand-in. We just need the chained
        # operations to look like the real ones — patching geopandas
        # internals would couple too tightly.
        from unittest.mock import MagicMock

        gdf = MagicMock()
        # gdf[["id", "geometry", "subtype", "class"]] -> filtered_gdf
        filtered = MagicMock()
        gdf.__getitem__.side_effect = (
            lambda key: filtered if isinstance(key, list) else gdf
        )
        # filtered[mask] returns final gdf with .shape / .set_crs / .to_file
        final = MagicMock()
        final.shape = (3, 4)
        filtered.geometry.geom_type.isin.return_value = [True, True, True]
        filtered.__getitem__.return_value = final
        mock_geodataframe.return_value = gdf

        from hastegeo.core.utils.footprints import download_building_footprints

        with tempfile.TemporaryDirectory() as tmp:
            output = os.path.join(tmp, "out.gpkg")
            count = download_building_footprints(
                bbox=(-156.7, 20.87, -156.66, 20.89),
                output_path=output,
            )

        self.assertEqual(count, 3)
        mock_geodataframe.assert_called_once_with(
            "building", (-156.7, 20.87, -156.66, 20.89)
        )
        gdf.__getitem__.assert_called_with(
            ["id", "geometry", "subtype", "class"]
        )
        final.set_crs.assert_called_once_with(epsg=4326, inplace=True)
        final.to_file.assert_called_once_with(output, driver="GPKG")

    @patch("hastegeo.core.utils.footprints.geodataframe")
    def test_aoi_polygon_filters_buildings_outside_mask(
        self, mock_geodataframe
    ):
        """When aoi_polygon is provided, footprints not intersecting the
        polygon are dropped. This is the core fix for the bbox-cornered
        nodata problem: the Overture query is bbox-only, so without this
        filter buildings in the unflown corners of a tilted image come
        through unfiltered."""
        import os
        import tempfile

        import geopandas as gpd
        import shapely.geometry
        from hastegeo.core.utils.footprints import download_building_footprints

        # Three buildings: two inside the AOI strip, one in the
        # bbox-corner outside the AOI. The AOI is a narrow rectangle on
        # the west side of the bbox.
        bbox = (0.0, 0.0, 10.0, 10.0)
        aoi = shapely.geometry.box(0.0, 0.0, 5.0, 10.0)
        gdf = gpd.GeoDataFrame(
            {
                "id": ["in-1", "in-2", "out-1"],
                "subtype": ["", "", ""],
                "class": ["", "", ""],
                "geometry": [
                    shapely.geometry.box(1.0, 1.0, 1.5, 1.5),
                    shapely.geometry.box(4.0, 4.0, 4.5, 4.5),
                    shapely.geometry.box(7.0, 7.0, 7.5, 7.5),
                ],
            },
            crs="EPSG:4326",
        )
        mock_geodataframe.return_value = gdf

        with tempfile.TemporaryDirectory() as tmp:
            output = os.path.join(tmp, "out.gpkg")
            count = download_building_footprints(
                bbox=bbox,
                output_path=output,
                aoi_polygon=aoi,
            )
            self.assertEqual(count, 2)
            # Read the gpkg back and verify only the inside buildings
            # survived — the out-1 corner building must have been
            # dropped by the polygon filter.
            written = gpd.read_file(output)
            self.assertEqual(set(written["id"]), {"in-1", "in-2"})

    @patch("hastegeo.core.utils.footprints.geodataframe")
    def test_aoi_polygon_clips_straddling_buildings_at_boundary(
        self, mock_geodataframe
    ):
        """A footprint straddling the AOI boundary is geometrically
        clipped at the edge (sliced), matching the
        clip_and_normalize_user_footprints semantics so both paths
        produce structurally-equivalent GPKGs."""
        import os
        import tempfile

        import geopandas as gpd
        import shapely.geometry
        from hastegeo.core.utils.footprints import download_building_footprints

        aoi = shapely.geometry.box(0.0, 0.0, 5.0, 10.0)
        # Building spans 4 → 6: half inside, half outside.
        gdf = gpd.GeoDataFrame(
            {
                "id": ["straddler"],
                "subtype": [""],
                "class": [""],
                "geometry": [shapely.geometry.box(4.0, 4.0, 6.0, 6.0)],
            },
            crs="EPSG:4326",
        )
        mock_geodataframe.return_value = gdf

        with tempfile.TemporaryDirectory() as tmp:
            output = os.path.join(tmp, "out.gpkg")
            count = download_building_footprints(
                bbox=(0.0, 0.0, 10.0, 10.0),
                output_path=output,
                aoi_polygon=aoi,
            )
            self.assertEqual(count, 1)
            written = gpd.read_file(output)
            # Geometry was sliced at the AOI boundary x=5.
            bounds = list(written.geometry.iloc[0].bounds)
            self.assertEqual(bounds, [4.0, 4.0, 5.0, 6.0])


class TestClipAndNormalizeUserFootprints(unittest.TestCase):
    """Tests for clip_and_normalize_user_footprints().

    Uses small in-memory GeoDataFrames written to temporary .gpkg files
    to exercise the real geopandas/fiona/shapely path. We deliberately
    avoid mocking these so we catch issues with CRS handling, geometry
    repair, clipping, and the .gpkg roundtrip — the failure modes most
    likely to surprise users supplying ad-hoc inputs."""

    @classmethod
    def setUpClass(cls):
        try:
            import geopandas  # noqa: F401
            import shapely  # noqa: F401
        except ImportError as e:  # pragma: no cover - env without GIS
            raise unittest.SkipTest(f"geopandas/shapely not available: {e}")

    def _aoi(self):
        import shapely.geometry

        return shapely.geometry.Polygon(
            [(0, 0), (10, 0), (10, 10), (0, 10), (0, 0)]
        )

    def _write_input(self, dst_dir, gdf, name="in.gpkg"):
        import os

        path = os.path.join(dst_dir, name)
        gdf.to_file(path, driver="GPKG")
        return path

    def test_happy_path_preserves_overlapping_polygons(self):
        import os
        import tempfile

        import geopandas as gpd
        import shapely.geometry
        from hastegeo.core.utils.footprints import (
            clip_and_normalize_user_footprints,
        )

        inside = shapely.geometry.box(2, 2, 3, 3)
        partial = shapely.geometry.box(8, 8, 12, 12)
        outside = shapely.geometry.box(20, 20, 21, 21)
        gdf = gpd.GeoDataFrame(
            {
                "id": ["a", "b", "c"],
                "subtype": ["residential", "commercial", "residential"],
                "class": ["house", "office", "house"],
                "geometry": [inside, partial, outside],
            },
            crs="EPSG:4326",
        )

        with tempfile.TemporaryDirectory() as tmp:
            input_path = self._write_input(tmp, gdf)
            output_path = os.path.join(tmp, "out.gpkg")
            count = clip_and_normalize_user_footprints(
                input_path, self._aoi(), output_path
            )

            self.assertEqual(count, 2)
            out = gpd.read_file(output_path)
            self.assertEqual(len(out), 2)
            self.assertEqual(out.crs.to_epsg(), 4326)
            self.assertEqual(
                set(out.columns), {"id", "geometry", "subtype", "class"}
            )

    def test_reprojects_from_web_mercator(self):
        import os
        import tempfile

        import geopandas as gpd
        import shapely.geometry
        from hastegeo.core.utils.footprints import (
            clip_and_normalize_user_footprints,
        )

        # Build a polygon in 4326 around (0.001, 0.001) so it falls inside
        # our AOI box (0,0)-(10,10), then project to Web Mercator before
        # writing so the helper has to call to_crs.
        small_4326 = shapely.geometry.box(0.001, 0.001, 0.002, 0.002)
        gdf_4326 = gpd.GeoDataFrame(
            {"id": ["a"], "geometry": [small_4326]}, crs="EPSG:4326"
        )
        gdf_3857 = gdf_4326.to_crs(epsg=3857)

        with tempfile.TemporaryDirectory() as tmp:
            input_path = self._write_input(tmp, gdf_3857)
            output_path = os.path.join(tmp, "out.gpkg")
            count = clip_and_normalize_user_footprints(
                input_path, self._aoi(), output_path
            )

            self.assertEqual(count, 1)
            out = gpd.read_file(output_path)
            self.assertEqual(out.crs.to_epsg(), 4326)
            # Geometry should be close to the original 4326 box, not the
            # huge mercator coords.
            self.assertLess(out.geometry.iloc[0].bounds[2], 1.0)

    def test_synthesizes_missing_id_subtype_class(self):
        import os
        import tempfile

        import geopandas as gpd
        import shapely.geometry
        from hastegeo.core.utils.footprints import (
            clip_and_normalize_user_footprints,
        )

        polys = [
            shapely.geometry.box(1, 1, 2, 2),
            shapely.geometry.box(3, 3, 4, 4),
        ]
        gdf = gpd.GeoDataFrame(
            {"geometry": polys}, crs="EPSG:4326"
        )  # no id/subtype/class

        with tempfile.TemporaryDirectory() as tmp:
            input_path = self._write_input(tmp, gdf)
            output_path = os.path.join(tmp, "out.gpkg")
            count = clip_and_normalize_user_footprints(
                input_path, self._aoi(), output_path
            )

            self.assertEqual(count, 2)
            out = gpd.read_file(output_path)
            # id synthesized from row index, others present but null
            self.assertEqual(
                sorted(out["id"].astype(str).tolist()), ["0", "1"]
            )
            self.assertTrue(out["subtype"].isna().all())
            self.assertTrue(out["class"].isna().all())

    def test_normalizes_int_ids_to_string(self):
        """User GPKGs with integer id columns (common in GIS data) must
        be cast to string on write. Without this the downstream join
        in GetValidationReport / GetAssessmentReport fails universally:
        labels_dict has string keys (JSON object keys are always
        strings on the wire), but a fiona-read int-id GPKG produces
        an int-keyed lookup table → matched == 0 even when labels are
        in the inference set."""
        import os
        import tempfile

        import fiona
        import geopandas as gpd
        import shapely.geometry
        from hastegeo.core.utils.footprints import (
            clip_and_normalize_user_footprints,
        )

        # User-supplied GPKG with integer building IDs
        gdf = gpd.GeoDataFrame(
            {
                "id": [101, 202, 303],
                "geometry": [
                    shapely.geometry.box(1, 1, 2, 2),
                    shapely.geometry.box(3, 3, 4, 4),
                    shapely.geometry.box(5, 5, 6, 6),
                ],
                "subtype": [None] * 3,
                "class": [None] * 3,
            },
            crs="EPSG:4326",
        )

        with tempfile.TemporaryDirectory() as tmp:
            input_path = self._write_input(tmp, gdf)
            output_path = os.path.join(tmp, "out.gpkg")
            count = clip_and_normalize_user_footprints(
                input_path, self._aoi(), output_path
            )
            self.assertEqual(count, 3)

            # Values preserved
            out = gpd.read_file(output_path)
            self.assertEqual(sorted(out["id"].tolist()), ["101", "202", "303"])

            # Critical: the on-disk type is string, so fiona reads it
            # back as string — matches what the JSON object-key path
            # used by the validation labels produces.
            with fiona.open(output_path) as src:
                ids = [feat["properties"]["id"] for feat in src]
            self.assertTrue(
                all(isinstance(v, str) for v in ids),
                f"Expected all str ids, got types: "
                f"{[type(v).__name__ for v in ids]}",
            )

    def test_drops_non_polygon_features(self):
        import os
        import tempfile

        import geopandas as gpd
        import shapely.geometry
        from hastegeo.core.utils.footprints import (
            clip_and_normalize_user_footprints,
        )

        gdf = gpd.GeoDataFrame(
            {
                "id": ["p", "ln", "pt"],
                "geometry": [
                    shapely.geometry.box(1, 1, 2, 2),
                    shapely.geometry.LineString([(3, 3), (4, 4)]),
                    shapely.geometry.Point(5, 5),
                ],
            },
            crs="EPSG:4326",
        )

        with tempfile.TemporaryDirectory() as tmp:
            # GPKG doesn't accept heterogeneous geometries; write each
            # feature to its own GeoJSON and merge them back into a GPKG.
            paths = []
            for i, row in gdf.iterrows():
                p = os.path.join(tmp, f"row_{i}.geojson")
                gpd.GeoDataFrame(
                    [row], crs=gdf.crs, geometry="geometry"
                ).to_file(p, driver="GeoJSON")
                paths.append(p)
            combined = gpd.GeoDataFrame(
                gpd.pd.concat(
                    [gpd.read_file(p) for p in paths], ignore_index=True
                ),
                crs="EPSG:4326",
            )
            input_gpkg = os.path.join(tmp, "mixed.gpkg")
            combined.to_file(input_gpkg, driver="GPKG")
            output_path = os.path.join(tmp, "out.gpkg")

            count = clip_and_normalize_user_footprints(
                input_gpkg, self._aoi(), output_path
            )

            # Only the polygon survives the polygon-only filter.
            self.assertEqual(count, 1)
            out = gpd.read_file(output_path)
            self.assertTrue(
                out.geometry.geom_type.isin(["Polygon", "MultiPolygon"]).all()
            )

    def test_fully_outside_aoi_raises(self):
        import os
        import tempfile

        import geopandas as gpd
        import shapely.geometry
        from hastegeo.core.utils.footprints import (
            clip_and_normalize_user_footprints,
        )

        far = shapely.geometry.box(100, 100, 101, 101)
        gdf = gpd.GeoDataFrame(
            {"id": ["x"], "geometry": [far]}, crs="EPSG:4326"
        )

        with tempfile.TemporaryDirectory() as tmp:
            input_path = self._write_input(tmp, gdf)
            output_path = os.path.join(tmp, "out.gpkg")
            with self.assertRaises(ValueError):
                clip_and_normalize_user_footprints(
                    input_path, self._aoi(), output_path
                )

    def test_no_polygons_raises(self):
        import os
        import tempfile

        import geopandas as gpd
        import shapely.geometry
        from hastegeo.core.utils.footprints import (
            clip_and_normalize_user_footprints,
        )

        gdf = gpd.GeoDataFrame(
            {
                "id": ["a", "b"],
                "geometry": [
                    shapely.geometry.LineString([(1, 1), (2, 2)]),
                    shapely.geometry.LineString([(3, 3), (4, 4)]),
                ],
            },
            crs="EPSG:4326",
        )

        with tempfile.TemporaryDirectory() as tmp:
            input_path = os.path.join(tmp, "in.gpkg")
            gdf.to_file(input_path, driver="GPKG")
            output_path = os.path.join(tmp, "out.gpkg")
            with self.assertRaises(ValueError) as cm:
                clip_and_normalize_user_footprints(
                    input_path, self._aoi(), output_path
                )
            self.assertIn("Polygon", str(cm.exception))

    def test_missing_crs_raises(self):
        """The helper must reject inputs without a CRS rather than silently
        treating them as 4326. Stripping CRS from a read-back GeoJSON is
        unreliable across drivers, so we patch :func:`geopandas.read_file`
        to return a CRS-less GeoDataFrame directly."""
        import os
        import tempfile
        from unittest.mock import patch

        import geopandas as gpd
        import shapely.geometry
        from hastegeo.core.utils.footprints import (
            clip_and_normalize_user_footprints,
        )

        nocrs = gpd.GeoDataFrame(
            {
                "id": ["a"],
                "geometry": [shapely.geometry.box(1, 1, 2, 2)],
            },
            crs=None,
        )

        with tempfile.TemporaryDirectory() as tmp:
            input_path = os.path.join(tmp, "in.gpkg")
            # Just touch the input path so the helper's existence check
            # (if any) doesn't fire; the read is mocked.
            with open(input_path, "wb"):
                pass
            output_path = os.path.join(tmp, "out.gpkg")
            with patch(
                "hastegeo.core.utils.footprints.gpd.read_file",
                return_value=nocrs,
            ):
                with self.assertRaises(ValueError) as cm:
                    clip_and_normalize_user_footprints(
                        input_path, self._aoi(), output_path
                    )
            self.assertIn("CRS", str(cm.exception))

    def test_overwrite_false_rejects_existing_output(self):
        import os
        import tempfile

        import geopandas as gpd
        import shapely.geometry
        from hastegeo.core.utils.footprints import (
            clip_and_normalize_user_footprints,
        )

        gdf = gpd.GeoDataFrame(
            {
                "id": ["a"],
                "geometry": [shapely.geometry.box(1, 1, 2, 2)],
            },
            crs="EPSG:4326",
        )
        with tempfile.TemporaryDirectory() as tmp:
            input_path = self._write_input(tmp, gdf)
            output_path = os.path.join(tmp, "out.gpkg")
            with open(output_path, "w") as f:
                f.write("existing")
            with self.assertRaises(FileExistsError):
                clip_and_normalize_user_footprints(
                    input_path, self._aoi(), output_path
                )

    def test_overwrite_true_replaces_existing_output(self):
        import os
        import tempfile

        import geopandas as gpd
        import shapely.geometry
        from hastegeo.core.utils.footprints import (
            clip_and_normalize_user_footprints,
        )

        gdf = gpd.GeoDataFrame(
            {
                "id": ["a"],
                "geometry": [shapely.geometry.box(1, 1, 2, 2)],
            },
            crs="EPSG:4326",
        )
        with tempfile.TemporaryDirectory() as tmp:
            input_path = self._write_input(tmp, gdf)
            output_path = os.path.join(tmp, "out.gpkg")
            with open(output_path, "w") as f:
                f.write("existing")
            count = clip_and_normalize_user_footprints(
                input_path, self._aoi(), output_path, overwrite=True
            )
            self.assertEqual(count, 1)

    def test_rejects_non_gpkg_output_path(self):
        from hastegeo.core.utils.footprints import (
            clip_and_normalize_user_footprints,
        )

        with self.assertRaises(ValueError):
            clip_and_normalize_user_footprints(
                "/tmp/in.gpkg",
                self._aoi(),
                "/tmp/out.geojson",
            )


if __name__ == "__main__":
    unittest.main()
