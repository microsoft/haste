# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License.

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from hastegeo.core.config import Config
from hastegeo.core.models.pretrained_inference import CatalogInferenceSpec
from hastegeo.core.models.training import CatalogModel
from hastegeo.core.processors.catalog_import import (
    ModelCatalogAssetImporter,
    dinov2_followup_entries,
    file_sha256,
)
from hastegeo.core.processors.model_catalog import CatalogConflictError


class TestCatalogImport(unittest.TestCase):
    def setUp(self) -> None:
        self.directory = Path(self.enterContext(TemporaryDirectory()))
        self.config = Config()
        self.config.storage_type = self.config.artifact_storage_type = "local"
        self.config.storage_config = {
            "directory": str(self.directory / "metadata")
        }
        self.config.artifact_storage_config = {
            "directory": str(self.directory / "artifacts")
        }
        self.importer = ModelCatalogAssetImporter(self.config)
        self.checkpoint = self.directory / "model.ckpt"
        self.backbone = self.directory / "config.json"
        self.checkpoint.write_bytes(b"opaque checkpoint fixture")
        self.backbone.write_text('{"model_type":"dinov3_vit"}')
        self.entry = CatalogModel(
            baseModelName="Fixture DINOv3",
            source="external",
            cataloguedByUser="operator",
            capabilities=["inference"],
            inferenceSpec=CatalogInferenceSpec(
                adapter="dinov3_upernet",
                checkpointFilePath="model.ckpt",
                checkpointSha256=file_sha256(self.checkpoint),
                backboneConfigPath="config.json",
                backboneConfigSha256=file_sha256(self.backbone),
                backbone="dinov3_vits16",
                labelGrouping="any",
                inputKind="rgb",
                numChannels=3,
                normalizationMeans=[0.485, 0.456, 0.406],
                normalizationStds=[0.229, 0.224, 0.225],
            ),
        )

    def test_import_is_idempotent_preserving_other_catalog_entries(
        self,
    ) -> None:
        self.importer.catalog.add(
            CatalogModel(
                baseModelName="Other",
                source="external",
                cataloguedByUser="operator",
                checkpointFilePath="elsewhere",
            )
        )
        first = self.importer.import_model(
            self.entry, self.checkpoint, self.backbone
        )
        with patch.object(
            self.importer.artifacts,
            "store_artifact",
            wraps=self.importer.artifacts.store_artifact,
        ) as upload:
            second = self.importer.import_model(
                self.entry, self.checkpoint, self.backbone
            )
        upload.assert_not_called()
        self.assertEqual(first, second)
        self.assertIn(file_sha256(self.checkpoint), first.checkpointFilePath)
        self.assertEqual(len(self.importer.catalog.records()), 2)

    def test_changed_local_asset_does_not_publish_a_catalog_entry(
        self,
    ) -> None:
        self.checkpoint.write_bytes(b"changed")
        with self.assertRaisesRegex(ValueError, "SHA-256"):
            self.importer.import_model(
                self.entry, self.checkpoint, self.backbone
            )
        self.assertEqual(self.importer.catalog.records(), [])

    def test_dinov3_cannot_enter_the_training_catalog_through_api_validation(
        self,
    ) -> None:
        for capabilities in (None, ["training"], ["training", "inference"]):
            with self.subTest(capabilities=capabilities):
                data = self.entry.model_dump(mode="json")
                data["capabilities"] = capabilities
                with self.assertRaisesRegex(ValueError, "inference only"):
                    CatalogModel.model_validate(data)

    def test_dinov3_requires_the_transformer_image_not_the_training_image(
        self,
    ) -> None:
        with patch.dict(
            "os.environ",
            {"AZURE_BATCH_TRANSFORMER_INFERENCE_DOCKER_IMAGE": ""},
        ):
            with self.assertRaisesRegex(ValueError, "transformer inference"):
                self.importer.catalog.inference_image(self.entry.inferenceSpec)
        with patch.dict(
            "os.environ",
            {
                "AZURE_BATCH_TRANSFORMER_INFERENCE_DOCKER_IMAGE": "registry/hastetransformerinference:fixture"
            },
        ):
            self.assertEqual(
                self.importer.catalog.inference_image(
                    self.entry.inferenceSpec
                ),
                "registry/hastetransformerinference:fixture",
            )

    def test_existing_corrupt_content_is_rejected_not_overwritten(
        self,
    ) -> None:
        first = self.importer.import_model(
            self.entry, self.checkpoint, self.backbone
        )
        stored = self.importer.artifacts.get_file_path(
            first.checkpointFilePath
        )
        Path(stored).write_bytes(b"corrupt")
        with self.assertRaisesRegex(ValueError, "SHA-256"):
            self.importer.import_model(
                self.entry, self.checkpoint, self.backbone
            )
        self.assertEqual(Path(stored).read_bytes(), b"corrupt")

    def test_conflicting_catalog_name_does_not_replace_original(self) -> None:
        first = self.importer.import_model(
            self.entry, self.checkpoint, self.backbone
        )
        changed = self.entry.model_copy(
            update={"description": "different recipe"}
        )
        with self.assertRaises(CatalogConflictError):
            self.importer.import_model(changed, self.checkpoint, self.backbone)
        self.assertEqual(
            self.importer.catalog.find(first.baseModelName), first
        )

    def test_six_dinov2_options_have_distinct_pinned_provenance(self) -> None:
        entries = dinov2_followup_entries("operator")
        self.assertEqual(len(entries), 6)
        self.assertEqual(len({entry.baseModelName for entry in entries}), 6)
        self.assertEqual(
            len({entry.inferenceSpec.checkpointSha256 for entry in entries}), 6
        )
        self.assertEqual(
            {
                (
                    entry.additionalInfo["condition"],
                    entry.additionalInfo["seed"],
                )
                for entry in entries
            },
            {
                (condition, seed)
                for condition in ("original_only", "source_balanced_50_50")
                for seed in range(3)
            },
        )
        for entry in entries:
            with self.subTest(model=entry.baseModelName):
                self.assertEqual(entry.capabilities, ["inference"])
                self.assertIsNone(entry.inferenceSpec.backboneConfigPath)
                self.assertEqual(entry.inferenceSpec.adapter, "dinov2_upernet")
                self.assertEqual(
                    entry.inferenceSpec.backbone, "dinov2_vits14_reg"
                )
                self.assertNotIn("?", entry.additionalInfo["checkpointUrl"])
                data = entry.model_dump(mode="json")
                data["capabilities"] = ["training", "inference"]
                with self.assertRaisesRegex(ValueError, "inference only"):
                    CatalogModel.model_validate(data)

    def test_dinov2_embedded_config_import_is_idempotent(self) -> None:
        entry = dinov2_followup_entries("operator")[0]
        entry.inferenceSpec.checkpointSha256 = file_sha256(self.checkpoint)
        first = self.importer.import_model(entry, self.checkpoint)
        second = self.importer.import_model(entry, self.checkpoint)
        self.assertEqual(first, second)
        self.assertIsNone(first.inferenceSpec.backboneConfigPath)
        self.assertEqual(len(self.importer.catalog.records()), 1)
        with self.assertRaisesRegex(ValueError, "embedded"):
            self.importer.import_model(entry, self.checkpoint, self.backbone)
        with patch.dict(
            "os.environ",
            {
                "AZURE_BATCH_TRANSFORMER_INFERENCE_DOCKER_IMAGE": "transformer:tag"
            },
        ):
            self.assertEqual(
                self.importer.catalog.inference_image(entry.inferenceSpec),
                "transformer:tag",
            )

    def test_dinov2_batch_checks_every_asset_before_any_registration(
        self,
    ) -> None:
        entries = dinov2_followup_entries("operator")
        digests = [entry.inferenceSpec.checkpointSha256 for entry in entries]
        digests[-1] = "0" * 64
        with patch(
            "hastegeo.core.processors.catalog_import.file_sha256",
            side_effect=digests,
        ), patch.object(self.importer, "import_model") as register:
            with self.assertRaisesRegex(ValueError, "SHA-256"):
                self.importer.import_dinov2_followups(
                    self.directory, "operator"
                )
        register.assert_not_called()
        self.assertEqual(self.importer.catalog.records(), [])

    def test_dinov2_rejects_unverified_or_incompatible_recipes(self) -> None:
        recipe = dinov2_followup_entries("operator")[0].inferenceSpec
        for changes in (
            {"checkpointSha256": None},
            {"inputKind": "raw"},
            {"backbone": "dinov2_vitb14_reg"},
            {"normalizationStds": [1.0, 1.0, 1.0]},
            {"backboneConfigPath": "unexpected.json"},
        ):
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                CatalogInferenceSpec.model_validate(
                    {**recipe.model_dump(), **changes}
                )
