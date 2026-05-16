# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License.
#
# Portions derived from the Overture Maps overturemaps-py package
# (https://github.com/OvertureMaps/overturemaps-py, MIT licensed),
# specifically core.py @ 0fad53bceb955b14ac069ef321cbc2486996d5c7.
# Modified to read from Azure Blob Storage instead of S3.

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
import pyarrow as pa
import pyarrow.compute as pc
import pyarrow.dataset as ds
import pyarrow.fs as fs

logger = logging.getLogger(__name__)

OVERTURE_ACCOUNT_NAME = "overturemapswestus2"
FALLBACK_RELEASE = "2026-02-18.0"
# Matches Overture release names like "2026-02-18.0"
_RELEASE_PATTERN = re.compile(r"^\d{4}-\d{2}-\d{2}\.\d+$")

# Allows for optional import of additional dependencies
try:
    import geopandas as gpd
    from geopandas import GeoDataFrame

    HAS_GEOPANDAS = True
except ImportError:
    HAS_GEOPANDAS = False
    GeoDataFrame = None


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
) -> "GeoDataFrame":
    """Loads geoparquet for specified type into a geopandas dataframe.

    Args:
        overture_type: type to load (e.g. "building").
        bbox: optional bounding box (xmin, ymin, xmax, ymax) in EPSG:4326.

    Returns:
        GeoDataFrame with the optionally filtered theme data.
    """
    if not HAS_GEOPANDAS:
        raise ImportError("geopandas is required to use this function")

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
) -> int:
    """Download Overture Maps building footprints for an AOI to a GeoPackage.

    The output gpkg contains only Polygon/MultiPolygon features in EPSG:4326
    with columns ``id``, ``geometry``, ``subtype``, ``class`` (the columns
    HASTE's downstream merge step expects).

    Args:
        bbox: AOI bounding box (xmin, ymin, xmax, ymax) in EPSG:4326.
        output_path: Destination ``.gpkg`` filename.
        overwrite: If False and the file already exists, raise FileExistsError.

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
    footprints = footprints[["id", "geometry", "subtype", "class"]]
    footprints = footprints[
        footprints.geometry.geom_type.isin(["Polygon", "MultiPolygon"])
    ]
    footprints.set_crs(epsg=4326, inplace=True)
    footprints.to_file(output_path, driver="GPKG")

    logger.info(
        "Wrote %d Overture building footprints to %s",
        footprints.shape[0],
        output_path,
    )
    return int(footprints.shape[0])
