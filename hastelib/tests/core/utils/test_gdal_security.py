# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License.

"""Tests for hastegeo.core.utils.gdal_security.

The pure-Python helpers (magic-byte sniffing, format/size helpers) run on
any host. The driver-allowlist tests require ``osgeo`` and are skipped
gracefully where GDAL is unavailable (they run in the conda/hatch env or
the Docker test image).
"""

import os
import tempfile
import unittest

from hastegeo.core.utils import gdal_security as g

try:
    from osgeo import gdal, ogr  # noqa: F401

    _HAS_GDAL = True
except ImportError:
    _HAS_GDAL = False


def _write(data: bytes) -> str:
    fd, path = tempfile.mkstemp()
    with os.fdopen(fd, "wb") as fh:
        fh.write(data)
    return path


class TestSniffFileType(unittest.TestCase):
    def setUp(self):
        self._paths = []

    def tearDown(self):
        for p in self._paths:
            try:
                os.remove(p)
            except OSError:
                pass

    def _mk(self, data):
        path = _write(data)
        self._paths.append(path)
        return path

    def test_tiff_little_and_big_endian(self):
        for magic in (b"II*\x00", b"MM\x00*", b"II+\x00", b"MM\x00+"):
            with self.subTest(magic=magic):
                self.assertEqual(
                    g.sniff_file_type(self._mk(magic + b"\x00" * 80)), "tiff"
                )

    def test_png_and_jpeg(self):
        png = b"\x89PNG\r\n\x1a\n" + b"\x00" * 64
        jpeg = b"\xff\xd8\xff\xe0" + b"\x00" * 64
        self.assertEqual(g.sniff_file_type(self._mk(png)), "png")
        self.assertEqual(g.sniff_file_type(self._mk(jpeg)), "jpeg")

    def test_gpkg_vs_plain_sqlite(self):
        base = b"SQLite format 3\x00" + b"\x00" * (68 - 16)
        gpkg = base + b"GPKG"
        gp10 = base + b"GP10"
        sqlite = base + b"\x00\x00\x00\x00"
        self.assertEqual(g.sniff_file_type(self._mk(gpkg)), "gpkg")
        self.assertEqual(g.sniff_file_type(self._mk(gp10)), "gpkg")
        self.assertEqual(g.sniff_file_type(self._mk(sqlite)), "sqlite")

    def test_geojson_and_junk(self):
        self.assertEqual(
            g.sniff_file_type(self._mk(b'   {"type":"FeatureCollection"}')),
            "geojson",
        )
        self.assertIsNone(
            g.sniff_file_type(self._mk(b"\x00\x01\x02\x03garbage"))
        )

    def test_missing_file_returns_none(self):
        self.assertIsNone(g.sniff_file_type("/no/such/file.bin"))


class TestUploadFormatHelpers(unittest.TestCase):
    def test_allowed_formats_normalize(self):
        self.assertEqual(g.assert_allowed_upload_format("GeoTIFF"), "geotiff")
        self.assertEqual(g.assert_allowed_upload_format("  TIF "), "tif")
        self.assertEqual(g.assert_allowed_upload_format("gpkg"), "gpkg")

    def test_disallowed_formats_raise(self):
        for v in ("hdf", "zip", "", "shp", None):
            with self.subTest(v=v):
                with self.assertRaises(ValueError):
                    g.assert_allowed_upload_format(v)

    def test_matches_declared_accepts_matching(self):
        tiff = _write(b"II*\x00" + b"\x00" * 80)
        gpkg = _write(b"SQLite format 3\x00" + b"\x00" * (68 - 16) + b"GPKG")
        try:
            g.assert_matches_declared(tiff, "tif")  # no raise
            g.assert_matches_declared(gpkg, "gpkg")  # no raise
        finally:
            os.remove(tiff)
            os.remove(gpkg)

    def test_matches_declared_rejects_mismatch(self):
        # An HDF4-ish / non-TIFF file declared as tif must be rejected.
        hdf_like = _write(b"\x0e\x03\x13\x01" + b"\x00" * 80)
        gpkg = _write(b"SQLite format 3\x00" + b"\x00" * (68 - 16) + b"GPKG")
        try:
            with self.assertRaises(ValueError):
                g.assert_matches_declared(hdf_like, "tif")
            with self.assertRaises(ValueError):
                g.assert_matches_declared(gpkg, "tif")
        finally:
            os.remove(hdf_like)
            os.remove(gpkg)


class TestSizeEnvHelpers(unittest.TestCase):
    def setUp(self):
        self._saved = {
            k: os.environ.get(k)
            for k in (
                "HASTE_MAX_UPLOAD_BYTES",
                "HASTE_MAX_IMAGERY_DOWNLOAD_BYTES",
            )
        }

    def tearDown(self):
        for k, v in self._saved.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v

    def test_defaults(self):
        os.environ.pop("HASTE_MAX_UPLOAD_BYTES", None)
        os.environ.pop("HASTE_MAX_IMAGERY_DOWNLOAD_BYTES", None)
        self.assertEqual(g.max_upload_bytes(), 5 * 1024**3)
        self.assertEqual(g.max_download_bytes(), 8 * 1024**3)

    def test_override_and_invalid(self):
        os.environ["HASTE_MAX_UPLOAD_BYTES"] = "123"
        self.assertEqual(g.max_upload_bytes(), 123)
        os.environ["HASTE_MAX_UPLOAD_BYTES"] = "not-an-int"
        self.assertEqual(g.max_upload_bytes(), 5 * 1024**3)
        os.environ["HASTE_MAX_UPLOAD_BYTES"] = "-5"
        self.assertEqual(g.max_upload_bytes(), 5 * 1024**3)


@unittest.skipUnless(_HAS_GDAL, "requires osgeo/GDAL")
class TestHardenGdal(unittest.TestCase):
    def test_disables_vulnerable_drivers_keeps_allowlist(self):
        g.harden_gdal(force=True)
        from osgeo import gdal as _gdal
        from osgeo import ogr as _ogr

        # CVE-bearing families must be gone.
        for name in ("HDF4", "HDF4Image", "HDF5", "netCDF"):
            with self.subTest(disabled=name):
                self.assertIsNone(_gdal.GetDriverByName(name))

        # Allowlisted raster drivers remain.
        for name in ("GTiff", "COG", "VRT", "JPEG", "PNG"):
            with self.subTest(kept=name):
                self.assertIsNotNone(_gdal.GetDriverByName(name))

        # Allowlisted vector drivers remain.
        for name in ("GPKG", "GeoJSON"):
            with self.subTest(kept_vector=name):
                self.assertIsNotNone(_ogr.GetDriverByName(name))

    def test_idempotent(self):
        g.harden_gdal(force=True)
        g.harden_gdal()  # second call must not raise or remove allowlisted
        from osgeo import gdal as _gdal

        self.assertIsNotNone(_gdal.GetDriverByName("GTiff"))


if __name__ == "__main__":
    unittest.main()
