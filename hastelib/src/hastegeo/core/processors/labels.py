# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License.
import logging

import numpy as np
import rasterio
import rasterio.warp
import requests
import shapely.geometry
from hastegeo.core.config import Config

from ..models.projects import (
    Feature,
    ImageLayer,
    LabelingImagery,
    LabelProject,
)
from ..utils.gdal_security import harden_gdal
from ..utils.metadata import MetadataUtils

# Harden GDAL drivers before any rasterio read (GDAL CVE compensating
# control — docs/known-vulnerabilities.md Root Cause C).
harden_gdal()


class LabelTaskGenerator:
    def __init__(self, image_data: ImageLayer, config: Config = None):
        self.logger = logging.getLogger(__name__)
        if config is None:
            config = Config()
        self.partition_key = image_data.projectId
        self.experiment_name = MetadataUtils.generate_id()
        self.experiment_dir = config.TEMP_DIR
        self.input_image_fn = (
            image_data.postEventProcessedImageryUrl
        )  # TODO Deprecate
        self.input_image_fn_pre_event = image_data.preEventProcessedImageryUrl
        self.input_image_fn_post_event = (
            image_data.postEventProcessedImageryUrl
        )
        self.titiler_endpoint = config.titiler_endpoint
        self.grid_size = None
        self.label_project = LabelProject()
        self.label_project.projectId = image_data.projectId
        self.label_project.imageLayerId = image_data.imageLayerId
        self.label_project.name = image_data.name
        self.label_project.imagery = LabelingImagery()
        self.label_project.imagery.enabled = True
        self.label_project.imagery.type = "TileLayer"
        self.label_project.imagery.tileSize = config.titiler_tileSize
        self.label_project.imagery.tileUrl = self.get_xyz_url(
            self.input_image_fn
        )  # NOTE: Legacy field, consider deprecating
        self.label_project.imagery.preEventTileUrl = self.get_xyz_url(
            self.input_image_fn_pre_event
        )
        self.label_project.imagery.postEventTileUrl = self.get_xyz_url(
            self.input_image_fn_post_event
        )
        self.label_project.imagery.bounds = [-180, -85.5, 180, 85.5]
        self.label_project.features = []
        self.label_project.labelprojectId = MetadataUtils.generate_id()
        self.label_project.creationDate = MetadataUtils.get_timestamp()

    def generate_task_file(self, geom: dict[str, any]) -> None:
        """Generates a task file and saves it in the save folder path."""
        shape = shapely.geometry.shape(geom)
        self.label_project.features.append(
            Feature(
                geometry=geom,
                bbox=list(shape.bounds),
                featureid=MetadataUtils.generate_id(),
            )
        )

    def get_xyz_url(self, imagery_url: str) -> str:
        """Generate XYZ URL for the url of a TIF file."""
        xyz_url = ""
        if imagery_url:
            urlencoded_imagery_url = requests.utils.quote(imagery_url, safe="")
            xyz_url = f"{self.titiler_endpoint}cog/tiles/WebMercatorQuad/{{z}}/{{x}}/{{y}}?scale=1&url={urlencoded_imagery_url}"
        return xyz_url

    def generate_task_files(self):
        """Generate task files."""
        self.logger.info("Generating task file")
        with rasterio.open(self.input_image_fn_post_event) as f:
            bounds = shapely.geometry.box(*f.bounds)
            geom = shapely.geometry.mapping(bounds)
            if f.crs.to_epsg() != 4326:
                geom = rasterio.warp.transform_geom(f.crs, "EPSG:4326", geom)

        if self.grid_size is None:
            self.generate_task_file(geom=geom)
        else:
            geom_epsg3857 = rasterio.warp.transform_geom(
                "EPSG:4326", "EPSG:3857", geom
            )
            shape = shapely.geometry.shape(geom_epsg3857)
            minx, miny, maxx, maxy = shape.bounds

            for x in np.arange(minx, maxx, self.grid_size):
                for y in np.arange(miny, maxy, self.grid_size):
                    grid = shapely.geometry.box(
                        x, y, x + self.grid_size, y + self.grid_size
                    )
                    grid = shapely.geometry.mapping(grid)
                    if shape.intersects(shapely.geometry.shape(grid)):
                        t_geom = rasterio.warp.transform_geom(
                            "EPSG:3857", "EPSG:4326", grid
                        )
                        self.generate_task_file(geom=t_geom)
        return self.label_project
