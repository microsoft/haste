# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License.

"""Tests for hastegeo.core.processors.prediction_edits.

The edited GeoPackage feeds a downstream POSITIONAL join against the
layer footprints, so row-order preservation is the headline guarantee
under test here.
"""

import os
import shutil
import tempfile
import unittest
from unittest.mock import MagicMock, patch

import fiona
import geopandas as gpd
from fiona.crs import CRS
from fiona.model import Feature
from hastegeo.core.models.projects import EditedPredictionVersion, Model
from hastegeo.core.processors.prediction_edits import (
    EDIT_THRESHOLD_FIELD,
    EDITED_CLASS_FIELD,
    OVERTURE_ID_FIELD,
    EditSummary,
    apply_edits,
    edited_version_artifact_name,
    next_version,
    store_edited_version,
)
from shapely.geometry import Polygon

DAMAGED = "Damaged"
NOT_DAMAGED = "NotDamaged"
UNKNOWN = "Unknown"

INFERENCE_SCHEMA = {
    "geometry": "MultiPolygon",
    "properties": {
        "id": "int",
        "damage_pct_0m": "float",
        "damage_pct_10m": "float",
        "damage_pct_20m": "float",
        "damaged": "int",
        "unknown_pct": "float",
    },
}


def square(index: int) -> Polygon:
    x = float(index)
    return Polygon([(x, 0), (x + 1, 0), (x + 1, 1), (x, 1)])


def multipolygon_mapping(index: int) -> dict:
    x = float(index)
    ring = [(x, 0.0), (x + 1, 0.0), (x + 1, 1.0), (x, 1.0), (x, 0.0)]
    return {"type": "MultiPolygon", "coordinates": [[ring]]}


def write_inference_gpkg(
    path: str,
    damage_values: list,
    unknown_values: list = None,
    epsg: int = 32610,
) -> str:
    """Write a GeoPackage shaped like merge_with_building_footprints.py."""
    unknown_values = unknown_values or [0.0] * len(damage_values)
    with fiona.open(
        path,
        "w",
        driver="GPKG",
        crs=CRS.from_epsg(epsg),
        schema=INFERENCE_SCHEMA,
    ) as dst:
        for index, damage in enumerate(damage_values):
            dst.write(
                Feature.from_dict(
                    **{
                        "type": "Feature",
                        "geometry": multipolygon_mapping(index),
                        "properties": {
                            "id": index,
                            "damage_pct_0m": damage,
                            "damage_pct_10m": damage / 2,
                            "damage_pct_20m": damage / 4,
                            "damaged": 1 if damage > 0 else 0,
                            "unknown_pct": unknown_values[index],
                        },
                    }
                )
            )
    return path


def write_embedding_gpkg(path: str, damaged_values: list) -> str:
    """Write a GeoPackage shaped like the interactive labeler's output."""
    frame = gpd.GeoDataFrame(
        {
            "id": list(range(len(damaged_values))),
            "damaged": damaged_values,
            "damage_pct_0m": [float(d) for d in damaged_values],
            "unknown_pct": [0.0] * len(damaged_values),
            "area": [100.0] * len(damaged_values),
            "geometry": [square(i) for i in range(len(damaged_values))],
        },
        crs="EPSG:4326",
    )
    frame.to_file(path, layer="predictions", driver="GPKG")
    return path


def write_footprints_gpkg(path: str, ids: list) -> str:
    frame = gpd.GeoDataFrame(
        {
            "id": ids,
            "geometry": [square(i) for i in range(len(ids))],
        },
        crs="EPSG:4326",
    )
    frame.to_file(path, driver="GPKG")
    return path


def read_rows(path: str, layer: str = None) -> list:
    with fiona.open(path, layer=layer) as src:
        return [dict(feature["properties"]) for feature in src]


class EditFixtureMixin(unittest.TestCase):
    def setUp(self):
        self.tmp_dir = tempfile.mkdtemp(prefix="haste-prediction-edits-")

    def tearDown(self):
        shutil.rmtree(self.tmp_dir, ignore_errors=True)

    def path(self, name: str) -> str:
        return os.path.join(self.tmp_dir, name)


