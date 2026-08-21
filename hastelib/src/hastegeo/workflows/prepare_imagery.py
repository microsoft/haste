# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License.

"""Helper script for running the imagery preprocess workflow."""

import argparse
import json
import os
import sys
import tempfile
from datetime import datetime, timezone
from string import Template

import requests
from hastegeo.core.config import Config
from hastegeo.core.utils.downloader import ImageryDownloader
from hastegeo.core.utils.gdal_security import harden_gdal
from hastegeo.core.utils.imagery import ImageryUtils
from hastegeo.core.utils.imagery import logger as imagery_utils_logger
from hastegeo.core.utils.logs import Logger as HasteLogger

WORKDIR = os.getenv("WORKDIR", ".")
LOG_DIR = os.path.join(WORKDIR, "logs")
LOG_FILE = "imagery_verbose.log"
os.makedirs(LOG_DIR, exist_ok=True)

logger = HasteLogger.get_logger(
    "run_imagery_preprocess", log_dir=LOG_DIR, log_file=LOG_FILE
)
logger.info("Executing %s", __file__)

imagery_utils_logger = HasteLogger.get_logger(
    imagery_utils_logger.name, log_dir=LOG_DIR, log_file=LOG_FILE
)

hasteconfig = Config()
GDAL_WARP_PARAMS = (
    os.getenv("GDAL_WARP_PARAMS") or hasteconfig.gdal_warp_params
)
GDAL_TRANSLATE_PARAMS = (
    os.getenv("GDAL_TRANSLATE_PARAMS") or hasteconfig.gdal_translate_params
)

PRE_EVENT_RAW_PREFIX = hasteconfig.get_artifact_types().PRE_EVENT_RAW.value
PRE_EVENT_PREVIEW_PREFIX = (
    hasteconfig.get_artifact_types().PRE_EVENT_PREVIEW.value
)
PRE_EVENT_MOSAIC_PREFIX = (
    hasteconfig.get_artifact_types().PRE_EVENT_MOSAIC.value
)
PRE_EVENT_PROCESSED_COG_PREFIX = (
    hasteconfig.get_artifact_types().PRE_EVENT_PROCESSED_COG.value
)

POST_EVENT_RAW_PREFIX = hasteconfig.get_artifact_types().POST_EVENT_RAW.value
POST_EVENT_PREVIEW_PREFIX = (
    hasteconfig.get_artifact_types().POST_EVENT_PREVIEW.value
)
POST_EVENT_MOSAIC_PREFIX = (
    hasteconfig.get_artifact_types().POST_EVENT_MOSAIC.value
)
POST_EVENT_PROCESSED_COG_PREFIX = (
    hasteconfig.get_artifact_types().POST_EVENT_PROCESSED_COG.value
)
BUILDING_FOOTPRINTS_PREFIX = (
    hasteconfig.get_artifact_types().BUILDING_FOOTPRINTS.value
)
VALID_AREA_MASK_PREFIX = hasteconfig.get_artifact_types().VALID_AREA_MASK.value


