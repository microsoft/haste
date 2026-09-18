# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License.
import json
import os
import tempfile
import unittest
from unittest.mock import Mock, patch

from hastegeo.core.config import Config
from hastegeo.core.processors.metadata import MetadataProcessor
from hastegeo.core.processors.project_details import (
    ProjectDetailsProcessor,
    assemble_project_details,
)


class TestAssembleProjectDetails(unittest.TestCase):
    def setUp(self) -> None:
        self.project = {"projectId": "project-1", "name": "Project"}
        self.layers = [
            {
                "imageLayerId": "layer-old",
                "creationDate": "2026-01-01T00:00:00Z",
            },
            {
                "imageLayerId": "layer-new",
                "creationDate": "2026-02-01T00:00:00Z",
            },
        ]

    def test_joins_records_by_storage_key_when_body_ids_are_missing(
        self,
    ) -> None:
        models = [
            {
                "modelId": "model-1",
                "imageLayerId": "layer-new",
                "creationDate": "2026-02-02T00:00:00Z",
            }
        ]
        artifacts = {"model-1": {"metrics": {"iou": 0.8}}}
        validations = {"layer-new": {"labels": {"building-1": {}}}}

        result = assemble_project_details(
            self.project,
            self.layers,
            models,
            [{"imageLayerId": "layer-new", "labels": [{"id": "a"}]}],
            artifacts,
            validations,
            {"model-1": "https://example.test/model-1.geojson"},
            include_models=True,
        )

        newest_layer = result["imageLayer"][0]
        self.assertEqual(newest_layer["imageLayerId"], "layer-new")
        self.assertEqual(
            newest_layer["models"][0]["artifacts"], artifacts["model-1"]
        )
        self.assertEqual(newest_layer["validationLabelCount"], 1)
        self.assertEqual(newest_layer["labelProjectCount"], 1)
        self.assertEqual(
            newest_layer["models"][0]["labelsUrl"],
            "https://example.test/model-1.geojson",
        )

    def test_preserves_existing_labels_url(self) -> None:
        models = [
            {
                "modelId": "model-1",
                "imageLayerId": "layer-new",
                "creationDate": "2026-02-02T00:00:00Z",
                "labelsUrl": "https://stored.test/labels.geojson",
            }
        ]

        result = assemble_project_details(
            self.project,
            self.layers,
            models,
            [],
            {},
            {},
            {"model-1": "https://generated.test/labels.geojson"},
            include_models=True,
        )

        model = result["imageLayer"][0]["models"][0]
        self.assertEqual(
            model["labelsUrl"], "https://stored.test/labels.geojson"
        )
        self.assertIsNone(model["artifacts"])

    def test_preserves_existing_layer_labels_url(self) -> None:
        layer = dict(
            self.layers[1], labelsUrl="https://stored.test/layer.geojson"
        )

        result = assemble_project_details(
            self.project,
            [layer],
            [],
            [{"imageLayerId": "layer-new", "labels": []}],
            {},
            {},
            {},
            include_models=False,
        )

        self.assertEqual(
            result["imageLayer"][0]["labelsUrl"],
            "https://stored.test/layer.geojson",
        )

    def test_uses_first_label_project_for_duplicate_layer(self) -> None:
        result = assemble_project_details(
            self.project,
            [self.layers[1]],
            [],
            [
                {"imageLayerId": "layer-new", "labels": [{"id": "first"}]},
                {
                    "imageLayerId": "layer-new",
                    "labels": [{"id": "second"}, {"id": "third"}],
                },
                {"labels": []},
            ],
            {},
            {},
            {},
            include_models=False,
        )

        self.assertEqual(result["imageLayer"][0]["labelProjectCount"], 1)

    def test_missing_related_records_keep_legacy_defaults(self) -> None:
        result = assemble_project_details(
            self.project,
            self.layers,
            [],
            [],
            {},
            {},
            {},
            include_models=True,
        )

        for image_layer in result["imageLayer"]:
            self.assertEqual(image_layer["models"], [])
            self.assertEqual(image_layer["modelCount"], 0)
            self.assertEqual(image_layer["validationLabelCount"], 0)
            self.assertNotIn("labelProjectCount", image_layer)

    def test_excluding_models_does_not_add_model_fields(self) -> None:
        result = assemble_project_details(
            self.project,
            self.layers,
            [],
            [],
            {},
            {},
            {},
            include_models=False,
        )

        for image_layer in result["imageLayer"]:
            self.assertNotIn("models", image_layer)
            self.assertNotIn("modelCount", image_layer)

    def test_inputs_are_not_mutated(self) -> None:
        assemble_project_details(
            self.project,
            self.layers,
            [],
            [],
            {},
            {},
            {},
            include_models=False,
        )

        self.assertNotIn("imageLayer", self.project)
        for image_layer in self.layers:
            self.assertNotIn("validationLabelCount", image_layer)

    def test_complete_fixture_matches_expected_response_bytes(self) -> None:
        result = assemble_project_details(
            self.project,
            [self.layers[1]],
            [
                {
                    "modelId": "model-1",
                    "imageLayerId": "layer-new",
                    "creationDate": "2026-02-02T00:00:00Z",
                }
            ],
            [{"imageLayerId": "layer-new", "labels": [{"id": "a"}]}],
            {"model-1": {"metrics": {"iou": 0.8}}},
            {"layer-new": {"labels": {"building-1": {}}}},
            {"model-1": "https://example.test/model-1.geojson"},
            include_models=True,
        )
        expected = {
            "projectId": "project-1",
            "name": "Project",
            "imageLayer": [
                {
                    "imageLayerId": "layer-new",
                    "creationDate": "2026-02-01T00:00:00Z",
                    "models": [
                        {
                            "modelId": "model-1",
                            "imageLayerId": "layer-new",
                            "creationDate": "2026-02-02T00:00:00Z",
                            "artifacts": {"metrics": {"iou": 0.8}},
                            "labelsUrl": (
                                "https://example.test/model-1.geojson"
                            ),
                        }
                    ],
                    "modelCount": 1,
                    "labelProjectCount": 1,
                    "labelsUrl": None,
                    "validationLabelCount": 1,
                }
            ],
            "imageLayerCount": 1,
        }

        self.assertEqual(json.dumps(result), json.dumps(expected))


