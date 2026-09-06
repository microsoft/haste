# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License.

"""Build an image layer's shared building-footprint vector tiles.

Every map that draws a layer's buildings — the interactive labeler today,
the results viewer later — needs the same thing: the layer's cached
building footprints as a PMTiles archive carrying a stable per-building
id. Geometry belongs to the *layer*, not to any one model: every model
trained on a layer draws exactly the same buildings. So the archive is
built once, when the footprints are cached, and shared.

The archive holds geometry plus two attributes:

* ``id`` — the footprint's row index, promoted to the native MVT feature
  id so a browser can drive per-building colouring through map
  feature-state, and
* ``overture_id`` — the Overture string id, which round-trips through the
  labeling APIs.

Nothing model-specific goes in the tiles. Per-model values (embedding
feature vectors, damage scores) travel in their own sidecars keyed by the
same ``id``, which is what keeps a dense urban tile small.

CRITICAL — row-order invariant:
    Predictions and embeddings join to the layer's ``buildingFootprintsUrl``
    GeoPackage **by row index**, so ``id`` MUST be ``0..N-1`` in the
    footprints file's native order. Rows are never dropped or reordered.

CRITICAL — where this runs:
    ``tippecanoe`` ships only in the HASTE training docker image
    (``docker/training/env/env.yml``). This module must therefore run as a
    queued Batch/local-runner task inside that container, never inline in
    an Azure Functions HTTP handler. See
    ``hastegeo.core.processors.footprint_tiles``.

Config (written by the processor, read by ``main``)::

    {
      "project_id": "...",
      "image_layer_id": "...",
      "output_dir": "outputs",
      "files": {
        "footprints": "inputs/<footprints>.gpkg",
        "pmtiles": "footprints_<imageLayerId>.pmtiles"
      },
      "tiles": {"minimum_zoom": 10, "maximum_zoom": 15},
      "store_artifacts": true
    }
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from typing import Any, Dict, Optional

import geopandas as gpd
from hastegeo.core.config import ArtifactTypes, Config, StorageType
from hastegeo.core.utils.gdal_security import harden_gdal
from hastegeo.core.utils.logs import Logger as HasteLogger

WORKDIR = os.getenv("WORKDIR", ".")
LOG_DIR = os.path.join(WORKDIR, "logs")
LOG_FILE = "footprint_tiles_verbose.log"
FRIENDLY_LOG_FILE = "footprint_tiles_friendly.log"
os.makedirs(LOG_DIR, exist_ok=True)

logger = HasteLogger.get_logger(
    "prepare_footprint_tiles", log_dir=LOG_DIR, log_file=LOG_FILE
)
logger.info("Executing %s", __file__)

# Harden GDAL/OGR before reading any user-reachable vector file (GDAL CVE
# compensating control — docs/known-vulnerabilities.md Root Cause C).
harden_gdal()

TIPPECANOE_BIN = "tippecanoe"
TILE_LAYER_NAME = "buildings"
# Buildings are invisible below z10, and the maps that read these tiles
# work at z<=15; anything above is produced by the map SDK via overzoom,
# on which queryRenderedFeatures and setFeatureState keep working.
DEFAULT_MIN_ZOOM = 10
DEFAULT_MAX_ZOOM = 15
# Tiles carry only these two attributes. Per-model values ride in their
# own sidecars, which keeps a dense urban tile small.
TILE_ID_FIELD = "id"
TILE_OVERTURE_ID_FIELD = "overture_id"
TILING_CRS = "EPSG:4326"

MANIFEST_FILENAME = "footprint_tiles_manifest.json"
TILING_GEOJSON_NAME = "footprints_4326.geojson"
DEFAULT_OUTPUT_DIR = "outputs"


class TippecanoeNotFoundError(RuntimeError):
    """Raised when the tippecanoe binary is unavailable."""


class TippecanoeError(RuntimeError):
    """Raised when tippecanoe runs but exits non-zero."""


def log_progress(message: str) -> None:
    """Append a friendly progress line consumed by the postprocessor."""
    logger.info(message)
    log_file = os.path.join(LOG_DIR, FRIENDLY_LOG_FILE)
    with open(log_file, "a") as handle:
        handle.write(f"{datetime.now(timezone.utc).isoformat()}|{message}\n")


def require_tippecanoe() -> str:
    """Return the tippecanoe executable path or fail with guidance.

    Raises:
        TippecanoeNotFoundError: when the binary is not on PATH. The
            message names the one image that ships it, so the failure is
            actionable rather than a bare ``FileNotFoundError`` traceback
            out of ``subprocess``.
    """
    binary = shutil.which(TIPPECANOE_BIN)
    if binary:
        return binary
    raise TippecanoeNotFoundError(
        "tippecanoe was not found on PATH, so the footprint vector tiles "
        "cannot be built. tippecanoe ships only in the HASTE training "
        "image (docker/training/env/env.yml); run this workflow as a "
        "queued task in that container "
        "(hastegeo.core.processors.footprint_tiles), never inline in the "
        "Azure Functions app."
    )


def footprints_to_tiling_geojson(
    footprints_path: str, geojson_path: str
) -> int:
    """Write a tiling-ready EPSG:4326 GeoJSON of the footprints.

    Emits exactly two attributes per feature: an integer ``id`` equal to
    the footprint's row index (the positional join key) and the Overture
    string id as ``overture_id``.

    Args:
        footprints_path: Building-footprints GeoPackage for the layer.
        geojson_path: Destination GeoJSON path.

    Returns:
        Number of footprints written.

    Raises:
        ValueError: if the GeoPackage is empty, has no CRS, or lacks the
            Overture ``id`` column.
    """
    footprints = gpd.read_file(footprints_path)
    if len(footprints) == 0:
        raise ValueError(
            f"Building footprints GeoPackage is empty: {footprints_path}"
        )
    if footprints.crs is None:
        raise ValueError(
            "Building footprints GeoPackage has no CRS, refusing to tile "
            f"unreferenced geometry: {footprints_path}"
        )
    if TILE_ID_FIELD not in footprints.columns:
        raise ValueError(
            "Building footprints GeoPackage has no 'id' column (expected "
            f"the Overture id): {footprints_path}"
        )

    # Tiles are always geographic; reproject only when needed so an
    # already-4326 layer keeps its exact coordinates.
    if footprints.crs.to_epsg() != 4326:
        logger.info(
            "Reprojecting footprints from %s to %s for tiling",
            footprints.crs,
            TILING_CRS,
        )
        footprints = footprints.to_crs(TILING_CRS)

    tiles_gdf = gpd.GeoDataFrame(
        {
            # Row index -> integer feature id. MUST stay 0..N-1 in native
            # footprint order to match the positional join.
            TILE_ID_FIELD: range(len(footprints)),
            TILE_OVERTURE_ID_FIELD: footprints[TILE_ID_FIELD].astype(str),
        },
        geometry=footprints.geometry.values,
        crs=TILING_CRS,
    )
    tiles_gdf.to_file(geojson_path, driver="GeoJSON")
    logger.info(
        "Wrote %d footprints to %s for tiling",
        len(tiles_gdf),
        geojson_path,
    )
    return len(tiles_gdf)


def run_tippecanoe(
    geojson_path: str,
    pmtiles_path: str,
    minimum_zoom: int = DEFAULT_MIN_ZOOM,
    maximum_zoom: int = DEFAULT_MAX_ZOOM,
) -> None:
    """Convert a footprints GeoJSON to PMTiles via tippecanoe.

    ``id`` becomes the native MVT feature id
    (``--use-attribute-for-id=id``) so a browser can colour buildings
    through map feature-state, and only ``id`` + ``overture_id`` survive
    into the tiles.

    Raises:
        TippecanoeNotFoundError: when the binary is missing.
        TippecanoeError: when tippecanoe exits non-zero.
    """
    binary = require_tippecanoe()
    cmd = [
        binary,
        "-o",
        pmtiles_path,
        "-l",
        TILE_LAYER_NAME,
        # Bake the row-index id into each tile as the MVT feature id.
        # Azure Maps' VectorTileSource does not honor client-side
        # promoteId, so the id has to be native.
        f"--use-attribute-for-id={TILE_ID_FIELD}",
        # Keep only the join key and the Overture id.
        "-y",
        TILE_ID_FIELD,
        "-y",
        TILE_OVERTURE_ID_FIELD,
        "--force",
        f"--minimum-zoom={int(minimum_zoom)}",
        f"--maximum-zoom={int(maximum_zoom)}",
        # Geometry-only features are tiny; lifting the 500 KB per-tile
        # cap guarantees no footprint is silently dropped.
        "--no-tile-size-limit",
        # Last-resort safety valve.
        "--drop-densest-as-needed",
        geojson_path,
    ]
    log_progress(f"Running tippecanoe -> {os.path.basename(pmtiles_path)}")
    try:
        subprocess.run(cmd, check=True)
    except subprocess.CalledProcessError as exc:
        raise TippecanoeError(
            f"tippecanoe failed with exit code {exc.returncode} while "
            f"building {os.path.basename(pmtiles_path)}"
        ) from exc


def build_footprint_pmtiles(
    footprints_path: str,
    pmtiles_path: str,
    minimum_zoom: int = DEFAULT_MIN_ZOOM,
    maximum_zoom: int = DEFAULT_MAX_ZOOM,
    geojson_path: Optional[str] = None,
) -> int:
    """Build the layer's footprint PMTiles archive.

    Returns:
        Number of footprints tiled.
    """
    # Fail before the (potentially slow) reprojection when the binary is
    # missing, so the error the user sees is the actionable one.
    require_tippecanoe()
    geojson_path = geojson_path or os.path.join(
        os.path.dirname(pmtiles_path) or ".", TILING_GEOJSON_NAME
    )
    count = footprints_to_tiling_geojson(footprints_path, geojson_path)
    run_tippecanoe(
        geojson_path,
        pmtiles_path,
        minimum_zoom=minimum_zoom,
        maximum_zoom=maximum_zoom,
    )
    log_progress(f"Built footprint tiles for {count} buildings")
    return count


def artifact_storage_available(config: Config) -> bool:
    """Report whether this process can reach artifact storage.

    Azure Batch tasks are not given storage credentials by default (the
    runner uploads ``outputs/`` for them), while the local docker runner
    does pass them through. Probing up front lets the workflow store the
    archive itself when it can and fall back to the runner's upload
    otherwise, instead of dying on a misleading credential error.
    """
    storage_config = config.artifact_storage_config or {}
    if config.artifact_storage_type == StorageType.BLOB.value:
        return bool(
            storage_config.get("connection_string")
            or storage_config.get("account_url")
        )
    if config.artifact_storage_type == StorageType.LOCAL.value:
        return bool(storage_config.get("directory"))
    return False


def store_artifacts(
    project_id: str,
    artifacts: Dict[str, str],
    config: Optional[Config] = None,
) -> Dict[str, str]:
    """Store artifacts through the artifact-storage façade.

    Args:
        project_id: Storage partition key.
        artifacts: ``{artifact_name: local_path}``.
        config: Optional config override.

    Returns:
        ``{artifact_name: download_url}`` for everything stored.
    """
    # Use the storage layer directly rather than ArtifactProcessor: that
    # processor also drives zip jobs and therefore imports the queue SDK,
    # which the training image does not install. This workflow only ever
    # needs to put bytes in blob storage.
    from hastegeo.core.artifact_storage.unified_artifact_storage import (
        UnifiedArtifactStorage,
    )

    config = config or Config()
    storage = UnifiedArtifactStorage(
        storage_type=config.artifact_storage_type,
        partition_key=project_id,
        **config.artifact_storage_config,
    )
    urls: Dict[str, str] = {}
    for artifact_name, local_path in artifacts.items():
        if not os.path.exists(local_path):
            raise FileNotFoundError(
                f"Artifact {artifact_name} not found at {local_path}"
            )
        storage.store_artifact(
            artifact_name=artifact_name, src_path=local_path
        )
        urls[artifact_name] = storage.get_download_url(
            identifier=artifact_name
        )
        logger.info("Stored artifact %s", artifact_name)
    return urls


def default_pmtiles_name(image_layer_id: str) -> str:
    """Artifact filename of a layer's footprint PMTiles archive."""
    return (
        ArtifactTypes.LAYER_FOOTPRINT_PMTILES.value.substitute(
            imageLayerId=image_layer_id
        )
        + ".pmtiles"
    )