class ImageryWorkflow:
    """Class to handle all steps in the imagery workflow."""

    def __init__(
        self,
        pre_event_urls=None,
        post_event_urls=None,
        source_type_pre_event=None,
        source_type_post_event=None,
        project_id=None,
        image_layer_id=None,
        fine_tune=False,
        dst_directory=None,
        user_building_footprints_url=None,
        clip_bbox=None,
    ):
        """Initialize the ImageryWorkflow class.
        Args:
            pre_event_urls (list): List of URLs for pre-event imagery.
            post_event_urls (list): List of URLs for post-event imagery.
            source_type_pre_event (str): Source of pre-event imagery (e.g., "maxar", "planet")
            source_type_post_event (str): Source of post-event imagery (e.g., "maxar", "planet")
            project_id (str): Project ID.
            image_layer_id (str): Image layer ID.
            fine_tune (bool): Flag to indicate if fine-tuning is needed.
            dst_directory (str): Directory to save processed files.
            user_building_footprints_url (str): Optional URL to a user-supplied
                building-footprints GeoPackage. When set, the workflow skips
                the Overture Maps download and instead downloads, reprojects
                (to EPSG:4326), and clips this file to the AOI.
        """
        self.pre_event_urls = pre_event_urls
        self.post_event_urls = post_event_urls
        self.source_type_pre_event = source_type_pre_event
        self.source_type_post_event = source_type_post_event
        self.project_id = project_id
        self.image_layer_id = image_layer_id
        self.fine_tune = fine_tune
        self.dst_directory = dst_directory or os.path.join(".", "outputs")
        self.user_building_footprints_url = user_building_footprints_url
        # Optional server-side clip AOI ([w, s, e, n] EPSG:4326). Applied to
        # both pre and post mosaics so only the drawn area is processed.
        self.clip_bbox = clip_bbox

        self.pre_event_raw_paths = []
        self.pre_event_preview_paths = []
        self.mosaic_pre_event_tif_filepath = ""
        self.pre_event_processed_path = ""

        self.post_event_raw_paths = []
        self.post_event_preview_paths = []
        self.mosaic_post_event_tif_filepath = ""
        self.post_event_processed_path = ""

        self.normalization_means = []
        self.normalization_stds = []
        self.building_footprints_path = ""
        # Human-readable error captured when the building-footprint step
        # fails — applies equally to the Overture download path and the
        # user-supplied path. The step is intentionally a soft-failure
        # inside this container (so the imagery COGs that have already
        # been produced still get uploaded with the manifest), but the
        # message is propagated through the manifest so
        # ImageryPostProcessor can mark the image layer FAILED and
        # surface the cause in the UI's statusMessage.
        self.building_footprints_error = ""
        # Path to the valid-area-mask GeoJSON file (the post-event AOI
        # polygon, EPSG:4326) and any error captured while extracting it.
        # The mask shares its extraction step with the building-footprints
        # bbox computation, so the same AOI failure will be surfaced here
        # (and on building_footprints_error).
        self.valid_area_mask_path = ""
        self.valid_area_mask_error = ""

    def generate_prefix(self, prefix: Template):
        """Generate a prefix for the output files based on the project ID and image layer ID."""
        return prefix.substitute(
            projectId=self.project_id,
            imageLayerId=self.image_layer_id,
        )

    def download_pre_event(self):
        """Download pre-event imagery from provided URLs.
        Save the downloaded files with a prefix based on the project ID and image layer ID.
        """
        preevent_tif_files = _download_imagery(
            urls=self.pre_event_urls,
            dst_directory=self.dst_directory,
        )
        if preevent_tif_files:
            raw_prefix = self.generate_prefix(PRE_EVENT_RAW_PREFIX)
            (
                self.pre_event_raw_paths,
                self.pre_event_preview_paths,
            ) = _save_raw_imagery(
                files_paths=preevent_tif_files,
                generate_preview=False,
                raw_prefix=raw_prefix,
            )

    def download_post_event(self):
        """Download post-event imagery from provided URLs.
        Save the downloaded files with a prefix based on the project ID and image layer ID.
        """
        postevent_tif_files = _download_imagery(
            urls=self.post_event_urls,
            dst_directory=self.dst_directory,
        )
        if not postevent_tif_files:
            raise RuntimeError("No post event imagery to process. ")
        if not postevent_tif_files or len(postevent_tif_files) == 0:
            raise RuntimeError("Unable to download raw imagery")
        elif not _are_all_valid_tif_files(postevent_tif_files):
            raise RuntimeError("Invalid files found.")

        raw_prefix = self.generate_prefix(POST_EVENT_RAW_PREFIX)
        preview_prefix = self.generate_prefix(POST_EVENT_PREVIEW_PREFIX)

        (
            self.post_event_raw_paths,
            self.post_event_preview_paths,
        ) = _save_raw_imagery(
            files_paths=postevent_tif_files,
            generate_preview=True,
            raw_prefix=raw_prefix,
            preview_prefix=preview_prefix,
        )

    def process_pre_event(self):
        """Process pre-event imagery.
        Create a mosaic of the pre-event imagery and convert it to a COG format.
        Save the processed file with a prefix based on the project ID and image layer ID.
        """
        if not self.pre_event_raw_paths or len(self.pre_event_raw_paths) == 0:
            logger.info("No pre event imagery to process")
            return
        save_as_prefix = self.generate_prefix(PRE_EVENT_MOSAIC_PREFIX)
        self.mosaic_pre_event_tif_filepath = _create_mosaic_cog(
            self.pre_event_raw_paths,
            dst_directory=self.dst_directory,
            save_as_prefix=save_as_prefix,
            clip_bbox=self.clip_bbox,
        )

        cog_file_name = self.generate_prefix(PRE_EVENT_PROCESSED_COG_PREFIX)
        self.pre_event_processed_path = ImageryUtils.convert_to_rgb_cog(
            tif_file=self.mosaic_pre_event_tif_filepath,
            output_file_path=os.path.join(
                self.dst_directory, f"{cog_file_name}.tif"
            ),
            gdal_translate_params=GDAL_TRANSLATE_PARAMS,
            source_type=self.source_type_pre_event,
            scale_rgb_params=_determine_scale_rgb_params(
                self.source_type_pre_event
            ),
        )

        if (
            not self.pre_event_processed_path
            or os.path.getsize(self.pre_event_processed_path) == 0
        ):
            raise RuntimeError(
                "Error creating RGB adjusted COG GeoTIFF for pre event imagery, invalid input file(s)."
            )

    def process_post_event(self):
        """Process post-event imagery.
        Create a mosaic of the post-event imagery and convert it to a COG format.
        Fine tune it if specified.
        Additionally, calculate normalization means and standard deviations."""
        # The raw mosaic COG (without RGB band and scale adjustments) serves as primary input to training and inference

        scale_rgb_params = _determine_scale_rgb_params(
            self.source_type_post_event
        )
        save_as_prefix = self.generate_prefix(POST_EVENT_MOSAIC_PREFIX)
        self.mosaic_post_event_tif_filepath = _create_mosaic_cog(
            self.post_event_raw_paths,
            dst_directory=self.dst_directory,
            save_as_prefix=save_as_prefix,
            clip_bbox=self.clip_bbox,
        )

        # The RGB band and scale adjusted imagery serves as supporting input to training and inference
        cog_file_name = self.generate_prefix(POST_EVENT_PROCESSED_COG_PREFIX)

        self.post_event_processed_path = ImageryUtils.convert_to_rgb_cog(
            tif_file=self.mosaic_post_event_tif_filepath,
            output_file_path=os.path.join(
                self.dst_directory, f"{cog_file_name}.tif"
            ),
            gdal_translate_params=GDAL_TRANSLATE_PARAMS,
            source_type=self.source_type_post_event,
            scale_rgb_params=scale_rgb_params,
        )
        if (
            not self.post_event_processed_path
            or os.path.getsize(self.post_event_processed_path) == 0
        ):
            raise RuntimeError(
                "Error creating RGB adjusted COG GeoTIFF for post event imagery, invalid input file(s)."
            )

        # Fine tuned file is generated with the same name as the processed file
        if self.fine_tune:
            self.post_event_processed_path = fine_tune_file(
                self.post_event_processed_path,
                scale_rgb_params=scale_rgb_params,
                dst_directory=self.dst_directory,
                save_as_prefix=cog_file_name,
                source_type=self.source_type_post_event,
            )

        self.normalization_means = ImageryUtils.get_normalization_means(
            self.mosaic_post_event_tif_filepath,
            source_type=self.source_type_post_event,
        )

        self.normalization_stds = ImageryUtils.get_normalization_std_devs(
            self.mosaic_post_event_tif_filepath,
            source_type=self.source_type_post_event,
        )

    def download_building_footprints(self):
        """Download Overture Maps building footprints for this layer's AOI.

        Derives the AOI from the post-event mosaic COG produced by
        :meth:`process_post_event` and writes a per-layer GeoPackage into
        ``self.dst_directory``.

        The download itself is delegated to a subprocess
        (``python -m hastegeo.core.utils.footprints``) so a crash in pyarrow's
        native code (e.g. when running under QEMU x86_64 emulation on arm64
        hosts), an Overture query timeout, or any other Overture-side fault
        is contained to a child process and does not take down the parent
        imageryprep workflow.

        Failure handling is deliberately split between two layers:

        * **Inside this container**, every failure mode is caught and
          recorded on ``self.building_footprints_error`` rather than
          re-raised. This lets the workflow continue past this step so the
          imagery COGs that have already been produced are still written to
          the manifest and uploaded.
        * **Outside this container**, ``ImageryPostProcessor`` reads the
          captured error from the manifest and marks the image layer
          FAILED with the same message, so the UI surfaces a clear cause
          instead of silently leaving the layer in a state where every
          inference run will fail.

        Sets ``self.building_footprints_path`` on success, or
        ``self.building_footprints_error`` (UI-displayable) on any failure.
        Also sets ``self.valid_area_mask_path`` to the AOI polygon GeoJSON
        on success (or ``self.valid_area_mask_error`` if the mask itself
        could not be extracted/saved). The two artifacts share an AOI
        extraction so they typically succeed or fail together.
        """
        if not self.mosaic_post_event_tif_filepath or not os.path.exists(
            self.mosaic_post_event_tif_filepath
        ):
            msg = (
                "Cannot download building footprints: post-event mosaic "
                "is not available."
            )
            logger.error(msg)
            self.building_footprints_path = ""
            self.building_footprints_error = msg
            self.valid_area_mask_path = ""
            self.valid_area_mask_error = (
                "Cannot extract valid-area mask: post-event mosaic is "
                "not available."
            )
            return

        prefix = self.generate_prefix(BUILDING_FOOTPRINTS_PREFIX)
        output_path = os.path.join(self.dst_directory, f"{prefix}.gpkg")
        mask_prefix = self.generate_prefix(VALID_AREA_MASK_PREFIX)
        mask_output_path = os.path.join(
            self.dst_directory, f"{mask_prefix}.geojson"
        )

        try:
            from hastegeo.core.utils.aoi import (
                extract_aoi_polygon,
                save_polygon_as_geojson,
            )

            # One AOI extraction serves both outputs: bbox-filter Overture
            # and persist the polygon as the downloadable valid-area mask.
            aoi_polygon = extract_aoi_polygon(
                self.mosaic_post_event_tif_filepath
            )
            bbox = aoi_polygon.bounds
        except Exception as exc:
            logger.error(
                "Failed extracting AOI for image layer %s",
                self.image_layer_id,
                exc_info=True,
            )
            self.building_footprints_path = ""
            self.building_footprints_error = (
                "Failed to extract area-of-interest from the post-event "
                f"mosaic before downloading building footprints: {exc}"
            )
            self.valid_area_mask_path = ""
            self.valid_area_mask_error = (
                "Failed to extract area-of-interest polygon from the "
                f"post-event mosaic: {exc}"
            )
            return

        # Persist the AOI polygon before kicking off the Overture
        # subprocess so the mask is captured even if the footprint
        # download later fails. Saving the geojson is a tiny local I/O
        # operation; failures here are also soft (recorded on
        # valid_area_mask_error) so they don't abort the footprint step.
        try:
            save_polygon_as_geojson(aoi_polygon, mask_output_path)
            self.valid_area_mask_path = mask_output_path
            self.valid_area_mask_error = ""
        except Exception as exc:
            logger.error(
                "Failed writing valid-area mask GeoJSON for image layer %s",
                self.image_layer_id,
                exc_info=True,
            )
            self.valid_area_mask_path = ""
            self.valid_area_mask_error = (
                "Failed to save valid-area-mask GeoJSON: " f"{exc}"
            )

        cmd = [
            sys.executable,
            "-m",
            "hastegeo.core.utils.footprints",
            # Use --bbox=VALUE so argparse doesn't treat a leading '-' in the
            # first coordinate (e.g. -156.7,...) as another option flag.
            f"--bbox={bbox[0]},{bbox[1]},{bbox[2]},{bbox[3]}",
            "--output-path",
            output_path,
            "--overwrite",
        ]
        # If the AOI polygon was saved successfully, hand its path to the
        # subprocess so the downloader can drop bbox-cornered footprints
        # that fall outside the actual valid-data region. Skipped silently
        # when the mask is missing (the bbox-only result is still useful).
        if self.valid_area_mask_path:
            cmd.append(f"--aoi-geojson={self.valid_area_mask_path}")
        timeout_seconds = int(
            os.getenv("HASTE_FOOTPRINTS_TIMEOUT_SECONDS", "1800")
        )
        try:
            import subprocess

            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=timeout_seconds,
                check=False,
            )
        except subprocess.TimeoutExpired:
            logger.error(
                "Building-footprint subprocess timed out after %ss for "
                "image layer %s",
                timeout_seconds,
                self.image_layer_id,
                exc_info=True,
            )
            self.building_footprints_path = ""
            self.building_footprints_error = (
                "Building-footprint download timed out after "
                f"{timeout_seconds} seconds."
            )
            return
        except Exception as exc:
            logger.error(
                "Building-footprint subprocess raised for image layer %s",
                self.image_layer_id,
                exc_info=True,
            )
            self.building_footprints_path = ""
            self.building_footprints_error = (
                "Building-footprint download could not be started: " f"{exc}"
            )
            return

        if result.returncode != 0 or not os.path.exists(output_path):
            stderr_tail = (result.stderr or "").strip().splitlines()
            stderr_msg = stderr_tail[-1] if stderr_tail else ""
            logger.error(
                "Building-footprint subprocess failed for image layer "
                "%s (returncode=%s). stderr:\n%s",
                self.image_layer_id,
                result.returncode,
                (result.stderr or "")[-2000:],
            )
            self.building_footprints_path = ""
            self.building_footprints_error = (
                "Building-footprint download failed "
                f"(exit code {result.returncode})"
                + (f": {stderr_msg}" if stderr_msg else ".")
            )
            return

        count = (result.stdout or "").strip().splitlines()
        count_msg = count[-1] if count else "?"
        logger.info(
            "Downloaded %s building footprints for image layer %s",
            count_msg,
            self.image_layer_id,
        )
        self.building_footprints_path = output_path
        self.building_footprints_error = ""

    def process_user_building_footprints(self):
        """Download, reproject, and clip a user-supplied building-footprint GPKG.

        This is the user-supplied counterpart to
        :meth:`download_building_footprints`. When the image layer was
        created with ``userBuildingFootprintsUrl`` set, the workflow takes
        this path *instead of* the Overture Maps download — the goal is
        to produce a GPKG file with the same shape (name from the
        BUILDING_FOOTPRINTS template, EPSG:4326, Polygon/MultiPolygon
        only, ``id``/``geometry``/``subtype``/``class`` columns) so the
        rest of the pipeline treats the two paths interchangeably.

        Failure handling mirrors the Overture path: errors are captured
        on ``self.building_footprints_error`` rather than raising, so the
        manifest still uploads the imagery COGs that have already been
        produced. ``ImageryPostProcessor`` reads the captured error and
        marks the image layer FAILED with the same message.

        Re-validates the URL via :func:`validate_footprint_url` before
        download (defense-in-depth against config rewrites that bypass
        the API allowlist check).

        Also persists the AOI polygon as the valid-area mask GeoJSON
        (``self.valid_area_mask_path``), mirroring
        :meth:`download_building_footprints`. Without this, layers
        processed via the user-supplied path would have no
        ``validAreaMaskUrl`` and the UI's "Download Valid Area Mask"
        menu would be greyed out.
        """
        if not self.mosaic_post_event_tif_filepath or not os.path.exists(
            self.mosaic_post_event_tif_filepath
        ):
            msg = (
                "Cannot process user-supplied building footprints: "
                "post-event mosaic is not available."
            )
            logger.error(msg)
            self.building_footprints_path = ""
            self.building_footprints_error = msg
            self.valid_area_mask_path = ""
            self.valid_area_mask_error = (
                "Cannot extract valid-area mask: post-event mosaic is "
                "not available."
            )
            return

        try:
            from hastegeo.core.utils.url_allowlist import (
                validate_footprint_url,
            )

            validate_footprint_url(self.user_building_footprints_url)
        except Exception as exc:
            logger.error(
                "User-supplied building-footprints URL failed validation "
                "for image layer %s",
                self.image_layer_id,
                exc_info=True,
            )
            self.building_footprints_path = ""
            self.building_footprints_error = (
                "User-supplied building-footprints URL is not allowed: "
                f"{exc}"
            )
            return

        try:
            from hastegeo.core.utils.aoi import (
                extract_aoi_polygon,
                save_polygon_as_geojson,
            )

            aoi_polygon = extract_aoi_polygon(
                self.mosaic_post_event_tif_filepath
            )
        except Exception as exc:
            logger.error(
                "Failed extracting AOI for image layer %s",
                self.image_layer_id,
                exc_info=True,
            )
            self.building_footprints_path = ""
            self.building_footprints_error = (
                "Failed to extract area-of-interest from the post-event "
                "mosaic before processing custom building footprints: "
                f"{exc}"
            )
            self.valid_area_mask_path = ""
            self.valid_area_mask_error = (
                "Failed to extract area-of-interest polygon from the "
                f"post-event mosaic: {exc}"
            )
            return

        # Persist the AOI polygon as the downloadable valid-area mask
        # before the user-footprint download/clip runs, so the mask is
        # captured even if those later steps fail. Mirrors the same
        # save-then-process ordering used by download_building_footprints
        # (the Overture path). Failures here are soft — recorded on
        # valid_area_mask_error rather than aborting the footprint step.
        mask_prefix = self.generate_prefix(VALID_AREA_MASK_PREFIX)
        mask_output_path = os.path.join(
            self.dst_directory, f"{mask_prefix}.geojson"
        )
        try:
            save_polygon_as_geojson(aoi_polygon, mask_output_path)
            self.valid_area_mask_path = mask_output_path
            self.valid_area_mask_error = ""
        except Exception as exc:
            logger.error(
                "Failed writing valid-area mask GeoJSON for image layer %s",
                self.image_layer_id,
                exc_info=True,
            )
            self.valid_area_mask_path = ""
            self.valid_area_mask_error = (
                "Failed to save valid-area-mask GeoJSON: " f"{exc}"
            )

        prefix = self.generate_prefix(BUILDING_FOOTPRINTS_PREFIX)
        output_path = os.path.join(self.dst_directory, f"{prefix}.gpkg")

        # Stage the download in a scratch dir so the runner's
        # outputs/*.* upload glob doesn't accidentally upload the raw
        # user input alongside the clipped artifact.
        max_bytes = int(
            os.getenv(
                "HASTE_USER_FOOTPRINTS_MAX_BYTES", str(500 * 1024 * 1024)
            )
        )
        download_timeout = int(
            os.getenv("HASTE_USER_FOOTPRINTS_TIMEOUT_SECONDS", "300")
        )

        with tempfile.TemporaryDirectory(prefix="user_footprints_") as scratch:
            staged_path = os.path.join(scratch, "user_footprints.gpkg")
            try:
                self._download_user_footprints_to(
                    self.user_building_footprints_url,
                    staged_path,
                    max_bytes=max_bytes,
                    timeout_seconds=download_timeout,
                )
            except Exception as exc:
                logger.error(
                    "Failed downloading user-supplied building footprints "
                    "for image layer %s",
                    self.image_layer_id,
                    exc_info=True,
                )
                self.building_footprints_path = ""
                self.building_footprints_error = (
                    "Failed to download user-supplied building footprints: "
                    f"{exc}"
                )
                return

            try:
                from hastegeo.core.utils.footprints import (
                    clip_and_normalize_user_footprints,
                )

                count = clip_and_normalize_user_footprints(
                    input_path=staged_path,
                    aoi_polygon=aoi_polygon,
                    output_path=output_path,
                    overwrite=True,
                )
            except Exception as exc:
                logger.error(
                    "Failed clipping user-supplied building footprints "
                    "for image layer %s",
                    self.image_layer_id,
                    exc_info=True,
                )
                self.building_footprints_path = ""
                self.building_footprints_error = (
                    "Failed to process user-supplied building footprints: "
                    f"{exc}"
                )
                return

        logger.info(
            "Wrote %d user-supplied building footprints (clipped to AOI) "
            "for image layer %s",
            count,
            self.image_layer_id,
        )
        self.building_footprints_path = output_path
        self.building_footprints_error = ""

    def _download_user_footprints_to(
        self,
        url: str,
        output_path: str,
        *,
        max_bytes: int,
        timeout_seconds: int,
    ):
        """Download the user-supplied gpkg to ``output_path``.

        One-shot fetch (no streaming) — the response body is read fully
        into memory, size-checked against ``max_bytes``, and written
        atomically. Refuses to follow cross-host redirects (so an
        allowlisted source can't bounce us to an internal host) and
        bounds the in-memory load at ``max_bytes`` (so a hostile or
        accidental multi-GB upload can't OOM the imageryprep container).
        """
        # Single-shot fetch — no streaming. ``allow_redirects=False`` so
        # an allowlisted source can't redirect to an internal host;
        # ``raise_for_status`` to fail loudly on 4xx/5xx; size check
        # against ``max_bytes`` to bound memory + disk; then atomic write.
        resp = requests.get(
            url, timeout=timeout_seconds, allow_redirects=False
        )
        if resp.status_code in (301, 302, 303, 307, 308):
            raise RuntimeError(
                "Redirects are not followed for user-supplied "
                f"building-footprint URLs (got {resp.status_code})."
            )
        resp.raise_for_status()
        if len(resp.content) > max_bytes:
            raise RuntimeError(
                f"User-supplied building footprints exceed the max size of "
                f"{max_bytes} bytes (got {len(resp.content)} bytes)."
            )
        with open(output_path, "wb") as f:
            f.write(resp.content)


