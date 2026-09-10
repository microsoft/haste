# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License.

"""Safe GeoPackage download names for raw and saved prediction artifacts."""

import re

from ..models.projects import Model


def prediction_download_filename(model: Model, version: int = 0) -> str:
    if version:
        return f"building_predictions_{model.modelId}_v{version}.gpkg"
    basename = (
        (model.predictionGpkgFilename or "")
        .replace("\\", "/")
        .rsplit("/", 1)[-1]
    )
    if re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_. -]{0,220}\.gpkg", basename):
        return basename
    return f"building_predictions_{model.modelId}_raw.gpkg"