def run(config: Dict[str, Any], output_dir: str) -> Dict[str, Any]:
    """Build the layer's footprint tiles and return the manifest.

    Args:
        config: Parsed workflow config (see the module docstring).
        output_dir: Directory the archive is written to. The runner
            uploads everything in here after the task completes.

    Returns:
        The manifest dict, which is also written to ``output_dir``.

    Raises:
        ValueError: when the identifiers are missing.
        FileNotFoundError: when the footprints file is absent.
    """
    files: Dict[str, Any] = config.get("files", {})
    tiles_config: Dict[str, Any] = config.get("tiles", {})
    project_id = config.get("project_id")
    image_layer_id = config.get("image_layer_id")
    if not project_id or not image_layer_id:
        raise ValueError("Config must set project_id and image_layer_id.")

    footprints_path = files.get("footprints")
    if not footprints_path or not os.path.exists(footprints_path):
        raise FileNotFoundError(
            f"Building footprints not found: {footprints_path}"
        )

    pmtiles_name = os.path.basename(
        files.get("pmtiles") or default_pmtiles_name(image_layer_id)
    )

    manifest: Dict[str, Any] = {
        "project_id": project_id,
        "image_layer_id": image_layer_id,
        "pmtiles_filename": pmtiles_name,
        "pmtiles_url": None,
        "building_count": 0,
    }

    log_progress("Building footprint vector tiles")
    pmtiles_path = os.path.join(output_dir, pmtiles_name)
    tiled_count = build_footprint_pmtiles(
        footprints_path,
        pmtiles_path,
        minimum_zoom=int(tiles_config.get("minimum_zoom", DEFAULT_MIN_ZOOM)),
        maximum_zoom=int(tiles_config.get("maximum_zoom", DEFAULT_MAX_ZOOM)),
        geojson_path=os.path.join(output_dir, TILING_GEOJSON_NAME),
    )
    manifest["building_count"] = int(tiled_count)

    if config.get("store_artifacts", True):
        workflow_config = Config()
        if artifact_storage_available(workflow_config):
            urls = store_artifacts(
                project_id,
                {pmtiles_name: pmtiles_path},
                config=workflow_config,
            )
            manifest["pmtiles_url"] = urls.get(pmtiles_name)
        else:
            log_progress(
                "Artifact storage is unreachable from this task; leaving "
                "the archive in outputs/ for the runner to upload."
            )

    # The GeoJSON is only tippecanoe's input; drop it so the runner does
    # not upload a second full copy of every footprint.
    stray_geojson = os.path.join(output_dir, TILING_GEOJSON_NAME)
    if os.path.exists(stray_geojson):
        os.remove(stray_geojson)

    log_progress("Finalizing outputs")
    with open(os.path.join(output_dir, MANIFEST_FILENAME), "w") as handle:
        json.dump(manifest, handle, indent=4)
    return manifest


def main() -> None:
    """CLI entrypoint: ``prepare-footprint-tiles --config <path>``."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--config", type=str, required=True, help="Path to config JSON file"
    )
    args = parser.parse_args()

    if not os.path.exists(args.config):
        logger.error("No config file found at location %s", args.config)
        sys.exit(1)

    with open(args.config) as handle:
        config = json.load(handle)
    if not config:
        logger.error("Config file is empty")
        sys.exit(1)

    output_dir = os.path.join(
        WORKDIR, config.get("output_dir", DEFAULT_OUTPUT_DIR)
    )
    os.makedirs(output_dir, exist_ok=True)

    try:
        run(config, output_dir)
        logger.info("Footprint tile preparation completed successfully.")
    except TippecanoeNotFoundError as exc:
        logger.error("%s", exc)
        log_progress(f"Footprint tile preparation failed: {exc}")
        raise
    except Exception as exc:
        logger.error("Error during footprint tile preparation", exc_info=True)
        log_progress(f"Error during footprint tile preparation: {exc}")
        raise


if __name__ == "__main__":
    try:
        main()
    except Exception as error:  # pragma: no cover - CLI guard
        logger.error(f"Error during main execution: {error}", exc_info=True)
        sys.exit(1)