def _download_imagery(urls, dst_directory):
    """Download imagery from provided URLs.
    Args:
        urls (list): List of URLs to download.
        dst_directory (str): Directory to save downloaded files.
    Returns:
        list: List of downloaded file paths.
    """
    if not urls:
        return []
    downloader = ImageryDownloader(
        sourceType="url", log_dir=LOG_DIR, log_file=LOG_FILE
    )
    download_params = {"urls": urls, "dst_directory": dst_directory}
    downloadedUrls = downloader.download_imagery(**download_params) or []
    if not downloadedUrls:
        raise RuntimeError(f"Unable to download raw imagery from URLs {urls}")
    return downloadedUrls


def _save_raw_imagery(
    files_paths,
    generate_preview=False,
    raw_prefix: str = None,
    preview_prefix: str = None,
):
    """Save raw imagery files with a specified prefix.
    Generates previews if specified.
    Args:
        files_paths (list): List of file paths to save.
        generate_preview (bool): (Optional) Flag to indicate if preview images should be generated.
                                Defaults to False
        save_as_prefix (str): (Optional) Prefix for the saved files.
    Returns:
        tuple: Tuple containing lists of raw image paths and preview image paths.
    """
    raw_image_paths = []
    preview_image_paths = []
    for file_path in files_paths:
        base_filename = os.path.basename(file_path)
        new_name = f"{raw_prefix}_{base_filename}"
        new_path = os.path.join(os.path.dirname(file_path), new_name)
        if generate_preview:
            preview_name = (
                f"{preview_prefix}_{os.path.splitext(base_filename)[0]}.jpeg"
            )
            preview_path = os.path.join(
                os.path.dirname(file_path), preview_name
            )
            ImageryUtils.convert_tif_to_jpeg(file_path, preview_path)
            preview_image_paths.append(preview_path)
        os.rename(file_path, new_path)
        raw_image_paths.append(new_path)
    return raw_image_paths, preview_image_paths