class TestProjectDetailsProcessor(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.types = Config.get_metadata_types()
        self.config = Mock()
        self.config.get_metadata_types.return_value = self.types
        self.processors = {}
        self.created_types = []

        for data_type in (
            self.types.PROJECT.value,
            self.types.IMAGELAYER.value,
            self.types.LABELS.value,
            self.types.MODEL.value,
            self.types.VALIDATION.value,
            self.types.MODEL_ARTIFACTS.value,
            self.types.TRAIN_LABELS.value,
        ):
            self.processors[data_type] = Mock()

        self.processors[self.types.PROJECT.value].load.return_value = {
            "projectId": "project-1",
            "name": "Project",
        }
        self.processors[
            self.types.IMAGELAYER.value
        ].load_all_from_partition.return_value = [
            {
                "imageLayerId": "layer-1",
                "creationDate": "2026-01-01T00:00:00Z",
            }
        ]
        self.processors[
            self.types.LABELS.value
        ].load_all_from_partition.return_value = []
        self.processors[
            self.types.MODEL.value
        ].load_all_from_partition.return_value = [
            {
                "modelId": "model-1",
                "imageLayerId": "layer-1",
                "creationDate": "2026-01-02T00:00:00Z",
            }
        ]
        self.processors[self.types.VALIDATION.value].load_map.return_value = {
            "layer-1": {"labels": {"building-1": {}}}
        }
        self.processors[
            self.types.MODEL_ARTIFACTS.value
        ].load_map.return_value = {"model-1": {"metrics": {"iou": 0.8}}}
        train_labels = self.processors[self.types.TRAIN_LABELS.value]
        train_labels.list_keys.return_value = ["model-1"]
        train_labels.build_url.return_value = (
            "https://example.test/model-1.geojson"
        )

    def factory(self, *, data_type, partition_key, config):
        self.assertEqual(partition_key, "project-1")
        self.assertIs(config, self.config)
        self.created_types.append(data_type)
        return self.processors[data_type]

    async def test_load_uses_keyed_maps_for_related_records(self) -> None:
        processor = ProjectDetailsProcessor(
            "project-1", self.config, self.factory
        )

        result = await processor.load(include_models=True)

        model = result["imageLayer"][0]["models"][0]
        self.assertEqual(model["artifacts"], {"metrics": {"iou": 0.8}})
        self.assertEqual(result["imageLayer"][0]["validationLabelCount"], 1)
        self.processors[
            self.types.VALIDATION.value
        ].load_map.assert_called_once_with(["layer-1"])
        self.processors[
            self.types.MODEL_ARTIFACTS.value
        ].load_map.assert_called_once_with(["model-1"])

    async def test_load_without_models_skips_model_storage(self) -> None:
        processor = ProjectDetailsProcessor(
            "project-1", self.config, self.factory
        )

        result = await processor.load(include_models=False)

        self.assertNotIn(self.types.MODEL.value, self.created_types)
        self.assertNotIn(self.types.MODEL_ARTIFACTS.value, self.created_types)
        self.assertNotIn(self.types.TRAIN_LABELS.value, self.created_types)
        self.assertNotIn("models", result["imageLayer"][0])

    async def test_train_label_listing_falls_back_to_legacy_export(
        self,
    ) -> None:
        train_labels = self.processors[self.types.TRAIN_LABELS.value]
        train_labels.list_keys.side_effect = NotImplementedError
        train_labels.export.return_value = (
            "https://fallback.test/model-1.geojson"
        )
        processor = ProjectDetailsProcessor(
            "project-1", self.config, self.factory
        )

        result = await processor.load(include_models=True)

        model = result["imageLayer"][0]["models"][0]
        self.assertEqual(
            model["labelsUrl"], "https://fallback.test/model-1.geojson"
        )
        train_labels.export.assert_called_once_with(
            "model-1", data_format="geojson"
        )

    async def test_missing_legacy_train_label_export_returns_none(
        self,
    ) -> None:
        train_labels = self.processors[self.types.TRAIN_LABELS.value]
        train_labels.list_keys.side_effect = NotImplementedError
        train_labels.export.side_effect = FileNotFoundError
        processor = ProjectDetailsProcessor(
            "project-1", self.config, self.factory
        )

        result = await processor.load(include_models=True)

        self.assertIsNone(result["imageLayer"][0]["models"][0]["labelsUrl"])

    async def test_existing_model_url_skips_train_label_storage(self) -> None:
        model = self.processors[self.types.MODEL.value]
        model.load_all_from_partition.return_value[0][
            "labelsUrl"
        ] = "https://stored.test/model.geojson"
        processor = ProjectDetailsProcessor(
            "project-1", self.config, self.factory
        )

        result = await processor.load(include_models=True)

        self.assertEqual(
            result["imageLayer"][0]["models"][0]["labelsUrl"],
            "https://stored.test/model.geojson",
        )
        self.assertNotIn(self.types.TRAIN_LABELS.value, self.created_types)

    async def test_unsupported_train_label_url_is_returned_as_none(
        self,
    ) -> None:
        train_labels = self.processors[self.types.TRAIN_LABELS.value]
        train_labels.build_url.side_effect = NotImplementedError
        processor = ProjectDetailsProcessor(
            "project-1", self.config, self.factory
        )

        result = await processor.load(include_models=True)

        model = result["imageLayer"][0]["models"][0]
        self.assertIsNone(model["labelsUrl"])

    async def test_project_load_failure_stops_partition_reads(self) -> None:
        self.processors[
            self.types.PROJECT.value
        ].load.side_effect = FileNotFoundError
        processor = ProjectDetailsProcessor(
            "project-1", self.config, self.factory
        )

        with self.assertRaises(FileNotFoundError):
            await processor.load(include_models=True)

        self.assertEqual(self.created_types, [self.types.PROJECT.value])


class TestProjectDetailsLocalStorage(unittest.IsolatedAsyncioTestCase):
    async def test_load_preserves_keyed_legacy_records_end_to_end(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as data_path:
            with patch.dict(
                os.environ,
                {
                    "METADATA_STORAGE_TYPE": "local",
                    "DATA_PATH": data_path,
                },
            ):
                config = Config()
                types = config.get_metadata_types()
                records = (
                    (
                        types.PROJECT.value,
                        "project-1",
                        {"projectId": "project-1"},
                    ),
                    (
                        types.IMAGELAYER.value,
                        "layer-1",
                        {
                            "imageLayerId": "layer-1",
                            "creationDate": "2026-01-01T00:00:00Z",
                        },
                    ),
                    (
                        types.MODEL.value,
                        "model-1",
                        {
                            "modelId": "model-1",
                            "imageLayerId": "layer-1",
                            "creationDate": "2026-01-02T00:00:00Z",
                        },
                    ),
                    (types.MODEL_ARTIFACTS.value, "model-1", {"metrics": {}}),
                    (types.VALIDATION.value, "layer-1", {"labels": {"a": {}}}),
                )
                for data_type, key, value in records:
                    MetadataProcessor(
                        data_type=data_type,
                        partition_key="project-1",
                        config=config,
                    ).save(key, value)

                result = await ProjectDetailsProcessor(
                    "project-1", config=config
                ).load(include_models=True)

        image_layer = result["imageLayer"][0]
        self.assertEqual(
            image_layer["models"][0]["artifacts"], {"metrics": {}}
        )
        self.assertEqual(image_layer["validationLabelCount"], 1)


if __name__ == "__main__":
    unittest.main()
