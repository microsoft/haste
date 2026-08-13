import unittest
import uuid

from hastegeo.core.models.publishing import (
    ArtifactBundle,
    PublishedDataset,
    SourceArtifact,
)
from hastegeo.core.publishing.stac import (
    ASSET_KEY_MAX_LENGTH,
    COLLECTION_ID_MAX_LENGTH,
    ITEM_ID_MAX_LENGTH,
    STAC_VERSION,
    build_collection_id,
    build_stac_objects,
    resolve_valid_mask_geometry,
    sanitize_asset_key,
    sanitize_collection_id,
    sanitize_item_id,
    serialize_stac_objects,
    validate_stac_objects,
)


class TestStacIdentifiers(unittest.TestCase):
    def test_identifier_rules_preserve_documented_punctuation(self) -> None:
        self.assertEqual(
            sanitize_collection_id("haste-Project_1.v2 / draft"),
            "haste-Project_1.v2-draft",
        )
        self.assertEqual(
            sanitize_item_id("response_(v2)+final,ok / 1"),
            "response_(v2)+final,ok-1",
        )
        self.assertEqual(
            sanitize_asset_key("damage_(merged)+v2.gpkg"),
            "damage_(merged)+v2.gpkg",
        )
        self.assertEqual(sanitize_item_id("valid."), "valid.")

    def test_identifier_rules_enforce_geocatalog_lengths(self) -> None:
        self.assertEqual(
            len(sanitize_collection_id("a" * 300)),
            COLLECTION_ID_MAX_LENGTH,
        )
        self.assertEqual(len(sanitize_item_id("a" * 300)), ITEM_ID_MAX_LENGTH)
        self.assertEqual(
            len(sanitize_asset_key("a" * 300)),
            ASSET_KEY_MAX_LENGTH,
        )

    def test_identifier_rules_reject_unicode_only_values(self) -> None:
        with self.assertRaisesRegex(ValueError, "letter or digit"):
            sanitize_collection_id("災害")


class TestValidMaskGeometry(unittest.TestCase):
    def test_resolves_union_bbox_and_area_in_wgs84(self) -> None:
        valid_mask = {
            "type": "FeatureCollection",
            "features": [
                {
                    "type": "Feature",
                    "properties": {},
                    "geometry": {
                        "type": "Polygon",
                        "coordinates": [
                            [[0, 0], [1, 0], [1, 1], [0, 1], [0, 0]]
                        ],
                    },
                },
                {
                    "type": "Feature",
                    "properties": {},
                    "geometry": {
                        "type": "Polygon",
                        "coordinates": [
                            [[2, 0], [3, 0], [3, 1], [2, 1], [2, 0]]
                        ],
                    },
                },
            ],
        }

        result = resolve_valid_mask_geometry(valid_mask)

        self.assertEqual(result.geometry["type"], "MultiPolygon")
        self.assertEqual(result.bbox, [0.0, 0.0, 3.0, 1.0])
        self.assertAlmostEqual(
            result.area_square_kilometers,
            24616.93,
            delta=25,
        )

    def test_reprojects_projected_mask_to_wgs84(self) -> None:
        valid_mask = {
            "type": "FeatureCollection",
            "features": [
                {
                    "type": "Feature",
                    "properties": {},
                    "geometry": {
                        "type": "Polygon",
                        "coordinates": [
                            [
                                [0, 0],
                                [111319.49, 0],
                                [111319.49, 111325.14],
                                [0, 111325.14],
                                [0, 0],
                            ]
                        ],
                    },
                }
            ],
        }

        result = resolve_valid_mask_geometry(valid_mask, "EPSG:3857")

        self.assertAlmostEqual(result.bbox[0], 0, places=5)
        self.assertAlmostEqual(result.bbox[1], 0, places=5)
        self.assertAlmostEqual(result.bbox[2], 1, places=5)
        self.assertAlmostEqual(result.bbox[3], 1, places=5)

    def test_rejects_wgs84_coordinates_outside_world_bounds(self) -> None:
        valid_mask = {
            "type": "FeatureCollection",
            "features": [
                {
                    "type": "Feature",
                    "properties": {},
                    "geometry": {
                        "type": "Polygon",
                        "coordinates": [
                            [[200, 0], [201, 0], [201, 1], [200, 1], [200, 0]]
                        ],
                    },
                }
            ],
        }

        with self.assertRaisesRegex(ValueError, "within EPSG:4326"):
            resolve_valid_mask_geometry(valid_mask)

    def test_rejects_non_polygon_geometry(self) -> None:
        valid_mask = {
            "type": "FeatureCollection",
            "features": [
                {
                    "type": "Feature",
                    "properties": {},
                    "geometry": {"type": "Point", "coordinates": [0, 0]},
                }
            ],
        }

        with self.assertRaisesRegex(ValueError, "polygon"):
            resolve_valid_mask_geometry(valid_mask)


