# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License.

"""Script for creating visualization of building footprints."""

import argparse
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


def classify(x):
    if x is None or not np.isfinite(x):
        return None
    thresholds = [0.2, 0.4, 0.6, 0.8]
    for i, threshold in enumerate(thresholds):
        if x <= threshold:
            return i
    return len(thresholds)


def main(args):
    """Main function for the output2visualizer.py script."""
    if os.path.realpath(args.output_fn) in {
        os.path.realpath(args.predictions_fn),
        os.path.realpath(args.merged_footprints_fn),
    }:
        raise ValueError("Output must not overwrite an input")
    if os.path.exists(args.output_fn) and not args.overwrite:
        raise FileExistsError(
            f"{args.output_fn} already exists. Use --overwrite to overwrite it."
        )

    with rasterio.open(args.predictions_fn, "r") as src:
        if src.crs is None:
            raise ValueError("Predictions must have a CRS")
        predictions_crs = src.crs
        height, width = src.shape
        transform = src.transform
        # Class zero is invalid, not observed background (which is class 1).
        observed = (src.read_masks(1) != 0) & np.isin(src.read(1), [1, 2, 3])
        profile = {
            "driver": "COG",
            "width": width,
            "height": height,
            "transform": transform,
            "crs": predictions_crs,
            "dtype": "uint8",
            "compress": "LZW",
            "blocksize": 512,
            "overview_resampling": "NEAREST",
            "resampling": "NEAREST",
        }

    with fiona.open(args.merged_footprints_fn, "r") as src:
        if not src.crs:
            raise ValueError("Footprints must have a CRS")
        footprints_crs = rasterio.crs.CRS.from_user_input(src.crs)

    if footprints_crs != predictions_crs:
        raise ValueError("Footprints and predictions must share a CRS")

    ############################################
    # Read predictions within building footprints
    # and track damage values
    ############################################
    shape_vals = []
    with fiona.open(args.merged_footprints_fn) as f:
        for row in f:
            geom = row["geometry"]
            val = classify(row["properties"]["damage_pct_0m"])
            unknown = row["properties"].get("unknown_pct")
            if geom is not None and val is not None and unknown != 1:
                shape_vals.append((geom, val + 1))

    mask = (
        rasterio.features.rasterize(
            shape_vals,
            out_shape=(height, width),
            transform=transform,
            fill=0,
            dtype="uint8",
        )
        if shape_vals
        else np.zeros((height, width), dtype=np.uint8)
    )
    mask[~observed] = 0

    colors = IDX_TO_COLOR[mask]
    colors = colors.transpose(2, 0, 1)

    profile["count"] = 4
    # Alpha carries validity; RGB zero components are legitimate colours.
    profile["nodata"] = None
    profile["BIGTIFF"] = "IF_SAFER"

    with rasterio.open(args.output_fn, "w", **profile) as f:
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
