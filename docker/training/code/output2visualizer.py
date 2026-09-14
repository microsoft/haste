# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License.

"""Script for creating visualization of building footprints."""

import argparse
import math
import os

import fiona
import numpy as np
import rasterio
import rasterio.enums
import rasterio.features

IDX_TO_COLOR = np.array(
    [
        [0, 0, 0, 0],
        [255, 255, 255, 255],
        [252, 190, 165, 255],
        [251, 112, 80, 255],
        [211, 32, 32, 255],
        [103, 0, 13, 255],
    ],
    dtype=np.uint8,
)


def set_up_parser() -> argparse.ArgumentParser:
    """Set up the argument parser."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--merged_footprints_fn",
        type=str,
        required=True,
        help="Path to the footprint file",
    )
    parser.add_argument(
        "--predictions_fn",
        type=str,
        required=True,
        help="Path to the prediction file",
    )
    parser.add_argument(
        "--output_fn", type=str, required=True, help="Path to the output file"
    )
    parser.add_argument(
        "--overwrite",
        action="store_true",
        help="Overwrite the output file if it exists",
    )

    return parser


def classify(x: float) -> int:
    thresholds = [0.2, 0.4, 0.6, 0.8]
    for i, threshold in enumerate(thresholds):
        if x <= threshold:
            return i
    return len(thresholds)


def main(args: argparse.Namespace) -> None:
    """Main function for the output2visualizer.py script."""
    if os.path.exists(args.output_fn) and not args.overwrite:
        raise FileExistsError(
            f"{args.output_fn} already exists. Use --overwrite to overwrite it."
        )

    with rasterio.open(args.predictions_fn, "r") as src:
        if not src.crs:
            raise ValueError("Prediction raster must declare a CRS.")
        predictions_crs = src.crs
        height, width = src.shape
        transform = src.transform

    ############################################
    # Read predictions within building footprints
    # and track damage values
    ############################################
    shape_vals = []
    with fiona.open(args.merged_footprints_fn) as f:
        if not f.crs:
            raise ValueError("Prediction GeoPackage must declare a CRS.")
        if rasterio.crs.CRS.from_wkt(f.crs_wkt) != predictions_crs:
            raise ValueError("Prediction raster and GeoPackage CRS differ.")
        for row in f:
            geom = row["geometry"]
            damage = row["properties"]["damage_pct_0m"]
            unknown = row["properties"]["unknown_pct"]
            if (
                geom is None
                or damage is None
                or unknown is None
                or not math.isfinite(damage)
                or not math.isfinite(unknown)
                or unknown > 0
            ):
                continue
            val = classify(damage) + 1
            shape_vals.append((geom, val))

    # rasterize([]) raises; an empty or entirely unscored run is a valid
    # transparent result, not a reason to drop rows or fabricate predictions.
    mask = np.zeros((height, width), dtype=np.uint8)
    if shape_vals:
        rasterio.features.rasterize(
            shape_vals, out=mask, transform=transform, fill=0
        )

    colors = IDX_TO_COLOR[mask]
    colors = colors.transpose(2, 0, 1)

    with rasterio.open(
        args.output_fn,
        "w",
        driver="COG",
        crs=predictions_crs,
        transform=transform,
        height=height,
        width=width,
        count=4,
        dtype="uint8",
        nodata=0,
        compress="LZW",
        blocksize=512,
        overview_resampling="nearest",
        BIGTIFF="IF_SAFER",
    ) as f:
        f.colorinterp = [
            rasterio.enums.ColorInterp.red,
            rasterio.enums.ColorInterp.green,
            rasterio.enums.ColorInterp.blue,
            rasterio.enums.ColorInterp.alpha,
        ]
        f.write(colors)


if __name__ == "__main__":
    # GDAL CVE compensating control (docs/known-vulnerabilities.md Root
    # Cause C): restrict GDAL drivers in-process. The GDAL_SKIP env in the
    # training image also covers this; soft-fail if hastegeo is absent.
    try:
        from hastegeo.core.utils.gdal_security import harden_gdal

        harden_gdal()
    except Exception:
        pass
    parser = set_up_parser()
    args = parser.parse_args()
    main(args)