class TestClassDerivation(EditFixtureMixin):
    def test_threshold_is_strictly_greater_than(self):
        src = write_inference_gpkg(
            self.path("src.gpkg"), [0.0, 0.5, 0.5000001, 0.9]
        )
        dst = self.path("dst.gpkg")

        summary = apply_edits(
            src, dst, threshold=0.5, unknown_threshold=0.0, overrides={}
        )

        classes = [row[EDITED_CLASS_FIELD] for row in read_rows(dst)]
        self.assertEqual(classes, [NOT_DAMAGED, NOT_DAMAGED, DAMAGED, DAMAGED])
        self.assertEqual(summary.damaged, 2)
        self.assertEqual(summary.not_damaged, 2)
        self.assertEqual(summary.unknown, 0)

    def test_zero_threshold_keeps_pristine_buildings_undamaged(self):
        src = write_inference_gpkg(self.path("src.gpkg"), [0.0, 0.0001])
        dst = self.path("dst.gpkg")

        apply_edits(src, dst, threshold=0.0, overrides={})

        classes = [row[EDITED_CLASS_FIELD] for row in read_rows(dst)]
        self.assertEqual(classes, [NOT_DAMAGED, DAMAGED])

    def test_unknown_takes_precedence_over_damaged(self):
        src = write_inference_gpkg(
            self.path("src.gpkg"),
            [0.9, 0.9, 0.1],
            unknown_values=[0.6, 0.0, 0.6],
        )
        dst = self.path("dst.gpkg")

        summary = apply_edits(
            src, dst, threshold=0.5, unknown_threshold=0.5, overrides={}
        )

        classes = [row[EDITED_CLASS_FIELD] for row in read_rows(dst)]
        self.assertEqual(classes, [UNKNOWN, DAMAGED, UNKNOWN])
        self.assertEqual(summary.unknown, 2)

    def test_unknown_threshold_is_strictly_greater_than(self):
        src = write_inference_gpkg(
            self.path("src.gpkg"),
            [0.9, 0.9],
            unknown_values=[0.5, 0.51],
        )
        dst = self.path("dst.gpkg")

        apply_edits(
            src, dst, threshold=0.5, unknown_threshold=0.5, overrides={}
        )

        classes = [row[EDITED_CLASS_FIELD] for row in read_rows(dst)]
        self.assertEqual(classes, [DAMAGED, UNKNOWN])

    def test_overrides_win_over_derived_classes(self):
        src = write_inference_gpkg(
            self.path("src.gpkg"),
            [0.9, 0.1, 0.1],
            unknown_values=[0.0, 0.0, 0.9],
        )
        dst = self.path("dst.gpkg")

        summary = apply_edits(
            src,
            dst,
            threshold=0.5,
            unknown_threshold=0.5,
            overrides={0: NOT_DAMAGED, 1: DAMAGED, 2: NOT_DAMAGED},
        )

        classes = [row[EDITED_CLASS_FIELD] for row in read_rows(dst)]
        self.assertEqual(classes, [NOT_DAMAGED, DAMAGED, NOT_DAMAGED])
        self.assertEqual(summary.overrides_applied, 3)

    def test_string_override_keys_are_accepted(self):
        src = write_inference_gpkg(self.path("src.gpkg"), [0.0, 0.0])
        dst = self.path("dst.gpkg")

        summary = apply_edits(
            src, dst, threshold=0.5, overrides={"1": DAMAGED}
        )

        classes = [row[EDITED_CLASS_FIELD] for row in read_rows(dst)]
        self.assertEqual(classes, [NOT_DAMAGED, DAMAGED])
        self.assertEqual(summary.overrides_applied, 1)

    def test_out_of_range_override_is_not_counted(self):
        src = write_inference_gpkg(self.path("src.gpkg"), [0.0, 0.0])
        dst = self.path("dst.gpkg")

        summary = apply_edits(src, dst, threshold=0.5, overrides={99: DAMAGED})

        self.assertEqual(summary.overrides_applied, 0)
        self.assertEqual(summary.total_rows, 2)


