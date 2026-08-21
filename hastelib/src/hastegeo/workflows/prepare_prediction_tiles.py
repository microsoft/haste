# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License.

"""Prepare the vector-tile + attribute payload the prediction editor needs.

The prediction editor has to render EVERY predicted building footprint of
an image layer in the browser, with its damage attributes. Two artifacts
make that possible and this workflow builds both:

1. **Footprint PMTiles** (``ArtifactTypes.LAYER_FOOTPRINT_PMTILES``) — a
   geometry-only vector-tile archive of the image layer's cached
   building-footprints GeoPackage, reprojected to EPSG:4326. Built once
   per image layer and reused by every model trained on that layer, so
   the workflow skips this step when the layer already has one.
2. **Prediction attribute sidecar** (``ArtifactTypes.PREDICTION_ATTRS``)
   — a compact columnar JSON payload of the model's per-building damage
   values, fetched once per editing session and indexed by the same
   integer id that is baked into the tiles.

CRITICAL — row-order invariant:
    Predictions join to the layer's ``buildingFootprintsUrl`` GeoPackage
    **by row index** (``hastegeo.core.utils.assessment``). Both artifacts
    key on that row index: the tiles carry ``id = 0..N-1`` (promoted to
    the MVT feature id via ``--use-attribute-for-id=id`` so the browser
    can drive per-building colouring through map feature-state) and the
    sidecar arrays are ordered by the very same index. Rows are never
    dropped or reordered, and a footprint/prediction count mismatch is a
    hard error rather than a silent misalignment.

CRITICAL — where this runs:
    ``tippecanoe`` ships only in the training docker image
    (``docker/training/env/env.yml``). This module must therefore run as
    a queued Batch/local-runner task inside that container — never
    inline in an Azure Functions HTTP handler. See
    ``hastegeo.core.processors.prediction_tiles``.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

import fiona
import geopandas as gpd
from hastegeo.core.config import ArtifactTypes, Config, StorageType
from hastegeo.core.utils.gdal_security import harden_gdal
from hastegeo.core.utils.logs import Logger as HasteLogger
from hastegeo.core.utils.predictions import PredictionSet, read_predictions

WORKDIR = os.getenv("WORKDIR", ".")
LOG_DIR = os.path.join(WORKDIR, "logs")
LOG_FILE = "prediction_tiles_verbose.log"
FRIENDLY_LOG_FILE = "prediction_tiles_friendly.log"
os.makedirs(LOG_DIR, exist_ok=True)

logger = HasteLogger.get_logger(
    "prepare_prediction_tiles", log_dir=LOG_DIR, log_file=LOG_FILE
)
logger.info("Executing %s", __file__)

# Harden GDAL/OGR before reading any user-reachable vector file (GDAL CVE
# compensating control — docs/known-vulnerabilities.md Root Cause C).
harden_gdal()

TIPPECANOE_BIN = "tippecanoe"
TILE_LAYER_NAME = "buildings"
# Buildings are invisible below z10 and the editor works at z<=15; tiles
# above that are produced by the map SDK via overzoom, on which
# queryRenderedFeatures + setFeatureState keep working. Same window as
# the interactive labeler's tiles (workflows/embed_buildings.py).
DEFAULT_MIN_ZOOM = 10
DEFAULT_MAX_ZOOM = 15
# Tiles carry only these two attributes; every damage value rides in the
# sidecar instead, which keeps a dense urban tile small.
TILE_ID_FIELD = "id"
TILE_OVERTURE_ID_FIELD = "overture_id"
TILING_CRS = "EPSG:4326"
# Damage/unknown values are fractions in [0, 1]; six decimals is well
# below any threshold a user can set and keeps the payload compact.
VALUE_PRECISION = 6

MANIFEST_FILENAME = "prediction_tiles_manifest.json"
DEFAULT_OUTPUT_DIR = "outputs"


class TippecanoeNotFoundError(RuntimeError):
    """Raised when the tippecanoe binary is unavailable."""


class TippecanoeError(RuntimeError):
    """Raised when tippecanoe runs but exits non-zero."""


class FootprintPredictionMismatchError(ValueError):
    """Raised when predictions and footprints do not line up row for row."""


def log_progress(message: str) -> None:
    """Append a friendly progress line consumed by the postprocessor."""
    logger.info(message)
    log_file = os.path.join(LOG_DIR, FRIENDLY_LOG_FILE)
    with open(log_file, "a") as handle:
        handle.write(f"{datetime.now(timezone.utc).isoformat()}|{message}\n")


# ---------------------------------------------------------------------------
# Footprint PMTiles
# ---------------------------------------------------------------------------
def require_tippecanoe() -> str:
    """Return the tippecanoe executable path or fail with guidance.

    Raises:
        TippecanoeNotFoundError: when the binary is not on PATH. The
            message names the one image that ships it so the failure is
            actionable instead of a bare ``FileNotFoundError`` traceback
            from ``subprocess``.
    """
    binary = shutil.which(TIPPECANOE_BIN)
    if binary:
        return binary
    raise TippecanoeNotFoundError(
        "tippecanoe was not found on PATH, so the footprint vector tiles "
        "cannot be built. tippecanoe ships only in the HASTE training "
        "image (docker/training/env/env.yml); run this workflow as a "
        "queued task in that container "
        "(hastegeo.core.processors.prediction_tiles), never inline in "
        "the Azure Functions app."
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
            # footprint order to match the positional prediction join.
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

    Mirrors ``workflows/embed_buildings.write_pmtiles``: ``id`` becomes
    the native MVT feature id (``--use-attribute-for-id=id``) so the
    browser can colour buildings through map feature-state, and only
    ``id`` + ``overture_id`` survive into the tiles.

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
        # Keep only the join key and the Overture id — damage values
        # travel in the sidecar.
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
            f"building {os.path.basename(pmtiles_path)}. Command: "
            f"{' '.join(cmd)}"
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
        os.path.dirname(pmtiles_path) or ".", "footprints_4326.geojson"
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


# ---------------------------------------------------------------------------
# Prediction attribute sidecar
# ---------------------------------------------------------------------------
def count_features(path: str, layer: Optional[str] = None) -> int:
    """Count features in a vector file without loading its geometry."""
    if layer is None:
        layers = fiona.listlayers(path)
        if not layers:
            raise ValueError(f"Vector file has no layers: {path}")
        layer = layers[0]
    with fiona.open(path, layer=layer) as src:
        return len(src)


def _prediction_layer(predictions_path: str) -> str:
    """Return the layer a prediction GeoPackage stores its rows in."""
    layers = fiona.listlayers(predictions_path)
    if not layers:
        raise ValueError(
            f"Prediction GeoPackage has no layers: {predictions_path}"
        )
    # The embedding flavor writes a named "predictions" layer; the
    # trained-inference flavor uses the default (first) layer.
    return "predictions" if "predictions" in layers else layers[0]


def _assert_row_counts_match(
    predictions_path: str, footprints_path: str
) -> int:
    """Fail loudly when predictions and footprints do not line up.

    The prediction -> footprint join is positional, so a count mismatch
    would silently attach every damage value to the wrong building.

    Returns:
        The (shared) row count.

    Raises:
        FootprintPredictionMismatchError: on any mismatch.
    """
    footprint_count = count_features(footprints_path)
    prediction_count = count_features(
        predictions_path, layer=_prediction_layer(predictions_path)
    )
    if footprint_count != prediction_count:
        raise FootprintPredictionMismatchError(
            "Prediction/footprint row count mismatch: "
            f"{prediction_count} predictions in {predictions_path} vs "
            f"{footprint_count} footprints in {footprints_path}. The "
            "prediction-to-footprint join is positional, so both files "
            "must have the same number of rows in the same order."
        )
    return footprint_count


def build_prediction_attrs(
    predictions_path: str, footprints_path: str
) -> Dict[str, Any]:
    """Build the columnar attribute payload for one model.

    Args:
        predictions_path: Prediction GeoPackage (either flavor — the
            trained-inference merge output or the embedding labeler's
            ``predictions`` layer).
        footprints_path: The image layer's building-footprints
            GeoPackage, used to resolve Overture ids positionally.

    Returns:
        ``{"n", "ids", "overtureIds", "damage", "unknown", "damaged"}``
        with every array the same length and ordered by row index.

    Raises:
        FootprintPredictionMismatchError: when the two files disagree on
            row count.
        ValueError: when the prediction row indices are not the
            contiguous range ``0..n-1``.
    """
    expected_count = _assert_row_counts_match(
        predictions_path, footprints_path
    )
    predictions: PredictionSet = read_predictions(
        predictions_path, footprints_path=footprints_path
    )
    rows = sorted(predictions.rows, key=lambda row: row.row_index)

    ids: List[int] = [int(row.row_index) for row in rows]
    if ids != list(range(expected_count)):
        raise ValueError(
            f"Prediction GeoPackage {predictions_path} does not carry a "
            f"contiguous 0..{expected_count - 1} row index; the editor "
            "indexes the sidecar arrays by tile feature id, so gaps or "
            "duplicates would mislabel buildings."
        )

    payload: Dict[str, Any] = {
        "n": expected_count,
        "ids": ids,
        "overtureIds": [
            "" if row.overture_id is None else str(row.overture_id)
            for row in rows
        ],
        "damage": [
            round(float(row.damage_fraction), VALUE_PRECISION) for row in rows
        ],
        "unknown": [
            round(float(row.unknown_fraction), VALUE_PRECISION) for row in rows
        ],
        "damaged": [int(row.damaged) for row in rows],
    }

    lengths = {
        key: len(value)
        for key, value in payload.items()
        if isinstance(value, list)
    }
    if set(lengths.values()) != {expected_count}:
        raise ValueError(
            "Prediction attribute arrays have inconsistent lengths "
            f"{lengths}; expected {expected_count} for every column."
        )
    return payload


def write_prediction_attrs(
    predictions_path: str, footprints_path: str, attrs_path: str
) -> Dict[str, Any]:
    """Build and write the attribute sidecar; return the payload."""
    payload = build_prediction_attrs(predictions_path, footprints_path)
    with open(attrs_path, "w") as handle:
        json.dump(payload, handle, separators=(",", ":"))
    log_progress(
        f"Wrote prediction attributes for {payload['n']} buildings -> "
        f"{os.path.basename(attrs_path)}"
    )
    return payload


# ---------------------------------------------------------------------------
# Artifact storage
# ---------------------------------------------------------------------------
def artifact_storage_available(config: Config) -> bool:
    """Report whether this process can reach artifact storage.

    Azure Batch tasks are not given storage credentials by default (the
    runner uploads ``outputs/`` for them), while the local docker runner
    does pass them through. Probing up front lets the workflow store the
    artifacts itself when it can and fall back to the runner's upload
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
    from hastegeo.core.processors.artifacts import ArtifactProcessor

    config = config or Config()
    processor = ArtifactProcessor(partition_key=project_id, config=config)
    urls: Dict[str, str] = {}
    for artifact_name, local_path in artifacts.items():
        if not os.path.exists(local_path):
            raise FileNotFoundError(
                f"Artifact {artifact_name} not found at {local_path}"
            )
        processor.store_artifact(
            artifact_name=artifact_name, src_path=local_path
        )
        urls[artifact_name] = processor.get_download_url(
            identifier=artifact_name
        )
        logger.info("Stored artifact %s", artifact_name)
    return urls


