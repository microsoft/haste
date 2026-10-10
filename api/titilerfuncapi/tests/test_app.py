# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License.

"""The tile server exposes one route and never hands GDAL a bad source."""

import os
import tempfile
import unittest
from unittest.mock import patch
from urllib.parse import quote

import numpy
import rasterio
from rasterio.errors import RasterioIOError
from rasterio.transform import from_origin
from starlette.testclient import TestClient

from api.titilerfuncapi import app as titiler_app
from api.titilerfuncapi.app.gdal_config import (
    GDAL_HARDENING,
    apply_gdal_hardening,
)

TILE = "/cog/tiles/WebMercatorQuad/15/23971/13734"


def _write_geotiff(path):
    with rasterio.open(
        path,
        "w",
        driver="GTiff",
        width=16,
        height=16,
        count=1,
        dtype="uint8",
        crs="EPSG:4326",
        transform=from_origin(85.0, 28.0, 0.001, 0.001),
    ) as dst:
        dst.write(numpy.ones((1, 16, 16), dtype="uint8"))


class TestRoutes(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(titiler_app.app)

    def test_only_tile_routes_are_registered(self):
        paths = sorted(r.path for r in titiler_app.cog.router.routes)
        self.assertEqual(
            paths,
            [
                "/tiles/{tileMatrixSetId}/{z}/{x}/{y}",
                "/tiles/{tileMatrixSetId}/{z}/{x}/{y}.{format}",
                "/tiles/{tileMatrixSetId}/{z}/{x}/{y}@{scale}x",
                "/tiles/{tileMatrixSetId}/{z}/{x}/{y}@{scale}x.{format}",
            ],
        )

    def test_everything_else_is_not_found(self):
        url = quote("https://data.source.coop/a.tif", safe="")
        for path in (
            "/",
            "/docs",
            "/redoc",
            "/openapi.json",
            "/api",
            f"/cog/info?url={url}",
            f"/cog/statistics?url={url}",
            f"/cog/preview.png?url={url}",
            f"/cog/bbox/0,0,1,1.tif?url={url}",
            f"/cog/point/0,0?url={url}",
            f"/cog/WebMercatorQuad/tilejson.json?url={url}",
            f"/cog/WebMercatorQuad/map?url={url}",
            "/cog/validate",
            "/cog/viewer",
            f"/stac/info?url={url}",
            f"/mosaicjson/info?url={url}",
            "/tileMatrixSets",
        ):
            with self.subTest(path=path):
                self.assertEqual(self.client.get(path).status_code, 404)

    def test_health_check(self):
        self.assertEqual(self.client.get("/healthz").status_code, 200)

    def test_rejected_url_never_reaches_rasterio(self):
        with patch.object(titiler_app.rasterio, "open") as opened:
            for url in (
                '<VRTDataset rasterXSize="1" rasterYSize="1"/>',
                "/proc/self/environ",
                "/vsicurl/http://169.254.169.254/metadata",
                "https://evil.blob.core.windows.net/c/a.tif",
            ):
                with self.subTest(url=url):
                    response = self.client.get(
                        f"{TILE}?url={quote(url, safe='')}"
                    )
                    self.assertEqual(response.status_code, 400)
                    self.assertNotIn("VRTDataset", response.text)
            opened.assert_not_called()

    def test_redirecting_source_is_rejected(self):
        url = "https://data.source.coop/a.tif"
        with patch.object(
            titiler_app.destination_checker,
            "check",
            side_effect=titiler_app.DatasetUrlError("dataset url redirects"),
        ), patch.object(titiler_app.rasterio, "open") as opened:
            response = self.client.get(f"{TILE}?url={quote(url, safe='')}")
        self.assertEqual(response.status_code, 400)
        opened.assert_not_called()

    def test_only_web_mercator_is_served(self):
        url = quote("https://data.source.coop/a.tif", safe="")
        with patch.object(titiler_app.destination_checker, "check"):
            response = self.client.get(
                f"/cog/tiles/WGS1984Quad/1/0/0?url={url}"
            )
        self.assertEqual(response.status_code, 422)


class TestGeoTIFFReader(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)

    def test_reads_geotiff(self):
        path = os.path.join(self.tmp.name, "ok.tif")
        _write_geotiff(path)
        with titiler_app.GeoTIFFReader(path) as src:
            self.assertEqual(src.dataset.driver, "GTiff")

    def test_refuses_vrt_content_even_with_tif_name(self):
        target = os.path.join(self.tmp.name, "target.tif")
        _write_geotiff(target)
        disguised = os.path.join(self.tmp.name, "innocent.tif")
        with open(disguised, "w") as fh:
            fh.write(
                '<VRTDataset rasterXSize="16" rasterYSize="16">'
                '<VRTRasterBand dataType="Byte" band="1"><SimpleSource>'
                f'<SourceFilename relativeToVRT="0">{target}</SourceFilename>'
                "<SourceBand>1</SourceBand></SimpleSource></VRTRasterBand>"
                "</VRTDataset>"
            )
        # Sanity: plain GDAL would happily open it as a VRT.
        with rasterio.open(disguised) as plain:
            self.assertEqual(plain.driver, "VRT")
        with self.assertRaises(RasterioIOError):
            titiler_app.GeoTIFFReader(disguised)


class TestGdalHardening(unittest.TestCase):
    def test_forces_values_and_drops_relaxing_settings(self):
        environ = {
            "GDAL_VRT_ENABLE_PYTHON": "YES",
            "GDAL_VRT_RAWRASTERBAND_ALLOWED_SOURCE": "ALL",
            "GDAL_HTTP_HEADER_FILE": "/home/site/headers",
            "UNRELATED": "kept",
        }
        apply_gdal_hardening(environ)
        for name, value in GDAL_HARDENING.items():
            self.assertEqual(environ[name], value)
        self.assertNotIn("GDAL_VRT_RAWRASTERBAND_ALLOWED_SOURCE", environ)
        self.assertNotIn("GDAL_HTTP_HEADER_FILE", environ)
        self.assertEqual(environ["UNRELATED"], "kept")

    def test_applied_at_import(self):
        for name, value in GDAL_HARDENING.items():
            self.assertEqual(os.environ.get(name), value)

    def test_tile_requests_run_with_hardened_gdal_env(self):
        self.assertEqual(
            titiler_app.cog.environment_dependency(), GDAL_HARDENING
        )


if __name__ == "__main__":
    unittest.main()
