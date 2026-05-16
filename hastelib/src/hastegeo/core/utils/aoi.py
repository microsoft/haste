# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License.

"""Helpers for deriving an area-of-interest polygon from a GeoTIFF.

Used by the imageryprep workflow to produce the bounding polygon that the
Overture Maps building-footprint download is filtered by. Originally lived
as the standalone script ``docker/training/code/extract_data_mask_from_geotiff.py``
in the inference workflow; lifted here so the imageryprep workflow can
generate footprints once per image layer.
"""

from __future__ import annotations

import logging
from typing import Optional, Tuple

import numpy as np
import rasterio
import rasterio.features
import shapely.geometry

logger = logging.getLogger(__name__)


def extract_aoi_polygon(
    cog_path: str,
    *,
    simplify_tolerance_meters: float = 10.0,
) -> shapely.geometry.Polygon:
    """Extract the largest valid-data polygon from a GeoTIFF, in EPSG:4326.

    The valid-data mask is built from pixels that are non-zero in any band
    (matching the original ``extract_data_mask_from_geotiff.py`` semantics).
    When multiple disconnected valid regions exist, the largest by area is
    chosen. The exterior ring is simplified by approximately
    ``simplify_tolerance_meters`` meters and any interior holes are dropped.

    The returned polygon is in EPSG:4326 regardless of the input CRS.

    Args:
        cog_path: Path to a readable GeoTIFF (typically the post-event mosaic).
        simplify_tolerance_meters: Douglas-Peucker tolerance applied to the
            exterior ring before reprojection. Defaults to 10 m.

    Returns:
        ``shapely.geometry.Polygon`` of the largest valid-data region in
        EPSG:4326.

    Raises:
        ValueError: If no valid-data region can be derived.
    """
    import fiona.transform

    with rasterio.open(cog_path) as f:
        data = f.read()
        transform = f.transform
        crs = f.crs.to_string()

    num_channels, _, _ = data.shape
    mask = ((data == 0).sum(axis=0) != num_channels).astype(np.uint8)

    features = list(rasterio.features.shapes(mask, transform=transform))

    geoms = []
    areas = []
    for geom, val in features:
        if val == 1:
            shape = shapely.geometry.shape(geom)
            areas.append(shape.area)
            geoms.append(geom)

    if not geoms:
        raise ValueError(
            f"No valid-data regions found in {cog_path} (mask is all zero)."
        )

    if len(geoms) > 1:
        logger.warning(
            "Found %d valid-data regions in %s; choosing largest by area.",
            len(geoms),
            cog_path,
        )
        max_area = max(areas)
        geom = next(g for g, a in zip(geoms, areas) if a == max_area)
    else:
        geom = geoms[0]

    shape = shapely.geometry.shape(geom)
    # Drop any holes — we only want the outer footprint
    exterior_shape = shapely.geometry.Polygon(list(shape.exterior.coords))

    if crs == "EPSG:4326":
        # 1 degree lat ≈ 111,139 m
        simplified = exterior_shape.simplify(
            simplify_tolerance_meters / 111_139.0
        )
        return simplified

    simplified = exterior_shape.simplify(simplify_tolerance_meters)
    geom_4326 = fiona.transform.transform_geom(
        crs, "EPSG:4326", shapely.geometry.mapping(simplified)
    )
    return shapely.geometry.shape(geom_4326)


def aoi_bbox_from_cog(
    cog_path: str,
) -> Tuple[float, float, float, float]:
    """Return the EPSG:4326 bounding box of the AOI polygon as (xmin, ymin, xmax, ymax)."""
    polygon = extract_aoi_polygon(cog_path)
    return polygon.bounds
