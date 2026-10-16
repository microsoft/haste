"""Exercise the GDAL-linked bindings against their shared native runtime."""

from __future__ import annotations

import json
import os
import shutil
import ssl
import subprocess
import tempfile
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

import haste_gdal_runtime as runtime
import numpy as np

EXPECTED_GDAL = "3.13.3"
EXPECTED_PROJ = "9.8.1"
EXPECTED_BINDINGS = {
    "osgeo.gdal": "3.13.3",
    "rasterio": "1.4.4",
    "fiona": "1.10.1",
    "pyogrio": "0.13.0",
    "pyproj": "3.7.2",
}
ALLOWED_DRIVERS = frozenset(
    {
        "COG",
        "ESRIJSON",
        "GPKG",
        "GTiff",
        "GeoJSON",
        "GeoJSONSeq",
        "JPEG",
        "MEM",
        "PNG",
        "SQLite",
        "TopoJSON",
        "VRT",
    }
)


def _create_test_certificate(directory: Path) -> tuple[Path, Path]:
    openssl = shutil.which("openssl")
    if openssl is None:
        raise RuntimeError(
            "openssl is required for the HTTPS /vsicurl smoke test"
        )
    certificate = directory / "localhost.crt"
    private_key = directory / "localhost.key"
    subprocess.run(
        [
            openssl,
            "req",
            "-x509",
            "-newkey",
            "rsa:2048",
            "-nodes",
            "-days",
            "1",
            "-keyout",
            str(private_key),
            "-out",
            str(certificate),
            "-subj",
            "/CN=127.0.0.1",
            "-addext",
            "subjectAltName=IP:127.0.0.1",
        ],
        check=True,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
    )
    return certificate, private_key


def _https_server(
    raster_path: Path, certificate: Path, private_key: Path
) -> tuple[ThreadingHTTPServer, threading.Thread]:
    content = raster_path.read_bytes()

    class RangeHandler(BaseHTTPRequestHandler):
        def do_HEAD(self) -> None:
            self.send_response(200)
            self.send_header("Content-Length", str(len(content)))
            self.send_header("Accept-Ranges", "bytes")
            self.end_headers()

        def do_GET(self) -> None:
            range_header = self.headers.get("Range")
            if range_header:
                unit, _, bounds = range_header.partition("=")
                if unit != "bytes":
                    self.send_error(400)
                    return
                start_text, _, end_text = bounds.partition("-")
                start = int(start_text)
                end = min(
                    int(end_text) if end_text else len(content) - 1,
                    len(content) - 1,
                )
                if start < 0 or start > end:
                    self.send_error(416)
                    return
                payload = content[start : end + 1]
                self.send_response(206)
                self.send_header(
                    "Content-Range",
                    f"bytes {start}-{end}/{len(content)}",
                )
            else:
                payload = content
                self.send_response(200)
            self.send_header("Content-Length", str(len(payload)))
            self.send_header("Accept-Ranges", "bytes")
            self.end_headers()
            self.wfile.write(payload)

        def log_message(self, format_string: str, *args: Any) -> None:
            return

    server = ThreadingHTTPServer(("127.0.0.1", 0), RangeHandler)
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    context.load_cert_chain(certificate, private_key)
    server.socket = context.wrap_socket(server.socket, server_side=True)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server, thread


