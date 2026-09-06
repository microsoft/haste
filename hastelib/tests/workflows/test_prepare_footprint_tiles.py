# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License.

"""Unit tests for the footprint tiling workflow.

The tippecanoe step needs the binary and is exercised on the dev stack,
not here. What these tests pin is the part that silently corrupts a map
when it goes wrong: the tiling GeoJSON's id space. Predictions and
embeddings join to the footprints GeoPackage positionally, so ``id`` has
to be 0..N-1 in the file's native order, and every row has to survive.
"""

import os
import tempfile
import unittest

import fiona
from fiona.crs import CRS
from fiona.model import Feature, Geometry
from hastegeo.workflows import prepare_footprint_tiles as workflow


def _square(i, offset=0.0):
    x = float(i) + offset
    return Geometry(
        type="Polygon",
        coordinates=[
            [
                (x, 0.0),
                (x + 0.0005, 0.0),
                (x + 0.0005, 0.0005),
                (x, 0.0005),
                (x, 0.0),
            ]
        ],
    )


def _write_footprints(path, overture_ids, crs="EPSG:4326"):
    schema = {"geometry": "Polygon", "properties": {"id": "str"}}
    with fiona.open(
        path,
        "w",
        driver="GPKG",
        crs=CRS.from_string(crs),
        schema=schema,
    ) as dst:
        for i, oid in enumerate(overture_ids):
            dst.write(Feature(geometry=_square(i), properties={"id": oid}))


class TestFootprintsToTilingGeojson(unittest.TestCase):
    def test_id_is_the_row_index_and_overture_id_is_preserved(self):
        with tempfile.TemporaryDirectory() as tmp:
            src = os.path.join(tmp, "footprints.gpkg")
            dst = os.path.join(tmp, "tiles.geojson")
            _write_footprints(src, ["over-a", "over-b", "over-c"])

            count = workflow.footprints_to_tiling_geojson(src, dst)
            self.assertEqual(count, 3)

            with fiona.open(dst) as read_back:
                rows = [feat["properties"] for feat in read_back]

        # The positional join key: 0..N-1 in the footprints file's order.
        self.assertEqual([row["id"] for row in rows], [0, 1, 2])
        self.assertEqual(
            [row["overture_id"] for row in rows],
            ["over-a", "over-b", "over-c"],
        )

    def test_every_footprint_survives(self):
        # A dropped row would shift every later id and silently mis-colour
        # buildings, so the count is a hard invariant.
        with tempfile.TemporaryDirectory() as tmp:
            src = os.path.join(tmp, "footprints.gpkg")
            dst = os.path.join(tmp, "tiles.geojson")
            _write_footprints(src, [f"over-{i}" for i in range(25)])

            count = workflow.footprints_to_tiling_geojson(src, dst)
            with fiona.open(dst) as read_back:
                self.assertEqual(len(list(read_back)), 25)

        self.assertEqual(count, 25)

    def test_reprojects_to_4326(self):
        with tempfile.TemporaryDirectory() as tmp:
            src = os.path.join(tmp, "footprints.gpkg")
            dst = os.path.join(tmp, "tiles.geojson")
            _write_footprints(src, ["a", "b"], crs="EPSG:3857")

            workflow.footprints_to_tiling_geojson(src, dst)
            with fiona.open(dst) as read_back:
                self.assertEqual(read_back.crs.to_epsg(), 4326)

    def test_rejects_an_empty_geopackage(self):
        with tempfile.TemporaryDirectory() as tmp:
            src = os.path.join(tmp, "footprints.gpkg")
            dst = os.path.join(tmp, "tiles.geojson")
            _write_footprints(src, [])

            with self.assertRaises(ValueError):
                workflow.footprints_to_tiling_geojson(src, dst)

    def test_rejects_footprints_without_an_overture_id(self):
        with tempfile.TemporaryDirectory() as tmp:
            src = os.path.join(tmp, "footprints.gpkg")
            dst = os.path.join(tmp, "tiles.geojson")
            schema = {
                "geometry": "Polygon",
                "properties": {"name": "str"},
            }
            with fiona.open(
                src,
                "w",
                driver="GPKG",
                crs=CRS.from_epsg(4326),
                schema=schema,
            ) as handle:
                handle.write(
                    Feature(geometry=_square(0), properties={"name": "no id"})
                )

            with self.assertRaises(ValueError):
                workflow.footprints_to_tiling_geojson(src, dst)


class TestArtifactNaming(unittest.TestCase):
    def test_archive_is_keyed_on_the_layer(self):
        self.assertEqual(
            workflow.default_pmtiles_name("layer-3"),
            "footprints_layer-3.pmtiles",
        )


class TestTippecanoeGuard(unittest.TestCase):
    def test_missing_binary_names_the_image_that_ships_it(self):
        # A bare FileNotFoundError from subprocess tells an operator
        # nothing; this message has to say where tippecanoe lives.
        if workflow.shutil.which(workflow.TIPPECANOE_BIN):
            self.skipTest("tippecanoe is installed in this environment")
        with self.assertRaises(workflow.TippecanoeNotFoundError) as ctx:
            workflow.require_tippecanoe()
        self.assertIn("training", str(ctx.exception))


if __name__ == "__main__":
    unittest.main()
