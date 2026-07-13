# Copyright (c) 2024 Overture Maps
# Licensed under the MIT License.
# Code from: https://github.com/OvertureMaps/overturemaps-py/blob/0fad53bceb955b14ac069ef321cbc2486996d5c7/overturemaps/core.py
# Modified to read from Azure Blob Storage instead of S3

"""Overture Maps client + a high-level building-footprint downloader.

This module is the single source of truth for fetching building footprints
inside HASTE. It is consumed by both the imageryprep workflow (where
footprints are cached per image layer) and historically by the inference
workflow (now slated to consume the cached gpkg).
"""

from __future__ import annotations

import logging
import os
import re
from functools import lru_cache
from typing import List, Optional, Tuple

import fsspec
import geopandas as gpd
import pyarrow as pa
import pyarrow.compute as pc
import pyarrow.dataset as ds
import pyarrow.fs as fs
from geopandas import GeoDataFrame

from .gdal_security import harden_gdal

logger = logging.getLogger(__name__)

# Harden GDAL/OGR drivers before any geopandas/fiona read of a
# user-supplied vector file (GDAL CVE compensating control —
# docs/known-vulnerabilities.md Root Cause C).
harden_gdal()

OVERTURE_ACCOUNT_NAME = "overturemapswestus2"
FALLBACK_RELEASE = "2026-02-18.0"
# Matches Overture release names like "2026-02-18.0"
_RELEASE_PATTERN = re.compile(r"^\d{4}-\d{2}-\d{2}\.\d+$")


type_theme_map = {
    "address": "addresses",
    "bathymetry": "base",
    "building": "buildings",
    "building_part": "buildings",
    "division": "divisions",
    "division_area": "divisions",
    "division_boundary": "divisions",
    "place": "places",
    "segment": "transportation",
    "connector": "transportation",
    "infrastructure": "base",
    "land": "base",
    "land_cover": "base",
    "land_use": "base",
    "water": "base",
}


# Expected output schema for a building-footprints GeoPackage. Downstream
# consumers (merge_with_building_footprints, GetBuildingFootprintsGeoJSON,
# the building-validation UI) tolerate missing ``subtype``/``class`` but
# always read by column name, so we synthesize a sentinel when the
# user-supplied input lacks them. Shared between the Overture path
# (download_building_footprints) and the user-supplied path
# (clip_and_normalize_user_footprints) so the two produce identical
# schemas.
_FOOTPRINT_OUTPUT_COLUMNS = ("id", "geometry", "subtype", "class")


def get_all_overture_types() -> List[str]:
    return list(type_theme_map.keys())


def record_batch_reader(
    overture_type, bbox=None
) -> Optional[pa.RecordBatchReader]:
    """Return a pyarrow RecordBatchReader for the desired bounding box and Azure path."""
    path = _dataset_path(overture_type)

    if bbox:
        xmin, ymin, xmax, ymax = bbox
        filter = (
            (pc.field("bbox", "xmin") < xmax)
            & (pc.field("bbox", "xmax") > xmin)
            & (pc.field("bbox", "ymin") < ymax)
            & (pc.field("bbox", "ymax") > ymin)
        )
    else:
        filter = None

    # Temporarily clear Azure storage env vars to prevent adlfs from using
    # local Azurite config when connecting to public Overture Maps blob storage
    saved_conn_str = os.environ.pop("AZURE_STORAGE_CONNECTION_STRING", None)
    saved_account = os.environ.pop("AZURE_STORAGE_ACCOUNT", None)

    try:
        t_fs = fsspec.filesystem(
            "az", account_name=OVERTURE_ACCOUNT_NAME, anon=True
        )
        pa_fs = fs.PyFileSystem(fs.FSSpecHandler(t_fs))

        dataset = ds.dataset(path, filesystem=pa_fs)
    finally:
        if saved_conn_str:
            os.environ["AZURE_STORAGE_CONNECTION_STRING"] = saved_conn_str
        if saved_account:
            os.environ["AZURE_STORAGE_ACCOUNT"] = saved_account

    batches = dataset.to_batches(filter=filter)

    # to_batches() can yield many empty batches; downstream consumers like
    # ParquetWriter emit a row group per batch which bloats output files.
    non_empty_batches = (b for b in batches if b.num_rows > 0)

    geoarrow_schema = geoarrow_schema_adapter(dataset.schema)
    return pa.RecordBatchReader.from_batches(
        geoarrow_schema, non_empty_batches
    )


def geodataframe(
    overture_type: str, bbox: Tuple[float, float, float, float] = None
) -> GeoDataFrame:
    """Loads geoparquet for specified type into a geopandas dataframe.

    Args:
        overture_type: type to load (e.g. "building").
        bbox: optional bounding box (xmin, ymin, xmax, ymax) in EPSG:4326.

    Returns:
        GeoDataFrame with the optionally filtered theme data.
    """
    reader = record_batch_reader(overture_type, bbox)
    return gpd.GeoDataFrame.from_arrow(reader)