class TestRowOrderPreservation(EditFixtureMixin):
    """The downstream footprint join is positional — order is the API."""

    def test_output_row_order_matches_input(self):
        damage = [0.9, 0.0, 0.42, 0.1, 0.75, 0.0, 1.0]
        src = write_inference_gpkg(self.path("src.gpkg"), damage)
        dst = self.path("dst.gpkg")

        apply_edits(
            src,
            dst,
            threshold=0.5,
            overrides={1: DAMAGED, 4: NOT_DAMAGED},
        )

        with fiona.open(src) as source:
            src_rows = [
                (
                    feature["properties"]["id"],
                    feature["properties"]["damage_pct_0m"],
                    feature["geometry"]["coordinates"][0][0][0],
                )
                for feature in source
            ]
        with fiona.open(dst) as edited:
            dst_rows = [
                (
                    feature["properties"]["id"],
                    feature["properties"]["damage_pct_0m"],
                    feature["geometry"]["coordinates"][0][0][0],
                )
                for feature in edited
            ]

        self.assertEqual(dst_rows, src_rows)
        self.assertEqual([row[0] for row in dst_rows], list(range(7)))

    def test_row_order_preserved_for_embedding_flavor(self):
        src = write_embedding_gpkg(self.path("src.gpkg"), [1, 0, 0, 1, 1])
        dst = self.path("dst.gpkg")

        apply_edits(src, dst, threshold=0.5, overrides={})

        src_ids = [row["id"] for row in read_rows(src, layer="predictions")]
        dst_ids = [row["id"] for row in read_rows(dst, layer="predictions")]
        self.assertEqual(dst_ids, src_ids)


class TestOutputSchema(EditFixtureMixin):
    def test_all_source_columns_are_preserved(self):
        src = write_inference_gpkg(self.path("src.gpkg"), [0.8, 0.2])
        dst = self.path("dst.gpkg")

        apply_edits(src, dst, threshold=0.5, overrides={})

        with fiona.open(src) as source:
            source_fields = list(source.schema["properties"].keys())
        with fiona.open(dst) as edited:
            edited_fields = list(edited.schema["properties"].keys())

        self.assertEqual(edited_fields[: len(source_fields)], source_fields)
        self.assertEqual(
            edited_fields[len(source_fields) :],
            [EDITED_CLASS_FIELD, EDIT_THRESHOLD_FIELD, OVERTURE_ID_FIELD],
        )

        rows = read_rows(dst)
        self.assertEqual([row["damage_pct_10m"] for row in rows], [0.4, 0.1])
        self.assertEqual([row["damage_pct_20m"] for row in rows], [0.2, 0.05])

    def test_damaged_column_follows_final_class(self):
        src = write_inference_gpkg(
            self.path("src.gpkg"),
            [0.9, 0.9, 0.1],
            unknown_values=[0.0, 0.9, 0.0],
        )
        dst = self.path("dst.gpkg")

        apply_edits(
            src, dst, threshold=0.5, unknown_threshold=0.5, overrides={}
        )

        rows = read_rows(dst)
        self.assertEqual([row["damaged"] for row in rows], [1, 0, 0])
        self.assertEqual(
            [row[EDITED_CLASS_FIELD] for row in rows],
            [DAMAGED, UNKNOWN, NOT_DAMAGED],
        )

    def test_edit_threshold_is_recorded_on_every_row(self):
        src = write_inference_gpkg(self.path("src.gpkg"), [0.1, 0.9])
        dst = self.path("dst.gpkg")

        apply_edits(src, dst, threshold=0.35, overrides={})

        rows = read_rows(dst)
        self.assertEqual(
            [row[EDIT_THRESHOLD_FIELD] for row in rows], [0.35, 0.35]
        )

    def test_crs_and_layer_name_are_preserved(self):
        src = write_inference_gpkg(
            self.path("src.gpkg"), [0.1, 0.9], epsg=32610
        )
        dst = self.path("dst.gpkg")

        apply_edits(src, dst, threshold=0.5, overrides={})

        self.assertEqual(fiona.listlayers(dst), ["src"])
        with fiona.open(dst) as edited:
            self.assertEqual(edited.crs.to_epsg(), 32610)

    def test_source_file_is_not_modified(self):
        src = write_inference_gpkg(self.path("src.gpkg"), [0.1, 0.9])
        before = read_rows(src)

        apply_edits(
            src, self.path("dst.gpkg"), threshold=0.5, overrides={0: DAMAGED}
        )

        self.assertEqual(read_rows(src), before)

    def test_existing_output_is_replaced(self):
        src = write_inference_gpkg(self.path("src.gpkg"), [0.9, 0.9, 0.9])
        dst = write_inference_gpkg(self.path("dst.gpkg"), [0.0])

        summary = apply_edits(src, dst, threshold=0.5, overrides={})

        self.assertEqual(summary.total_rows, 3)
        self.assertEqual(len(read_rows(dst)), 3)


