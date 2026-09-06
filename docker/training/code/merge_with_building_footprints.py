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
from hastegeo.core.utils.predictions import read_footprint_ids
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


def score_shape(
    raster: rasterio.io.DatasetReader,
    geometry: shapely.geometry.base.BaseGeometry,
) -> tuple[float | None, float | None]:
    """Score valid pixels only; outside/nodata is unknown, not undamaged.

    Preserve the existing raster class contract: 3 is damaged and 4 is
    unknown. Zero is unlabeled, even when the raster has another nodata
    value. ``filled=False`` also respects its mask and nodata metadata.
    """
    if geometry.is_empty:
        return None, None
    try:
        masked, _ = rasterio.mask.mask(
            raster, [geometry], crop=True, filled=False, indexes=1
        )
    except ValueError as error:
        if "Input shapes do not overlap raster" not in str(error):
            raise
        return None, None
    values = masked.compressed()
    values = values[(values != 0) & np.isfinite(values)]
    if not len(values):
        return None, None
    return float(np.mean(values == 3)), float(np.mean(values == 4))


def main(args: argparse.Namespace) -> None:
    """Write one prediction row for every cached source footprint."""
    if os.path.realpath(args.output_fn) in {
        os.path.realpath(args.footprints_fn),
        os.path.realpath(args.predictions_fn),
    }:
        raise ValueError("Prediction output must not overwrite an input.")
    if os.path.exists(args.output_fn) and not args.overwrite:
        raise FileExistsError(args.output_fn)

    # Validate before creating any output; IDs must agree with layer tiles.
    overture_ids = read_footprint_ids(args.footprints_fn)
    schema = {
        "geometry": "MultiPolygon",
        "properties": {
            "id": "int",
            "overture_id": "str",
            "damage_pct_0m": "float",
            "damage_pct_10m": "float",
            "damage_pct_20m": "float",
            "damaged": "int",
            "unknown_pct": "float",
        },
    }

    scored_damage = []
    with rasterio.open(args.predictions_fn) as raster, fiona.open(
        args.footprints_fn
    ) as footprints:
        if not raster.crs:
            raise ValueError("Prediction raster must declare a CRS.")
        predictions_crs = raster.crs.to_string()
        footprints_crs = footprints.crs.to_string()
        metric_crs = metric_crs_for(predictions_crs, raster.bounds)
        if os.path.exists(args.output_fn):
            fiona.remove(args.output_fn, driver="GPKG")
        with fiona.open(
            args.output_fn,
            "w",
            driver="GPKG",
            crs=predictions_crs,
            schema=schema,
        ) as dst:
            for index, feature in enumerate(tqdm(footprints)):
                geom = feature["geometry"]
                shape = None
                damage, unknown = None, None
                if geom is not None:
                    geom = fiona.transform.transform_geom(
                        footprints_crs, predictions_crs, geom
                    )
                    shape = shapely.geometry.shape(geom)
                    if shape.geom_type == "Polygon":
                        shape = shapely.geometry.MultiPolygon([shape])
                    if shape.geom_type != "MultiPolygon":
                        raise ValueError(
                            "Footprints must be polygon geometries."
                        )
                    damage, unknown = score_shape(raster, shape.buffer(0))
                damages = [damage, None, None]
                # A larger buffer may overlap imagery even when the actual
                # building is unscored. Do not invent scores for that row.
                if damage is not None:
                    scored_damage.append(damage)
                    for slot, distance in enumerate((10, 20), start=1):
                        buffered = buffered_shape(
                            geom, predictions_crs, metric_crs, distance
                        )
                        damages[slot], _ = score_shape(raster, buffered)
                dst.write(
                    {
                        "geometry": (
                            shapely.geometry.mapping(shape)
                            if shape is not None
                            else None
                        ),
                        "properties": {
                            "id": index,
                            "overture_id": overture_ids[index],
                            "damage_pct_0m": damages[0],
                            "damage_pct_10m": damages[1],
                            "damage_pct_20m": damages[2],
                            "damaged": int(damage is not None and damage > 0),
                            "unknown_pct": unknown,
                        },
                    }
                )

    print(f"Output written to {args.output_fn}")
    print(
        f"{len(overture_ids)} source rows; "
        f"{len(overture_ids) - len(scored_damage)} unscored"
    )
    damage_values = np.asarray(scored_damage, dtype=float)
    breakpoints = [0, 0.2, 0.4, 0.6, 0.8, 1.0001]
    for i in range(1, len(breakpoints)):
        count = np.sum(
            (damage_values >= breakpoints[i - 1])
            & (damage_values < breakpoints[i])
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
