import unittest

import geopandas as gpd
from shapely.geometry import Polygon

from hastegeo.core.publishing.tile import (
    detect_damage_mask,
    render_collection_tile,
)

_PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"


def _square(x: float, y: float, size: float = 0.0005) -> Polygon:
    return Polygon(
        [(x, y), (x + size, y), (x + size, y + size), (x, y + size)]
    )


class TestTileRenderer(unittest.TestCase):
    def setUp(self) -> None:
        self.aoi = gpd.GeoDataFrame(
            {"geometry": [_square(-67.1, 10.4, 0.02)]}, crs="EPSG:4326"
        )
        self.buildings = gpd.GeoDataFrame(
            {
                "damaged": [0, 1, 0, 1],
                "geometry": [
                    _square(-67.10, 10.40),
                    _square(-67.09, 10.41),
                    _square(-67.08, 10.42),
                    _square(-67.07, 10.43),
                ],
            },
            crs="EPSG:4326",
        )

    def test_renders_a_png(self) -> None:
        png = render_collection_tile(
            self.buildings,
            self.aoi,
            title="Caracas damage assessment",
            subtitle="4 buildings assessed | 2 flagged as damaged",
            width=400,
            height=210,
        )
        self.assertTrue(png.startswith(_PNG_SIGNATURE))
        self.assertGreater(len(png), 200)

    def test_renders_without_a_damage_column(self) -> None:
        buildings = self.buildings.drop(columns=["damaged"])
        png = render_collection_tile(
            buildings, self.aoi, title="X", width=200, height=120
        )
        self.assertTrue(png.startswith(_PNG_SIGNATURE))

    def test_renders_with_no_buildings(self) -> None:
        empty = self.buildings.iloc[0:0]
        png = render_collection_tile(
            empty, self.aoi, title="X", width=200, height=120
        )
        self.assertTrue(png.startswith(_PNG_SIGNATURE))

    def test_detect_damage_mask_variants(self) -> None:
        numeric = detect_damage_mask(self.buildings)
        self.assertEqual(list(numeric), [False, True, False, True])

        strings = self.buildings.assign(
            damaged=["no", "damaged", "false", "yes"]
        )
        self.assertEqual(
            list(detect_damage_mask(strings)), [False, True, False, True]
        )

        self.assertIsNone(
            detect_damage_mask(self.buildings.drop(columns=["damaged"]))
        )

    def test_rejects_degenerate_aoi_bounds(self) -> None:
        empty_aoi = self.aoi.iloc[0:0]
        with self.assertRaises(ValueError):
            render_collection_tile(self.buildings, empty_aoi, title="X")


if __name__ == "__main__":
    unittest.main()
