# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License.

"""Script for creating segmentation masks from geojson labels and images.

NOTE: Even though there exists an argument `--buffer_in_meters`, there are no checks to
ensure that the input imagery is in a projected coordinate system (i.e. meters). If the
input imagery is in a geographic coordinate system, the buffer will be in degrees, which
is likely not what you want!

By default the whole label file is turned into a single image/mask pair covering the
extent of the labels. Setting `labels.cluster_size_in_meters` instead tiles the labels
onto a grid and emits one image/mask pair per populated grid cell, which keeps each
training tile small and dense with labels when the labeled area is sparse and spread
out over a large scene.
"""

import argparse
import os
import shutil
import subprocess
from typing import List, Optional

import cv2
import fiona
import fiona.transform
import numpy as np
import rasterio
import rasterio.mask
import shapely  # shapely>=2 (via geopandas) for STRtree
import shapely.geometry
from bda.config import get_args


def add_create_masks_parser(
    parser: argparse.ArgumentParser,
) -> argparse.ArgumentParser:
    """Adds the arguments for the create_masks.py script to the base parser."""
    parser.add_argument(
        "--labels.fn",
        type=str,
        help="Path to GeoJSON file containing polygon labels (output from the labeling tool)",
    )
    parser.add_argument(
        "--imagery.raw_fn",
        type=str,
        help="Path to raw input imagery as a COG (cloud-optimized GeoTIFF)",
    )
    parser.add_argument(
        "--experiment_dir", type=str, help="Directory to write dataset to"
    )
    parser.add_argument(
        "--labels.classes", nargs="+", type=str, help="List of class names"
    )
    parser.add_argument(
        "--labels.buffer_in_meters",
        type=int,
        help="Buffer in meters around labels",
    )
    parser.add_argument(
        "--labels.class_to_buffer", type=str, help="Class name to buffer"
    )
    parser.add_argument(
        "--labels.class_to_buffer_by",
        type=str,
        help="Class name to set buffered pixels to",
    )
    parser.add_argument(
        "--labels.cluster_size_in_meters",
        type=float,
        required=False,
        help="Size of grid cells (in the units of the imagery CRS) used to cluster"
        " labels into separate image/mask pairs. If not provided, all labels are"
        " processed together into a single pair.",
    )
    parser.add_argument(
        "--labels.min_pixels_per_cluster",
        type=int,
        required=False,
        help="Minimum number of labeled pixels required to keep a cluster (default 1000)",
    )
    parser.add_argument(
        "--overwrite",
        action="store_true",
        help="Whether to overwrite the output dataset if it already exists",
    )

    return parser


