# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License.

"""Compact native fixtures shared by sidecar, producer and workflow tests."""

from pathlib import Path

import fiona
import rasterio
from shapely.geometry import box, mapping

PREDICTION_FIELDS = {
    "id": "int",
    "overture_id": "str",
    "damage_pct_0m": "float",
    "unknown_pct": "float",
    "damaged": "int",
}


def write_gpkg(
    path: Path,
    rows: list[dict],
    *,
    fields: dict = PREDICTION_FIELDS,
    crs: str | None = "EPSG:6933",
    layer: str = "inference",
    geometries: list | None = None,
) -> str:
    if path.exists():
        fiona.remove(str(path), driver="GPKG")
    with fiona.open(
        str(path),
        "w",
        driver="GPKG",
        crs=crs,
        layer=layer,
        schema={"geometry": "Polygon", "properties": fields},
    ) as dst:
        for index, props in enumerate(rows):
            geometry = (
                geometries[index]
                if geometries is not None
                else box(index * 20, 0, index * 20 + 10, 10)
            )
            dst.write(
                {
                    "geometry": mapping(geometry)
                    if geometry is not None
                    else None,
                    "properties": {key: props.get(key) for key in fields},
                }
            )
    return str(path)


def prediction_rows(damages=(0.0, 0.25), unknowns=None) -> list[dict]:
    unknowns = unknowns if unknowns is not None else [0.0] * len(damages)
    return [
        {
            "id": index,
            "overture_id": f"building-{index}",
            "damage_pct_0m": damage,
            "unknown_pct": unknowns[index],
            "damaged": int(damage is not None and damage > 0),
            "area": 100.0,
        }
        for index, damage in enumerate(damages)
    ]


def write_pair(
    directory: Path, rows: list[dict], *, embedding: bool = False
) -> tuple[str, str]:
    footprints = write_gpkg(
        directory / "footprints.gpkg",
        [{"id": f"building-{i}"} for i in range(len(rows))],
        fields={"id": "str"},
    )
    fields = dict(PREDICTION_FIELDS)
    if embedding:
        fields["area"] = "float"
    predictions = write_gpkg(
        directory / "predictions.gpkg",
        rows,
        fields=fields,
        layer="predictions" if embedding else "inference",
    )
    return footprints, predictions


def write_raster(path, array, transform, *, crs="EPSG:32610", nodata=0) -> str:
    with rasterio.open(
        str(path),
        "w",
        driver="GTiff",
        crs=crs,
        transform=transform,
        width=array.shape[1],
        height=array.shape[0],
        count=1,
        dtype=array.dtype,
        nodata=nodata,
    ) as dst:
        dst.write(array, 1)
    return str(path)
