# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License.

"""Tests for saving a version's GeoPackage AND sidecar in one call.

The map renders from the attribute sidecar, not from the GeoPackage. A
version stored without its own sidecar therefore draws the RAW model's
classes while claiming to show the analyst's edit — the exact silent
disagreement :func:`save_edited_version` exists to prevent. These tests
pin that both artifacts are produced together and that the sidecar
describes the EDITED file.
"""

import json
import os
import shutil
import tempfile
import unittest

import fiona
from fiona.crs import CRS
from fiona.model import Feature
from hastegeo.core.processors.prediction_edits import (
    SavedEditedVersion,
    save_edited_version,
    store_version_attrs,
)
from shapely.geometry import Polygon, mapping

INFERENCE_SCHEMA = {
    "geometry": "Polygon",
    "properties": {
        "id": "int",
        "damage_pct_0m": "float",
        "damaged": "int",
        "unknown_pct": "float",
    },
}
FOOTPRINT_SCHEMA = {
    "geometry": "Polygon",
    "properties": {"id": "str", "subtype": "str", "class": "str"},
}


def _square(index: int) -> Polygon:
    x = -122.0 + index * 0.001
    y = 47.0 + index * 0.001
    return Polygon(
        [(x, y), (x + 0.0001, y), (x + 0.0001, y + 0.0001), (x, y + 0.0001)]
    )


def write_raw_predictions(path: str, damages: list, unknowns: list) -> str:
    with fiona.open(
        path,
        "w",
        driver="GPKG",
        crs=CRS.from_epsg(4326),
        schema=INFERENCE_SCHEMA,
    ) as dst:
        for index, damage in enumerate(damages):
            dst.write(
                Feature.from_dict(
                    **{
                        "geometry": mapping(_square(index)),
                        "properties": {
                            "id": index,
                            "damage_pct_0m": damage,
                            "damaged": 1 if damage >= 0.5 else 0,
                            "unknown_pct": unknowns[index],
                        },
                    }
                )
            )
    return path


def write_footprints(path: str, count: int) -> str:
    with fiona.open(
        path,
        "w",
        driver="GPKG",
        crs=CRS.from_epsg(4326),
        schema=FOOTPRINT_SCHEMA,
    ) as dst:
        for index in range(count):
            dst.write(
                Feature.from_dict(
                    **{
                        "geometry": mapping(_square(index)),
                        "properties": {
                            "id": f"overture-{index}",
                            "subtype": "residential",
                            "class": "house",
                        },
                    }
                )
            )
    return path


class FakeArtifactProcessor:
    """Records stores and keeps a copy of every uploaded file."""

    def __init__(self, root: str):
        self.root = root
        self.stored: list = []

    def store_artifact(self, artifact_name: str, src_path: str) -> None:
        self.stored.append(artifact_name)
        shutil.copyfile(src_path, os.path.join(self.root, artifact_name))

    def get_download_url(self, identifier: str) -> str:
        return f"https://blob.example/{identifier}?sas"

    def read_json(self, artifact_name: str) -> dict:
        with open(os.path.join(self.root, artifact_name)) as handle:
            return json.load(handle)


