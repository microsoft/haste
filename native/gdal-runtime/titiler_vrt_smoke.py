"""Verify rasterio WarpedVRT reprojection with the VRT driver disabled."""

from __future__ import annotations

import tempfile
from pathlib import Path

import haste_gdal_runtime as runtime


def main() -> int:
    manifest = runtime.load_manifest()
    policy = runtime.Policy(
        expected_gdal=manifest["gdal_release"],
        allowed_drivers=frozenset({"GTiff", "COG", "JPEG", "PNG", "MEM"}),
        required_bindings=("rasterio",),
    )
    runtime.configure(policy)
    runtime.secure_startup(policy)

    import numpy as np
    import rasterio
    from osgeo import gdal
    from rasterio.transform import from_origin
    from rasterio.vrt import WarpedVRT

    if gdal.GetDriverByName("VRT") is not None:
        raise RuntimeError(
            "The VRT driver is registered in the TiTiler policy"
        )

    with tempfile.TemporaryDirectory() as temp_dir:
        path = Path(temp_dir) / "source.tif"
        with rasterio.open(
            path,
            "w",
            driver="GTiff",
            width=16,
            height=16,
            count=1,
            dtype="uint8",
            crs="EPSG:4326",
            transform=from_origin(-100, 40, 0.01, 0.01),
        ) as dataset:
            dataset.write(np.ones((1, 16, 16), dtype="uint8"))

        with rasterio.open(path) as source:
            with WarpedVRT(source, crs="EPSG:3857") as warped:
                if not warped.read(1).any():
                    raise RuntimeError("WarpedVRT returned an empty raster")

    print("WarpedVRT reprojection passed with the VRT driver disabled")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
