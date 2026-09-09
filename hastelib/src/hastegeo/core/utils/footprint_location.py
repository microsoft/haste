# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License.

"""Small, exact geometry reads for keyboard review of unloaded footprints."""

from typing import Any

import fiona
from fiona.transform import transform_geom
from shapely.geometry import mapping, shape

from .gdal_security import harden_gdal
from .prediction_attrs import source_id


def footprint_location(path: str, building_id: str) -> dict[str, Any]:
    harden_gdal()
    feature = None
    with fiona.open(path) as footprints:
        if not footprints.crs or "id" not in footprints.schema["properties"]:
            raise ValueError("Footprints require a CRS and source IDs")
        for row_id, row in enumerate(footprints):
            if source_id(row["properties"]["id"]) != building_id:
                continue
            if feature is not None:
                raise ValueError("Footprint source ID is not unique")
            if row["geometry"] is None:
                raise ValueError("Building footprint has no geometry")
            point = shape(row["geometry"]).representative_point()
            if point.is_empty:
                raise ValueError("Building footprint has empty geometry")
            projected = transform_geom(
                footprints.crs, "EPSG:4326", mapping(point)
            )
            feature = {
                "type": "Feature",
                "properties": {"id": building_id, "rowId": row_id},
                "geometry": {
                    "type": "Point",
                    "coordinates": list(projected["coordinates"]),
                },
            }
    if feature is None:
        raise FileNotFoundError("Building footprint not found")
    return {"type": "FeatureCollection", "features": [feature]}
