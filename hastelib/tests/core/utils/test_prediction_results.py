# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License.

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

import fiona
from hastegeo.core.utils.assessment import (
    build_assessment_inputs_from_gpkgs,
    compute_assessment_report,
)
from hastegeo.core.utils.prediction_results import (
    iter_building_predictions,
    load_binary_building_predictions,
    source_building_ids,
)
from shapely.geometry import box, mapping


class TestPredictionResults(unittest.TestCase):
    def setUp(self) -> None:
        directory = Path(self.enterContext(TemporaryDirectory()))
        self.footprints = directory / "footprints.gpkg"
        self.predictions = directory / "predictions.gpkg"
        self.write(
            self.footprints,
            {"id": "str"},
            [
                {"id": "A"},
                {"id": "B"},
                {"id": "C"},
            ],
        )

    @staticmethod
    def write(path: Path, fields: dict, rows: list[dict]) -> None:
        with fiona.open(
            path,
            "w",
            driver="GPKG",
            crs="EPSG:3857",
            schema={"geometry": "Polygon", "properties": fields},
        ) as target:
            for index, properties in enumerate(rows):
                target.write(
                    {
                        "geometry": mapping(
                            box(index * 20, 0, index * 20 + 10, 10)
                        ),
                        "properties": properties,
                    }
                )

    def test_catalog_source_ids_survive_order_changes_and_nodata(self) -> None:
        self.write(
            self.predictions,
            {
                "id": "int",
                "source_building_id": "str",
                "damaged": "int",
                "damage_pct_0m": "float",
                "unknown_pct": "float",
            },
            [
                {
                    "id": 0,
                    "source_building_id": "C",
                    "damaged": None,
                    "damage_pct_0m": None,
                    "unknown_pct": None,
                },
                {
                    "id": 1,
                    "source_building_id": "A",
                    "damaged": 1,
                    "damage_pct_0m": 0.8,
                    "unknown_pct": 0.0,
                },
                {
                    "id": 2,
                    "source_building_id": "B",
                    "damaged": 0,
                    "damage_pct_0m": 0.0,
                    "unknown_pct": 0.0,
                },
            ],
        )
        binary = load_binary_building_predictions(
            str(self.footprints), str(self.predictions)
        )
        self.assertEqual(binary, {"A": 1, "B": 0})
        inputs = build_assessment_inputs_from_gpkgs(
            str(self.footprints),
            str(self.predictions),
            labels=[("A", "Damaged"), ("C", "NotDamaged")],
        )
        report = compute_assessment_report(inputs)
        self.assertEqual(report["predictions"]["total"], 3)
        self.assertEqual(report["predictions"]["knownNonCloudy"], 2)
        self.assertEqual(report["predictions"]["cloudy"], 0)
        self.assertEqual(report["predictions"]["unscored"], 1)
        self.assertEqual(report["predictions"]["predictedDamaged"], 1)
        self.assertEqual(report["matched"], 1)
        self.assertEqual(report["labeledMissingFromPredictions"], 1)

    def test_legacy_positional_join_and_unknown_binary_values(self) -> None:
        self.write(
            self.predictions,
            {"id": "int", "damaged": "int"},
            [
                {"id": 2, "damaged": 1},
                {"id": 0, "damaged": 0},
                {"id": 1, "damaged": -1},
            ],
        )
        self.assertEqual(
            load_binary_building_predictions(
                str(self.footprints), str(self.predictions)
            ),
            {"C": 1, "A": 0},
        )

    def test_invalid_explicit_identity_does_not_fall_back_to_row_order(
        self,
    ) -> None:
        self.write(
            self.predictions,
            {"id": "int", "source_building_id": "str"},
            [
                {"id": 0, "source_building_id": "not-in-source"},
            ],
        )
        with self.assertRaisesRegex(ValueError, "identity is invalid"):
            list(
                iter_building_predictions(
                    str(self.footprints), str(self.predictions)
                )
            )

    def test_missing_source_id_uses_the_same_fid_as_catalog_aggregation(
        self,
    ) -> None:
        self.footprints.unlink()
        self.write(
            self.footprints, {"other": "str"}, [{"other": "a"}, {"other": "b"}]
        )
        ids = source_building_ids(str(self.footprints))
        self.write(
            self.predictions,
            {"id": "int", "source_building_id": "str", "damaged": "int"},
            [
                {"id": 0, "source_building_id": ids[0], "damaged": 1},
            ],
        )
        self.assertEqual(
            load_binary_building_predictions(
                str(self.footprints), str(self.predictions)
            ),
            {ids[0]: 1},
        )
