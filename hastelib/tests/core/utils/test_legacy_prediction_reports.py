# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License.

"""Report-only positional compatibility never weakens producer/edit inputs."""

import os
import tempfile
import unittest

import fiona
from hastegeo.core.utils.assessment import (
    build_assessment_inputs_from_gpkgs,
    compute_assessment_report,
)
from hastegeo.core.utils.prediction_attrs import build_prediction_attrs
from hastegeo.core.utils.prediction_edits import apply_prediction_edits
from hastegeo.core.utils.predictions import (
    FootprintPredictionMismatchError,
    read_effective_prediction_classes,
    read_predictions,
)

from .prediction_edit_fixtures import native_snapshot, write_prediction_pair


class LegacyPredictionReportTest(unittest.TestCase):
    def setUp(self) -> None:
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.directory = temporary.name
        self.raw, self.footprints = write_prediction_pair(
            self.directory, [0.0, 1.0, None], [0.0, 0.0, None]
        )
        self.legacy = os.path.join(self.directory, "legacy.gpkg")

    def write_legacy(
        self,
        ids: tuple = (0, 1, 2),
        *,
        id_type: str = "int",
        overture_ids: tuple | None = None,
        edited: bool = False,
        crs: str | None = "EPSG:6933",
    ) -> None:
        with fiona.open(self.raw) as src:
            layer = src.name
            fields = dict(src.schema["properties"])
            geometry_type = src.schema["geometry"]
            source = [
                {
                    "geometry": row["geometry"],
                    "properties": dict(row["properties"]),
                }
                for row in src
            ]
        fields["id"] = id_type
        if overture_ids is None:
            del fields["overture_id"]
        if edited:
            fields["edited_class"] = "str"
        if os.path.exists(self.legacy):
            fiona.remove(self.legacy, driver="GPKG")
        with fiona.open(
            self.legacy,
            "w",
            driver="GPKG",
            layer=layer,
            crs=crs,
            schema={"geometry": geometry_type, "properties": fields},
        ) as dst:
            for position, row_id in enumerate(ids):
                row = source[position % len(source)]
                props = dict(row["properties"])
                props["id"] = row_id
                if overture_ids is None:
                    del props["overture_id"]
                else:
                    props["overture_id"] = overture_ids[position]
                if edited:
                    props["edited_class"] = "Damaged"
                    props["damaged"] = 1
                dst.write({"geometry": row["geometry"], "properties": props})

    def assert_reports_reject(self) -> None:
        with self.assertRaises(FootprintPredictionMismatchError):
            read_effective_prediction_classes(self.legacy, self.footprints)
        with self.assertRaises(FootprintPredictionMismatchError):
            build_assessment_inputs_from_gpkgs(self.footprints, self.legacy)

    def test_both_report_readers_accept_legacy_raw_without_mutating_files(
        self,
    ) -> None:
        self.write_legacy()
        before = native_snapshot(self.legacy)
        files_before = sorted(os.listdir(self.directory))
        for source_flag in (None, False):
            with self.subTest(is_edited=source_flag):
                classes = read_effective_prediction_classes(
                    self.legacy, self.footprints, is_edited=source_flag
                )
                inputs = build_assessment_inputs_from_gpkgs(
                    self.footprints, self.legacy, is_edited=source_flag
                )
                report = compute_assessment_report(inputs)
                self.assertEqual(
                    classes,
                    {
                        "building-0": "NotDamaged",
                        "building-1": "Damaged",
                        "building-2": "Unknown",
                    },
                )
                self.assertEqual(
                    inputs.damage_fractions,
                    {"building-0": 0.0, "building-1": 1.0, "building-2": None},
                )
                self.assertFalse(inputs.is_edited)
                self.assertEqual(report["predictions"]["total"], 3)
                self.assertEqual(report["predictions"]["predictedDamaged"], 1)
                self.assertEqual(report["predictions"]["cloudy"], 1)
        self.assertEqual(native_snapshot(self.legacy), before)
        self.assertEqual(sorted(os.listdir(self.directory)), files_before)
        with fiona.open(self.legacy) as src:
            self.assertNotIn("overture_id", src.schema["properties"])

    def test_legacy_embedding_schema_is_supported_without_score_heuristics(
        self,
    ) -> None:
        self.raw, self.footprints = write_prediction_pair(
            self.directory,
            [0.0, 1.0, None],
            [0.0, 0.0, None],
            flavor="embedding",
        )
        self.write_legacy()
        classes = read_effective_prediction_classes(
            self.legacy, self.footprints, flavor="embedding"
        )
        inputs = build_assessment_inputs_from_gpkgs(
            self.footprints, self.legacy, flavor="embedding"
        )
        self.assertEqual(classes["building-1"], "Damaged")
        self.assertEqual(
            compute_assessment_report(inputs)["predictions"][
                "predictedDamaged"
            ],
            1,
        )
        with self.assertRaises(ValueError):
            read_effective_prediction_classes(
                self.legacy, self.footprints, threshold=0.5
            )

    def test_binary_legacy_inference_still_supports_thresholds(self) -> None:
        self.write_legacy()
        classes = read_effective_prediction_classes(
            self.legacy, self.footprints, flavor="inference", threshold=1.0
        )
        inputs = build_assessment_inputs_from_gpkgs(
            self.footprints, self.legacy
        )
        self.assertEqual(classes["building-1"], "NotDamaged")
        self.assertEqual(
            compute_assessment_report(inputs, threshold=1.0)["predictions"][
                "predictedDamaged"
            ],
            0,
        )

    def test_both_reports_reject_mismatched_counts_order_and_stored_ids(
        self,
    ) -> None:
        for ids in (
            (0, 1),
            (0, 1, 2, 3),
            (1, 0, 2),
            (0, 0, 2),
            (0, 2, 3),
            (-1, 1, 2),
            (0, 1, 9),
            (None, 1, 2),
        ):
            with self.subTest(ids=ids):
                self.write_legacy(ids)
                self.assert_reports_reject()
        for id_type, ids in (
            ("str", ("0", "1", "2")),
            ("float", (0.0, 1.0, 2.0)),
        ):
            with self.subTest(id_type=id_type):
                self.write_legacy(ids, id_type=id_type)
                self.assert_reports_reject()

    def test_present_overture_ids_are_verified_by_both_reports(self) -> None:
        self.write_legacy(
            overture_ids=("building-0", "building-1", "building-2")
        )
        self.assertEqual(
            read_effective_prediction_classes(self.legacy, self.footprints)[
                "building-1"
            ],
            "Damaged",
        )
        build_assessment_inputs_from_gpkgs(self.footprints, self.legacy)
        for ids in (
            ("building-1", "building-0", "building-2"),
            ("building-0", "wrong", "building-2"),
            ("building-0", None, "building-2"),
        ):
            with self.subTest(ids=ids):
                self.write_legacy(overture_ids=ids)
                self.assert_reports_reject()

    def test_both_reports_still_require_crs(self) -> None:
        self.write_legacy(crs=None)
        with self.assertRaisesRegex(ValueError, "CRS"):
            read_effective_prediction_classes(self.legacy, self.footprints)
        with self.assertRaisesRegex(ValueError, "CRS"):
            build_assessment_inputs_from_gpkgs(self.footprints, self.legacy)

    def test_edited_sources_never_use_positional_compatibility(self) -> None:
        self.write_legacy(edited=True)
        for source_flag in (None, False, True):
            with self.subTest(is_edited=source_flag), self.assertRaises(
                ValueError
            ):
                read_effective_prediction_classes(
                    self.legacy, self.footprints, is_edited=source_flag
                )
        self.write_legacy()
        with self.assertRaises(ValueError):
            read_effective_prediction_classes(
                self.legacy, self.footprints, is_edited=True
            )

    def test_producers_sidecars_and_edit_application_remain_strict(
        self,
    ) -> None:
        self.write_legacy()
        with self.assertRaises(ValueError):
            read_predictions(self.legacy, self.footprints)
        with self.assertRaises(ValueError):
            build_prediction_attrs(
                self.legacy, self.footprints, prediction_revision="generation"
            )
        gpkg = os.path.join(self.directory, "must-not-exist.gpkg")
        attrs = os.path.join(self.directory, "must-not-exist.json")
        with self.assertRaises(ValueError):
            apply_prediction_edits(
                self.legacy,
                self.footprints,
                gpkg,
                attrs,
                prediction_revision="generation",
                version=1,
            )
        self.assertFalse(os.path.exists(gpkg))
        self.assertFalse(os.path.exists(attrs))

    def test_empty_legacy_raw_is_a_valid_empty_report(self) -> None:
        self.raw, self.footprints = write_prediction_pair(self.directory, [])
        self.write_legacy(ids=())
        self.assertEqual(
            read_effective_prediction_classes(self.legacy, self.footprints), {}
        )
        inputs = build_assessment_inputs_from_gpkgs(
            self.footprints, self.legacy
        )
        self.assertEqual(
            compute_assessment_report(inputs)["predictions"]["total"], 0
        )
