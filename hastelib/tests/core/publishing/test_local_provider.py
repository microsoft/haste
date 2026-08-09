import json
import tempfile
import unittest
import uuid
from pathlib import Path

from hastegeo.core.artifact_storage.unified_artifact_storage import (
    UnifiedArtifactStorage,
)
from hastegeo.core.models.publishing import (
    ArtifactBundle,
    PublishedDataset,
    PublishRequest,
    SourceArtifact,
)
from hastegeo.core.publishing.local_provider import LocalPublishingProvider
from hastegeo.core.utils.metadata import MetadataUtils


class FakeConfig:
    artifact_storage_type = "local"

    def __init__(self, directory: str) -> None:
        self.artifact_storage_config = {"directory": directory}
        self.publishing_config = {"publishing_enabled": True}


class TestLocalPublishingProvider(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary_directory.cleanup)
        self.config = FakeConfig(self.temporary_directory.name)
        self.storage = UnifiedArtifactStorage(
            storage_type="local",
            directory=self.temporary_directory.name,
        )
        Path(self.temporary_directory.name, "damage.gpkg").write_bytes(
            b"damage"
        )
        Path(self.temporary_directory.name, "mask.geojson").write_text(
            "{}", encoding="utf-8"
        )
        self.provider = LocalPublishingProvider(
            config=self.config,
            artifact_storage=self.storage,
        )
        self.project_id = uuid.uuid4()
        self.dataset = PublishedDataset(
            datasetId=uuid.uuid4(),
            requestId=uuid.uuid4(),
            requestFingerprint="a" * 64,
            name="Dataset",
            projectId=self.project_id,
            imageLayerId="layer",
            modelId="42",
            target="local",
            status="IN_PROGRESS",
            publishedByUser="publisher",
            createdDate="2026-08-06T00:00:00Z",
            updatedDate="2026-08-06T00:00:00Z",
            assessmentSummary={"predictedDamaged": 5},
        )
        self.request = PublishRequest(
            requestId=self.dataset.requestId,
            projectId=self.project_id,
            imageLayerId="layer",
            modelId="42",
            name="Dataset",
            target="local",
            artifacts=["gpkg"],
        )
        damage_etag = self.storage.get_artifact_etag("damage.gpkg")
        mask_etag = self.storage.get_artifact_etag("mask.geojson")
        self.bundle = ArtifactBundle(
            selectedArtifacts=[
                SourceArtifact(
                    kind="gpkg",
                    sourcePath="damage.gpkg",
                    mediaType="application/geopackage+sqlite3",
                    sizeBytes=6,
                    sourceEtag=damage_etag,
                )
            ],
            supportingArtifacts=[
                SourceArtifact(
                    kind="valid_mask",
                    sourcePath="mask.geojson",
                    mediaType="application/geo+json",
                    sizeBytes=2,
                    sourceEtag=mask_etag,
                )
            ],
        )

    def test_publish_copies_only_selected_artifacts_and_provenance(
        self,
    ) -> None:
        self.provider.validate(self.request, self.bundle)

        result = self.provider.start_publish(self.dataset, self.bundle)

        self.assertEqual(len(result.artifacts), 1)
        self.assertEqual(result.artifacts[0].kind.value, "gpkg")
        prefix = (
            f"{MetadataUtils.hash_string(str(self.project_id))}/published/"
            f"{self.dataset.datasetId}"
        )
        self.assertTrue(
            self.storage.artifact_exists(result.artifacts[0].publishedPath)
        )
        self.assertFalse(
            self.storage.artifact_exists(f"{prefix}/valid_mask_mask.geojson")
        )
        report_path = result.providerMetadata["assessmentReportPath"]
        with open(
            Path(self.temporary_directory.name, report_path),
            encoding="utf-8",
        ) as report_file:
            self.assertEqual(json.load(report_file), {"predictedDamaged": 5})

    def test_publish_and_unpublish_are_idempotent(self) -> None:
        first = self.provider.start_publish(self.dataset, self.bundle)
        second = self.provider.start_publish(self.dataset, self.bundle)

        self.assertEqual(
            first.artifacts[0].publishedPath,
            second.artifacts[0].publishedPath,
        )
        self.provider.start_unpublish(self.dataset)
        repeated = self.provider.start_unpublish(self.dataset)

        self.assertEqual(repeated.providerMetadata["deletedArtifactCount"], 0)

    def test_validate_rejects_empty_bundle(self) -> None:
        with self.assertRaisesRegex(ValueError, "at least one"):
            self.provider.validate(self.request, ArtifactBundle())

    def test_disabled_info_and_invalid_continuation_are_explicit(self) -> None:
        self.config.publishing_config["publishing_enabled"] = False
        self.assertFalse(self.provider.info.isEnabled)
        self.assertEqual(
            self.provider.info.disabledReason, "Publishing is disabled"
        )

        with self.assertRaisesRegex(RuntimeError, "continuation"):
            self.provider.continue_publish(self.dataset, self.bundle)


if __name__ == "__main__":
    unittest.main()