def geoarrow_schema_adapter(schema: pa.Schema) -> pa.Schema:
    """Convert a geoarrow-compatible schema to a proper geoarrow schema.

    Assumes there is a single ``geometry`` column with WKB formatting.
    """
    geometry_field_index = schema.get_field_index("geometry")
    geometry_field = schema.field(geometry_field_index)
    geoarrow_geometry_field = geometry_field.with_metadata(
        {b"ARROW:extension:name": b"geoarrow.wkb"}
    )
    return schema.set(geometry_field_index, geoarrow_geometry_field)


@lru_cache(maxsize=1)
def get_latest_release() -> str:
    """Discover the latest Overture Maps release from Azure Blob Storage.

    Lists the ``release/`` prefixes in the overturemapswestus2 container and
    returns the most recent version string (lexicographic sort works because
    release names follow the ``YYYY-MM-DD.N`` convention).

    Falls back to ``FALLBACK_RELEASE`` if the listing fails or returns no
    valid release names.
    """
    saved_conn_str = os.environ.pop("AZURE_STORAGE_CONNECTION_STRING", None)
    saved_account = os.environ.pop("AZURE_STORAGE_ACCOUNT", None)

    try:
        t_fs = fsspec.filesystem(
            "az", account_name=OVERTURE_ACCOUNT_NAME, anon=True
        )
        entries = t_fs.ls("release/")
        release_names = [
            entry.rstrip("/").split("/")[-1]
            for entry in entries
            if _RELEASE_PATTERN.match(entry.rstrip("/").split("/")[-1])
        ]
        if not release_names:
            logger.warning(
                "No valid Overture releases found, falling back to %s",
                FALLBACK_RELEASE,
            )
            return FALLBACK_RELEASE

        release_names.sort(reverse=True)
        latest = release_names[0]
        logger.info("Resolved latest Overture Maps release: %s", latest)
        return latest
    except Exception:
        logger.warning(
            "Failed to list Overture releases, falling back to %s",
            FALLBACK_RELEASE,
            exc_info=True,
        )
        return FALLBACK_RELEASE
    finally:
        if saved_conn_str:
            os.environ["AZURE_STORAGE_CONNECTION_STRING"] = saved_conn_str
        if saved_account:
            os.environ["AZURE_STORAGE_ACCOUNT"] = saved_account


def _dataset_path(overture_type: str, release: str = None) -> str:
    """Returns the Azure blob path of the Overture dataset to use."""
    if release is None:
        release = get_latest_release()
    theme = type_theme_map[overture_type]
    return f"release/{release}/theme={theme}/type={overture_type}/"


def download_building_footprints(
    bbox: Tuple[float, float, float, float],
    output_path: str,
    *,
    overwrite: bool = False,
    aoi_polygon=None,
) -> int:
    """Download Overture Maps building footprints for an AOI to a GeoPackage.

    The output gpkg contains only Polygon/MultiPolygon features in EPSG:4326
    with columns ``id``, ``geometry``, ``subtype``, ``class`` (the columns
    HASTE's downstream merge step expects).

    Args:
        bbox: AOI bounding box (xmin, ymin, xmax, ymax) in EPSG:4326. The
            bbox alone is the only filter Overture supports server-side,
            so this still gates how much data is pulled.
        output_path: Destination ``.gpkg`` filename.
        overwrite: If False and the file already exists, raise FileExistsError.
        aoi_polygon: Optional shapely geometry in EPSG:4326. If provided,
            footprints are geometrically clipped to the polygon: anything
            fully outside is dropped, and footprints that straddle the
            AOI boundary are sliced at the edge. This matches the
            user-supplied-footprints path (``clip_and_normalize_user_footprints``)
            so the two routes produce structurally-equivalent GPKGs.

    Returns:
        Number of features written.
    """
    if not output_path.endswith(".gpkg"):
        raise ValueError("output_path must end with .gpkg")
    if os.path.exists(output_path):
        if not overwrite:
            raise FileExistsError(
                f"Output file '{output_path}' already exists "
                "(pass overwrite=True to replace)."
            )
        os.remove(output_path)

    footprints = geodataframe("building", bbox)
    footprints = footprints[list(_FOOTPRINT_OUTPUT_COLUMNS)]
    footprints = footprints[
        footprints.geometry.geom_type.isin(["Polygon", "MultiPolygon"])
    ]
    footprints.set_crs(epsg=4326, inplace=True)

    if aoi_polygon is not None:
        before = int(footprints.shape[0])
        # Geometrically clip footprints to the AOI polygon. Matches
        # clip_and_normalize_user_footprints — the two paths must
        # produce structurally-equivalent GPKGs so downstream merge /
        # validation / assessment code can treat them interchangeably.
        # Repair invalid geometries before clip so gpd.clip doesn't
        # drop them or raise; ``make_valid`` is preferred (shapely 2.x
        # native), ``buffer(0)`` is the legacy fallback.
        try:
            footprints["geometry"] = footprints.geometry.make_valid()
        except AttributeError:  # pragma: no cover - shapely < 2.0
            footprints["geometry"] = footprints.geometry.buffer(0)

        import geopandas as _gpd

        aoi_gdf = _gpd.GeoDataFrame(geometry=[aoi_polygon], crs="EPSG:4326")
        try:
            footprints = _gpd.clip(footprints, aoi_gdf, keep_geom_type=True)
        except TypeError:  # pragma: no cover - geopandas < 0.10
            footprints = _gpd.clip(footprints, aoi_gdf)
        # gpd.clip can produce Point/LineString slivers from
        # boundary-only intersections even with keep_geom_type=True
        # on some inputs; re-filter defensively.
        footprints = footprints[
            footprints.geometry.geom_type.isin(["Polygon", "MultiPolygon"])
        ]
        footprints = footprints[~footprints.geometry.is_empty]
        after = int(footprints.shape[0])
        logger.info(
            "AOI-polygon clip kept %d of %d bbox-matched footprints "
            "(dropped %d outside the valid-area mask)",
            after,
            before,
            before - after,
        )

    footprints.to_file(output_path, driver="GPKG")

    logger.info(
        "Wrote %d Overture building footprints to %s",
        footprints.shape[0],
        output_path,
    )
    return int(footprints.shape[0])


