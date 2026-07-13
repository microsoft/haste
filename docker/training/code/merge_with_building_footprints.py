# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License.

"""Script for merging building footprints with damage predictions."""

import argparse
import os

import fiona
import fiona.transform
import numpy as np
import pyproj
import rasterio
import rasterio.mask
import shapely.geometry
from tqdm import tqdm


def metric_crs_for(predictions_crs: str, raster_bounds) -> str:
    """Return a metre-based CRS suitable for buffering in ``predictions_crs``.

    Buffer distances in this script are expressed in **metres**, but
    ``shapely.buffer`` operates in the geometry's own coordinate units. So
    the CRS we buffer in matters:

    * If ``predictions_crs`` is *projected* (UTM / Web Mercator, units of
      metres) we return it unchanged and buffering happens directly.
    * If ``predictions_crs`` is *geographic* (e.g. EPSG:4326, units of
      degrees) buffering by a metre value would be nonsensical
      (``buffer(10)`` would be ~10 degrees ~= 1100 km), so we estimate a
      local UTM CRS from the raster's centre and buffer in that instead.

    This mirrors the ``estimate_utm_crs`` convention used elsewhere in the
    codebase (see ``hastegeo.core.utils.assessment._building_areas_m2``).

    ``raster_bounds`` is a ``(left, bottom, right, top)`` tuple expressed in
    ``predictions_crs``.
    """
    crs = pyproj.CRS.from_user_input(predictions_crs)
    if not crs.is_geographic:
        # Already metric — buffer distances in metres are correct as-is.
        return predictions_crs

    left, bottom, right, top = raster_bounds
    center_lon = (left + right) / 2.0
    center_lat = (bottom + top) / 2.0
    # Standard UTM zone from the AOI centre. Northern hemisphere zones are
    # EPSG:326xx, southern EPSG:327xx.
    zone = int((center_lon + 180) / 6) + 1
    epsg = (32600 if center_lat >= 0 else 32700) + zone
    return f"EPSG:{epsg}"


def buffered_shape(
    building_geom,
    predictions_crs: str,
    metric_crs: str,
    buffer_m: float,
) -> "shapely.geometry.base.BaseGeometry":
    """Buffer ``building_geom`` by ``buffer_m`` metres, in ``predictions_crs``.

    ``building_geom`` is a GeoJSON-like mapping already expressed in
    ``predictions_crs``. The returned shapely geometry is also in
    ``predictions_crs`` so it can be handed straight to
    ``rasterio.mask.mask`` (which requires the mask geometry to share the
    raster's CRS).

    When ``metric_crs`` differs from ``predictions_crs`` (i.e. the raster is
    geographic and ``buffer_m`` is non-zero) we round-trip the geometry
    through the metric CRS: project to metres, buffer, then project back to
    ``predictions_crs``. This is what makes the buffer distance metrically
    correct regardless of the raster's CRS.
    """
    # ``buffer(0)`` is unit-independent (it just cleans the geometry), and
    # for a projected raster ``metric_crs`` equals ``predictions_crs``. In
    # both cases we can buffer directly without a reprojection round-trip.
    if buffer_m == 0 or metric_crs == predictions_crs:
        return shapely.geometry.shape(building_geom).buffer(buffer_m)

    geom_metric = fiona.transform.transform_geom(
        predictions_crs, metric_crs, building_geom
    )
    buffered = shapely.geometry.shape(geom_metric).buffer(buffer_m)
    buffered_back = fiona.transform.transform_geom(
        metric_crs, predictions_crs, shapely.geometry.mapping(buffered)
    )
    return shapely.geometry.shape(buffered_back)