def _create_mosaic_cog(
    tif_files, dst_directory=None, save_as_prefix=None, clip_bbox=None
):
    """Create a mosaic of TIFF files and convert to COG.
    Args:
        tif_files (list): List of TIFF files to mosaic (combine).
        dst_directory (str): (Optional) Directory to save the mosaic file. Defaults to current directory
        save_as_prefix (str): (Optional) Prefix for the saved mosaic file.
        clip_bbox (list): (Optional) [w, s, e, n] EPSG:4326 AOI to clip to.
    Returns:
        str: Path to the created mosaic file."""
    dst_directory = dst_directory or "."
    return ImageryUtils.mosaic_imagery(
        tif_files,
        os.path.join(dst_directory, f"{save_as_prefix}.tif"),
        GDAL_WARP_PARAMS,
        clip_bbox=clip_bbox,
    )


def _determine_scale_rgb_params(source_type):
    """Determine if scale RGB parameters are needed based on the source type.
    Args:
        source_type (str): Source type of the imagery.
    Returns:
        bool: True if scale RGB parameters are needed, False otherwise.
    """
    if source_type in ["planet_scope", "planet_skysat"]:
        return True
    return False


def _are_all_valid_tif_files(tif_files):
    """Check if all files in the list are valid TIFF files.
    Args:
        tif_files (list): List of TIFF files to check.
    Returns:
        bool: True if all files are valid TIFF files, False otherwise.
    Raises:
        RuntimeError: If no TIFF files are found or if any file is not a valid TIFF file.
    """
    if not tif_files or len(tif_files) == 0:
        raise RuntimeError("No TIFF files found")

    for tif_file in tif_files:
        if not tif_file or not ImageryUtils.is_gtiff(tif_file):
            raise RuntimeError(f"Invalid TIFF file: {tif_file}")
    return True