# ---------------------------------------------------------------------------
# CLI / workflow entrypoint
# ---------------------------------------------------------------------------
def default_pmtiles_name(image_layer_id: str) -> str:
    """Artifact filename of a layer's footprint PMTiles archive."""
    return (
        ArtifactTypes.LAYER_FOOTPRINT_PMTILES.value.substitute(
            imageLayerId=image_layer_id
        )
        + ".pmtiles"
    )


def default_attrs_name(model_id: str) -> str:
    """Artifact filename of a model's prediction attribute sidecar."""
    return (
        ArtifactTypes.PREDICTION_ATTRS.value.substitute(modelId=model_id)
        + ".json"
    )


def run(config: Dict[str, Any], output_dir: str) -> Dict[str, Any]:
    """Run the workflow described by ``config`` and return its manifest.

    Args:
        config: Parsed workflow config (see the module docstring of
            ``hastegeo.core.processors.prediction_tiles`` for the shape
            the processor writes).
        output_dir: Directory the artifacts are written to. The runner
            uploads everything in here after the task completes.

    Returns:
        The manifest dict, which is also written to ``output_dir``.
    """
    files: Dict[str, Any] = config.get("files", {})
    tiles_config: Dict[str, Any] = config.get("tiles", {})
    project_id = config.get("project_id")
    image_layer_id = config.get("image_layer_id")
    model_id = config.get("model_id")
    if not project_id or not image_layer_id or not model_id:
        raise ValueError(
            "Config must set project_id, image_layer_id and model_id."
        )

    footprints_path = files.get("footprints")
    predictions_path = files.get("predictions")
    if not footprints_path or not os.path.exists(footprints_path):
        raise FileNotFoundError(
            f"Building footprints not found: {footprints_path}"
        )
    if not predictions_path or not os.path.exists(predictions_path):
        raise FileNotFoundError(
            f"Prediction GeoPackage not found: {predictions_path}"
        )

    pmtiles_name = os.path.basename(
        files.get("pmtiles") or default_pmtiles_name(image_layer_id)
    )
    attrs_name = os.path.basename(
        files.get("attrs") or default_attrs_name(model_id)
    )
    build_pmtiles = bool(tiles_config.get("build_pmtiles", True))

    manifest: Dict[str, Any] = {
        "project_id": project_id,
        "image_layer_id": image_layer_id,
        "model_id": model_id,
        "pmtiles_filename": "",
        "pmtiles_built": False,
        "pmtiles_url": None,
        "attrs_filename": attrs_name,
        "attrs_url": None,
        "building_count": 0,
        "prediction_flavor": "",
        "supports_threshold": False,
    }

    to_store: Dict[str, str] = {}

    if build_pmtiles:
        log_progress("Building footprint vector tiles")
        pmtiles_path = os.path.join(output_dir, pmtiles_name)
        build_footprint_pmtiles(
            footprints_path,
            pmtiles_path,
            minimum_zoom=int(
                tiles_config.get("minimum_zoom", DEFAULT_MIN_ZOOM)
            ),
            maximum_zoom=int(
                tiles_config.get("maximum_zoom", DEFAULT_MAX_ZOOM)
            ),
            geojson_path=os.path.join(output_dir, "footprints_4326.geojson"),
        )
        manifest["pmtiles_filename"] = pmtiles_name
        manifest["pmtiles_built"] = True
        to_store[pmtiles_name] = pmtiles_path
    else:
        log_progress("Reusing existing footprint vector tiles")

    log_progress("Building prediction attributes")
    attrs_path = os.path.join(output_dir, attrs_name)
    payload = write_prediction_attrs(
        predictions_path, footprints_path, attrs_path
    )
    predictions = read_predictions(predictions_path)
    manifest["building_count"] = int(payload["n"])
    manifest["prediction_flavor"] = predictions.flavor
    manifest["supports_threshold"] = bool(predictions.supports_threshold)
    to_store[attrs_name] = attrs_path

    if config.get("store_artifacts", True):
        haste_config = Config()
        if artifact_storage_available(haste_config):
            urls = store_artifacts(project_id, to_store, config=haste_config)
            manifest["pmtiles_url"] = urls.get(pmtiles_name)
            manifest["attrs_url"] = urls.get(attrs_name)
        else:
            # Not an error: on Azure Batch the runner uploads outputs/
            # and the postprocessor resolves the URLs from the task's
            # output prefix instead.
            logger.warning(
                "Artifact storage is not configured in this container; "
                "leaving upload to the runner and URL resolution to the "
                "postprocessor."
            )

    # The GeoJSON is only tippecanoe's input; drop it so the runner does
    # not upload a second full copy of every footprint.
    stray_geojson = os.path.join(output_dir, "footprints_4326.geojson")
    if os.path.exists(stray_geojson):
        os.remove(stray_geojson)

    log_progress("Finalizing outputs")
    with open(os.path.join(output_dir, MANIFEST_FILENAME), "w") as handle:
        json.dump(manifest, handle, indent=4)
    return manifest


def main() -> None:
    """CLI entrypoint: ``prepare-prediction-tiles --config <path>``."""
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
        logger.info("Prediction tile preparation completed successfully.")
    except TippecanoeNotFoundError as exc:
        logger.error("%s", exc)
        log_progress(f"Prediction tile preparation failed: {exc}")
        raise
    except Exception as exc:
        logger.error("Error during prediction tile preparation", exc_info=True)
        log_progress(f"Error during prediction tile preparation: {exc}")
        raise


if __name__ == "__main__":
    try:
        main()
    except Exception as error:  # pragma: no cover - CLI guard
        logger.error(f"Error during main execution: {error}", exc_info=True)
        sys.exit(1)