class TestStacObjects(unittest.TestCase):
    def setUp(self) -> None:
        self.dataset = PublishedDataset(
            datasetId=uuid.UUID("11111111-1111-4111-8111-111111111111"),
            requestId=uuid.UUID("22222222-2222-4222-8222-222222222222"),
            requestFingerprint="a" * 64,
            name="Caracas damage assessment",
            description="Post-event building damage predictions",
            projectId=uuid.UUID("33333333-3333-4333-8333-333333333333"),
            projectName="Venezuela Earthquake / Caracas",
            imageLayerId="layer-1",
            imageLayerName="Post-event",
            modelId="42",
            modelName="Damage model",
            target="planetary_computer",
            status="IN_PROGRESS",
            publishedByUser="publisher",
            createdDate="2026-08-07T00:00:00Z",
            updatedDate="2026-08-07T01:00:00Z",
            assessmentSummary={
                "predictions": {
                    "total": 100,
                    "knownNonCloudy": 90,
                    "cloudy": 10,
                    "predictedDamaged": 18,
                    "predictedDamagedPctOfKnown": 20.0,
                },
                "metrics": {"precision": 0.8, "recall": 0.75},
                "populationEstimate": {
                    "estimatedDamaged": 19.2,
                    "ciLower": 15.0,
                    "ciUpper": 24.0,
                },
            },
        )
        self.damage = SourceArtifact(
            kind="gpkg",
            sourcePath="source/damage.gpkg",
            mediaType="application/geopackage+sqlite3",
            sizeBytes=100,
            sourceEtag="damage-etag",
        )
        self.footprints = SourceArtifact(
            kind="footprints",
            sourcePath="source/footprints.gpkg",
            mediaType="application/geopackage+sqlite3",
            sizeBytes=200,
            sourceEtag="footprints-etag",
        )
        self.mask = SourceArtifact(
            kind="valid_mask",
            sourcePath="source/mask.geojson",
            mediaType="application/geo+json",
            sizeBytes=300,
            sourceEtag="mask-etag",
        )
        self.valid_mask = {
            "type": "FeatureCollection",
            "features": [
                {
                    "type": "Feature",
                    "properties": {},
                    "geometry": {
                        "type": "Polygon",
                        "coordinates": [
                            [
                                [-67.1, 10.4],
                                [-67.0, 10.4],
                                [-67.0, 10.5],
                                [-67.1, 10.5],
                                [-67.1, 10.4],
                            ]
                        ],
                    },
                }
            ],
        }
        self.hrefs = {
            self.damage.sourcePath: "https://storage.test/damage.gpkg",
            self.footprints.sourcePath: (
                "https://storage.test/footprints.gpkg"
            ),
            self.mask.sourcePath: "https://storage.test/mask.geojson",
        }
        self.projections = {
            self.damage.sourcePath: "EPSG:4326",
            self.footprints.sourcePath: "EPSG:4326",
        }
        self.collection_href = (
            "https://catalog.test/stac/collections/"
            "haste-33333333-3333-4333-8333-333333333333"
        )

    def _build(self, source: ArtifactBundle, **kwargs):
        return build_stac_objects(
            self.dataset,
            source,
            self.valid_mask,
            self.hrefs,
            self.projections,
            self.collection_href,
            **kwargs,
        )

    def test_collection_id_is_stable_and_collision_resistant(self) -> None:
        renamed = self.dataset.model_copy(update={"projectName": "Renamed"})
        same_name_other_project = self.dataset.model_copy(
            update={
                "projectId": uuid.UUID("44444444-4444-4444-8444-444444444444")
            }
        )

        collection_id = build_collection_id(self.dataset)

        self.assertEqual(collection_id, build_collection_id(renamed))
        self.assertNotEqual(
            collection_id,
            build_collection_id(same_name_other_project),
        )
        self.assertTrue(collection_id.endswith(str(self.dataset.projectId)))

    def test_builds_collection_and_exact_selected_assets(self) -> None:
        objects = self._build(
            ArtifactBundle(
                selectedArtifacts=[self.damage, self.footprints],
                supportingArtifacts=[self.mask],
            )
        )

        validate_stac_objects(objects)
        documents = serialize_stac_objects(objects)
        item = documents.item
        collection = documents.collection

        self.assertEqual(collection["stac_version"], STAC_VERSION)
        self.assertEqual(item["stac_version"], STAC_VERSION)
        self.assertEqual(
            collection["id"],
            "haste-33333333-3333-4333-8333-333333333333",
        )
        self.assertEqual(item["id"], "11111111-1111-4111-8111-111111111111")
        self.assertEqual(set(item["assets"]), {"damage", "footprints"})
        self.assertEqual(
            item["assets"]["damage"]["type"],
            "application/geopackage+sqlite3",
        )
        self.assertEqual(item["assets"]["damage"]["roles"], ["data"])
        self.assertEqual(item["assets"]["damage"]["proj:code"], "EPSG:4326")
        self.assertEqual(
            item["assets"]["footprints"]["type"],
            "application/geopackage+sqlite3",
        )
        self.assertEqual(item["assets"]["footprints"]["roles"], ["data"])
        self.assertEqual(item["properties"]["ai4g:buildings_total"], 100)
        self.assertEqual(item["properties"]["ai4g:buildings_cloud"], 10)
        self.assertEqual(item["properties"]["ai4g:buildings_clear"], 90)
        self.assertEqual(item["properties"]["ai4g:buildings_damaged"], 18)
        self.assertEqual(item["properties"]["ai4g:damaged_pct_of_clear"], 20.0)
        self.assertEqual(item["properties"]["ai4g:validation_precision"], 0.8)
        self.assertEqual(item["properties"]["ai4g:validation_recall"], 0.75)
        self.assertEqual(
            item["properties"]["ai4g:validation_extrapolated_damaged"],
            19.2,
        )
        self.assertEqual(item["properties"]["ai4g:validation_ci_lower"], 15.0)
        self.assertEqual(item["properties"]["ai4g:validation_ci_upper"], 24.0)
        self.assertGreater(item["properties"]["ai4g:aoi_area_km2"], 0)

    def test_collection_description_is_a_rolling_dataset_summary(
        self,
    ) -> None:
        first = self._build(
            ArtifactBundle(
                selectedArtifacts=[self.damage],
                supportingArtifacts=[self.mask],
            )
        )
        first_collection = serialize_stac_objects(first).collection

        self.assertIn(
            "1 published dataset.", first_collection["description"]
        )
        self.assertIn(
            "Caracas damage assessment", first_collection["description"]
        )
        self.assertIn(
            "18 of 100 buildings assessed as damaged",
            first_collection["description"],
        )
        entries = first_collection["ai4g:datasets"]
        self.assertEqual(len(entries), 1)
        self.assertEqual(entries[0]["id"], str(self.dataset.datasetId))
        self.assertEqual(entries[0]["buildings_damaged"], 18)
        self.assertEqual(entries[0]["buildings_total"], 100)

        second_dataset = self.dataset.model_copy(
            update={
                "datasetId": uuid.UUID(
                    "55555555-5555-4555-8555-555555555555"
                ),
                "name": "Second layer assessment",
            }
        )
        second = build_stac_objects(
            second_dataset,
            ArtifactBundle(
                selectedArtifacts=[self.damage],
                supportingArtifacts=[self.mask],
            ),
            self.valid_mask,
            self.hrefs,
            self.projections,
            self.collection_href,
            existing_collection=first_collection,
        )
        second_collection = serialize_stac_objects(second).collection

        self.assertIn(
            "2 published datasets.", second_collection["description"]
        )
        self.assertIn(
            "Caracas damage assessment", second_collection["description"]
        )
        self.assertIn(
            "Second layer assessment", second_collection["description"]
        )
        self.assertEqual(len(second_collection["ai4g:datasets"]), 2)

    def test_collection_extent_merges_existing_project_items(self) -> None:
        existing_collection = {
            "id": build_collection_id(self.dataset),
            "summaries": {"ai4g:project_id": [str(self.dataset.projectId)]},
            "extent": {
                "spatial": {"bbox": [[-70, 8, -69, 9]]},
                "temporal": {
                    "interval": [
                        [
                            "2025-01-01T00:00:00Z",
                            "2025-02-01T00:00:00Z",
                        ]
                    ]
                },
            },
        }

        objects = self._build(
            ArtifactBundle(
                selectedArtifacts=[self.damage],
                supportingArtifacts=[self.mask],
            ),
            existing_collection=existing_collection,
        )
        extent = serialize_stac_objects(objects).collection["extent"]

        self.assertEqual(
            extent["spatial"]["bbox"],
            [[-70.0, 8.0, -67.0, 10.5]],
        )
        self.assertEqual(
            extent["temporal"]["interval"],
            [["2025-01-01T00:00:00Z", "2026-08-07T00:00:00Z"]],
        )

    def test_collection_extent_rejects_reversed_interval(self) -> None:
        existing_collection = {
            "id": build_collection_id(self.dataset),
            "summaries": {"ai4g:project_id": [str(self.dataset.projectId)]},
            "extent": {
                "spatial": {"bbox": [[-70, 8, -69, 9]]},
                "temporal": {
                    "interval": [
                        [
                            "2025-02-01T00:00:00Z",
                            "2025-01-01T00:00:00Z",
                        ]
                    ]
                },
            },
        }

        with self.assertRaisesRegex(ValueError, "interval"):
            self._build(
                ArtifactBundle(
                    selectedArtifacts=[self.damage],
                    supportingArtifacts=[self.mask],
                ),
                existing_collection=existing_collection,
            )

    def test_collection_extent_requires_matching_project_provenance(
        self,
    ) -> None:
        source = ArtifactBundle(
            selectedArtifacts=[self.damage],
            supportingArtifacts=[self.mask],
        )
        base_collection = {
            "id": build_collection_id(self.dataset),
            "extent": {
                "spatial": {"bbox": [[-70, 8, -69, 9]]},
                "temporal": {
                    "interval": [
                        [
                            "2025-01-01T00:00:00Z",
                            "2025-02-01T00:00:00Z",
                        ]
                    ]
                },
            },
        }
        for project_ids in (
            None,
            ["44444444-4444-4444-8444-444444444444"],
        ):
            existing_collection = dict(base_collection)
            if project_ids is not None:
                existing_collection["summaries"] = {
                    "ai4g:project_id": project_ids
                }
            with self.subTest(project_ids=project_ids):
                with self.assertRaisesRegex(ValueError, "provenance"):
                    self._build(
                        source,
                        existing_collection=existing_collection,
                    )

    def test_item_datetime_is_stable_across_retries(self) -> None:
        source = ArtifactBundle(
            selectedArtifacts=[self.damage],
            supportingArtifacts=[self.mask],
        )
        retried = self.dataset.model_copy(
            update={
                "updatedDate": "2026-09-01T00:00:00Z",
                "publishedDate": "2026-09-02T00:00:00Z",
            }
        )

        first = self._build(source)
        retry = build_stac_objects(
            retried,
            source,
            self.valid_mask,
            self.hrefs,
            self.projections,
            self.collection_href,
        )

        self.assertEqual(first.item.datetime, retry.item.datetime)
        self.assertEqual(
            serialize_stac_objects(first).item["properties"]["datetime"],
            "2026-08-07T00:00:00Z",
        )

    def test_selected_mask_is_exposed_as_aoi_asset(self) -> None:
        objects = self._build(
            ArtifactBundle(selectedArtifacts=[self.damage, self.mask])
        )

        self.assertEqual(set(objects.item.assets), {"damage", "aoi"})
        self.assertEqual(objects.item.assets["aoi"].roles, ["metadata"])
        self.assertEqual(
            objects.item.assets["aoi"].media_type,
            "application/geo+json",
        )

    def test_footprints_only_item_uses_footprints_projection(self) -> None:
        objects = build_stac_objects(
            self.dataset,
            ArtifactBundle(
                selectedArtifacts=[self.footprints],
                supportingArtifacts=[self.mask],
            ),
            self.valid_mask,
            self.hrefs,
            {self.footprints.sourcePath: "EPSG:3857"},
            self.collection_href,
        )
        item = serialize_stac_objects(objects).item

        self.assertEqual(item["properties"]["proj:code"], "EPSG:3857")
        self.assertEqual(
            item["assets"]["footprints"]["proj:code"], "EPSG:3857"
        )

    def test_projected_aoi_only_item_uses_source_projection(self) -> None:
        objects = build_stac_objects(
            self.dataset,
            ArtifactBundle(selectedArtifacts=[self.mask]),
            self.valid_mask,
            self.hrefs,
            self.projections,
            self.collection_href,
            valid_mask_crs="EPSG:3857",
        )
        item = serialize_stac_objects(objects).item

        self.assertEqual(item["properties"]["proj:code"], "EPSG:3857")
        self.assertEqual(item["assets"]["aoi"]["proj:code"], "EPSG:3857")

    def test_rejects_invalid_asset_inputs(self) -> None:
        source = ArtifactBundle(
            selectedArtifacts=[self.damage],
            supportingArtifacts=[self.mask],
        )
        with self.assertRaisesRegex(ValueError, "HTTPS"):
            build_stac_objects(
                self.dataset,
                source,
                self.valid_mask,
                {self.damage.sourcePath: "http://storage.test/damage.gpkg"},
                self.projections,
                self.collection_href,
            )
        with self.assertRaisesRegex(ValueError, "projection"):
            build_stac_objects(
                self.dataset,
                source,
                self.valid_mask,
                self.hrefs,
                {},
                self.collection_href,
            )
        with self.assertRaisesRegex(ValueError, "known EPSG"):
            build_stac_objects(
                self.dataset,
                source,
                self.valid_mask,
                self.hrefs,
                {self.damage.sourcePath: "EPSG:999999"},
                self.collection_href,
            )
        with self.assertRaisesRegex(ValueError, "at least one"):
            self._build(ArtifactBundle(supportingArtifacts=[self.mask]))

    def test_flat_assessment_summary_is_mapped(self) -> None:
        dataset = self.dataset.model_copy(
            update={
                "assessmentSummary": {
                    "predictedDamaged": 12,
                    "precision": 0.7,
                    "recall": 0.6,
                    "estimatedDamaged": 15.5,
                    "ciLower": 10.0,
                    "ciUpper": 20.0,
                }
            }
        )

        objects = build_stac_objects(
            dataset,
            ArtifactBundle(
                selectedArtifacts=[self.damage],
                supportingArtifacts=[self.mask],
            ),
            self.valid_mask,
            self.hrefs,
            self.projections,
            self.collection_href,
        )
        properties = serialize_stac_objects(objects).item["properties"]

        self.assertEqual(properties["ai4g:buildings_damaged"], 12)
        self.assertEqual(properties["ai4g:validation_precision"], 0.7)
        self.assertEqual(properties["ai4g:validation_recall"], 0.6)
        self.assertEqual(
            properties["ai4g:validation_extrapolated_damaged"], 15.5
        )
        self.assertEqual(properties["ai4g:validation_ci_lower"], 10.0)
        self.assertEqual(properties["ai4g:validation_ci_upper"], 20.0)


if __name__ == "__main__":
    unittest.main()