def fine_tune_file(
    post_event_processed_path,
    scale_rgb_params,
    dst_directory=None,
    save_as_prefix=None,
    source_type=None,
):
    """Fine-tune a GeoTIFF file.
    Args:
        post_event_processed_path (str): Path to the input GeoTIFF file.
        scale_rgb_params (bool): Flag to indicate if scale RGB parameters are needed.
        dst_directory (str): (Optional) Directory to save the fine-tuned file. Defaults to current directory.
        save_as_prefix (str): (Optional) Prefix for the saved fine-tuned file.
        source_type (str): Source type of the imagery."""
    dst_directory = dst_directory or "."
    os.makedirs(os.path.join(WORKDIR, "temp"), exist_ok=True)
    temp_path = os.path.join(WORKDIR, "temp", f"temp_{save_as_prefix}.tif")
    if post_event_processed_path:
        ImageryUtils.fine_tune_gtiff(
            file_path=post_event_processed_path,
            output_path=temp_path,
        )
        return ImageryUtils.convert_to_rgb_cog(
            tif_file=temp_path,
            output_file_path=os.path.join(
                dst_directory, f"{save_as_prefix}.tif"
            ),
            gdal_translate_params=GDAL_TRANSLATE_PARAMS,
            source_type=source_type,
            scale_rgb_params=scale_rgb_params,
        )
    raise RuntimeError("Unable to fine-tune COG GeoTIFF, invalid file.")