class SaveFixture(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.mkdtemp(prefix="haste-save-version-")
        self.addCleanup(shutil.rmtree, self.tmpdir, True)
        self.blobs = os.path.join(self.tmpdir, "blobs")
        os.makedirs(self.blobs)
        self.processor = FakeArtifactProcessor(self.blobs)
        # Row 0 pristine, row 1 borderline, row 2 clearly damaged.
        self.raw = write_raw_predictions(
            os.path.join(self.tmpdir, "raw.gpkg"),
            damages=[0.0, 0.6, 0.9],
            unknowns=[0.0, 0.0, 0.0],
        )
        self.footprints = write_footprints(
            os.path.join(self.tmpdir, "footprints.gpkg"), 3
        )

    def save(self, version: int = 1, **kwargs) -> SavedEditedVersion:
        params = {
            "threshold": 0.5,
            "unknown_threshold": 0.0,
            "overrides": {},
        }
        params.update(kwargs)
        return save_edited_version(
            "project-1",
            "model-123",
            version,
            self.raw,
            self.footprints,
            processor=self.processor,
            **params,
        )


class TestSaveProducesBothArtifacts(SaveFixture):
    def test_stores_the_gpkg_and_its_sidecar(self):
        saved = self.save(version=2)

        self.assertEqual(
            self.processor.stored,
            [
                "edited_predictions_model-123_v2.gpkg",
                "prediction_attrs_model-123_v2.json",
            ],
        )
        self.assertEqual(
            saved.gpkg_url,
            "https://blob.example/edited_predictions_model-123_v2.gpkg?sas",
        )
        self.assertEqual(
            saved.attrs_url,
            "https://blob.example/prediction_attrs_model-123_v2.json?sas",
        )

    def test_response_body_carries_the_attrs_url(self):
        body = self.save(version=1).to_dict()

        self.assertEqual(
            sorted(body),
            [
                "buildingCount",
                "editedCount",
                "gpkgUrl",
                "predictionAttrsUrl",
                "version",
            ],
        )
        self.assertEqual(body["version"], 1)
        self.assertEqual(body["buildingCount"], 3)
        self.assertTrue(body["predictionAttrsUrl"])

    def test_temporary_working_directory_is_cleaned_up(self):
        before = set(os.listdir(tempfile.gettempdir()))
        self.save()
        leaked = [
            name
            for name in set(os.listdir(tempfile.gettempdir())) - before
            if name.startswith("haste-edited-version-")
        ]
        self.assertEqual(leaked, [])


class TestSidecarDescribesTheEditedFile(SaveFixture):
    def test_threshold_change_is_reflected_in_the_sidecar(self):
        # At threshold 0.8 only row 2 stays damaged, even though the raw
        # model called rows 1 and 2 damaged at 0.5.
        self.save(version=1, threshold=0.8)

        payload = self.processor.read_json(
            "prediction_attrs_model-123_v1.json"
        )

        self.assertEqual(payload["damaged"], [0, 0, 1])
        self.assertEqual(
            payload["classes"], ["NotDamaged", "NotDamaged", "Damaged"]
        )

    def test_overrides_are_reflected_in_the_sidecar(self):
        self.save(version=1, overrides={0: "Unknown", 2: "NotDamaged"})

        payload = self.processor.read_json(
            "prediction_attrs_model-123_v1.json"
        )

        self.assertEqual(
            payload["classes"], ["Unknown", "Damaged", "NotDamaged"]
        )
        self.assertEqual(payload["damaged"], [0, 1, 0])

    def test_raw_fractions_and_ids_are_preserved(self):
        self.save(version=1, overrides={0: "Damaged"})

        payload = self.processor.read_json(
            "prediction_attrs_model-123_v1.json"
        )

        self.assertEqual(payload["n"], 3)
        self.assertEqual(payload["ids"], [0, 1, 2])
        self.assertEqual(payload["damage"], [0.0, 0.6, 0.9])
        self.assertEqual(
            payload["overtureIds"],
            ["overture-0", "overture-1", "overture-2"],
        )

    def test_sidecar_disagrees_with_the_raw_model_on_purpose(self):
        # Guards the regression this feature exists to fix: rendering
        # the raw sidecar for an edited version would show [0, 1, 1].
        self.save(version=1, overrides={1: "NotDamaged"})

        payload = self.processor.read_json(
            "prediction_attrs_model-123_v1.json"
        )

        self.assertEqual(payload["damaged"], [0, 0, 1])


class TestSaveValidation(SaveFixture):
    def test_invalid_threshold_stores_nothing(self):
        with self.assertRaises(ValueError):
            self.save(threshold=1.5)

        self.assertEqual(self.processor.stored, [])

    def test_unknown_override_class_stores_nothing(self):
        with self.assertRaises(ValueError):
            self.save(overrides={0: "Rubble"})

        self.assertEqual(self.processor.stored, [])

    def test_footprint_mismatch_stores_no_sidecar(self):
        # apply_edits succeeds row-wise only when the counts line up, so
        # a mismatch must fail the save rather than half-store it.
        self.footprints = write_footprints(
            os.path.join(self.tmpdir, "short.gpkg"), 2
        )

        with self.assertRaises(ValueError):
            self.save()

        self.assertNotIn(
            "prediction_attrs_model-123_v1.json", self.processor.stored
        )


class TestStoreVersionAttrs(SaveFixture):
    def test_missing_local_file_raises(self):
        with self.assertRaises(FileNotFoundError):
            store_version_attrs(
                "project-1",
                "model-123",
                1,
                os.path.join(self.tmpdir, "missing.json"),
                processor=self.processor,
            )

        self.assertEqual(self.processor.stored, [])


if __name__ == "__main__":
    unittest.main()