def set_up_parser() -> argparse.ArgumentParser:
    """Set up the argument parser."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--footprints_fn",
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
        help="Overwrite existing files",
    )

    return parser


def main(args):
    """Main function for the merge_with_building_footprints.py script."""
    with rasterio.open(args.predictions_fn, "r") as src:
        predictions_crs = src.crs.to_string()

    with fiona.open(args.footprints_fn, "r") as src:
        footprints_crs = src.crs.to_string()

    # Clip building footprints to image data mask
    projected_building_geoms = []
    valid_building_geoms = []
    with fiona.open(args.footprints_fn) as f:
        for row in tqdm(f):
            projected_geom = fiona.transform.transform_geom(
                footprints_crs, predictions_crs, row["geometry"]
            )
            projected_building_geoms.append(projected_geom)

    ############################################
    # Read predictions within building footprints
    # and track damage values
    ############################################
    damage_vals_per_geom = []
    unknown_val_per_geom = []
    print(f"Reading predictions from {args.predictions_fn}")
    with rasterio.open(args.predictions_fn) as f:
        # Buffer distances below are in METRES. shapely buffers in the
        # geometry's own units, so for a geographic prediction CRS
        # (e.g. EPSG:4326, degrees) we buffer in an estimated metric UTM
        # CRS and transform back; for a projected CRS we buffer directly.
        # Compute the metric CRS once here (not per geometry) — the loop
        # below can run over many thousands of footprints.
        metric_crs = metric_crs_for(predictions_crs, f.bounds)
        # Compute the fraction of damage per geometry and buffer size option
        for building_geom in tqdm(projected_building_geoms):
            skip_geom = False
            t_dmg_vals = []
            for buffer in [0, 10, 20]:
                building_shape = buffered_shape(
                    building_geom, predictions_crs, metric_crs, buffer
                )
                try:
                    building_mask, transform = rasterio.mask.mask(
                        f, [building_shape], crop=True, nodata=0, filled=True
                    )
                except ValueError:
                    # If the geometry is outside the raster bounds, we skip it.
                    # This typically happens because overture bounds are not cropped off as a straight line
                    # and can end up downloading buildings outside the prediction bounds
                    print(
                        f"WARNING: Geometry {building_geom} is outside the raster bounds, skipping."
                    )
                    skip_geom = True
                    break
                vals, counts = np.unique(building_mask, return_counts=True)
                val_counts = dict(zip(vals, counts))
                N = 0
                for k, v in val_counts.items():
                    if k != 0:
                        N += v

                if 3 in val_counts:
                    fraction_damaged = min(val_counts[3] / N, 1)
                else:
                    fraction_damaged = 0
                t_dmg_vals.append(fraction_damaged)

            if not skip_geom:
                valid_building_geoms.append(building_geom)
                damage_vals_per_geom.append(t_dmg_vals)

        print(f"Incoming Projected Geoms = {len(projected_building_geoms)} ")
        print(f"Valid Building Geoms = {len(valid_building_geoms)} ")
        print(f"Damage vals calculated for {len(damage_vals_per_geom)} geoms")

        # Compute the fraction of unknown (cloud covered) pixels per geometry
        for building_geom in tqdm(valid_building_geoms):
            # No buffering here (buffer 0 == the geometry itself), so this
            # masks the footprint directly in ``predictions_crs`` and needs
            # no metric-CRS round-trip.
            building_shape = shapely.geometry.shape(building_geom)

            building_mask, transform = rasterio.mask.mask(
                f, [building_shape], crop=True, nodata=0, filled=True
            )
            vals, counts = np.unique(building_mask, return_counts=True)
            val_counts = dict(zip(vals, counts))

            N = 0
            for k, v in val_counts.items():
                if k != 0:
                    N += v

            if 4 in val_counts:
                fraction_unknown = val_counts[4] / N
            else:
                fraction_unknown = 0
            unknown_val_per_geom.append(fraction_unknown)

        print(f"Unknown vals calculated for {len(unknown_val_per_geom)} geoms")

    ############################################
    # Write damage values to file
    ############################################
    schema = {
        "geometry": "MultiPolygon",
        "properties": {
            "id": "int",
            "damage_pct_0m": "float",
            "damage_pct_10m": "float",
            "damage_pct_20m": "float",
            "damaged": "int",
            "unknown_pct": "float",
        },
    }

    if os.path.exists(args.output_fn):
        os.remove(args.output_fn)

    with fiona.open(
        args.output_fn, "w", driver="GPKG", crs=predictions_crs, schema=schema
    ) as f:
        for i, geom in enumerate(tqdm(valid_building_geoms)):
            shape = shapely.geometry.shape(geom)
            if geom["type"] == "Polygon":
                geom = shapely.geometry.mapping(
                    shapely.geometry.MultiPolygon([shape])
                )

            row = {
                "type": "Feature",
                "geometry": geom,
                "properties": {
                    "id": i,
                    "damage_pct_0m": damage_vals_per_geom[i][0],
                    "damage_pct_10m": damage_vals_per_geom[i][1],
                    "damage_pct_20m": damage_vals_per_geom[i][2],
                    "damaged": 1 if damage_vals_per_geom[i][0] > 0 else 0,
                    "unknown_pct": unknown_val_per_geom[i],
                },
            }
            f.write(row)

    print(f"Output written to {args.output_fn}")
    damage_vals_per_geom = np.array(damage_vals_per_geom)
    breakpoints = [0, 0.2, 0.4, 0.6, 0.8, 1.0001]
    for i in range(1, len(breakpoints)):
        count = np.sum(
            (damage_vals_per_geom[:, 0] >= breakpoints[i - 1])
            & (damage_vals_per_geom[:, 0] < breakpoints[i])
        )
        print(
            f"- {count} buildings with damage fraction between {breakpoints[i-1]*100:0.0f}% and {breakpoints[i]*100:0.0f}%"
        )


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