def log_progress(message):
    """Write progress steps and messages to a file"""
    # Create a directory for logs if it doesn't exist
    log_file = os.path.join(LOG_DIR, "imagery_friendly.log")

    with open(log_file, "a") as f:
        f.write(f"{datetime.now(timezone.utc).isoformat()}|{message}\n")


def main():
    # Restrict GDAL to the driver allowlist before any imagery parsing
    # (GDAL CVE compensating control — docs/known-vulnerabilities.md
    # Root Cause C). Idempotent; also runs at ImageryUtils import.
    harden_gdal()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--config", type=str, required=True, help="Path to config file"
    )

    args = parser.parse_args()

    if not os.path.exists(args.config):
        logger.error("No config file found at location %s", args.config)
        sys.exit(1)

    with open(args.config) as f:
        config = json.load(f)

    if not config:
        logger.error("Config file is empty")
        sys.exit(1)

    output_dir = os.path.join(WORKDIR, config.get("output_dir", "outputs"))
    os.makedirs(output_dir, exist_ok=True)

    try:
        imagery_workflow = ImageryWorkflow(
            pre_event_urls=config.get("pre_event_imagery_urls"),
            post_event_urls=config.get("post_event_imagery_urls"),
            project_id=config.get("project_id"),
            image_layer_id=config.get("image_layer_id"),
            source_type_pre_event=config.get("source_type_pre_event"),
            source_type_post_event=config.get("source_type_post_event"),
            fine_tune=config.get("fine_tune", False),
            dst_directory=output_dir,
            user_building_footprints_url=config.get(
                "user_building_footprints_url"
            ),
            clip_bbox=config.get("clip_bbox"),
        )

        log_progress("Downloading imagery")
        imagery_workflow.download_pre_event()
        config["raw_pre_event_filenames"] = [
            os.path.basename(f) for f in imagery_workflow.pre_event_raw_paths
        ]
        config["preview_pre_event_filenames"] = [
            os.path.basename(f)
            for f in imagery_workflow.pre_event_preview_paths
        ]

        imagery_workflow.download_post_event()
        config["raw_post_event_filenames"] = [
            os.path.basename(f) for f in imagery_workflow.post_event_raw_paths
        ]
        config["preview_post_event_filenames"] = [
            os.path.basename(f)
            for f in imagery_workflow.post_event_preview_paths
        ]

        log_progress("Converting to COG")
        imagery_workflow.process_pre_event()
        config["pre_event_mosaic_filename"] = os.path.basename(
            imagery_workflow.mosaic_pre_event_tif_filepath
        )
        config["pre_event_processed_filename"] = os.path.basename(
            imagery_workflow.pre_event_processed_path
        )

        imagery_workflow.process_post_event()
        config["post_event_mosaic_filename"] = os.path.basename(
            imagery_workflow.mosaic_post_event_tif_filepath
        )
        config["post_event_processed_filename"] = os.path.basename(
            imagery_workflow.post_event_processed_path
        )
        config["normalization_means"] = imagery_workflow.normalization_means
        config["normalization_stds"] = imagery_workflow.normalization_stds

        log_progress("Downloading building footprints")
        if imagery_workflow.user_building_footprints_url:
            # User explicitly supplied a GPKG URL; skip the Overture
            # download path entirely and clip/reproject the user file.
            imagery_workflow.process_user_building_footprints()
        else:
            imagery_workflow.download_building_footprints()
        config["building_footprints_filename"] = (
            os.path.basename(imagery_workflow.building_footprints_path)
            if imagery_workflow.building_footprints_path
            else ""
        )
        # Propagate any captured failure message so ImageryPostProcessor
        # can mark the layer FAILED with a UI-displayable cause without
        # this subprocess having to raise (which would lose the imagery
        # COGs we have already produced above). Applies equally to the
        # Overture and user-supplied paths.
        config[
            "building_footprints_error"
        ] = imagery_workflow.building_footprints_error
        # Valid-area mask is generated as a side-effect of the same AOI
        # extraction. It's surfaced as a downloadable artifact in the UI;
        # a missing mask is logged but not treated as a layer-failure on
        # its own — the building-footprints error already covers any
        # shared AOI failure.
        config["valid_area_mask_filename"] = (
            os.path.basename(imagery_workflow.valid_area_mask_path)
            if imagery_workflow.valid_area_mask_path
            else ""
        )
        config[
            "valid_area_mask_error"
        ] = imagery_workflow.valid_area_mask_error

        log_progress("Finalizing outputs")
        with open(os.path.join(output_dir, "imagery_manifest.json"), "w") as f:
            json.dump(config, f, indent=4)
        logger.info("Imagery preprocessing completed successfully.")
    except Exception as e:
        logger.error("Error during imagery preprocessing", exc_info=True)
        log_progress(f"Error during imagery preprocessing: {e}")
        raise e


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        logger.error(f"Error during main execution: {e}", exc_info=True)
        sys.exit(1)
