import unittest
import uuid

from hastegeo.core.models.projects import ImageLayer
from hastegeo.core.models.publishing import (
    ArtifactKind,
    PublishMetadataUpdate,
    PublishRequest,
)
from hastegeo.core.publishing.source import (
    PublishingArtifactUnavailableError,
    PublishingSourceNotEligibleError,
    PublishingSourceNotFoundError,
    PublishingSourceResolver,
    _imagery_sources,
)
from hastegeo.core.utils.metadata import MetadataUtils


class TestImagerySources(unittest.TestCase):
    def test_collects_distinct_ordered_provider_sources(self) -> None:
        layer = ImageLayer(
            sourceTypePreEvent="WorldView-3",
            sourceTypePostEvent="Sentinel-2",
        )
        self.assertEqual(
            _imagery_sources(layer), ["WorldView-3", "Sentinel-2"]
        )

    def test_dedupes_case_insensitively_preserving_first(self) -> None:
        layer = ImageLayer(
            sourceTypePreEvent="Maxar",
            sourceTypePostEvent="maxar",
            sourceType="MAXAR",
        )
        self.assertEqual(_imagery_sources(layer), ["Maxar"])

    def test_drops_placeholders_and_blanks(self) -> None:
        # "n/a" (the Unknown dropdown value), "rgb/no_processing" (bring-your-
        # own) and "mercy_corps" (a processing profile) are not imagery vendors.
        layer = ImageLayer(
            sourceTypePreEvent="n/a",
            sourceTypePostEvent="rgb/no_processing",
        )
        self.assertEqual(_imagery_sources(layer), [])
        self.assertEqual(
            _imagery_sources(ImageLayer(sourceTypePostEvent="mercy_corps")), []
        )

    def test_keeps_real_source_alongside_placeholder(self) -> None:
        layer = ImageLayer(
            sourceTypePreEvent="n/a",
            sourceTypePostEvent="maxar",
        )
        self.assertEqual(_imagery_sources(layer), ["maxar"])


class TestPublishMetadataUpdateImagery(unittest.TestCase):
    def _update(self, **kwargs) -> PublishMetadataUpdate:
        return PublishMetadataUpdate(
            projectId=uuid.uuid4(), datasetId=uuid.uuid4(), **kwargs
        )

    def test_none_leaves_unchanged(self) -> None:
        self.assertIsNone(self._update().imagerySources)

    def test_empty_list_clears(self) -> None:
        self.assertEqual(self._update(imagerySources=[]).imagerySources, [])

    def test_trims_dedupes_and_drops_blanks(self) -> None:
        update = self._update(
            imagerySources=["  Vantor ", "Planet", "vantor", "  "]
        )
        self.assertEqual(update.imagerySources, ["Vantor", "Planet"])


class FakeTypes:
    class PROJECT:
        value = "project"

    class IMAGELAYER:
        value = "imagelayer"

    class MODEL:
        value = "model"


class FakeConfig:
    artifact_storage_type = "local"
    artifact_storage_config = {}

    @staticmethod
    def get_metadata_types():
        return FakeTypes

    @staticmethod
    def get_status_types():
        class Types:
            class COMPLETED:
                value = "Processed"

        return Types


class FakeMetadataProcessor:
    records = {}

    def __init__(
        self,
        data_type: str,
        partition_key: str = None,
        config=None,
    ) -> None:
        self.data_type = data_type
        self.partition_key = partition_key

    def load(self, key: str) -> dict:
        try:
            return self.records[(self.data_type, self.partition_key, key)]
        except KeyError as error:
            raise FileNotFoundError(key) from error


class FakeArtifactStorage:
    def __init__(self, artifacts: dict[str, int]) -> None:
        self.artifacts = artifacts

    def resolve_artifact_path(self, location: str) -> str:
        return location.removeprefix("storage://")

    def artifact_exists(self, artifact_path: str) -> bool:
        return artifact_path in self.artifacts

    def get_artifact_size(self, artifact_path: str) -> int:
        return self.artifacts[artifact_path]

    def get_artifact_etag(self, artifact_path: str) -> str:
        return f"etag-{artifact_path}-{self.artifacts[artifact_path]}"


