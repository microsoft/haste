# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License.

"""Small native fixtures shared by edit application and report tests."""

import os
from collections.abc import Callable, Sequence
from typing import Any

import fiona
from shapely.geometry import box, mapping, shape


def write_prediction_pair(
    directory: str,
    scores: Sequence[float | None],
    unknowns: Sequence[float | None] | None = None,
    *,
    flavor: str = "inference",
    crs: str = "EPSG:6933",
    null_geometry: bool = False,
) -> tuple[str, str]:
    footprints = os.path.join(directory, "footprints.gpkg")
    raw = os.path.join(directory, "raw.gpkg")
    fields = {
        "id": "int",
        "overture_id": "str",
        "damage_pct_0m": "float",
        "damage_pct_10m": "float",
        "damage_pct_20m": "float",
        "unknown_pct": "float",
        "damaged": "int",
        "source_note": "str",
    }
    if flavor == "embedding":
        fields["area"] = "float"
    unknowns = unknowns if unknowns is not None else [0.0] * len(scores)
    for path in (raw, footprints):
        if os.path.exists(path):
            fiona.remove(path, driver="GPKG")
    with fiona.open(
        footprints,
        "w",
        driver="GPKG",
        crs=crs,
        schema={"geometry": "Polygon", "properties": {"id": "str"}},
    ) as fp, fiona.open(
        raw,
        "w",
        driver="GPKG",
        crs=crs,
        layer="predictions" if flavor == "embedding" else "inference",
        schema={"geometry": "Polygon", "properties": fields},
    ) as dst:
        for index, score in enumerate(scores):
            geom = (
                None
                if null_geometry
                else mapping(box(index * 20, 0, index * 20 + 10, 10))
            )
            oid = f"building-{index}"
            fp.write({"geometry": geom, "properties": {"id": oid}})
            props = {
                "id": index,
                "overture_id": oid,
                "damage_pct_0m": score,
                "damage_pct_10m": score,
                "damage_pct_20m": score,
                "unknown_pct": unknowns[index],
                "damaged": int(score is not None and score > 0),
                "source_note": f"original-{index}",
            }
            if flavor == "embedding":
                props["area"] = 100.0
            dst.write({"geometry": geom, "properties": props})
    return raw, footprints


def native_snapshot(path: str) -> dict[str, Any]:
    """Compare actual geometry/schema/properties, not hand-written file bytes."""
    layers = fiona.listlayers(path)
    with fiona.open(path, layer=layers[0]) as src:
        return {
            "layers": layers,
            "crs": src.crs_wkt,
            "schema": src.schema,
            "rows": [
                {
                    "geometry": shape(row["geometry"]).wkb_hex
                    if row["geometry"] is not None
                    else None,
                    "properties": dict(row["properties"]),
                }
                for row in src
            ],
        }


def rewrite_properties(
    path: str, change: Callable[[int, dict[str, Any]], None]
) -> None:
    """Simulate a corrupt/legacy vector artifact through GDAL, never SQLite."""
    layer = fiona.listlayers(path)[0]
    with fiona.open(path, layer=layer) as src:
        schema, crs = src.schema, src.crs_wkt
        rows = [
            {
                "geometry": row["geometry"],
                "properties": dict(row["properties"]),
            }
            for row in src
        ]
    for index, row in enumerate(rows):
        change(index, row["properties"])
    fiona.remove(path, driver="GPKG")
    with fiona.open(
        path,
        "w",
        driver="GPKG",
        layer=layer,
        schema=schema,
        crs_wkt=crs,
    ) as dst:
        dst.writerecords(rows)
