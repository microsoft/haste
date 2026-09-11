# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License.

"""Native saved-version tests: model preservation, pins and eager sidecars."""

import json
import math
import os
import tempfile
import unittest
from unittest.mock import patch

import fiona
from hastegeo.core.utils.prediction_attrs import (
    build_edited_prediction_attrs,
    build_prediction_attrs,
    write_edited_prediction_attrs,
)
from hastegeo.core.utils.prediction_edits import (
    PredictionOverride,
    apply_prediction_edits,
)
from hastegeo.core.utils.predictions import (
    FootprintPredictionMismatchError,
    read_effective_prediction_classes,
    read_predictions,
)

from .prediction_edit_fixtures import (
    native_snapshot,
    rewrite_properties,
    write_prediction_pair,
)


class PredictionEditsTest(unittest.TestCase):
    def setUp(self) -> None:
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.directory = temporary.name
        self.raw, self.footprints = write_prediction_pair(
            self.directory, [0.0, 0.2, 0.8, None], [0.0, 0.0, 0.6, None]
        )

    def apply(self, version: int = 1, **kwargs):
        return apply_prediction_edits(
            self.raw,
            self.footprints,
            os.path.join(self.directory, f"v{version}.gpkg"),
            os.path.join(self.directory, f"v{version}.json"),
            prediction_revision="generation-a",
            version=version,
            **kwargs,
        )

    def assert_no_outputs(self) -> None:
        self.assertFalse(
            os.path.exists(os.path.join(self.directory, "v1.gpkg"))
        )
        self.assertFalse(
            os.path.exists(os.path.join(self.directory, "v1.json"))
        )

    def test_preserves_raw_native_geometry_crs_identity_and_all_model_scores(
        self,
    ) -> None:
        before = native_snapshot(self.raw)
        footprints_before = native_snapshot(self.footprints)
        result = self.apply(
            threshold=0.5,
            unknown_threshold=0.5,
            overrides=[
                PredictionOverride(3, "Damaged"),
                PredictionOverride(0, "Damaged"),
                PredictionOverride(2, "NotDamaged"),
            ],
        )
        self.assertEqual(native_snapshot(self.raw), before)
        self.assertEqual(native_snapshot(self.footprints), footprints_before)
        saved = native_snapshot(result.gpkg_path)
        self.assertEqual(saved["layers"], before["layers"])
        self.assertEqual(saved["crs"], before["crs"])
        for original, edited in zip(before["rows"], saved["rows"]):
            self.assertEqual(edited["geometry"], original["geometry"])
            for key, value in original["properties"].items():
                if key != "damaged":
                    self.assertEqual(edited["properties"][key], value)
            self.assertEqual(
                edited["properties"]["model_damaged"],
                original["properties"]["damaged"],
            )
        self.assertEqual(result.count, 4)
        self.assertEqual(result.summary.total_rows, 4)
        self.assertEqual(result.summary.overrides_applied, 3)
        self.assertEqual(result.summary.changed_from_model, 4)
        self.assertEqual(
            result.summary.counts,
            {"Damaged": 2, "NotDamaged": 2, "Unknown": 0},
        )
        self.assertEqual(
            result.payload["classes"],
            ["Damaged", "NotDamaged", "NotDamaged", "Damaged"],
        )
        self.assertEqual(
            result.payload["modelClasses"],
            ["NotDamaged", "Damaged", "Unknown", "Unknown"],
        )
        self.assertEqual(
            result.payload["overrideClasses"],
            ["Damaged", None, "NotDamaged", "Damaged"],
        )
        self.assertEqual(result.payload["damage"], [0.0, 0.2, 0.8, None])
        self.assertEqual(result.payload["unknown"], [0.0, 0.0, 0.6, None])
        self.assertEqual(result.payload["damaged"], [1, 0, 0, 1])
        self.assertEqual(result.payload["predictionRevision"], "generation-a")
        self.assertEqual(result.payload["predictionVersion"], 1)
        self.assertIs(result.payload["isEdited"], True)
        self.assertEqual(result.payload["schemaVersion"], 1)
        self.assertEqual(result.payload["threshold"], 0.5)
        self.assertEqual(result.payload["unknownThreshold"], 0.5)
        with open(result.attrs_path, encoding="utf-8") as handle:
            self.assertEqual(json.load(handle), result.payload)
        for key, value in result.payload.items():
            if isinstance(value, list):
                self.assertEqual(len(value), 4, key)

    def test_damage_and_unknown_threshold_boundaries_are_strict(self) -> None:
        self.raw, self.footprints = write_prediction_pair(
            self.directory,
            [0.0, 0.5, math.nextafter(0.5, 1.0), 1.0],
        )
        result = self.apply(threshold=0.5)
        self.assertEqual(
            result.payload["classes"], ["NotDamaged"] * 2 + ["Damaged"] * 2
        )
        self.assertEqual(result.payload["damage"][2], math.nextafter(0.5, 1.0))
        endpoint = self.apply(version=2, threshold=1.0)
        self.assertEqual(endpoint.payload["classes"], ["NotDamaged"] * 4)
        self.raw, self.footprints = write_prediction_pair(
            self.directory,
            [0.9, 0.9],
            [0.5, math.nextafter(0.5, 1.0)],
        )
        cloud = self.apply(version=3, threshold=0.5, unknown_threshold=0.5)
        self.assertEqual(cloud.payload["classes"], ["Damaged", "Unknown"])
        self.assertEqual(
            self.apply(version=4, unknown_threshold=1.0).payload["classes"],
            ["Damaged"] * 2,
        )

    def test_zero_defaults_keep_pristine_and_tiny_positive_distinct(
        self,
    ) -> None:
        self.raw, self.footprints = write_prediction_pair(
            self.directory, [0.0, 1e-12]
        )
        self.assertEqual(
            self.apply().payload["classes"], ["NotDamaged", "Damaged"]
        )

    def test_binary_inference_still_accepts_thresholds(self) -> None:
        self.raw, self.footprints = write_prediction_pair(
            self.directory, [0.0, 1.0]
        )
        result = self.apply(threshold=1.0, flavor="inference")
        self.assertEqual(result.payload["flavor"], "inference")
        self.assertEqual(result.payload["classes"], ["NotDamaged"] * 2)

    def test_embedding_rejects_nonzero_thresholds_before_writing(self) -> None:
        self.raw, self.footprints = write_prediction_pair(
            self.directory,
            [0.0, 1.0],
            flavor="embedding",
        )
        for kwargs in ({"threshold": 0.1}, {"unknown_threshold": 1.0}):
            with self.subTest(kwargs=kwargs), self.assertRaises(ValueError):
                self.apply(**kwargs)
            self.assert_no_outputs()
        result = self.apply(overrides=[PredictionOverride(0, "Unknown")])
        self.assertEqual(result.payload["flavor"], "embedding")
        self.assertEqual(fiona.listlayers(result.gpkg_path), ["predictions"])
        self.assertEqual(
            read_effective_prediction_classes(
                result.gpkg_path,
                self.footprints,
                is_edited=True,
                threshold=1.0,
            ),
            {"building-0": "Unknown", "building-1": "Damaged"},
        )

    def test_right_click_pin_restores_model_not_saved_or_threshold_class(
        self,
    ) -> None:
        self.raw, self.footprints = write_prediction_pair(
            self.directory, [0.2]
        )
        first = self.apply(threshold=0.5)
        before = native_snapshot(first.gpkg_path)
        self.assertEqual(first.payload["classes"], ["NotDamaged"])
        self.assertEqual(first.payload["modelClasses"], ["Damaged"])
        restored = self.apply(
            version=2,
            threshold=0.5,
            overrides=[
                PredictionOverride(0, first.payload["modelClasses"][0])
            ],
        )
        self.assertEqual(restored.payload["classes"], ["Damaged"])
        self.assertEqual(restored.payload["overrideClasses"], ["Damaged"])
        self.assertEqual(restored.summary.changed_from_model, 0)
        self.assertEqual(restored.summary.overrides_applied, 1)
        again = self.apply(
            version=3,
            threshold=0.5,
            overrides=[
                PredictionOverride(0, restored.payload["overrideClasses"][0])
            ],
        )
        self.assertEqual(again.payload["overrideClasses"], ["Damaged"])
        self.assertEqual(native_snapshot(first.gpkg_path), before)

    def test_complete_snapshot_carries_prior_assignments_when_resaving(
        self,
    ) -> None:
        first = self.apply(overrides=[PredictionOverride(0, "Damaged")])
        snapshot = [
            PredictionOverride(index, value)
            for index, value in enumerate(first.payload["overrideClasses"])
            if value is not None
        ]
        snapshot.append(PredictionOverride(1, "Unknown"))
        second = self.apply(version=2, overrides=snapshot)
        self.assertEqual(second.payload["classes"][:2], ["Damaged", "Unknown"])
        self.assertEqual(
            second.payload["overrideClasses"][:2], ["Damaged", "Unknown"]
        )
        self.assertEqual(
            second.payload["modelClasses"], first.payload["modelClasses"]
        )
        with open(first.attrs_path, encoding="utf-8") as handle:
            self.assertEqual(json.load(handle), first.payload)

    def test_edited_baseline_is_rejected(self) -> None:
        first = self.apply()
        self.raw = first.gpkg_path
        with self.assertRaisesRegex(ValueError, "raw prediction"):
            self.apply(version=2)
        self.assertFalse(
            os.path.exists(os.path.join(self.directory, "v2.gpkg"))
        )

    def test_raw_sidecar_classes_do_not_mark_an_edited_baseline(self) -> None:
        raw_attrs = build_prediction_attrs(
            self.raw, self.footprints, prediction_revision="generation-a"
        )
        self.assertIn("classes", raw_attrs)
        self.assertNotIn("isEdited", raw_attrs)
        self.assertEqual(
            self.apply().payload["modelClasses"], raw_attrs["classes"]
        )

    def test_existing_destinations_are_never_replaced(self) -> None:
        first = self.apply()
        before = native_snapshot(first.gpkg_path)
        with self.assertRaises(FileExistsError):
            self.apply()
        self.assertEqual(native_snapshot(first.gpkg_path), before)
        fiona.remove(first.gpkg_path, driver="GPKG")
        with self.assertRaises(FileExistsError):
            self.apply()
        with open(first.attrs_path, encoding="utf-8") as handle:
            self.assertEqual(json.load(handle), first.payload)
        self.assertFalse(os.path.exists(first.gpkg_path))

    def test_input_output_aliases_and_hardlinks_are_rejected(self) -> None:
        before = native_snapshot(self.raw)
        target = os.path.join(self.directory, "new.json")
        for gpkg, attrs in (
            (self.raw, target),
            (target, self.raw),
            (target, target),
        ):
            with self.subTest(gpkg=gpkg, attrs=attrs), self.assertRaises(
                ValueError
            ):
                apply_prediction_edits(
                    self.raw,
                    self.footprints,
                    gpkg,
                    attrs,
                    prediction_revision="generation-a",
                    version=1,
                )
        linked = os.path.join(self.directory, "v1.gpkg")
        os.link(self.raw, linked)
        with self.assertRaises(ValueError):
            self.apply()
        self.assertEqual(native_snapshot(self.raw), before)

    def test_invalid_thresholds_are_rejected_before_writing(self) -> None:
        for name in ("threshold", "unknown_threshold"):
            for value in (
                True,
                None,
                "0.5",
                -0.1,
                1.1,
                float("nan"),
                float("inf"),
            ):
                with self.subTest(name=name, value=value), self.assertRaises(
                    ValueError
                ):
                    self.apply(**{name: value})
                self.assert_no_outputs()

    def test_invalid_override_ids_duplicates_and_classes_fail_before_writing(
        self,
    ) -> None:
        cases = [
            [PredictionOverride(value, "Damaged")]
            for value in (-1, 4, True, 1.0, "1")
        ] + [
            [
                PredictionOverride(0, "Damaged"),
                PredictionOverride(0, "Unknown"),
            ],
            [PredictionOverride(0, "Other")],
            [PredictionOverride(0, None)],
            [{"row_index": 0, "edited_class": "Damaged"}],
        ]
        for overrides in cases:
            with self.subTest(overrides=overrides), self.assertRaises(
                ValueError
            ):
                self.apply(overrides=overrides)
            self.assert_no_outputs()

    def test_nonpositive_or_noninteger_versions_fail_before_writing(
        self,
    ) -> None:
        for version in (0, -1, True, 1.0, "1"):
            with self.subTest(version=version), self.assertRaises(ValueError):
                self.apply(version=version)
        self.assert_no_outputs()

    def test_source_overture_mismatch_fails_before_writing(self) -> None:
        rewrite_properties(
            self.raw, lambda i, p: p.update(overture_id="wrong")
        )
        with self.assertRaises(FootprintPredictionMismatchError):
            self.apply()
        self.assert_no_outputs()

    def test_empty_sources_produce_valid_empty_edited_artifacts(self) -> None:
        self.raw, self.footprints = write_prediction_pair(self.directory, [])
        result = self.apply()
        self.assertEqual(result.count, 0)
        self.assertEqual(result.summary.changed_from_model, 0)
        self.assertEqual(result.payload["classes"], [])
        self.assertEqual(result.payload["modelClasses"], [])
        self.assertEqual(result.payload["overrideClasses"], [])
        self.assertTrue(result.payload["isEdited"])
        self.assertEqual(
            read_effective_prediction_classes(
                result.gpkg_path, self.footprints, is_edited=True
            ),
            {},
        )

    def test_failed_json_write_cleans_only_new_artifacts(self) -> None:
        before = native_snapshot(self.raw)

        def fail_dump(payload, handle, **kwargs) -> None:
            handle.write('{"incomplete":')
            raise OSError("test disk failure")

        with patch(
            "hastegeo.core.utils.prediction_attrs.json.dump",
            side_effect=fail_dump,
        ), self.assertRaises(OSError):
            self.apply()
        self.assert_no_outputs()
        self.assertEqual(native_snapshot(self.raw), before)

    def test_builder_reads_written_effective_classes_and_verifies_provenance(
        self,
    ) -> None:
        result = self.apply(overrides=[PredictionOverride(3, "Damaged")])
        payload = build_edited_prediction_attrs(
            result.gpkg_path,
            self.footprints,
            prediction_revision="generation-a",
            version=1,
        )
        self.assertEqual(payload, result.payload)
        with self.assertRaises(ValueError):
            build_prediction_attrs(
                result.gpkg_path,
                self.footprints,
                prediction_revision="generation-a",
            )
        with self.assertRaises(FileExistsError):
            write_edited_prediction_attrs(
                result.gpkg_path,
                self.footprints,
                result.attrs_path,
                prediction_revision="generation-a",
                version=1,
            )
        rewrite_properties(
            result.gpkg_path,
            lambda i, p: p.update(model_class="Damaged") if i == 3 else None,
        )
        with self.assertRaisesRegex(ValueError, "baseline"):
            build_edited_prediction_attrs(
                result.gpkg_path,
                self.footprints,
                prediction_revision="generation-a",
                version=1,
            )

    def test_effective_reader_source_marker_must_match(self) -> None:
        result = self.apply()
        with self.assertRaises(ValueError):
            read_effective_prediction_classes(
                self.raw, self.footprints, is_edited=True
            )
        with self.assertRaises(ValueError):
            read_effective_prediction_classes(
                result.gpkg_path, self.footprints, is_edited=False
            )
        self.assertEqual(
            read_effective_prediction_classes(
                result.gpkg_path, self.footprints
            ),
            dict(
                zip(result.payload["overtureIds"], result.payload["classes"])
            ),
        )
        self.assertFalse(read_predictions(result.gpkg_path).supports_threshold)
        self.assertTrue(read_predictions(self.raw).supports_threshold)

    def test_geographic_crs_and_null_geometries_are_preserved(self) -> None:
        self.raw, self.footprints = write_prediction_pair(
            self.directory, [None], [None], crs="EPSG:4326", null_geometry=True
        )
        before = native_snapshot(self.raw)
        result = self.apply(overrides=[PredictionOverride(0, "Damaged")])
        after = native_snapshot(result.gpkg_path)
        self.assertEqual(after["crs"], before["crs"])
        self.assertIsNone(after["rows"][0]["geometry"])
        self.assertEqual(result.payload["classes"], ["Damaged"])
        self.assertEqual(result.payload["modelClasses"], ["Unknown"])
        self.assertEqual(result.payload["damage"], [None])
        self.assertEqual(native_snapshot(self.raw), before)

    def test_provenance_validation_precedes_writes_and_fingerprint_is_optional(
        self,
    ) -> None:
        with self.assertRaises(ValueError):
            apply_prediction_edits(
                self.raw,
                self.footprints,
                os.path.join(self.directory, "v1.gpkg"),
                os.path.join(self.directory, "v1.json"),
                prediction_revision="",
                version=1,
            )
        self.assert_no_outputs()
        result = self.apply(footprint_fingerprint="optional-identity")
        self.assertEqual(
            result.payload["footprintFingerprint"], "optional-identity"
        )
        self.assertEqual(
            result.summary.to_dict()["changedFromModel"],
            result.summary.changed_from_model,
        )
