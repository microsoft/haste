# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License.

"""Join catalog prediction rows by source identity, with legacy row-ID support."""

from collections.abc import Iterator
from typing import Any

from .gdal_security import harden_gdal


def source_building_ids(footprints_path: str) -> list[str]:
    harden_gdal()
    import fiona

    with fiona.open(footprints_path) as footprints:
        ids = [
            str(
                feature["properties"].get("id")
                if feature["properties"].get("id") is not None
                else feature["id"]
            )
            for feature in footprints
        ]
    if len(set(ids)) != len(ids):
        raise ValueError("Source building identities are duplicated")
    return ids


def iter_building_predictions(
    footprints_path: str, predictions_path: str
) -> Iterator[tuple[str, dict[str, Any]]]:
    ids = source_building_ids(footprints_path)
    import fiona

    known = set(ids)
    seen: set[str] = set()
    with fiona.open(predictions_path) as predictions:
        for feature in predictions:
            props = dict(feature["properties"])
            if "source_building_id" in props:
                source_id = props["source_building_id"]
                if source_id is None or str(source_id) not in known:
                    raise ValueError(
                        "Prediction source building identity is invalid"
                    )
                building_id = str(source_id)
            else:
                index = props.get("id")
                if (
                    not isinstance(index, int)
                    or index < 0
                    or index >= len(ids)
                ):
                    continue
                building_id = ids[index]
            if building_id in seen:
                raise ValueError(
                    "Prediction source building identity is duplicated"
                )
            seen.add(building_id)
            yield building_id, props


def load_binary_building_predictions(
    footprints_path: str, predictions_path: str
) -> dict[str, int]:
    return {
        building_id: props["damaged"]
        for building_id, props in iter_building_predictions(
            footprints_path, predictions_path
        )
        if props.get("damaged") in (0, 1)
    }