class TestOvertureIds(EditFixtureMixin):
    def test_overture_ids_are_written(self):
        src = write_inference_gpkg(self.path("src.gpkg"), [0.9, 0.1, 0.5])
        footprints = write_footprints_gpkg(
            self.path("fp.gpkg"), ["ovt-a", "ovt-b", "ovt-c"]
        )
        dst = self.path("dst.gpkg")

        apply_edits(
            src,
            dst,
            threshold=0.5,
            overrides={},
            footprints_path=footprints,
        )

        rows = read_rows(dst)
        self.assertEqual(
            [row[OVERTURE_ID_FIELD] for row in rows],
            ["ovt-a", "ovt-b", "ovt-c"],
        )

    def test_overture_id_is_empty_without_footprints(self):
        src = write_inference_gpkg(self.path("src.gpkg"), [0.9, 0.1])
        dst = self.path("dst.gpkg")

        apply_edits(src, dst, threshold=0.5, overrides={})

        rows = read_rows(dst)
        self.assertEqual([row[OVERTURE_ID_FIELD] for row in rows], ["", ""])

    def test_footprint_length_mismatch_raises(self):
        src = write_inference_gpkg(self.path("src.gpkg"), [0.9, 0.1, 0.5])
        footprints = write_footprints_gpkg(
            self.path("fp.gpkg"), ["ovt-a", "ovt-b"]
        )
        dst = self.path("dst.gpkg")

        with self.assertRaises(ValueError) as ctx:
            apply_edits(
                src,
                dst,
                threshold=0.5,
                overrides={},
                footprints_path=footprints,
            )

        self.assertIn("mismatch", str(ctx.exception))
        self.assertFalse(os.path.exists(dst))


class TestValidation(EditFixtureMixin):
    def test_invalid_override_class_raises(self):
        src = write_inference_gpkg(self.path("src.gpkg"), [0.9, 0.1])

        with self.assertRaises(ValueError) as ctx:
            apply_edits(
                src,
                self.path("dst.gpkg"),
                threshold=0.5,
                overrides={0: "destroyed"},
            )

        message = str(ctx.exception)
        self.assertIn("destroyed", message)
        self.assertIn("Damaged", message)
        self.assertFalse(os.path.exists(self.path("dst.gpkg")))

    def test_invalid_override_row_index_raises(self):
        src = write_inference_gpkg(self.path("src.gpkg"), [0.9, 0.1])

        with self.assertRaises(ValueError) as ctx:
            apply_edits(
                src,
                self.path("dst.gpkg"),
                threshold=0.5,
                overrides={"not-an-index": DAMAGED},
            )

        self.assertIn("integer", str(ctx.exception))

    def test_percentage_threshold_raises(self):
        src = write_inference_gpkg(self.path("src.gpkg"), [0.9, 0.1])

        with self.assertRaises(ValueError) as ctx:
            apply_edits(src, self.path("dst.gpkg"), threshold=50, overrides={})

        self.assertIn("fraction", str(ctx.exception))

    def test_negative_unknown_threshold_raises(self):
        src = write_inference_gpkg(self.path("src.gpkg"), [0.9, 0.1])

        with self.assertRaises(ValueError):
            apply_edits(
                src,
                self.path("dst.gpkg"),
                threshold=0.5,
                unknown_threshold=-0.1,
                overrides={},
            )

    @patch("hastegeo.core.processors.prediction_edits.derive_class")
    def test_partial_output_is_removed_on_failure(self, derive):
        derive.side_effect = RuntimeError("boom")
        src = write_inference_gpkg(self.path("src.gpkg"), [0.9, 0.1])
        dst = self.path("dst.gpkg")

        with self.assertRaises(RuntimeError):
            apply_edits(src, dst, threshold=0.5, overrides={})

        self.assertFalse(os.path.exists(dst))


