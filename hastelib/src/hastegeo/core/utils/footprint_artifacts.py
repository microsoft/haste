# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License.

"""Constrain privileged footprint reads to the owning layer's archive."""

from pathlib import Path
from urllib.parse import unquote, urlsplit

from ..config import Config
from ..models.projects import ImageLayer
from .blob import split_blob_url
from .metadata import MetadataUtils


def validate_layer_footprint_url(
    url: str, layer: ImageLayer, config: Config
) -> None:
    partition = MetadataUtils.hash_string(layer.projectId)
    filename = f"footprints_{layer.imageLayerId}.pmtiles"
    parsed = urlsplit(url)
    if not parsed.scheme and config.artifact_storage_type == "local":
        expected = (
            Path(config.artifact_storage_config["directory"])
            / partition
            / filename
        ).resolve()
        if Path(url).resolve() == expected:
            return
    elif parsed.scheme in ("http", "https"):
        container, blob = split_blob_url(url)
        allowed = {
            (
                config.artifact_storage_config.get("container"),
                f"{partition}/{filename}",
            )
        }
        if layer.footprintTilesJob:
            allowed.add(
                (
                    config.storage_config.get("container"),
                    f"{partition}/{layer.footprintTilesJob.taskId}/{filename}",
                )
            )
        if (container, unquote(blob)) in allowed:
            return
    raise ValueError("Footprint archive is outside its layer namespace")