def clip_and_normalize_user_footprints(
    input_path: str,
    aoi_polygon,
    output_path: str,
    *,
    overwrite: bool = False,
):
    """Clip a user-supplied building-footprint GPKG to an AOI polygon.

    Reads ``input_path`` (any GDAL-supported vector format readable by
    geopandas), reprojects to EPSG:4326 if needed, filters to polygonal
    geometries, clips to ``aoi_polygon`` (EPSG:4326), normalizes the
    schema to ``(id, geometry, subtype, class)`` synthesizing any
    missing non-geometry column, and writes a GeoPackage to
    ``output_path``.

    This is the "user-supplied" counterpart to
    :func:`download_building_footprints`: both produce GPKG files with
    the same schema so the rest of HASTE's pipeline can treat them
    interchangeably.

    Args:
        input_path: Path to a local building-footprint GPKG (or any
            geopandas-readable vector file).
        aoi_polygon: ``shapely.geometry.Polygon`` (or any geometry)
            describing the AOI, **in EPSG:4326**. Typically the output
            of :func:`hastegeo.core.utils.aoi.extract_aoi_polygon`.
        output_path: Destination ``.gpkg`` path.
        overwrite: Replace the output if it already exists.

    Returns:
        Number of features written.

    Raises:
        ImportError: If geopandas is not available.
        ValueError: If the input has no CRS, no polygonal geometries, or
            nothing remains after clipping to the AOI.
        FileExistsError: If ``overwrite`` is False and ``output_path``
            already exists.
    """
    if not output_path.endswith(".gpkg"):
        raise ValueError("output_path must end with .gpkg")
    if os.path.exists(output_path):
        if not overwrite:
            raise FileExistsError(
                f"Output file '{output_path}' already exists "
                "(pass overwrite=True to replace)."
            )
        os.remove(output_path)

    gdf = gpd.read_file(input_path)
    if gdf.crs is None:
        raise ValueError(
            "Input GPKG is missing a CRS; embed one (e.g. EPSG:4326) and retry."
        )

    polygon_mask = gdf.geometry.geom_type.isin(["Polygon", "MultiPolygon"])
    gdf = gdf.loc[polygon_mask].copy()
    if gdf.empty:
        raise ValueError(
            "Input GPKG contains no Polygon/MultiPolygon features."
        )

    if gdf.crs.to_epsg() != 4326:
        logger.info(
            "Reprojecting %d building footprints from %s to EPSG:4326",
            len(gdf),
            gdf.crs,
        )
        gdf = gdf.to_crs(epsg=4326)

    # Repair invalid geometries (self-intersections, etc.) before clip so
    # gpd.clip doesn't drop them or raise. ``buffer(0)`` is the long-standing
    # geopandas/shapely idiom; ``make_valid`` is the post-2.0 native API,
    # which we prefer when available.
    try:
        gdf["geometry"] = gdf.geometry.make_valid()
    except AttributeError:  # pragma: no cover - shapely < 2.0
        gdf["geometry"] = gdf.geometry.buffer(0)

    aoi_gdf = gpd.GeoDataFrame(geometry=[aoi_polygon], crs="EPSG:4326")
    try:
        clipped = gpd.clip(gdf, aoi_gdf, keep_geom_type=True)
    except TypeError:  # pragma: no cover - geopandas < 0.10
        clipped = gpd.clip(gdf, aoi_gdf)
    # gpd.clip can produce Point/LineString slivers from boundary-only
    # intersections even with keep_geom_type=True on some inputs; same
    # belt-and-suspenders re-filter the Overture path applies.
    clipped = clipped[
        clipped.geometry.geom_type.isin(["Polygon", "MultiPolygon"])
    ]
    clipped = clipped[~clipped.geometry.is_empty]

    if clipped.empty:
        raise ValueError(
            "No user-supplied building footprints intersected the AOI."
        )

    # Synthesize ``id`` from row index when missing; preserve any
    # existing values otherwise. Missing ``subtype``/``class`` are left
    # as ``None`` (downstream readers gate on column presence).
    #
    # The ``id`` column is force-cast to *string* even when the input
    # already provided it. The Overture path produces string GUIDs;
    # downstream consumers (the validation UI, then the validation /
    # assessment reports that join labels to inference) key on the
    # JSON-serialized id, which for an integer column comes through as
    # a JS number → stringly-coerced object key on PUT → str on the
    # server. Meanwhile this gpkg's fiona-read id stays int. That mix
    # caused 'No validation labels could be matched to inference
    # results' for every user GPKG with int ids (which is most GIS
    # data). Normalizing here makes the two paths interchangeable.
    if "id" not in clipped.columns:
        clipped = clipped.reset_index(drop=True)
        clipped["id"] = clipped.index.astype(str)
    else:
        clipped["id"] = clipped["id"].astype(str)
    if "subtype" not in clipped.columns:
        clipped["subtype"] = None
    if "class" not in clipped.columns:
        clipped["class"] = None

    out = clipped[list(_FOOTPRINT_OUTPUT_COLUMNS)].copy()
    out.set_crs(epsg=4326, inplace=True, allow_override=True)
    out.to_file(output_path, driver="GPKG")

    logger.info(
        "Wrote %d user-supplied building footprints (clipped to AOI) to %s",
        out.shape[0],
        output_path,
    )
    return int(out.shape[0])