class TestPublishingSourceResolver(unittest.TestCase):
    def setUp(self) -> None:
        self.project_id = str(uuid.uuid4())
        self.layer_id = "layer-1"
        self.model_id = "42"
        self.project_prefix = MetadataUtils.hash_string(self.project_id)
        self.imagery_task_id = "img-task"
        self.inference_task_id = "inf-task"
        self.paths = {
            "damage": (
                f"{self.project_prefix}/{self.inference_task_id}/"
                "predicted_damage_Model.gpkg"
            ),
            "mask": (
                f"{self.project_prefix}/{self.imagery_task_id}/"
                f"valid_area_mask_{self.project_id}_{self.layer_id}.geojson"
            ),
            "footprints": (
                f"{self.project_prefix}/{self.imagery_task_id}/"
                f"building_footprints_{self.project_id}_{self.layer_id}.gpkg"
            ),
            "image": (
                f"{self.project_prefix}/{self.imagery_task_id}/"
                f"processed_imagery_post_event_cog_{self.project_id}_"
                f"{self.layer_id}.tif"
            ),
        }
        FakeMetadataProcessor.records = {
            ("project", self.project_id, self.project_id): {
                "projectId": self.project_id,
                "name": "Project",
            },
            ("imagelayer", self.project_id, self.layer_id): {
                "imageLayerId": self.layer_id,
                "projectId": self.project_id,
                "name": "Layer",
                "status": "Processed",
                "preprocessJob": {
                    "taskId": self.imagery_task_id,
                    "jobId": "imagery-job",
                    "imageLayerId": self.layer_id,
                    "projectId": self.project_id,
                    "status": "Processed",
                },
                "validAreaMaskUrl": f"storage://{self.paths['mask']}",
                "buildingFootprintsUrl": (
                    f"storage://{self.paths['footprints']}"
                ),
                "postEventProcessedImageryUrl": (
                    f"storage://{self.paths['image']}"
                ),
            },
            ("model", self.project_id, self.model_id): {
                "modelId": self.model_id,
                "projectId": self.project_id,
                "imageLayerId": self.layer_id,
                "name": "Model",
                "inferenceStatus": "Processed",
                "inferenceOutputPath": (
                    f"{self.project_prefix}/{self.inference_task_id}"
                ),
                "currentInferenceTaskId": self.inference_task_id,
                "inferenceJobs": [
                    {
                        "jobId": "inference-job",
                        "taskId": self.inference_task_id,
                        "modelId": self.model_id,
                        "projectId": self.project_id,
                        "status": "Processed",
                    }
                ],
                "gpkgUrl": f"storage://{self.paths['damage']}",
            },
        }
        self.artifact_storage = FakeArtifactStorage(
            dict(zip(self.paths.values(), (10, 20, 30, 40)))
        )
        self.resolver = PublishingSourceResolver(
            config=FakeConfig(),
            processor_factory=FakeMetadataProcessor,
            artifact_storage=self.artifact_storage,
        )

    def build_request(self, artifacts: list[str]) -> PublishRequest:
        return PublishRequest(
            requestId=uuid.uuid4(),
            projectId=self.project_id,
            imageLayerId=self.layer_id,
            modelId=self.model_id,
            name="Dataset",
            target="local",
            artifacts=artifacts,
        )

    def test_options_return_only_verified_artifacts(self) -> None:
        del self.artifact_storage.artifacts[self.paths["image"]]

        options = self.resolver.resolve_options(
            self.project_id, self.layer_id, self.model_id
        )

        self.assertEqual(options.defaultName, "Project – Layer")
        self.assertEqual(
            {artifact.kind for artifact in options.availableArtifacts},
            {
                ArtifactKind.GPKG,
                ArtifactKind.VALID_MASK,
                ArtifactKind.FOOTPRINTS,
            },
        )

    def test_bundle_separates_selected_and_supporting_artifacts(self) -> None:
        request = self.build_request(["gpkg"])

        bundle = self.resolver.resolve_bundle(
            request, supporting_kinds=[ArtifactKind.VALID_MASK]
        )

        self.assertEqual(
            [artifact.kind for artifact in bundle.selectedArtifacts],
            [ArtifactKind.GPKG],
        )
        self.assertEqual(
            [artifact.kind for artifact in bundle.supportingArtifacts],
            [ArtifactKind.VALID_MASK],
        )

    def test_bundle_rejects_unavailable_requested_artifact(self) -> None:
        del self.artifact_storage.artifacts[self.paths["footprints"]]
        request = self.build_request(["footprints"])

        with self.assertRaisesRegex(
            PublishingArtifactUnavailableError, "footprints"
        ):
            self.resolver.resolve_bundle(request)

    def test_options_reject_incomplete_inference(self) -> None:
        FakeMetadataProcessor.records[
            ("model", self.project_id, self.model_id)
        ]["inferenceStatus"] = "InProgress"

        with self.assertRaisesRegex(
            PublishingSourceNotEligibleError, "Processed"
        ):
            self.resolver.resolve_options(
                self.project_id, self.layer_id, self.model_id
            )

    def test_options_reject_missing_and_mismatched_sources(self) -> None:
        project_key = ("project", self.project_id, self.project_id)
        project = FakeMetadataProcessor.records.pop(project_key)
        with self.assertRaises(PublishingSourceNotFoundError):
            self.resolver.resolve_options(
                self.project_id, self.layer_id, self.model_id
            )
        FakeMetadataProcessor.records[project_key] = project
        FakeMetadataProcessor.records[
            ("imagelayer", self.project_id, self.layer_id)
        ]["projectId"] = str(uuid.uuid4())
        with self.assertRaisesRegex(FileNotFoundError, "does not belong"):
            self.resolver.resolve_options(
                self.project_id, self.layer_id, self.model_id
            )

    def test_options_reject_when_no_artifacts_exist(self) -> None:
        self.artifact_storage.artifacts.clear()

        with self.assertRaisesRegex(
            PublishingSourceNotEligibleError, "no available"
        ):
            self.resolver.resolve_options(
                self.project_id, self.layer_id, self.model_id
            )

    def test_bundle_rejects_missing_supporting_artifact(self) -> None:
        del self.artifact_storage.artifacts[self.paths["mask"]]
        request = self.build_request(["gpkg"])

        with self.assertRaisesRegex(
            PublishingArtifactUnavailableError, "supporting"
        ):
            self.resolver.resolve_bundle(
                request, supporting_kinds=[ArtifactKind.VALID_MASK]
            )

    def test_options_reject_tampered_same_container_source_paths(self) -> None:
        model_record = FakeMetadataProcessor.records[
            ("model", self.project_id, self.model_id)
        ]
        model_record["gpkgUrl"] = "storage://users_acl.json"
        self.artifact_storage.artifacts["users_acl.json"] = 100

        layer_record = FakeMetadataProcessor.records[
            ("imagelayer", self.project_id, self.layer_id)
        ]
        sibling_path = self.paths["mask"].replace(
            self.project_prefix,
            MetadataUtils.hash_string(str(uuid.uuid4())),
            1,
        )
        layer_record["validAreaMaskUrl"] = f"storage://{sibling_path}"
        self.artifact_storage.artifacts[sibling_path] = 100

        options = self.resolver.resolve_options(
            self.project_id, self.layer_id, self.model_id
        )

        self.assertNotIn(
            ArtifactKind.GPKG,
            {artifact.kind for artifact in options.availableArtifacts},
        )
        self.assertNotIn(
            ArtifactKind.VALID_MASK,
            {artifact.kind for artifact in options.availableArtifacts},
        )

    def test_options_reject_output_not_owned_by_completed_current_job(
        self,
    ) -> None:
        model_record = FakeMetadataProcessor.records[
            ("model", self.project_id, self.model_id)
        ]
        model_record[
            "inferenceOutputPath"
        ] = f"{self.project_prefix}/forged-task"
        forged_path = (
            f"{self.project_prefix}/forged-task/predicted_damage_Model.gpkg"
        )
        model_record["gpkgUrl"] = f"storage://{forged_path}"
        self.artifact_storage.artifacts[forged_path] = 10

        options = self.resolver.resolve_options(
            self.project_id, self.layer_id, self.model_id
        )

        self.assertNotIn(
            ArtifactKind.GPKG,
            {artifact.kind for artifact in options.availableArtifacts},
        )

    def test_embedding_gpkg_requires_completed_owned_job(self) -> None:
        model_record = FakeMetadataProcessor.records[
            ("model", self.project_id, self.model_id)
        ]
        embedding_path = (
            f"{self.project_prefix}/building_predictions_{self.model_id}.gpkg"
        )
        model_record.update(
            {
                "modelType": "embedding",
                "status": "Processed",
                "gpkgUrl": f"storage://{embedding_path}",
                "inferenceOutputPath": None,
                "currentInferenceTaskId": None,
                "inferenceJobs": [],
                "embeddingJob": None,
            }
        )
        self.artifact_storage.artifacts[embedding_path] = 10

        without_job = self.resolver.resolve_options(
            self.project_id, self.layer_id, self.model_id
        )
        self.assertNotIn(
            ArtifactKind.GPKG,
            {artifact.kind for artifact in without_job.availableArtifacts},
        )

        model_record["embeddingJob"] = {
            "jobId": "embedding-job",
            "taskId": "embedding-task",
            "modelId": self.model_id,
            "projectId": self.project_id,
            "status": "Processed",
        }
        with_job = self.resolver.resolve_options(
            self.project_id, self.layer_id, self.model_id
        )
        self.assertIn(
            ArtifactKind.GPKG,
            {artifact.kind for artifact in with_job.availableArtifacts},
        )

    def test_ensure_project_exists_maps_missing_record(self) -> None:
        del FakeMetadataProcessor.records[
            ("project", self.project_id, self.project_id)
        ]

        with self.assertRaises(FileNotFoundError):
            self.resolver.ensure_project_exists(self.project_id)


if __name__ == "__main__":
    unittest.main()