class TestEditSummary(unittest.TestCase):
    def test_to_dict(self):
        summary = EditSummary(
            total_rows=3,
            counts={DAMAGED: 1, NOT_DAMAGED: 1, UNKNOWN: 1},
            overrides_applied=2,
        )

        self.assertEqual(
            summary.to_dict(),
            {
                "totalRows": 3,
                "counts": {DAMAGED: 1, NOT_DAMAGED: 1, UNKNOWN: 1},
                "overridesApplied": 2,
            },
        )


class TestNextVersion(unittest.TestCase):
    def test_empty_model_starts_at_one(self):
        self.assertEqual(next_version(Model(modelId="m1")), 1)
        self.assertEqual(next_version({}), 1)
        self.assertEqual(next_version({"editedPredictions": None}), 1)

    def test_single_existing_version(self):
        model = Model(
            modelId="m1",
            editedPredictions=[
                EditedPredictionVersion(
                    version=1,
                    gpkgUrl="https://example/v1.gpkg",
                    createdAt="2026-08-21T00:00:00Z",
                )
            ],
        )

        self.assertEqual(next_version(model), 2)

    def test_multiple_existing_versions_use_the_maximum(self):
        model_doc = {
            "editedPredictions": [
                {"version": 1, "gpkgUrl": "v1"},
                {"version": 3, "gpkgUrl": "v3"},
                {"version": 2, "gpkgUrl": "v2"},
            ]
        }

        self.assertEqual(next_version(model_doc), 4)

    def test_non_integer_versions_are_ignored(self):
        model_doc = {
            "editedPredictions": [
                {"version": 1},
                {"version": None},
                {"gpkgUrl": "no-version"},
            ]
        }

        self.assertEqual(next_version(model_doc), 2)


class TestStoreEditedVersion(EditFixtureMixin):
    def test_artifact_name_embeds_model_and_version(self):
        self.assertEqual(
            edited_version_artifact_name("model-123", 4),
            "edited_predictions_model-123_v4.gpkg",
        )

    def test_stores_and_returns_download_url(self):
        gpkg = write_inference_gpkg(self.path("edited.gpkg"), [0.9])
        processor = MagicMock()
        processor.get_download_url.return_value = "https://example/v2.gpkg"

        url = store_edited_version(
            "project-1",
            "model-123",
            2,
            gpkg,
            processor=processor,
        )

        self.assertEqual(url, "https://example/v2.gpkg")
        processor.store_artifact.assert_called_once_with(
            artifact_name="edited_predictions_model-123_v2.gpkg",
            src_path=gpkg,
        )
        processor.get_download_url.assert_called_once_with(
            identifier="edited_predictions_model-123_v2.gpkg"
        )

    def test_missing_local_file_raises(self):
        processor = MagicMock()

        with self.assertRaises(FileNotFoundError):
            store_edited_version(
                "project-1",
                "model-123",
                1,
                self.path("missing.gpkg"),
                processor=processor,
            )

        processor.store_artifact.assert_not_called()


if __name__ == "__main__":
    unittest.main()
