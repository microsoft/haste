# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License.
import os
import traceback
from pathlib import Path
from typing import List

import cv2  # type: ignore
import numpy as np  # type: ignore
import rasterio
from osgeo import gdal

from ..utils.logs import Logger
from .gdal_security import harden_gdal
from .source_types import normalize_source_type

# Restrict GDAL to an allowlist of drivers (and enable exceptions) before
# any imagery is parsed — compensating control for the deferred GDAL CVE
# exception (docs/known-vulnerabilities.md Root Cause C).
harden_gdal()

logger = Logger.get_logger(__name__)


class ImageryUtils:
    """
    A utility class for performing various image processing tasks on geospatial imagery.

    Methods:
        adjust_contrast(image: numpy.ndarray) -> numpy.ndarray:
            Adjust the contrast of the given image using histogram equalization.

        reduce_noise(image: numpy.ndarray) -> numpy.ndarray:
            Reduce noise in the given image using median blur.

        is_gtiff(file_path: str) -> bool:
            Check if the given file is a GeoTIFF.

        is_cog(file_path: str) -> bool:
            Check if the given file is a Cloud Optimized GeoTIFF (COG).

        is_rgb(file_path: str) -> bool:
            Check if the given file is an RGB image.

        fine_tune_gtiff(file_path: str, output_path: str, adjust_contrast: bool) -> bool:
            Fine-tune a GeoTIFF file by optionally adjusting contrast and reducing noise.

        convert_to_rgb_cog(tif_files: List[str], output_file_path: str = None, gdal_warp_params: str = '', gdal_translate_params:str='') -> str:
            Convert a list of TIFF files to a single RGB Cloud Optimized GeoTIFF (COG).

        convert_tif_to_jpeg(tif_path: str, output_path: str = None, quality_percentage: str = "100") -> str:
            Convert a TIFF file to a JPEG file with optional quality percentage.
    """

    @staticmethod
    def adjust_contrast(image):
        return cv2.equalizeHist(image)

    @staticmethod
    def reduce_noise(image):
        return cv2.medianBlur(image, 3)

    @staticmethod
    def is_gtiff(file_path):
        """
        Check if the given file is a GeoTIFF file.

        This method attempts to open the file using GDAL and checks if the file's
        driver is 'GTiff' (GeoTIFF format).

        Args:
            file_path (str): The path to the file to be checked.

        Returns:
            bool: True if the file is a GeoTIFF, False otherwise.
        """
        try:
            with gdal.Open(file_path) as dataset:
                if dataset is None:
                    return False
                if dataset.GetDriver().ShortName != "GTiff":
                    return False
                return True
        except (OSError, RuntimeError):
            return False

    @staticmethod
    def is_cog(file_path):
        """
        Check if a given file is a Cloud Optimized GeoTIFF (COG).

        A Cloud Optimized GeoTIFF (COG) is a regular GeoTIFF that is organized in a way that makes it more efficient for cloud-based applications.

        Args:
            file_path (str): The path to the file to be checked.

        Returns:
            bool: True if the file is a COG, False otherwise.
        """
        try:
            with gdal.Open(file_path) as dataset:
                if dataset is None:
                    return False
                metadata = dataset.GetMetadata("IMAGE_STRUCTURE")

                if "COMPRESSION" not in metadata or metadata[
                    "COMPRESSION"
                ] not in (
                    "DEFLATE",
                    "LZW",
                ):
                    return False
                if "LAYOUT" not in metadata or metadata["LAYOUT"] != "COG":
                    return False
                return True
        except (OSError, RuntimeError):
            return False

    @staticmethod
    def is_rgb(file_path):
        """
        Check if the given file is an RGB image.

        Args:
            file_path (str): The path to the file to check.

        Returns:
            bool: True if the file is an RGB image, False otherwise.
        """
        try:
            with gdal.Open(file_path) as dataset:
                if dataset is None or dataset.RasterCount < 3:
                    return False

                color_interpretation = [
                    "Undefined",
                    "Gray",
                    "Palette",
                    "Red",
                    "Green",
                    "Blue",
                    "Alpha",
                    "Hue",
                    "Saturation",
                    "Lightness",
                    "Cyan",
                    "Magenta",
                    "Yellow",
                    "Black",
                    "YCbCr_Y",
                    "YCbCr_Cb",
                    "YCbCr_Cr",
                ]
                colors = [
                    color_interpretation[
                        dataset.GetRasterBand(i).GetColorInterpretation()
                    ]
                    for i in range(1, 4)
                ]
                return colors == ["Red", "Green", "Blue"]
        except (OSError, RuntimeError):
            return False

    @staticmethod
    def fine_tune_gtiff(file_path, output_path, adjust_contrast=False):
        """
        Fine-tunes a GeoTIFF file by optionally adjusting its contrast and reducing noise.

        Args:
            file_path (str): The path to the input GeoTIFF file.
            output_path (str): The path where the output GeoTIFF file will be saved.
            adjust_contrast (bool, optional): If True, adjusts the contrast of the image. Defaults to False.

        Returns:
            bool: True if the operation was successful, False otherwise.
        """
        try:
            with gdal.Open(file_path) as dataset:
                if dataset is None:
                    return False
                driver = gdal.GetDriverByName("GTiff")
                out_dataset = driver.CreateCopy(output_path, dataset, 0)
                for i in range(1, dataset.RasterCount + 1):
                    band = dataset.GetRasterBand(i)
                    data = band.ReadAsArray()
                    if adjust_contrast:
                        data = ImageryUtils.adjust_contrast(data)
                    data = ImageryUtils.reduce_noise(data)
                    out_band = out_dataset.GetRasterBand(i)
                    out_band.WriteArray(data)
                out_dataset.FlushCache()
                return True
        except (OSError, RuntimeError):
            return False

    @staticmethod
    def convert_tif_to_jpeg(
        tif_path: str,
        output_path: str = None,
        quality_percentage="100",
        source_type=None,
    ):
        """
        Converts a TIFF image to a JPEG image with optional resizing and quality settings.

        Args:
            tif_path (str): The file path of the input TIFF image.
            output_path (str, optional): The file path for the output JPEG image. If not provided,
                                         the output path will be the same as the input path with a .jpeg extension.
            quality_percentage (str, optional): The quality percentage for the JPEG image (default is "100").

        Returns:
            str: The file path of the converted JPEG image if successful, otherwise None.

        Raises:
            Exception: If the TIFF file cannot be opened or the conversion fails.
        """
        try:
            if output_path is None:
                output_path = os.path.splitext(tif_path)[0] + ".jpeg"

            with gdal.Open(tif_path) as dataset:
                if not dataset:
                    raise Exception(f"Unable to open TIFF file: {tif_path}")

                band_order = ImageryUtils.get_rgb_band_indexes(
                    tif_path, source_type
                )
                logger.info(
                    f"Band Order Found in JPEG conversion ---> {band_order}"
                )

                width = dataset.RasterXSize
                height = dataset.RasterYSize
                max_dimension = 2400
                if width > max_dimension or height > max_dimension:
                    scale = min(max_dimension / width, max_dimension / height)
                    new_width = int(width * scale)
                    new_height = int(height * scale)
                    logger.info(
                        f"Resizing image from ({width}, {height}) to ({new_width}, {new_height}) for JPEG conversion."
                    )
                    jpeg_options = gdal.TranslateOptions(
                        format="JPEG",
                        creationOptions=[f"QUALITY={quality_percentage}"],
                        width=new_width,
                        height=new_height,
                    )
                else:
                    jpeg_options = gdal.TranslateOptions(
                        format="JPEG",
                        creationOptions=[f"QUALITY={quality_percentage}"],
                    )
                logger.info(f"JPEG options used ---> {jpeg_options}")
                gdal.Translate(output_path, dataset, options=jpeg_options)
                logger.info(
                    f"TIFF file converted to highly compressed JPEG at {output_path}"
                )

            return output_path
        except Exception as e:
            error_message = f"{__class__.__name__}.convert_cog_to_jpeg: Conversion failed: {str(e)}"
            logger.error(error_message, exc_info=True)
            return None

    @staticmethod
    def get_rgb_band_indexes(tif_file, source_type=None):
        """
        Args:
                tif_file (str): Path to the TIFF file.
                source_type (str, optional): Type of the imagery source. Supported values are "planet_scope", "planet_skysat", and "vantor"
                        ("maxar" is accepted as the pre-rebrand alias). Defaults to None.

        Returns:
            list: A list of integers representing the band indexes for Red, Green, and Blue channels.

        Raises:
            RuntimeError: If the dataset cannot be opened.

        Determines the order of bands to use for RGB conversion based on the imagery product.
        Planet Specs:
        https://assets.planet.com/docs/Planet_Combined_Imagery_Product_Specs_letter_screen.pdf
        Vantor Specs:
        https://ard.maxar.com/docs/ard-order-delivery/metadata/tile-metadata/#eobands
        Sentinel2 Specs:
        https://docs.sentinel-hub.com/api/latest/data/sentinel-2-l2a/

        Supported products include:
          Planet Scope:
              - 3-band multispectral: bands ordered as Red, Green, Blue.
              - 4-band multispectral: bands ordered as Blue, Green, Red, (NIR ignored for RGB).
              - 8-band multispectral: bands ordered as Coastal Blue, Blue, Green I, Green, Red, Yellow, Red Edge, NIR (RGB extracted as Red, Green, Blue).

          Planet SkySat:
              - Multispectral (4 bands): Blue, Green, Red, NIR (returning RGB as Red, Green, Blue).
              - Panchromatic: single band.

          Vantor:
              - Visual RGB: Red, Green, Blue.
              - Multispectral 4-band: Blue, Green, Red, NIR1 (RGB extracted as Red, Green, Blue).
              - Multispectral 8-band: Blue, Coastal Blue, Green, Red, NIR1, Yellow, Red Edge, NIR2 (RGB extracted as Red, Green, Blue).
              - Panchromatic: single band.
          Sentinel:
              - 13-band multispectral with 4 visible bands, 6 Near-Infrared bands, and 3 Short-Wave Infrared bands. RGB extracted as B4, B3, B2
              - 3-band multispectral: bands ordered as B4, B3, B2. RGB extracted as B4, B3, B2

        Fallback: Use GDAL color interpretation.
        """
        with gdal.Open(tif_file) as dataset:
            if dataset is None:
                raise RuntimeError(
                    "Failed to open the dataset for band organization."
                )

            num_bands = dataset.RasterCount

            # Helper to map keywords to band index.
            def map_bands(keywords):
                mapping = {}
                for idx, key in enumerate(keywords, start=1):
                    mapping[key] = idx
                return mapping

            if source_type == "planet_scope":
                if num_bands == 3:
                    mapping = map_bands(["red", "green", "blue"])
                    return [mapping["red"], mapping["green"], mapping["blue"]]
                elif num_bands == 4:
                    mapping = map_bands(["blue", "green", "red", "nir"])
                    return [mapping["red"], mapping["green"], mapping["blue"]]
                elif num_bands == 8:
                    mapping = map_bands(
                        [
                            "coastal blue",
                            "blue",
                            "green i",
                            "green",
                            "red",
                            "yellow",
                            "red edge",
                            "nir",
                        ]
                    )
                    return [mapping["red"], mapping["green"], mapping["blue"]]

            elif source_type == "planet_skysat":
                if num_bands == 4:
                    mapping = map_bands(["blue", "green", "red", "nir"])
                    return [mapping["red"], mapping["green"], mapping["blue"]]
                elif num_bands == 1:
                    return [1]

            elif normalize_source_type(source_type) == "vantor":
                if num_bands == 3:
                    mapping = map_bands(["red", "green", "blue"])
                    return [mapping["red"], mapping["green"], mapping["blue"]]
                elif num_bands == 4:
                    mapping = map_bands(["blue", "green", "red", "nir1"])
                    return [mapping["red"], mapping["green"], mapping["blue"]]
                elif num_bands == 8:
                    mapping = map_bands(
                        [
                            "blue",
                            "coastal blue",
                            "green",
                            "red",
                            "nir1",
                            "yellow",
                            "red edge",
                            "nir2",
                        ]
                    )
                    return [mapping["red"], mapping["green"], mapping["blue"]]

            elif source_type == "sentinel_2":
                if num_bands == 13:
                    mapping = map_bands(
                        [
                            "B1",
                            "B2",
                            "B3",
                            "B4",
                            "B5",
                            "B6",
                            "B7",
                            "B8",
                            "B8A",
                            "B9",
                            "B10",
                            "B11",
                            "B12",
                        ]
                    )
                    return [mapping["B4"], mapping["B3"], mapping["B2"]]
                elif num_bands == 3:
                    mapping = map_bands(["B4", "B3", "B2"])
                    return [mapping["B4"], mapping["B3"], mapping["B2"]]

            # Fallback using GDAL color interpretation.
            color_interpretation = [
                "Undefined",
                "Gray",
                "Palette",
                "Red",
                "Green",
                "Blue",
                "Alpha",
                "Hue",
                "Saturation",
                "Lightness",
                "Cyan",
                "Magenta",
                "Yellow",
                "Black",
                "YCbCr_Y",
                "YCbCr_Cb",
                "YCbCr_Cr",
            ]
            default_mapping = {}
            for i in range(1, num_bands + 1):
                band = dataset.GetRasterBand(i)
                color = color_interpretation[band.GetColorInterpretation()]
                logger.info(f"Band {i}: {color}")
                if color in ["Red", "Green", "Blue"]:
                    default_mapping[color] = i
            if (
                "Red" in default_mapping
                and "Green" in default_mapping
                and "Blue" in default_mapping
            ):
                return [
                    default_mapping["Red"],
                    default_mapping["Green"],
                    default_mapping["Blue"],
                ]

            return [1, 2, 3]

    @staticmethod
    def mosaic_imagery(
        tif_files: List[str],
        output_file_path: str = None,
        gdal_warp_params: str = "",
        clip_bbox: List[float] = None,
    ) -> str:
        """
        Parameters:
            tif_files (List[str]): List of paths to the input TIFF files.
            output_file_path (str, optional): Path to the output COG file. If not provided, a default path is generated.
            gdal_warp_params (str): GDAL warp parameters as a string.
            clip_bbox (List[float], optional): [west, south, east, north] in
                EPSG:4326. When provided, the output mosaic is clipped to this
                box via gdalwarp ``-te``/``-te_srs`` (GDAL reprojects the bounds
                to the mosaic's CRS), so only the drawn AOI is produced.

        Returns:
            str: Path to the output COG file.

        Raises:
            ValueError: If `gdal_warp_params` is not a non-empty string or if `tif_files` is None or empty.
            RuntimeError: If VRT creation or COG creation fails.
        """
        try:
            if (
                not isinstance(gdal_warp_params, str)
                or not gdal_warp_params.strip()
            ):
                raise ValueError("gdal_warp_params must be a non-empty string")
            if tif_files is None or len(tif_files) == 0:
                raise ValueError("tif_files cannot be None or empty")
            if output_file_path is None:
                output_file_path = (
                    os.path.splitext(tif_files[0])[0] + "_out_mosaic.tif"
                )

            vrt_input_files = []
            temp_files = []

            # Process each file with gdalwarp using nearest neighbor resampling
            # This handles rotated geotransforms without changing projection
            for i, tif_file in enumerate(tif_files):
                with rasterio.open(tif_file) as src:
                    # Check if the file has a rotated geotransform
                    geotransform = src.transform
                    has_rotation = geotransform.b != 0 or geotransform.d != 0

                    if has_rotation:
                        logger.info(
                            f"Processing rotated geotransform for {tif_file}"
                        )
                        temp_file = (
                            os.path.splitext(tif_file)[0]
                            + f"_temp_warped_{i}.tif"
                        )

                        # Use gdalwarp with nearest neighbor to handle rotation
                        # while preserving original projection
                        warp_options = gdal.WarpOptions(
                            resampleAlg="near",  # Nearest neighbor resampling
                            creationOptions=["COMPRESS=DEFLATE", "TILED=YES"],
                        )

                        result = gdal.Warp(
                            temp_file, tif_file, options=warp_options
                        )
                        if result is None:
                            error_msg = gdal.GetLastErrorMsg()
                            raise RuntimeError(
                                f"Failed to warp {tif_file}: {error_msg}"
                            )

                        result.FlushCache()
                        result = None
                        temp_files.append(temp_file)
                        vrt_input_files.append(temp_file)
                        logger.info(f"Warped file created: {temp_file}")
                    else:
                        # File doesn't have rotation, use as-is
                        vrt_input_files.append(tif_file)

            try:
                vrt_path = Path(output_file_path).with_suffix(".vrt")

                # Create a VRT (Virtual Raster) file to combine multiple TIFF files into a single virtual dataset
                vrt_options = gdal.BuildVRTOptions()
                vrt = gdal.BuildVRT(
                    str(vrt_path), vrt_input_files, options=vrt_options
                )
                if vrt is None:
                    error_msg = gdal.GetLastErrorMsg()
                    raise RuntimeError(f"Failed to create VRT: {error_msg}")

                vrt.FlushCache()
                vrt = None
                logger.info(f"VRT file created at {vrt_path}")

                # Check if vrt file exists on disk
                if not os.path.exists(vrt_path):
                    raise RuntimeError("VRT file does not exist on disk")

                # Use gdal.Warp to convert the VRT to a COG (Cloud Optimized GeoTIFF)
                warp_option_list = gdal_warp_params.split()
                if clip_bbox:
                    west, south, east, north = (float(v) for v in clip_bbox)
                    # -te bounds are given in EPSG:4326 (-te_srs); GDAL
                    # reprojects them to the mosaic's CRS before clipping.
                    warp_option_list += [
                        "-te",
                        str(west),
                        str(south),
                        str(east),
                        str(north),
                        "-te_srs",
                        "EPSG:4326",
                    ]
                    logger.info(f"Clipping mosaic to AOI bbox {clip_bbox}")
                warp_options = gdal.WarpOptions(options=warp_option_list)
                result = gdal.Warp(
                    output_file_path, str(vrt_path), options=warp_options
                )
                if result is None:
                    error_msg = gdal.GetLastErrorMsg()
                    raise RuntimeError(
                        f"Failed to create mosaic COG: {error_msg}"
                    )

                result.FlushCache()
                result = None
                logger.info(f"Mosaic COG file created at {output_file_path}")

                # Clean up VRT
                try:
                    os.remove(vrt_path)
                except OSError:
                    pass

            finally:
                # Clean up temporary files
                for temp_file in temp_files:
                    try:
                        os.remove(temp_file)
                        logger.info(f"Cleaned up temporary file: {temp_file}")
                    except OSError as e:
                        logger.warning(
                            f"Could not delete temporary file {temp_file}: {e}"
                        )

            return output_file_path

        except (ValueError, RuntimeError) as e:
            error_message = f"{__class__.__name__}.mosaic_imagery: GDAL processing failed: {str(e)}\n{traceback.format_exc()}"
            logger.error(error_message)
            raise

    @staticmethod
    def get_scale_imagery_params(file_path, source_type=None):
        """
        Get scaling parameters for imagery bands.

        This method reads the first three bands of a raster image file and computes
        scaling parameters based on the 2nd and 98th percentiles of the pixel values.
        These parameters can be used to scale the pixel values to a range of 0 to 255,
        which is useful for visualizing the image.

        Args:
            file_path (str): The file path to the raster image.
            source_type (str, optional): The type of the imagery source.

        Returns:
            list of list: A list containing three lists, each with four elements:
                        [p2, p98, 0, 255], where p2 and p98 are the 2nd and 98th
                        percentiles of the pixel values for each of the first three bands.
                        Returns None if the image has fewer than three bands or if an error occurs.
                        Returns [0, 600, 0, 255] for each band in Planet SkySat imagery.

        Raises:
            Exception: If there is an error processing the raster image with GDAL.
        """
        try:
            with gdal.Open(file_path) as dataset:
                if dataset is None:
                    return None
                num_bands = dataset.RasterCount
                if num_bands < 3:
                    return None
                scale_params = []
                for i in range(1, 4):
                    if source_type == "planet_skysat":
                        scale_params.append([0, 600, 0, 255])
                        continue
                    # All other source types that need scaling
                    band = dataset.GetRasterBand(i)
                    # Read the band as array for a robust statistic computation
                    array = band.ReadAsArray()
                    if array is None:
                        return None
                    # Use the 2nd and 98th percentiles to reduce the effect of outliers
                    # NOTE: need to identify suitable defaults to use if np.nan.
                    # np.nan will break gdal translate.
                    p_low = np.percentile(array, 2)
                    p_high = np.percentile(array, 98)
                    scale_params.append([p_low, p_high, 0, 255])
                return scale_params
        except Exception as e:
            error_message = (
                f"{__class__.__name__}.convert_to_rgb_cog_organize_rgb: GDAL processing failed: {str(e)}\n"
                f"{traceback.format_exc()}"
            )
            logger.error(error_message, exc_info=True)
            return None

    @staticmethod
    def convert_to_rgb_cog(
        tif_file: str,
        output_file_path: str = None,
        gdal_translate_params: str = "",
        source_type=None,
        scale_rgb_params=False,
    ) -> str:
        """
        Converts a given TIFF file to an RGB Cloud Optimized GeoTIFF (COG) using GDAL.
        Args:
            tif_file (str): Path to the input TIFF file.
            output_file_path (str, optional): Path to the output RGB COG file. If not provided,
                                              the output file will be named based on the input file.
            gdal_translate_params (str): GDAL translate parameters as a non-empty string.
            source_type (optional): Source type to determine the RGB band indexes.
            scale_rgb_params (bool, optional): Whether to scale RGB parameters. Defaults to False.
        Returns:
            str: Path to the created RGB COG file, or None if the process fails.
        Raises:
            ValueError: If `gdal_translate_params` is not a non-empty string, or if `tif_file` is None or does not exist.
            RuntimeError: If the scale parameters cannot be computed or if the RGB COG creation fails.
        Logs:
            Logs the creation of the COG file or any errors encountered during the process.
        """
        if not gdal_translate_params or not isinstance(
            gdal_translate_params, str
        ):
            raise ValueError(
                "gdal_translate_params must be a non-empty string"
            )
        try:
            if tif_file is None:
                raise ValueError("tif_file cannot be None")
            if not os.path.exists(tif_file):
                raise ValueError("tif file does not exist")
            if output_file_path is None:
                output_file_path = (
                    os.path.splitext(tif_file)[0] + "_out_rgb_cog.tif"
                )

            band_order = ImageryUtils.get_rgb_band_indexes(
                tif_file, source_type
            )
            logger.info(f"Band Order Found ---> {band_order}")

            if scale_rgb_params:
                scale_params = ImageryUtils.get_scale_imagery_params(
                    tif_file, source_type
                )
                logger.info(f"Scale Params Found ---> {scale_params}")
                if scale_params is None:
                    raise RuntimeError("Failed to compute scale parameters")
                result = gdal.Translate(
                    destName=output_file_path,
                    srcDS=tif_file,
                    options=gdal.TranslateOptions(
                        format="COG",
                        outputType=gdal.GDT_Byte,
                        creationOptions=gdal_translate_params.split(),
                        bandList=band_order,
                        scaleParams=scale_params,
                    ),
                )
            else:
                result = gdal.Translate(
                    destName=output_file_path,
                    srcDS=tif_file,
                    options=gdal.TranslateOptions(
                        format="COG",
                        outputType=gdal.GDT_Byte,
                        creationOptions=gdal_translate_params.split(),
                        bandList=band_order,
                    ),
                )

            if result is None:
                raise RuntimeError("Failed to create RGB COG")
            result.FlushCache()  # Ensure the COG file is written to disk

            logger.info(f"RGB adjusted COG file created at {output_file_path}")
            return output_file_path
        except (ValueError, RuntimeError) as e:
            error_message = (
                f"{__class__.__name__}.convert_to_rgb_cog_organize_rgb: GDAL processing failed: {str(e)}\n"
                f"{traceback.format_exc()}"
            )
            logger.error(error_message, exc_info=True)
            return None

    @staticmethod
    def get_normalization_means(file_path, source_type=None):
        """
        Get normalization mean values for imagery bands.

        This method finds the number bands of a raster image file and sets
        normalization mean values for each band.

        Args:
            file_path (str): The file path to the raster image.
            source_type (str, optional): The type of the imagery source.
        source_type is not used in this method but is included for consistency with other methods.
        Returns:
            list: A list containing a mean value for each band.

        Raises:
            Exception: If there is an error processing the raster image with GDAL.
        """
        try:
            normalization_means = []
            with gdal.Open(file_path) as dataset:
                if dataset is None:
                    return None
                num_bands = dataset.RasterCount
                for i in range(1, num_bands + 1):
                    normalization_means.append(0)
            return normalization_means
        except Exception as e:
            error_message = (
                f"{__class__.__name__}.get_normalization_means: GDAL processing failed: {str(e)}\n"
                f"{traceback.format_exc()}"
            )
            logger.error(error_message, exc_info=True)
            return None

    @staticmethod
    def get_normalization_std_devs(file_path, source_type=None):
        """
        Get normalization standard deviation values for imagery bands.

        This method finds the number bands of a raster image file and sets
        normalization standard deviation values for each band.

        Args:
            file_path (str): The file path to the raster image.
            source_type (str, optional): The type of the imagery source.
        source_type is not used in this method but is included for consistency with other methods.
        Returns:
            list: A list containing a standard deviation value for each band.

        Raises:
            Exception: If there is an error processing the raster image with GDAL.
        """
        try:
            normalization_stds = []
            with gdal.Open(file_path) as dataset:
                if dataset is None:
                    return None
                num_bands = dataset.RasterCount
                for i in range(1, num_bands + 1):
                    bands = dataset.GetRasterBand(i)
                    data = bands.ReadAsArray()
                    if data is None:
                        return None
                    # Use the 98th percentile to reduce the effect of outliers
                    p98 = np.percentile(data, 98)
                    normalization_stds.append(int(p98))
            return normalization_stds
        except Exception as e:
            error_message = (
                f"{__class__.__name__}.get_normalization_std_devs: GDAL processing failed: {str(e)}\n"
                f"{traceback.format_exc()}"
            )
            logger.error(error_message, exc_info=True)
            return None