def _smoke_bindings(directory: Path) -> None:
    import fiona
    import pyogrio
    import pyproj
    import rasterio
    from osgeo import gdal, ogr
    from rasterio.shutil import copy as copy_raster
    from rasterio.transform import from_origin
    from rasterio.vrt import WarpedVRT

    binding_policy = runtime.Policy(
        expected_gdal=EXPECTED_GDAL,
        allowed_drivers=ALLOWED_DRIVERS,
        required_bindings=runtime.BINDINGS,
    )
    report = runtime.secure_startup(binding_policy)
    for binding, expected_version in EXPECTED_BINDINGS.items():
        actual_version = report["bindings"][binding]["version"].split("+")[0]
        if actual_version != expected_version:
            raise RuntimeError(
                f"{binding} is {actual_version}, expected {expected_version}"
            )
    actual_proj = report["bindings"]["pyproj"]["proj"]
    if actual_proj != EXPECTED_PROJ:
        raise RuntimeError(
            f"pyproj reports PROJ {actual_proj}, expected {EXPECTED_PROJ}"
        )

    first = directory / "first.tif"
    second = directory / "second.tif"
    profile = {
        "driver": "GTiff",
        "width": 2,
        "height": 2,
        "count": 1,
        "dtype": "uint8",
        "crs": "EPSG:4326",
    }
    first_pixels = np.array([[1, 2], [3, 4]], dtype=np.uint8)
    second_pixels = np.array([[5, 6], [7, 8]], dtype=np.uint8)
    for path, pixels, x_offset in (
        (first, first_pixels, 0),
        (second, second_pixels, 2),
    ):
        with rasterio.open(
            path,
            "w",
            **profile,
            transform=from_origin(x_offset, 2, 1, 1),
        ) as dataset:
            dataset.write(pixels, 1)
        with rasterio.open(path) as dataset:
            if not np.array_equal(dataset.read(1), pixels):
                raise RuntimeError(
                    f"rasterio round trip failed for {path.name}"
                )
            if dataset.crs.to_epsg() != 4326:
                raise RuntimeError(f"unexpected CRS for {path.name}")

    cog_path = directory / "first-cog.tif"
    with rasterio.open(first) as source:
        copy_raster(
            source,
            cog_path,
            driver="COG",
            compress="ZSTD",
        )
    with rasterio.open(cog_path) as dataset:
        if not np.array_equal(dataset.read(1), first_pixels):
            raise RuntimeError("rasterio COG copy changed raster pixels")
    cog = gdal.Open(str(cog_path), gdal.GA_ReadOnly)
    if (
        cog is None
        or cog.GetMetadata("IMAGE_STRUCTURE").get("LAYOUT") != "COG"
    ):
        raise RuntimeError("GDAL did not recognize the output as a COG")
    cog = None

    vrt_path = directory / "mosaic.vrt"
    vrt_dataset = gdal.BuildVRT(str(vrt_path), [str(first), str(second)])
    if vrt_dataset is None:
        raise RuntimeError("GDAL BuildVRT failed")
    vrt_dataset.FlushCache()
    vrt_dataset = None
    with rasterio.open(vrt_path) as dataset:
        expected_pixels = np.concatenate((first_pixels, second_pixels), axis=1)
        if dataset.width != 4 or dataset.height != 2:
            raise RuntimeError("VRT mosaic has unexpected dimensions")
        if not np.array_equal(dataset.read(1), expected_pixels):
            raise RuntimeError("VRT mosaic pixels differ from source pixels")

    gdal_source = gdal.Open(str(first), gdal.GA_ReadOnly)
    if gdal_source is None:
        raise RuntimeError("osgeo.gdal could not open the rasterio GeoTIFF")
    warped_path = directory / "warped.tif"
    warped = gdal.Warp(str(warped_path), gdal_source, dstSRS="EPSG:3857")
    if warped is None:
        raise RuntimeError("GDAL Warp reprojection failed")
    warped.FlushCache()
    warped = None
    gdal_source = None
    with rasterio.open(warped_path) as dataset:
        if dataset.crs.to_epsg() != 3857 or dataset.width == 0:
            raise RuntimeError(
                "GDAL Warp produced an invalid reprojected raster"
            )

    with rasterio.open(first) as source:
        with WarpedVRT(source, crs="EPSG:3857") as warped_vrt:
            if warped_vrt.crs.to_epsg() != 3857:
                raise RuntimeError("rasterio WarpedVRT reprojection failed")
            if warped_vrt.read(1).size == 0:
                raise RuntimeError("rasterio WarpedVRT returned no pixels")

    fiona_path = directory / "fiona.gpkg"
    schema = {"geometry": "Point", "properties": {"name": "str"}}
    feature = {
        "geometry": {"type": "Point", "coordinates": (1.0, 2.0)},
        "properties": {"name": "fiona"},
    }
    with fiona.open(
        fiona_path,
        "w",
        driver="GPKG",
        layer="fiona_features",
        schema=schema,
        crs="EPSG:4326",
    ) as destination:
        destination.write(feature)
    with fiona.open(fiona_path, layer="fiona_features") as source:
        if len(source) != 1 or source.crs.to_epsg() != 4326:
            raise RuntimeError("Fiona GeoPackage write/read failed")

    ogr_geometry = ogr.CreateGeometryFromJson(json.dumps(feature["geometry"]))
    if ogr_geometry is None:
        raise RuntimeError("OGR could not create the test point geometry")
    pyogrio_path = directory / "pyogrio.geojson"
    geometry_wkb = bytes(ogr_geometry.ExportToWkb())
    pyogrio.raw.write(
        pyogrio_path,
        np.array([geometry_wkb], dtype=object),
        [np.array(["pyogrio"], dtype=object)],
        ["name"],
        layer="pyogrio_features",
        driver="GeoJSON",
        geometry_type="Point",
        crs=pyproj.CRS.from_epsg(4326).to_wkt(),
    )
    metadata, _, geometries, fields = pyogrio.raw.read(
        pyogrio_path,
        layer="pyogrio_features",
    )
    if metadata["geometry_type"] != "Point":
        raise RuntimeError("Pyogrio did not report the expected GeoJSON type")
    if len(geometries) != 1 or fields[0][0] != "pyogrio":
        raise RuntimeError("Pyogrio GeoJSON write/read failed")
    with fiona.open(pyogrio_path) as source:
        if len(source) != 1 or source[0]["properties"]["name"] != "pyogrio":
            raise RuntimeError("Fiona could not read Pyogrio GeoJSON output")

    transformer = pyproj.Transformer.from_crs(
        "EPSG:4326", "EPSG:3857", always_xy=True
    )
    projected_x, projected_y = transformer.transform(1.0, 2.0)
    if not (111000 < projected_x < 112000 and 222000 < projected_y < 223000):
        raise RuntimeError(
            "pyproj returned an unexpected projected coordinate"
        )

    certificate, private_key = _create_test_certificate(directory)
    server, thread = _https_server(first, certificate, private_key)
    try:
        url = f"/vsicurl/https://127.0.0.1:{server.server_port}/first.tif"
        previous_curl_bundle = os.environ.get("CURL_CA_BUNDLE")
        previous_ssl_cert = os.environ.get("SSL_CERT_FILE")
        previous_no_proxy = os.environ.get("NO_PROXY")
        previous_no_proxy_lower = os.environ.get("no_proxy")
        previous_curl_config = gdal.GetConfigOption("CURL_CA_BUNDLE")
        previous_ssl_config = gdal.GetConfigOption("SSL_CERT_FILE")
        os.environ["CURL_CA_BUNDLE"] = str(certificate)
        os.environ["SSL_CERT_FILE"] = str(certificate)
        os.environ["NO_PROXY"] = "127.0.0.1,localhost"
        os.environ["no_proxy"] = "127.0.0.1,localhost"
        gdal.SetConfigOption("CURL_CA_BUNDLE", str(certificate))
        gdal.SetConfigOption("SSL_CERT_FILE", str(certificate))
        try:
            network_dataset = gdal.Open(url, gdal.GA_ReadOnly)
            if network_dataset is None:
                raise RuntimeError("GDAL /vsicurl/ HTTPS read failed")
            if network_dataset.ReadAsArray().tolist() != first_pixels.tolist():
                raise RuntimeError("GDAL /vsicurl/ pixels differ from source")
            network_dataset = None
        finally:
            if previous_curl_bundle is None:
                os.environ.pop("CURL_CA_BUNDLE", None)
            else:
                os.environ["CURL_CA_BUNDLE"] = previous_curl_bundle
            if previous_ssl_cert is None:
                os.environ.pop("SSL_CERT_FILE", None)
            else:
                os.environ["SSL_CERT_FILE"] = previous_ssl_cert
            if previous_no_proxy is None:
                os.environ.pop("NO_PROXY", None)
            else:
                os.environ["NO_PROXY"] = previous_no_proxy
            if previous_no_proxy_lower is None:
                os.environ.pop("no_proxy", None)
            else:
                os.environ["no_proxy"] = previous_no_proxy_lower
            gdal.SetConfigOption("CURL_CA_BUNDLE", previous_curl_config)
            gdal.SetConfigOption("SSL_CERT_FILE", previous_ssl_config)
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)

    print(
        "Binding workflow smoke passed: rasterio, fiona, pyogrio, pyproj, "
        "GDAL Warp/BuildVRT/WarpedVRT and HTTPS /vsicurl/"
    )


def main() -> int:
    runtime.configure()
    with tempfile.TemporaryDirectory(prefix="haste-gdal-smoke-") as temp_dir:
        _smoke_bindings(Path(temp_dir))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
