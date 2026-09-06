# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License.

"""Native GeoPackage tests for the shared raw reader and sidecar contract."""

import json
import os
import tempfile
import unittest

import fiona
from hastegeo.core.utils.prediction_attrs import (
    FootprintPredictionMismatchError,
    attrs_artifact_name,
    build_prediction_attrs,
    write_prediction_attrs,
)
from hastegeo.core.utils.predictions import read_predictions
from shapely.geometry import box, mapping


class PredictionAttributesTest(unittest.TestCase):
    def setUp(self) -> None:
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.directory = temporary.name
        self.footprints = os.path.join(self.directory, "footprints.gpkg")
        self.predictions = os.path.join(self.directory, "result.gpkg")
        self.attrs = os.path.join(self.directory, "attrs.json")

    def write_footprints(
        self,
        ids: tuple = ("source-a", "source-b"),
        crs: str | None = "EPSG:4326",
    ) -> None:
        if os.path.exists(self.footprints):
            fiona.remove(self.footprints, driver="GPKG")
        with fiona.open(
            self.footprints,
            "w",
            driver="GPKG",
            schema={"geometry": "Polygon", "properties": {"id": "str"}},
            crs=crs,
        ) as dst:
            for index, source_id in enumerate(ids):
                dst.write(
                    {
                        "geometry": mapping(box(index, 0, index + 0.01, 0.01)),
                        "properties": {"id": source_id},
                    }
                )

    def write_predictions(
        self,
        values: tuple = (0.0, 1.0),
        unknowns: tuple | None = None,
        ids: tuple | None = None,
        overture_ids: tuple | None = None,
        flavor: str = "inference",
        crs: str | None = "EPSG:4326",
        omit: str | None = None,
        id_type: str = "int",
        damaged: tuple | None = None,
    ) -> None:
        fields = {
            "id": id_type,
            "overture_id": "str",
            "damage_pct_0m": "float",
            "unknown_pct": "float",
            "damaged": "int",
        }
        if flavor == "embedding":
            fields["area"] = "float"
        if omit:
            del fields[omit]
        if os.path.exists(self.predictions):
            fiona.remove(self.predictions, driver="GPKG")
        with fiona.open(
            self.predictions,
            "w",
            driver="GPKG",
            layer="predictions" if flavor == "embedding" else "inference",
            schema={"geometry": "Polygon", "properties": fields},
            crs=crs,
        ) as dst:
            for index, damage in enumerate(values):
                props = {
                    "id": index if ids is None else ids[index],
                    "overture_id": (
                        f"source-{chr(97 + index)}"
                        if overture_ids is None
                        else overture_ids[index]
                    ),
                    "damage_pct_0m": damage,
                    "unknown_pct": (
                        0.0 if unknowns is None else unknowns[index]
                    ),
                    "damaged": (
                        int(damage is not None and damage > 0)
                        if damaged is None
                        else damaged[index]
                    ),
                }
                if flavor == "embedding":
                    props["area"] = 100.0
                if omit:
                    del props[omit]
                dst.write(
                    {
                        "geometry": mapping(box(index, 0, index + 0.01, 0.01)),
                        "properties": props,
                    }
                )

    def build(self, **kwargs) -> dict:
        return build_prediction_attrs(
            self.predictions,
            self.footprints,
            prediction_revision="generation-1",
            **kwargs,
        )

    def test_binary_inference_stays_inference_even_for_one_row(self) -> None:
        for values in ((0.0, 1.0), (0.0,), (1.0,)):
            with self.subTest(values=values):
                self.write_predictions(values=values)
                result = read_predictions(self.predictions)
                self.assertEqual(result.flavor, "inference")
                self.assertTrue(result.supports_threshold)
                self.assertEqual(result.crs.to_epsg(), 4326)

    def test_embedding_schema_controls_flavor_including_empty(self) -> None:
        for values in ((0.0, 1.0), ()):
            with self.subTest(values=values):
                self.write_predictions(values=values, flavor="embedding")
                result = read_predictions(self.predictions)
                self.assertEqual(result.flavor, "embedding")
                self.assertFalse(result.supports_threshold)

    def test_explicit_flavor_must_match_schema(self) -> None:
        self.write_predictions()
        for flavor in ("other", "embedding"):
            with self.subTest(flavor=flavor), self.assertRaises(ValueError):
                read_predictions(self.predictions, flavor=flavor)

    def test_actual_json_has_provenance_and_source_aligned_columns(
        self,
    ) -> None:
        self.write_footprints()
        self.write_predictions(values=(0.0, 0.25))
        payload = write_prediction_attrs(
            self.predictions,
            self.footprints,
            self.attrs,
            prediction_revision="generation-1",
            footprint_fingerprint="optional-fingerprint",
        )
        with open(self.attrs, encoding="utf-8") as handle:
            self.assertEqual(json.load(handle), payload)
        self.assertEqual(payload["schemaVersion"], 1)
        self.assertEqual(payload["predictionRevision"], "generation-1")
        self.assertEqual(
            payload["footprintFingerprint"], "optional-fingerprint"
        )
        self.assertEqual(payload["n"], 2)
        self.assertEqual(payload["ids"], [0, 1])
        self.assertEqual(payload["overtureIds"], ["source-a", "source-b"])
        self.assertEqual(payload["damage"], [0.0, 0.25])
        self.assertEqual(payload["classes"], ["NotDamaged", "Damaged"])
        self.assertEqual(payload["damaged"], [0, 1])
        for value in payload.values():
            if isinstance(value, list):
                self.assertEqual(len(value), 2)

    def test_null_nonfinite_and_cloud_scores_are_unknown(self) -> None:
        self.write_footprints(("source-a", "source-b", "source-c", "source-d"))
        self.write_predictions(
            values=(None, float("nan"), float("inf"), 0.8),
            unknowns=(None, 0.0, float("-inf"), 0.1),
            damaged=(0, 0, 0, 1),
        )
        payload = write_prediction_attrs(
            self.predictions,
            self.footprints,
            self.attrs,
            prediction_revision="generation-1",
        )
        self.assertEqual(payload["damage"], [None, None, None, 0.8])
        self.assertEqual(payload["unknown"], [None, 0.0, None, 0.1])
        self.assertEqual(payload["classes"], ["Unknown"] * 4)
        with open(self.attrs, encoding="utf-8") as handle:
            text = handle.read()
        self.assertNotIn("NaN", text)
        self.assertNotIn("Infinity", text)
        self.assertEqual(json.loads(text), payload)

    def test_tiny_positive_scores_keep_zero_default_semantics(self) -> None:
        self.write_footprints()
        self.write_predictions(values=(1e-10, 0.0), unknowns=(0.0, 1e-10))
        payload = self.build()
        self.assertEqual(payload["damage"][0], 1e-10)
        self.assertEqual(payload["classes"], ["Damaged", "Unknown"])
        self.assertNotIn("footprintFingerprint", payload)

    def test_unscored_unknown_fraction_does_not_become_known(self) -> None:
        self.write_footprints()
        self.write_predictions(unknowns=(None, 0.0))
        self.assertEqual(self.build()["classes"], ["Unknown", "Damaged"])

    def test_empty_sources_write_valid_empty_columns(self) -> None:
        self.write_footprints(())
        self.write_predictions(values=())
        payload = self.build()
        self.assertEqual(payload["n"], 0)
        for key in (
            "ids",
            "overtureIds",
            "damage",
            "unknown",
            "damaged",
            "classes",
        ):
            self.assertEqual(payload[key], [])

    def test_prediction_stored_ids_cannot_be_reenumerated(self) -> None:
        self.write_footprints()
        for ids in ((1, 0), (0, 0), (0, 2), (-1, 0)):
            with self.subTest(ids=ids):
                self.write_predictions(ids=ids)
                with self.assertRaises(FootprintPredictionMismatchError):
                    self.build()

    def test_string_ids_cannot_be_coerced_to_row_indices(self) -> None:
        self.write_predictions(ids=("0", "1"), id_type="str")
        with self.assertRaises(FootprintPredictionMismatchError):
            read_predictions(self.predictions)

    def test_count_and_equal_count_source_mismatches_fail(self) -> None:
        self.write_predictions()
        for ids in (
            ("source-a",),
            ("source-b", "source-a"),
            ("replacement-a", "replacement-b"),
        ):
            with self.subTest(ids=ids):
                self.write_footprints(ids)
                with self.assertRaises(FootprintPredictionMismatchError):
                    self.build()

    def test_missing_duplicate_and_null_source_ids_fail(self) -> None:
        self.write_footprints()
        for ids in (
            ("source-a", "source-a"),
            (None, "source-b"),
            ("", "source-b"),
        ):
            with self.subTest(ids=ids):
                self.write_predictions(overture_ids=ids)
                with self.assertRaises(FootprintPredictionMismatchError):
                    self.build()

    def test_duplicate_footprint_ids_fail(self) -> None:
        self.write_footprints(("same", "same"))
        self.write_predictions()
        with self.assertRaises(FootprintPredictionMismatchError):
            self.build()

    def test_missing_required_columns_fail(self) -> None:
        for name in (
            "id",
            "overture_id",
            "damage_pct_0m",
            "unknown_pct",
            "damaged",
        ):
            with self.subTest(name=name):
                self.write_predictions(omit=name)
                with self.assertRaisesRegex(ValueError, "missing columns"):
                    read_predictions(self.predictions)

    def test_missing_crs_fails_for_either_source(self) -> None:
        self.write_footprints()
        self.write_predictions(crs=None)
        with self.assertRaisesRegex(ValueError, "CRS"):
            self.build()
        self.write_footprints(crs=None)
        self.write_predictions()
        with self.assertRaisesRegex(ValueError, "CRS"):
            self.build()

    def test_out_of_range_scores_and_nonbinary_calls_fail(self) -> None:
        for values, unknowns, damaged in (
            ((-0.1, 0.0), (0.0, 0.0), (0, 0)),
            ((1.1, 0.0), (0.0, 0.0), (1, 0)),
            ((0.0, 0.0), (0.0, 1.1), (0, 0)),
            ((0.0, 0.0), (0.0, 0.0), (0, 2)),
        ):
            with self.subTest(
                values=values, unknowns=unknowns, damaged=damaged
            ):
                self.write_predictions(
                    values=values, unknowns=unknowns, damaged=damaged
                )
                with self.assertRaises(ValueError):
                    read_predictions(self.predictions)

    def test_missing_revision_and_write_failures_propagate(self) -> None:
        self.write_footprints()
        self.write_predictions()
        with self.assertRaises(ValueError):
            build_prediction_attrs(
                self.predictions, self.footprints, prediction_revision=""
            )
        with self.assertRaises(OSError):
            write_prediction_attrs(
                self.predictions,
                self.footprints,
                self.directory,
                prediction_revision="generation-1",
            )

    def test_artifact_name_uses_safe_reference_basename(self) -> None:
        self.assertEqual(
            attrs_artifact_name("5557"), "prediction_attrs_5557.json"
        )
        for model_id in ("../5557", "", "1/2"):
            with self.subTest(model_id=model_id), self.assertRaises(
                ValueError
            ):
                attrs_artifact_name(model_id)

    def test_sidecar_cannot_overwrite_an_input(self) -> None:
        self.write_footprints()
        self.write_predictions()
        for path in (self.footprints, self.predictions):
            with self.subTest(path=path), self.assertRaises(ValueError):
                write_prediction_attrs(
                    self.predictions,
                    self.footprints,
                    path,
                    prediction_revision="revision",
                )
            with fiona.open(path) as src:
                self.assertEqual(len(src), 2)