def _run(command: List[str], what: str) -> None:
    """Runs a subprocess, raising with captured output when it fails.

    Args:
        command (List[str]): The command to run.
        what (str): Human-readable description used in the error message.

    Raises:
        RuntimeError: If the command exits non-zero.
    """
    result = subprocess.run(command, capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(
            f"{what} failed with exit code {result.returncode}.\n"
            f"Command: {' '.join(command)}\n"
            f"stderr: {result.stderr}\n"
            f"stdout: {result.stdout}"
        )


def get_class_names_from_labels(labels_fn: str, key: str = "class") -> set:
    """Get the class names from a GeoJSON file.

    Args:
        labels_fn (str): Path to GeoJSON file containing polygon labels (output from the
            labeling tool).
        key (str): The key in the GeoJSON file to use for the class names.

    Returns:
        set: Set of class names.
    """
    class_names = set()
    if not os.path.exists(labels_fn):
        raise RuntimeError(f"Labels file {labels_fn} missing")
    with fiona.open(labels_fn) as f:
        for feature in f:
            class_names.add(feature["properties"][key])
    return class_names


def validate_cluster_crs(image_crs, input_image_fn: str) -> None:
    """Reject imagery whose CRS makes `cluster_size_in_meters` meaningless.

    The grid is built in the imagery's own coordinate units. On a geographic
    CRS those units are degrees, so a 1000 "meter" cell becomes a 1000-degree
    cell -- larger than the planet -- and every label collapses into a single
    cluster. Clustering silently no-ops instead of failing, which is the worst
    outcome, so fail fast rather than guessing a conversion.

    Nothing upstream guarantees a projected CRS: the imageryprep mosaic step
    preserves the source projection, and merge_with_building_footprints.py
    carries an explicit geographic-CRS fallback for rasters from this same
    lineage.

    Args:
        image_crs: The rasterio CRS of the input imagery, or None.
        input_image_fn (str): Path to the imagery, used in the error message.

    Raises:
        ValueError: If the CRS is missing or not projected.
    """
    if image_crs is None:
        raise ValueError(
            f"{input_image_fn} has no CRS, so labels.cluster_size_in_meters"
            " cannot be interpreted. Georeference the imagery or leave"
            " clustering off."
        )
    if not image_crs.is_projected:
        raise ValueError(
            f"{input_image_fn} is in a geographic CRS ({image_crs.to_string()})"
            " whose units are degrees, so labels.cluster_size_in_meters would"
            " be treated as degrees and collapse every label into one cluster."
            " Reproject the imagery to a projected CRS (e.g. the local UTM"
            " zone) or leave clustering off."
        )


def assign_features_to_grid(
    feature_shapes: List, bounds_shape, cluster_size: float
) -> List[tuple]:
    """Lay a `cluster_size` grid over `bounds_shape` and populate its cells.

    Pure geometry -- split out from `cluster_labels` so the grid/assignment
    logic can be tested without GDAL or a label file on disk.

    Args:
        feature_shapes (List): Shapely geometries, already in the grid CRS.
        bounds_shape: Shapely geometry whose bounds define the grid extent.
        cluster_size (float): Grid cell size in the units of the grid CRS.

    Returns:
        List[tuple]: One (cell_geometry, [feature indices]) pair per populated
            cell, in row-major order over the grid.
    """
    minx, miny, maxx, maxy = bounds_shape.bounds
    envelope = bounds_shape.envelope

    if not feature_shapes:
        return []

    # Index the features so each cell tests only nearby candidates. Scanning
    # the whole feature list per cell is O(cells x features), and the case
    # this feature exists for -- sparse labels spread over a large scene --
    # is exactly the one that maximizes both terms.
    tree = shapely.STRtree(feature_shapes)

    cells = []
    for x in np.arange(minx, maxx, cluster_size):
        for y in np.arange(miny, maxy, cluster_size):
            grid_cell = shapely.geometry.box(
                x, y, x + cluster_size, y + cluster_size
            )

            # STRtree.query with a predicate returns exact matches, not just
            # bounding-box candidates, so this is equivalent to the full scan.
            # Sorted to keep cluster contents order-stable regardless of the
            # tree's internal ordering.
            indices = sorted(
                int(i) for i in tree.query(grid_cell, predicate="intersects")
            )
            if not indices:
                continue

            # Clip the cell to the overall label extent so edge cells don't
            # request imagery well outside the labeled area.
            cell_geom = grid_cell.intersection(envelope)
            if cell_geom.is_empty:
                continue

            cells.append((cell_geom, indices))

    return cells


def cluster_labels(
    labels_fn: str, cluster_size: float, dst_crs: str
) -> List[dict]:
    """Cluster labels into spatial grid cells.

    Each populated cell of a `cluster_size` grid laid over the labels becomes one
    cluster. Features are assigned to every cell they intersect, so a polygon
    straddling a cell boundary appears in both (each copy clipped by that cell's
    raster extent later on).

    Args:
        labels_fn (str): Path to GeoJSON file containing polygon labels.
        cluster_size (float): Size of grid cells in the units of `dst_crs`
            (typically meters).
        dst_crs (str): Target CRS to use for clustering (the imagery CRS).

    Returns:
        List[dict]: One dict per populated cell with 'geom' (the cell geometry in
            `dst_crs`), 'features' (the original, untransformed features), and
            'cluster_id'.
    """
    with fiona.open(labels_fn) as f:
        src_crs = f.crs.to_string()
        features = list(f)
        label_bounds = f.bounds

    if not features:
        return []

    # Transform every feature ONCE up front. Doing this inside the grid loop
    # instead (as the reference implementation did) re-projects every feature
    # for every cell, which is O(cells x features) and dominates runtime on
    # real label sets.
    feature_shapes = [
        shapely.geometry.shape(
            fiona.transform.transform_geom(
                src_crs, dst_crs, feature["geometry"]
            )
        )
        for feature in features
    ]

    bounds_geom = fiona.transform.transform_geom(
        src_crs,
        dst_crs,
        shapely.geometry.mapping(shapely.geometry.box(*label_bounds)),
    )
    bounds_shape = shapely.geometry.shape(bounds_geom)

    cells = assign_features_to_grid(feature_shapes, bounds_shape, cluster_size)

    return [
        {
            "geom": shapely.geometry.mapping(cell_geom),
            "features": [features[idx] for idx in indices],
            "cluster_id": cluster_id,
        }
        for cluster_id, (cell_geom, indices) in enumerate(cells)
    ]


def create_mask_for_labels(
    input_label_fn: str,
    input_image_fn: str,
    output_dir: str,
    class_names: List[str],
    class_name_to_idx_map: dict,
    buffer_in_meters: int,
    class_to_buffer: str,
    class_to_buffer_by: str,
    do_buffering: bool = True,
    crop_geom: Optional[dict] = None,
    suffix: str = "",
    num_channels: Optional[int] = None,
) -> tuple:
    """Create a mask and cropped image for a set of labels.

    Args:
        input_label_fn: Path to GeoJSON file with labels.
        input_image_fn: Path to input imagery.
        output_dir: Directory to write output to.
        class_names: List of class names.
        class_name_to_idx_map: Mapping from class names to mask values.
        buffer_in_meters: Buffer distance in meters.
        class_to_buffer: Class name to buffer.
        class_to_buffer_by: Class name to use for buffered pixels.
        do_buffering: Whether to apply the buffering step at all.
        crop_geom: Optional geometry (in the imagery CRS) to crop to. If None,
            crops to the label bounds.
        suffix: Optional suffix to add to output filenames.
        num_channels: Optional number of leading channels to keep from the
            imagery. If None, all channels are kept.

    Returns:
        tuple: (output_cropped_image_fn, output_buffered_mask_fn)
    """
    name = os.path.basename(input_image_fn).replace(".tif", "")

    output_mask_fn = os.path.join(output_dir, f"{name}{suffix}_mask.tif")
    output_warped_label_fn = os.path.join(
        output_dir, f"{name}{suffix}_labels_warped.geojson"
    )
    output_cropped_image_fn = os.path.join(
        output_dir, "images", f"{name}{suffix}_cropped.tif"
    )
    output_buffered_mask_fn = os.path.join(
        output_dir, "masks", f"{name}{suffix}_buffered.tif"
    )

    ##########
    # Load information about the input image
    with rasterio.open(input_image_fn) as f:
        profile = f.profile
        dst_crs = f.crs.to_string()

    ##########
    # Warp the labels to the CRS of the input image
    command = [
        "ogr2ogr",
        "-f",
        "GeoJSON",
        "-t_srs",
        dst_crs,
        output_warped_label_fn,
        input_label_fn,
    ]
    _run(command, "ogr2ogr")

    ##########
    # Crop the input image to the given extent, or to the extent of the labels
    if crop_geom is None:
        with fiona.open(input_label_fn) as f:
            geom = shapely.geometry.mapping(shapely.geometry.box(*f.bounds))
        geom = dict(fiona.transform.transform_geom("epsg:4326", dst_crs, geom))
        del geom["geometries"]
        geom = shapely.geometry.mapping(shapely.geometry.shape(geom).envelope)
    else:
        geom = crop_geom

    with rasterio.open(input_image_fn) as f:
        data, transform = rasterio.mask.mask(f, [geom], crop=True)

    if num_channels is not None and num_channels != data.shape[0]:
        if num_channels > data.shape[0]:
            # Slicing cannot invent bands. Left unchecked this writes a short
            # image and the failure surfaces much later as an opaque model
            # input-channel mismatch during fine-tuning.
            raise ValueError(
                f"imagery.num_channels is {num_channels} but"
                f" {input_image_fn} has only {data.shape[0]} band(s)."
                " Set imagery.num_channels to match the imagery."
            )
        print(
            f"\n{'!' * 60}\n"
            f"WARNING: Clipping imagery from {data.shape[0]} channels to"
            f" {num_channels} channels.\n"
            f"Channels {num_channels + 1}-{data.shape[0]} will be dropped!\n"
            f"{'!' * 60}\n"
        )
        data = data[:num_channels]

    _, height, width = data.shape

    profile["height"] = height
    profile["width"] = width
    profile["count"] = data.shape[0]
    profile["transform"] = transform
    profile["predictor"] = 2
    with rasterio.open(output_cropped_image_fn, "w", **profile) as f:
        f.write(data)

    ##########
    # Create mask
    with rasterio.open(output_cropped_image_fn) as f:
        profile = f.profile
        left, bottom, right, top = f.bounds
        width = f.width
        height = f.height
        dst_crs = f.crs.to_string()

    command = [
        "gdal_rasterize",
        "-q",  # be quiet about it
        "-ot",
        "Byte",  # the output dtype of the raster should be uint8
        "-a_nodata",
        "0",  # the nodata value should be "0", this value will represent not-labeled in our training process
        "-init",
        "0",  # initialize all values to 0
        "-burn",
        str(
            class_name_to_idx_map[class_names[0]]
        ),  # we will burn in the first class value to all polygons in the GeoJSON that match the first class label
        "-of",
        "GTiff",  # the output should be a GeoTIFF
        "-co",
        "TILED=YES",  # the output should be tiled, similar to COGs -- https://www.cogeo.org/ -- this is important for fast windowed reads
        "-co",
        "BLOCKXSIZE=512",  # this is important for fast windowed reads
        "-co",
        "BLOCKYSIZE=512",  # this is important for fast windowed reads
        "-co",
        "INTERLEAVE=PIXEL",  # this is important for fast windowed reads
        "-where",
        f"class='{class_names[0]}'",  # burn in values for polygons where the class label is the first class label
        "-te",
        str(left),
        str(bottom),
        str(right),
        str(
            top
        ),  # the output GeoTIFF should cover the same bounds as the input image
        "-ts",
        str(width),
        str(
            height
        ),  # the output GeoTIFF should have the same height and width as the input image
        "-co",
        "COMPRESS=LZW",  # compress it
        "-co",
        "PREDICTOR=2",  # compress it good
        "-co",
        "BIGTIFF=YES",  # just incase the image is bigger than 4GB
        output_warped_label_fn,
        output_mask_fn,
    ]
    _run(command, "gdal_rasterize")

    for i in range(1, len(class_names)):
        command = [
            "gdal_rasterize",
            "-q",
            "-b",
            "1",
            "-burn",
            str(class_name_to_idx_map[class_names[i]]),
            "-where",
            f"class='{class_names[i]}'",
            input_label_fn,
            output_mask_fn,
        ]
        _run(command, f"gdal_rasterize for class '{class_names[i]}'")

    ##########
    # Buffer mask around buildings
    with rasterio.open(output_mask_fn) as f:
        mask = f.read().squeeze()
        mask_profile = f.profile

    if do_buffering:
        nodata_mask = (mask != class_name_to_idx_map[class_to_buffer]).astype(
            np.uint8
        )
        transform = cv2.distanceTransform(
            nodata_mask, distanceType=cv2.DIST_L2, maskSize=3
        )
        background_mask = (transform > 0) & (transform < buffer_in_meters)
        mask[background_mask] = class_name_to_idx_map[class_to_buffer_by]

    with rasterio.open(output_buffered_mask_fn, "w", **mask_profile) as f:
        f.write(mask, 1)

    ##########
    # Check that the buffered mask and the cropped image have the same dimensions
    with rasterio.open(output_cropped_image_fn) as f:
        t_height, t_width = f.shape
    with rasterio.open(output_buffered_mask_fn) as f:
        assert f.shape[0] == t_height
        assert f.shape[1] == t_width

    os.remove(output_warped_label_fn)
    os.remove(output_mask_fn)

    return output_cropped_image_fn, output_buffered_mask_fn


def main() -> None:
    """Main function for the create_masks.py script."""
    print("Entered create_masks.py")
    args = get_args(
        description=__doc__, add_extra_parser=add_create_masks_parser
    )

    input_label_fn = args["labels"]["fn"]
    input_image_fn = args["imagery"]["raw_fn"]
    output_dir = args["experiment_dir"]
    class_names = args["labels"]["classes"]
    buffer_in_meters = args["labels"]["buffer_in_meters"]
    class_to_buffer = args["labels"]["class_to_buffer"]
    class_to_buffer_by = args["labels"]["class_to_buffer_by"]
    cluster_size = args["labels"].get("cluster_size_in_meters")
    min_pixels_per_cluster = args["labels"].get("min_pixels_per_cluster")
    if min_pixels_per_cluster is None:
        min_pixels_per_cluster = 1000
    num_channels = args["imagery"].get("num_channels")
    overwrite = args["overwrite"]

    # we include +1 as we use 0 as a "not labeled" class by convention
    class_name_to_idx_map = {
        class_name: idx + 1 for idx, class_name in enumerate(class_names)
    }

    do_buffering = True
    if (class_to_buffer not in class_names) or (
        class_to_buffer_by not in class_names
    ):
        print(
            "WARNING: The class to buffer or the class to buffer by is not in the list of classes. Not doing any buffering."
        )
        do_buffering = False

    if set(class_names) != get_class_names_from_labels(input_label_fn):
        print(
            "WARNING: The class names in the config file do not match the class names"
            + " in the input label file."
        )

    assert os.path.exists(input_label_fn)
    assert input_label_fn.endswith(".geojson")
    assert os.path.exists(input_image_fn)
    assert input_image_fn.endswith(".tif")

    name = os.path.basename(input_image_fn).replace(".tif", "")

    # Make sure the output directories exist
    os.makedirs(os.path.join(output_dir, "images"), exist_ok=True)
    os.makedirs(os.path.join(output_dir, "masks"), exist_ok=True)
    os.makedirs(os.path.join(output_dir, "labels"), exist_ok=True)

    # Make a backup of the input label file
    shutil.copy(input_label_fn, os.path.join(output_dir, "labels"))

    # Clustering happens in the imagery CRS so cluster_size is in the same
    # units as the imagery (meters for a projected CRS).
    with rasterio.open(input_image_fn) as f:
        image_crs = f.crs
        dst_crs = image_crs.to_string() if image_crs is not None else None

    if cluster_size is not None:
        validate_cluster_crs(image_crs, input_image_fn)
        print(f"Clustering labels with grid size {cluster_size}...")
        clusters = cluster_labels(input_label_fn, cluster_size, dst_crs)
        print(f"Found {len(clusters)} clusters")
    else:
        # No clustering -- process all labels as a single cluster
        clusters = [{"geom": None, "features": None, "cluster_id": 0}]

    created_files = []
    skipped_existing = 0
    for cluster in clusters:
        cluster_id = cluster["cluster_id"]

        if cluster_size is not None:
            suffix = f"_cluster_{cluster_id}"
            # Write a temporary label file holding just this cluster's
            # features; create_mask_for_labels warps and rasterizes from it.
            temp_label_fn = os.path.join(
                output_dir, f"temp_cluster_{cluster_id}.geojson"
            )
            with fiona.open(input_label_fn) as src:
                schema = src.schema
                crs = src.crs
            with fiona.open(
                temp_label_fn, "w", driver="GeoJSON", crs=crs, schema=schema
            ) as dst:
                for feature in cluster["features"]:
                    dst.write(feature)
            # Cluster geometry is already in the imagery CRS
            crop_geom = cluster["geom"]
        else:
            suffix = ""
            temp_label_fn = input_label_fn
            crop_geom = None

        output_cropped_image_fn = os.path.join(
            output_dir, "images", f"{name}{suffix}_cropped.tif"
        )
        output_buffered_mask_fn = os.path.join(
            output_dir, "masks", f"{name}{suffix}_buffered.tif"
        )
        if (
            os.path.exists(output_cropped_image_fn)
            and os.path.exists(output_buffered_mask_fn)
            and not overwrite
        ):
            print(
                f"Output files for cluster {cluster_id} already exist, use"
                " --overwrite to overwrite them. Skipping."
            )
            skipped_existing += 1
            if cluster_size is not None:
                os.remove(temp_label_fn)
            continue

        try:
            img_fn, mask_fn = create_mask_for_labels(
                temp_label_fn,
                input_image_fn,
                output_dir,
                class_names,
                class_name_to_idx_map,
                buffer_in_meters,
                class_to_buffer,
                class_to_buffer_by,
                do_buffering,
                crop_geom,
                suffix,
                num_channels,
            )
        except ValueError as e:
            # rasterio.mask raises when the crop geometry doesn't overlap the
            # raster -- possible for a grid cell that only covers imagery
            # nodata. Skip that cluster rather than failing the whole run.
            if cluster_size is None:
                raise
            print(f"WARNING: skipping cluster {cluster_id}: {e}")
            continue
        finally:
            if cluster_size is not None and os.path.exists(temp_label_fn):
                os.remove(temp_label_fn)

        # Drop clusters that ended up with too little labeled area to be
        # worth training on.
        with rasterio.open(mask_fn) as f:
            num_labeled_pixels = int(np.sum(f.read(1) > 0))

        if (
            cluster_size is not None
            and num_labeled_pixels < min_pixels_per_cluster
        ):
            print(
                f"Cluster {cluster_id} has only {num_labeled_pixels} labeled"
                f" pixels (min: {min_pixels_per_cluster}), removing..."
            )
            os.remove(img_fn)
            os.remove(mask_fn)
        else:
            print(
                f"Created cluster {cluster_id} with {num_labeled_pixels}"
                " labeled pixels"
            )
            created_files.append((img_fn, mask_fn))

    if not created_files:
        if skipped_existing:
            # Everything already on disk and --overwrite wasn't passed; this is
            # the pre-existing "nothing to do" exit, not a failure.
            print(
                "Output files already exist, use --overwrite to overwrite"
                " them. Exiting."
            )
            return
        raise RuntimeError(
            "No image/mask pairs were created. If clustering is enabled, try a"
            " larger labels.cluster_size_in_meters or a smaller"
            " labels.min_pixels_per_cluster."
        )
    print(f"Successfully created {len(created_files)} image/mask pairs")


if __name__ == "__main__":
    # GDAL CVE compensating control (docs/known-vulnerabilities.md Root
    # Cause C): restrict GDAL drivers in-process. The GDAL_SKIP env in the
    # training image also covers this; soft-fail if hastegeo is absent.
    try:
        from hastegeo.core.utils.gdal_security import harden_gdal

        harden_gdal()
    except Exception:
        pass
    main()
