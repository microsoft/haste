"""Rasterize a damage GeoPackage into a single-band classification COG.

This is HASTE's own derived output (predicted building damage), not the source
imagery — so it can be published and rendered in the Planetary Computer Explorer
without redistributing licensed source pixels. See
``spec/features/data-publishing/explorer-visualization.md``.

The encoding is a single ``uint8`` band: ``1`` = damaged, ``0`` = undamaged,
``255`` = nodata (outside every footprint). The damaged/undamaged split reuses
``tile.py``'s ``detect_damage_mask`` so the raster agrees with the collection
thumbnail. Heavy geo deps (rasterio/numpy) are imported lazily inside the render
call to keep them off the module import path.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any, Optional

from .tile import detect_damage_mask

# Single-band uint8 encoding.
UNDAMAGED_VALUE = 0
DAMAGED_VALUE = 1
DAMAGE_CLASS_NODATA = 255

# STAC asset identity for the classification COG (the renderable raster).
DAMAGE_CLASS_ASSET_KEY = "damage_class"
DAMAGE_CLASS_ASSET_TITLE = "Damage classification"
DAMAGE_CLASS_MEDIA_TYPE = (
    "image/tiff; application=geotiff; profile=cloud-optimized"
)

# Discrete colormap the Explorer render option applies (value -> RGBA). Mirrors
# tile.py's palette: undamaged grey (#7f8fa6), damaged red (#ff4d4d).
DAMAGE_CLASS_COLORMAP = {
    UNDAMAGED_VALUE: (127, 143, 166, 255),
    DAMAGED_VALUE: (255, 77, 77, 255),
}


@dataclass(frozen=True)
class DamageRasterResult:
    """Outcome of a successful rasterization (the COG is written to ``path``)."""

    path: str
    width: int
    height: int
    resolution_m: float
    total_buildings: int
    damaged_buildings: int
    coarsened: bool


def rasterize_damage_cog(
    buildings: Any,
    aoi: Any,
    out_path: str,
    *,
    target_meters: float = 0.5,
    max_pixels_per_side: int = 8192,
    logger: Any = None,
) -> Optional[DamageRasterResult]:
    """Rasterize ``buildings`` (classified by damage) into a COG at ``out_path``.

    Returns ``None`` when there is nothing to render (no AOI extent or no
    building geometries); otherwise writes a Cloud-Optimized GeoTIFF and returns
    its dimensions/counts. The grid is a metric UTM projection clipped to the
    AOI bounds; the pixel size starts at ``target_meters`` and is coarsened if
    the AOI would otherwise exceed ``max_pixels_per_side`` on a side.
    """
    import numpy as np
    import rasterio
    import rasterio.shutil
    from rasterio.features import rasterize
    from rasterio.transform import from_origin

    if aoi is None or len(aoi) == 0:
        return None

    # Project both layers to a metric CRS so pixel sizes are in real meters.
    metric_crs = aoi.estimate_utm_crs()
    aoi_m = aoi.to_crs(metric_crs)
    minx, miny, maxx, maxy = (float(v) for v in aoi_m.total_bounds)
    if not (math.isfinite(minx) and math.isfinite(maxx)) or maxx <= minx or maxy <= miny:
        return None

    buildings_m = (
        buildings.to_crs(metric_crs)
        if buildings is not None and len(buildings)
        else None
    )
    if buildings_m is None or len(buildings_m) == 0:
        return None

    # Pick a resolution that keeps the raster within the per-side pixel cap.
    span = max(maxx - minx, maxy - miny)
    resolution = float(target_meters)
    coarsened = False
    if span / resolution > max_pixels_per_side:
        resolution = span / max_pixels_per_side
        coarsened = True
        if logger is not None:
            logger.info(
                "Damage raster coarsened to %.3f m to fit %d px/side cap",
                resolution,
                max_pixels_per_side,
            )
    width = max(1, int(math.ceil((maxx - minx) / resolution)))
    height = max(1, int(math.ceil((maxy - miny) / resolution)))
    transform = from_origin(minx, maxy, resolution, resolution)

    # Damaged wins over undamaged on overlap: burn undamaged first, damaged last.
    damaged_mask = detect_damage_mask(buildings_m)
    geoms = list(buildings_m.geometry.values)
    if damaged_mask is None:
        damaged_flags = [False] * len(geoms)
    else:
        damaged_flags = [bool(v) for v in damaged_mask]
    damaged_count = sum(damaged_flags)

    shapes = [
        (geom, DAMAGED_VALUE if flag else UNDAMAGED_VALUE)
        for flag, geom in sorted(
            zip(damaged_flags, geoms), key=lambda pair: pair[0]
        )
        if geom is not None and not geom.is_empty
    ]
    if not shapes:
        return None

    raster = rasterize(
        shapes,
        out_shape=(height, width),
        transform=transform,
        fill=DAMAGE_CLASS_NODATA,
        default_value=UNDAMAGED_VALUE,
        dtype="uint8",
        all_touched=False,
    ).astype(np.uint8)

    profile = {
        "driver": "GTiff",
        "height": height,
        "width": width,
        "count": 1,
        "dtype": "uint8",
        "crs": metric_crs,
        "transform": transform,
        "nodata": DAMAGE_CLASS_NODATA,
        "tiled": True,
        "blockxsize": 512,
        "blockysize": 512,
        "compress": "deflate",
    }
    # Write a tiled GeoTIFF in memory, then copy to a valid COG on disk (the GDAL
    # COG driver is create-copy only, so it can't be opened for direct write).
    with rasterio.MemoryFile() as memfile:
        with memfile.open(**profile) as tmp:
            tmp.write(raster, 1)
            tmp.write_colormap(1, DAMAGE_CLASS_COLORMAP)
        rasterio.shutil.copy(
            memfile.name,
            out_path,
            driver="COG",
            compress="DEFLATE",
            overview_resampling="nearest",
        )

    return DamageRasterResult(
        path=out_path,
        width=width,
        height=height,
        resolution_m=resolution,
        total_buildings=len(geoms),
        damaged_buildings=damaged_count,
        coarsened=coarsened,
    )