def _main():
    """Argparse entry point so the workflow can call this in a subprocess.

    See ``ImageryWorkflow.download_building_footprints`` in
    ``hastegeo.workflows.prepare_imagery`` — it spawns
    ``python -m hastegeo.core.utils.footprints`` so a crash in pyarrow's
    native code (or a stuck Overture query) is contained to a subprocess and
    doesn't bring down the parent imageryprep workflow.
    """
    import argparse
    import sys

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--bbox",
        required=True,
        help="AOI bounding box in EPSG:4326 as 'xmin,ymin,xmax,ymax'",
    )
    parser.add_argument(
        "--output-path",
        required=True,
        help="Destination .gpkg filename",
    )
    parser.add_argument(
        "--overwrite",
        action="store_true",
        help="Replace the output file if it already exists",
    )
    parser.add_argument(
        "--aoi-geojson",
        default=None,
        help=(
            "Optional path to a GeoJSON file with the valid-area polygon "
            "(EPSG:4326). Footprints whose geometry does not intersect "
            "this polygon are dropped, removing buildings from the bbox "
            "corners that fall outside the imagery's valid-data region. "
            "Loading failures are logged and AOI filtering is skipped — "
            "the bbox-only result is still written."
        ),
    )
    args = parser.parse_args()

    try:
        xmin, ymin, xmax, ymax = (float(v) for v in args.bbox.split(","))
    except ValueError as e:
        parser.error(f"--bbox must be 'xmin,ymin,xmax,ymax': {e}")

    logging.basicConfig(level=logging.INFO, format="%(message)s")

    aoi_polygon = None
    if args.aoi_geojson:
        try:
            aoi_gdf = gpd.read_file(args.aoi_geojson)
            if aoi_gdf.crs is not None and aoi_gdf.crs.to_epsg() != 4326:
                aoi_gdf = aoi_gdf.to_crs(epsg=4326)
            aoi_polygon = aoi_gdf.union_all()
            if aoi_polygon.is_empty:
                logger.warning(
                    "AOI geojson %s produced an empty geometry; "
                    "skipping AOI filter",
                    args.aoi_geojson,
                )
                aoi_polygon = None
        except Exception:
            logger.warning(
                "Failed to load AOI geojson %s; falling back to "
                "bbox-only filtering",
                args.aoi_geojson,
                exc_info=True,
            )
            aoi_polygon = None

    count = download_building_footprints(
        bbox=(xmin, ymin, xmax, ymax),
        output_path=args.output_path,
        overwrite=args.overwrite,
        aoi_polygon=aoi_polygon,
    )
    sys.stdout.write(f"{count}\n")
    sys.stdout.flush()


if __name__ == "__main__":
    _main()
