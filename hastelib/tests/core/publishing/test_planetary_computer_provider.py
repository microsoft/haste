import copy
import os
import unittest
import uuid

from hastegeo.core.models.publishing import (
    ArtifactBundle,
    ArtifactKind,
    PublishedDataset,
    PublishOperation,
    PublishRequest,
    SourceArtifact,
)
from hastegeo.core.publishing.planetary_computer_provider import (
    PlanetaryComputerPhase,
    PlanetaryComputerProviderError,
    PlanetaryComputerPublishingProvider,
)
from hastegeo.core.publishing.planetary_computer_transport import (
    PlanetaryComputerOperationKind,
    PlanetaryComputerOperationStep,
)


class FakeConfig:
    artifact_storage_type = "blob"
    artifact_storage_config = {}

    def __init__(self) -> None:
        self.publishing_config = {
            "pc_provider_enabled": True,
            "pc_geocatalog_url": "https://catalog.test",
            "pc_ingestion_source": "haste-source",
            "pc_collection_prefix": "haste-",
            "pc_explorer_url": "https://catalog.test",
            "pc_verify_attempts": 2,
        }


class FakeArtifactStorage:
    def __init__(
        self,
        base_url: str = "https://source.blob.core.windows.net/container",
    ) -> None:
        self.base_url = base_url
        self.blobs: set = set()
        self.copied: list = []
        self.stored: list = []

    def get_base_url(self) -> str:
        return self.base_url

    def resolve_artifact_path(self, path: str) -> str:
        return path

    def artifact_exists(self, path: str) -> bool:
        return path in self.blobs

    def get_artifact_etag(self, path: str) -> str:
        return f"etag-{path}"

    def copy_artifact(self, source: str, destination: str, etag: str) -> str:
        self.copied.append((source, destination))
        self.blobs.add(destination)
        return destination

    def fetch_artifact(
        self, identifier=None, extra_partition_keys=None,
        src_path=None, dst_path=None,
    ) -> str:
        target = os.path.join(dst_path, src_path)
        os.makedirs(os.path.dirname(target), exist_ok=True)
        with open(target, "w", encoding="utf-8") as handle:
            handle.write("staged")
        return dst_path

    def store_artifact(
        self, artifact_name, data=None, src_path=None, namespace=None,
    ) -> str:
        path = "/".join([*(namespace or []), artifact_name])
        self.stored.append(path)
        self.blobs.add(path)
        return path


class FakeSdkAdapter:
    def __init__(self) -> None:
        self.collections = {}
        self.items = {}
        self.pending_collection = None
        self.pending_item = None
        self.pending_delete = None
        self.create_collection_calls = 0
        self.create_item_calls = 0
        self.delete_item_calls = 0
        self.replace_calls = 0
        self.materialize_items = True
        self.complete_collection_operations = True
        self.ingestion_source_calls = 0
        self.delete_collection_calls = 0
        self.pending_collection_delete = None
        self.collection_asset_uploads = []
        self.item_updates = []

    def get_ingestion_source(self, source_id):
        self.ingestion_source_calls += 1
        return {
            "id": source_id,
            "kind": "BlobManagedIdentity",
            # MPC Pro returns the container as `containerUri` (camelCase).
            "connectionInfo": {
                "containerUri": "https://source.blob.core.windows.net/container"
            },
        }

    @staticmethod
    def get_signed_asset_url(href):
        return f"{href}?sv=test&sig=secret"

    def get_collection(self, collection_id):
        return copy.deepcopy(self.collections.get(collection_id))

    def replace_collection(self, collection_id, body):
        self.replace_calls += 1
        self.collections[collection_id] = copy.deepcopy(body)

    def start_create_collection(self, collection_id, body):
        self.create_collection_calls += 1
        self.pending_collection = (collection_id, copy.deepcopy(body))
        return self._operation(
            PlanetaryComputerOperationKind.CREATE_COLLECTION,
            collection_id,
            None,
            "https://catalog.test/operations/collection",
            False,
        )

    def continue_create_collection(self, collection_id, token):
        if not self.complete_collection_operations:
            return self._operation(
                PlanetaryComputerOperationKind.CREATE_COLLECTION,
                collection_id,
                None,
                token,
                False,
            )
        pending_id, body = self.pending_collection
        self.collections[pending_id] = body
        return self._operation(
            PlanetaryComputerOperationKind.CREATE_COLLECTION,
            collection_id,
            None,
            None,
            True,
        )

    def get_item(self, collection_id, item_id):
        return copy.deepcopy(self.items.get((collection_id, item_id)))

    def update_item(self, collection_id, item_id, body):
        self.item_updates.append((collection_id, item_id, copy.deepcopy(body)))
        self.items[(collection_id, item_id)] = copy.deepcopy(body)

    def start_create_item(self, collection_id, item_id, body):
        self.create_item_calls += 1
        self.pending_item = (collection_id, item_id, copy.deepcopy(body))
        return self._operation(
            PlanetaryComputerOperationKind.CREATE_ITEM,
            collection_id,
            item_id,
            "https://catalog.test/operations/item",
            False,
        )

    def continue_create_item(self, collection_id, item_id, token):
        if self.materialize_items:
            pending_collection, pending_item, body = self.pending_item
            self.items[
                (pending_collection, pending_item)
            ] = self._managed_item(body)
        return self._operation(
            PlanetaryComputerOperationKind.CREATE_ITEM,
            collection_id,
            item_id,
            None,
            True,
        )

    def start_delete_item(self, collection_id, item_id):
        self.delete_item_calls += 1
        self.pending_delete = (collection_id, item_id)
        return self._operation(
            PlanetaryComputerOperationKind.DELETE_ITEM,
            collection_id,
            item_id,
            "https://catalog.test/operations/delete",
            False,
        )

    def continue_delete_item(self, collection_id, item_id, token):
        self.items.pop(self.pending_delete, None)
        return self._operation(
            PlanetaryComputerOperationKind.DELETE_ITEM,
            collection_id,
            item_id,
            None,
            True,
        )

    def list_item_ids(self, collection_id, limit=100):
        return [
            item_id
            for (cid, item_id) in self.items
            if cid == collection_id
        ]

    def start_delete_collection(self, collection_id):
        self.delete_collection_calls += 1
        self.pending_collection_delete = collection_id
        return self._operation(
            PlanetaryComputerOperationKind.DELETE_COLLECTION,
            collection_id,
            None,
            "https://catalog.test/operations/delete-collection",
            False,
        )

    def continue_delete_collection(self, collection_id, token):
        self.collections.pop(self.pending_collection_delete, None)
        return self._operation(
            PlanetaryComputerOperationKind.DELETE_COLLECTION,
            collection_id,
            None,
            None,
            True,
        )

    def upload_collection_asset(
        self, collection_id, key, data, filename, media_type,
        roles=None, title=None,
    ):
        self.collection_asset_uploads.append(
            {
                "collection_id": collection_id,
                "key": key,
                "data": data,
                "media_type": media_type,
                "roles": roles,
                "title": title,
            }
        )

    @staticmethod
    def _operation(kind, collection_id, item_id, token, complete):
        return PlanetaryComputerOperationStep(
            kind=kind,
            collection_id=collection_id,
            item_id=item_id,
            continuation_token=token,
            is_complete=complete,
        )

    @staticmethod
    def _managed_item(body):
        item = copy.deepcopy(body)
        for key, asset in item["assets"].items():
            asset["href"] = (
                "https://managed.blob.core.windows.net/"
                f"collection/{key}.data"
            )
        return item


class TestPlanetaryComputerPublishingProvider(unittest.TestCase):
    def setUp(self) -> None:
        self.config = FakeConfig()
        self.storage = FakeArtifactStorage()
        self.sdk = FakeSdkAdapter()
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
        self.damage = SourceArtifact(
            kind=ArtifactKind.GPKG,
            sourcePath="project/damage.gpkg",
            mediaType="application/geopackage+sqlite3",
            sizeBytes=100,
            sourceEtag="damage-etag",
        )
        self.mask = SourceArtifact(
            kind=ArtifactKind.VALID_MASK,
            sourcePath="project/mask.geojson",
            mediaType="application/geo+json",
            sizeBytes=100,
            sourceEtag="mask-etag",
        )
        self.bundle = ArtifactBundle(
            selectedArtifacts=[self.damage],
            supportingArtifacts=[self.mask],
        )
        self.dataset = PublishedDataset(
            datasetId=uuid.UUID("11111111-1111-4111-8111-111111111111"),
            requestId=uuid.UUID("22222222-2222-4222-8222-222222222222"),
            requestFingerprint="a" * 64,
            name="Caracas damage assessment",
            description="Post-event damage",
            projectId=uuid.UUID("33333333-3333-4333-8333-333333333333"),
            projectName="Caracas",
            imageLayerId="layer-1",
            imageLayerName="Post-event",
            modelId="42",
            modelName="Damage model",
            target="planetary_computer",
            status="IN_PROGRESS",
            publishedByUser="publisher",
            createdDate="2026-08-08T00:00:00Z",
            updatedDate="2026-08-08T00:00:00Z",
            selectedArtifactKinds=[ArtifactKind.GPKG],
            sourceArtifacts=[self.damage],
            assessmentSummary={"predictedDamaged": 10},
        )
        self.request = PublishRequest(
            requestId=self.dataset.requestId,
            projectId=self.dataset.projectId,
            imageLayerId=self.dataset.imageLayerId,
            modelId=self.dataset.modelId,
            name=self.dataset.name,
            target="planetary_computer",
            artifacts=[ArtifactKind.GPKG],
        )
        self.provider = PlanetaryComputerPublishingProvider(
            config=self.config,
            artifact_storage=self.storage,
            sdk_adapter=self.sdk,
            json_reader=lambda artifact: self.valid_mask,
            projection_resolver=lambda artifact: "EPSG:4326",
            asset_reachability_checker=self._record_reachable_asset,
        )
        self.reachable_assets = []

    def _record_reachable_asset(self, href: str) -> None:
        self.reachable_assets.append(href)

    @staticmethod
    def _continued(dataset, result):
        return dataset.model_copy(
            update={
                "providerMetadata": {
                    **dataset.providerMetadata,
                    **result.providerMetadata,
                    "continuationToken": result.continuationToken,
                }
            }
        )

    def test_new_collection_publish_runs_all_bounded_phases(self) -> None:
        self.provider.validate(self.request, self.bundle)
        self.assertEqual(self.sdk.ingestion_source_calls, 0)

        collection_pending = self.provider.start_publish(
            self.dataset,
            self.bundle,
        )
        collection_dataset = self._continued(
            self.dataset,
            collection_pending,
        )
        item_pending = self.provider.continue_publish(
            collection_dataset,
            self.bundle,
        )
        item_dataset = self._continued(collection_dataset, item_pending)
        completed = self.provider.continue_publish(
            item_dataset,
            self.bundle,
        )

        self.assertFalse(collection_pending.isComplete)
        self.assertEqual(
            collection_pending.providerMetadata["phase"],
            PlanetaryComputerPhase.COLLECTION_OPERATION.value,
        )
        self.assertEqual(
            item_pending.providerMetadata["phase"],
            PlanetaryComputerPhase.ITEM_OPERATION.value,
        )
        self.assertTrue(completed.isComplete)
        self.assertEqual(
            completed.links["stac_collection"],
            "https://catalog.test/stac/collections/"
            "haste-33333333-3333-4333-8333-333333333333",
        )
        self.assertEqual(completed.links["explorer"], "https://catalog.test")
        self.assertEqual(
            completed.artifacts[0].publishedPath,
            "https://managed.blob.core.windows.net/collection/damage.data",
        )
        self.assertTrue(
            completed.providerMetadata["assetsCopiedToManagedStorage"]
        )
        self.assertNotIn("phase", completed.providerMetadata)
        self.assertEqual(self.sdk.create_collection_calls, 1)
        self.assertEqual(self.sdk.create_item_calls, 1)
        self.assertEqual(self.sdk.ingestion_source_calls, 1)
        self.assertEqual(len(self.reachable_assets), 1)
        self.assertIn("sig=secret", self.reachable_assets[0])

    def test_existing_item_replay_is_verified_without_duplicate_ingest(
        self,
    ) -> None:
        first = self.provider.start_publish(self.dataset, self.bundle)
        collection_dataset = self._continued(self.dataset, first)
        second = self.provider.continue_publish(
            collection_dataset,
            self.bundle,
        )
        item_dataset = self._continued(collection_dataset, second)
        completed = self.provider.continue_publish(
            item_dataset,
            self.bundle,
        )

        replayed = self.provider.start_publish(self.dataset, self.bundle)

        self.assertTrue(completed.isComplete)
        self.assertTrue(replayed.isComplete)
        self.assertEqual(self.sdk.create_item_calls, 1)
        self.assertGreaterEqual(self.sdk.replace_calls, 2)

    def test_retry_replaces_invalid_deterministic_item(self) -> None:
        first = self.provider.start_publish(self.dataset, self.bundle)
        current = self._continued(self.dataset, first)
        second = self.provider.continue_publish(current, self.bundle)
        current = self._continued(current, second)
        completed = self.provider.continue_publish(current, self.bundle)
        collection_id = completed.providerMetadata["collectionId"]
        item_id = completed.providerMetadata["itemIds"][0]
        self.sdk.items[(collection_id, item_id)]["assets"]["damage"][
            "type"
        ] = "text/plain"

        delete_pending = self.provider.start_publish(
            self.dataset,
            self.bundle,
        )
        deleting = self._continued(self.dataset, delete_pending)
        ingest_pending = self.provider.continue_publish(
            deleting,
            self.bundle,
        )
        ingesting = self._continued(deleting, ingest_pending)
        retried = self.provider.continue_publish(
            ingesting,
            self.bundle,
        )

        self.assertEqual(
            delete_pending.providerMetadata["phase"],
            PlanetaryComputerPhase.ITEM_REPLACE_DELETE_OPERATION.value,
        )
        self.assertEqual(
            ingest_pending.providerMetadata["phase"],
            PlanetaryComputerPhase.ITEM_OPERATION.value,
        )
        self.assertTrue(retried.isComplete)
        self.assertEqual(self.sdk.delete_item_calls, 1)
        self.assertEqual(self.sdk.create_item_calls, 2)

    def test_item_verification_is_bounded(self) -> None:
        self.sdk.materialize_items = False
        first = self.provider.start_publish(self.dataset, self.bundle)
        current = self._continued(self.dataset, first)
        second = self.provider.continue_publish(current, self.bundle)
        current = self._continued(current, second)
        verification = self.provider.continue_publish(current, self.bundle)
        current = self._continued(current, verification)
        verification = self.provider.continue_publish(current, self.bundle)
        current = self._continued(current, verification)

        with self.assertRaisesRegex(
            PlanetaryComputerProviderError,
            "verification timed out",
        ):
            self.provider.continue_publish(current, self.bundle)

    def test_operation_polling_is_bounded_and_retry_resets_state(self) -> None:
        self.sdk.complete_collection_operations = False
        first = self.provider.start_publish(self.dataset, self.bundle)
        current = self._continued(self.dataset, first)
        for _ in range(self.provider.max_verify_attempts):
            pending = self.provider.continue_publish(current, self.bundle)
            current = self._continued(current, pending)

        with self.assertRaisesRegex(
            PlanetaryComputerProviderError,
            "ingestion timed out",
        ):
            self.provider.continue_publish(current, self.bundle)

        reset = self.provider.prepare_retry(
            current,
            PublishOperation.PUBLISH,
        )
        self.assertNotIn("phase", reset)
        self.assertNotIn("continuationToken", reset)
        self.assertNotIn("operationAttempts", reset)

    def test_unpublish_deletes_only_item_and_is_idempotent(self) -> None:
        first = self.provider.start_publish(self.dataset, self.bundle)
        current = self._continued(self.dataset, first)
        second = self.provider.continue_publish(current, self.bundle)
        current = self._continued(current, second)
        completed = self.provider.continue_publish(current, self.bundle)
        published = self.dataset.model_copy(
            update={"providerMetadata": completed.providerMetadata}
        )
        collection_id = completed.providerMetadata["collectionId"]

        delete_pending = self.provider.start_unpublish(published)
        deleting = self._continued(published, delete_pending)
        item_deleted = self.provider.continue_unpublish(deleting)
        collection_deleting = self._continued(deleting, item_deleted)
        deleted = self.provider.continue_unpublish(collection_deleting)
        repeated = self.provider.start_unpublish(published)

        self.assertFalse(delete_pending.isComplete)
        # Item delete completes, then the now-empty collection is deleted.
        self.assertFalse(item_deleted.isComplete)
        self.assertEqual(
            item_deleted.providerMetadata["phase"],
            PlanetaryComputerPhase.DELETE_COLLECTION_OPERATION.value,
        )
        self.assertTrue(deleted.isComplete)
        self.assertTrue(repeated.isComplete)
        self.assertNotIn(collection_id, self.sdk.collections)
        self.assertEqual(self.sdk.delete_item_calls, 1)
        self.assertEqual(self.sdk.delete_collection_calls, 1)

    def test_unpublish_keeps_collection_with_remaining_datasets(self) -> None:
        first = self.provider.start_publish(self.dataset, self.bundle)
        current = self._continued(self.dataset, first)
        second = self.provider.continue_publish(current, self.bundle)
        current = self._continued(current, second)
        completed = self.provider.continue_publish(current, self.bundle)
        published = self.dataset.model_copy(
            update={"providerMetadata": completed.providerMetadata}
        )
        collection_id = completed.providerMetadata["collectionId"]
        # A second dataset still lives in the same (project-level) collection.
        self.sdk.items[(collection_id, "other-item")] = {"id": "other-item"}

        delete_pending = self.provider.start_unpublish(published)
        deleting = self._continued(published, delete_pending)
        deleted = self.provider.continue_unpublish(deleting)

        self.assertTrue(deleted.isComplete)
        self.assertEqual(self.sdk.delete_item_calls, 1)
        # Collection survives because another dataset remains; no delete.
        self.assertEqual(self.sdk.delete_collection_calls, 0)
        self.assertIn(collection_id, self.sdk.collections)
        # Its rolling summary drops the unpublished dataset.
        remaining = self.sdk.collections[collection_id]["haste:datasets"]
        self.assertNotIn(
            str(self.dataset.datasetId),
            [entry["id"] for entry in remaining],
        )

    def test_unpublish_drains_inflight_item_before_deleting_it(self) -> None:
        first = self.provider.start_publish(self.dataset, self.bundle)
        current = self._continued(self.dataset, first)
        item_pending = self.provider.continue_publish(current, self.bundle)
        failed = self._continued(current, item_pending)

        delete_pending = self.provider.start_unpublish(failed)
        deleting = self._continued(failed, delete_pending)
        item_deleted = self.provider.continue_unpublish(deleting)
        collection_deleting = self._continued(deleting, item_deleted)
        deleted = self.provider.continue_unpublish(collection_deleting)

        self.assertEqual(
            delete_pending.providerMetadata["phase"],
            PlanetaryComputerPhase.DELETE_OPERATION.value,
        )
        self.assertTrue(deleted.isComplete)
        self.assertEqual(self.sdk.delete_item_calls, 1)
        self.assertEqual(self.sdk.delete_collection_calls, 1)
        collection_id = failed.providerMetadata["collectionId"]
        item_id = failed.providerMetadata["itemIds"][0]
        self.assertNotIn((collection_id, item_id), self.sdk.items)
        self.assertNotIn(collection_id, self.sdk.collections)

    def test_unpublish_collection_crash_window_requires_item_discovery(
        self,
    ) -> None:
        first = self.provider.start_publish(self.dataset, self.bundle)
        stale = self._continued(self.dataset, first)
        collection_id = stale.providerMetadata["collectionId"]
        item_id = stale.providerMetadata["itemIds"][0]
        self.sdk.continue_create_collection(
            collection_id,
            stale.providerMetadata["continuationToken"],
        )
        documents = self.provider._build_documents(
            self.dataset,
            self.bundle,
            self.provider._projection_codes(self.dataset, self.bundle),
            self.sdk.get_collection(collection_id),
        )
        self.sdk.start_create_item(collection_id, item_id, documents.item)

        discovery = self.provider.start_unpublish(stale)

        self.assertFalse(discovery.isComplete)
        self.assertEqual(
            discovery.providerMetadata["phase"],
            PlanetaryComputerPhase.DELETE_DISCOVER.value,
        )

    def test_unpublish_discovery_timeout_fails_closed(self) -> None:
        metadata = self.provider._cleanup_discovery_metadata(
            self.provider._stable_metadata(self.dataset)
        )
        current = self.dataset.model_copy(
            update={"providerMetadata": metadata}
        )
        for _ in range(self.provider.max_verify_attempts):
            pending = self.provider._start_delete_or_discover(
                current,
                current.providerMetadata,
                metadata["collectionId"],
                metadata["itemIds"][0],
            )
            current = self._continued(current, pending)

        with self.assertRaisesRegex(
            PlanetaryComputerProviderError,
            "cleanup verification timed out",
        ):
            self.provider._start_delete_or_discover(
                current,
                current.providerMetadata,
                metadata["collectionId"],
                metadata["itemIds"][0],
            )

    def test_failed_phase_less_unpublish_requires_discovery(self) -> None:
        failed = self.dataset.model_copy(update={"providerMetadata": {}})

        discovery = self.provider.start_unpublish(failed)

        self.assertFalse(discovery.isComplete)
        self.assertEqual(
            discovery.providerMetadata["phase"],
            PlanetaryComputerPhase.DELETE_DISCOVER.value,
        )

    def test_duplicate_delete_enters_bounded_verification(self) -> None:
        class ConflictError(RuntimeError):
            status_code = 409

        metadata = self.provider._stable_metadata(self.dataset)
        metadata["assetsCopiedToManagedStorage"] = True
        collection_id = metadata["collectionId"]
        item_id = metadata["itemIds"][0]
        self.sdk.items[(collection_id, item_id)] = {
            "id": item_id,
            "collection": collection_id,
        }
        self.sdk.start_delete_item = lambda *args: (_ for _ in ()).throw(
            ConflictError("already deleting")
        )
        published = self.dataset.model_copy(
            update={"providerMetadata": metadata}
        )

        pending = self.provider.start_unpublish(published)

        self.assertFalse(pending.isComplete)
        self.assertEqual(
            pending.providerMetadata["phase"],
            PlanetaryComputerPhase.DELETE_VERIFY.value,
        )

    def test_validation_rejects_emulator_and_missing_mask(self) -> None:
        emulator_provider = PlanetaryComputerPublishingProvider(
            config=self.config,
            artifact_storage=FakeArtifactStorage(
                "https://devstoreaccount1.blob.core.windows.net/data"
            ),
            sdk_adapter=self.sdk,
            json_reader=lambda artifact: self.valid_mask,
            projection_resolver=lambda artifact: "EPSG:4326",
            asset_reachability_checker=lambda href: None,
        )

        with self.assertRaisesRegex(ValueError, "storage emulator"):
            emulator_provider.validate(self.request, self.bundle)
        with self.assertRaisesRegex(ValueError, "valid-area mask"):
            self.provider.validate(
                self.request,
                ArtifactBundle(selectedArtifacts=[self.damage]),
            )

    def test_explorer_url_allows_query_but_geocatalog_stays_strict(
        self,
    ) -> None:
        # MPC Pro Explorer links carry a query string
        # (?geocatalogname=...&c=...&z=...); the display-only Explorer URL must
        # accept it, while the GeoCatalog URL stays scheme + host only.
        explorer = (
            "https://explorer.geocatalog.spatio.azure.com/explorer"
            "?geocatalogname=damage-assessment-gc.eastus&c=30.05%2C29.99&z=2"
        )
        config = FakeConfig()
        config.publishing_config["pc_explorer_url"] = explorer
        provider = PlanetaryComputerPublishingProvider(
            config=config,
            artifact_storage=self.storage,
            sdk_adapter=self.sdk,
            json_reader=lambda artifact: self.valid_mask,
            projection_resolver=lambda artifact: "EPSG:4326",
            asset_reachability_checker=self._record_reachable_asset,
        )

        provider.validate(self.request, self.bundle)
        self.assertEqual(provider.explorer_url, explorer)

        # A query string (or path) on the GeoCatalog URL is still rejected.
        strict_config = FakeConfig()
        strict_config.publishing_config["pc_geocatalog_url"] = (
            "https://catalog.test/stac?foo=bar"
        )
        strict_provider = PlanetaryComputerPublishingProvider(
            config=strict_config,
            artifact_storage=self.storage,
            sdk_adapter=self.sdk,
            json_reader=lambda artifact: self.valid_mask,
            projection_resolver=lambda artifact: "EPSG:4326",
            asset_reachability_checker=self._record_reachable_asset,
        )
        with self.assertRaisesRegex(ValueError, "must use HTTPS"):
            strict_provider.validate(self.request, self.bundle)

    def test_configured_license_is_applied_to_stac_documents(self) -> None:
        self.config.publishing_config["pc_publishing_license"] = "CC-BY-SA-4.0"
        provider = PlanetaryComputerPublishingProvider(
            config=self.config,
            artifact_storage=self.storage,
            sdk_adapter=self.sdk,
            json_reader=lambda artifact: self.valid_mask,
            projection_resolver=lambda artifact: "EPSG:4326",
            asset_reachability_checker=lambda href: None,
        )

        documents = provider._build_documents(
            self.dataset,
            self.bundle,
            provider._projection_codes(self.dataset, self.bundle),
            None,
        )

        self.assertEqual(documents.collection["license"], "CC-BY-SA-4.0")
        self.assertEqual(
            documents.item["properties"]["license"], "CC-BY-SA-4.0"
        )
        # Default when unset is CC-BY-4.0 (not the old hardcoded "proprietary").
        self.assertEqual(self.provider.license_id, "CC-BY-4.0")

    def test_assets_are_staged_into_the_publish_container(self) -> None:
        publish = FakeArtifactStorage(
            "https://publishsa.blob.core.windows.net/publish"
        )
        provider = PlanetaryComputerPublishingProvider(
            config=self.config,
            artifact_storage=self.storage,
            publish_storage=publish,
            sdk_adapter=self.sdk,
            json_reader=lambda artifact: self.valid_mask,
            projection_resolver=lambda artifact: "EPSG:4326",
            asset_reachability_checker=lambda href: None,
        )

        documents = provider._build_documents(
            self.dataset,
            self.bundle,
            provider._projection_codes(self.dataset, self.bundle),
            None,
        )

        damage_href = documents.item["assets"]["damage"]["href"]
        self.assertEqual(
            damage_href,
            "https://publishsa.blob.core.windows.net/publish/"
            f"published/{self.dataset.datasetId}/gpkg_damage.gpkg",
        )
        # The asset was copied into the publish container, not referenced in the
        # (firewalled) primary store.
        self.assertIn(
            f"published/{self.dataset.datasetId}/gpkg_damage.gpkg",
            publish.stored,
        )

    def test_ingestion_source_validates_against_publish_container(
        self,
    ) -> None:
        publish = FakeArtifactStorage(
            "https://publishsa.blob.core.windows.net/publish"
        )
        # The GeoCatalog source points at the primary store, not the publish
        # container, so validation must reject it.
        provider = PlanetaryComputerPublishingProvider(
            config=self.config,
            artifact_storage=self.storage,
            publish_storage=publish,
            sdk_adapter=self.sdk,
            json_reader=lambda artifact: self.valid_mask,
            projection_resolver=lambda artifact: "EPSG:4326",
            asset_reachability_checker=lambda href: None,
        )

        with self.assertRaisesRegex(
            PlanetaryComputerProviderError, "does not"
        ):
            provider.start_publish(self.dataset, self.bundle)

    def test_collection_tile_rendered_and_uploaded_best_effort(self) -> None:
        # Bundle with only the AOI mask (no readable buildings GPKG) renders an
        # AOI-only tile and uploads it as the collection thumbnail.
        bundle = ArtifactBundle(supportingArtifacts=[self.mask])

        self.provider._upload_collection_tile(self.dataset, bundle, "haste-c")

        self.assertEqual(len(self.sdk.collection_asset_uploads), 1)
        upload = self.sdk.collection_asset_uploads[0]
        self.assertEqual(upload["collection_id"], "haste-c")
        self.assertEqual(upload["key"], "thumbnail")
        self.assertEqual(upload["roles"], ["thumbnail"])
        self.assertTrue(upload["data"].startswith(b"\x89PNG"))

    def test_collection_tile_failure_never_raises(self) -> None:
        # An empty mask (no features) can't render; must be swallowed.
        provider = PlanetaryComputerPublishingProvider(
            config=self.config,
            artifact_storage=self.storage,
            sdk_adapter=self.sdk,
            json_reader=lambda artifact: {"type": "FeatureCollection", "features": []},
            projection_resolver=lambda artifact: "EPSG:4326",
            asset_reachability_checker=lambda href: None,
        )
        provider._upload_collection_tile(
            self.dataset, ArtifactBundle(supportingArtifacts=[self.mask]), "c"
        )
        self.assertEqual(self.sdk.collection_asset_uploads, [])

    def _seed_published_item(self, links=None):
        collection_id, item_id = self.provider._ids(self.dataset)
        self.sdk.items[(collection_id, item_id)] = {
            "type": "Feature",
            "id": item_id,
            "collection": collection_id,
            "properties": {"title": "Old", "description": "Old desc"},
            "links": links
            if links is not None
            else [
                {
                    "rel": "preview",
                    "href": "https://old.example.com",
                    "type": "text/html",
                }
            ],
            "assets": {},
        }
        return collection_id, item_id

    def test_update_published_metadata_patches_item(self) -> None:
        self._seed_published_item()
        edited = self.dataset.model_copy(
            update={
                "name": "New name",
                "description": "New description",
                "interactiveViewerUrl": "https://viewer.example.com/x",
            }
        )

        self.provider.update_published_metadata(edited)

        self.assertEqual(len(self.sdk.item_updates), 1)
        _, _, body = self.sdk.item_updates[0]
        self.assertEqual(body["properties"]["title"], "New name")
        self.assertEqual(body["properties"]["description"], "New description")
        preview = [
            link for link in body["links"] if link.get("rel") == "preview"
        ]
        self.assertEqual(len(preview), 1)
        self.assertEqual(preview[0]["href"], "https://viewer.example.com/x")

    def test_update_published_metadata_clears_viewer_link(self) -> None:
        self._seed_published_item()
        edited = self.dataset.model_copy(
            update={"name": "N", "interactiveViewerUrl": None, "description": ""}
        )

        self.provider.update_published_metadata(edited)

        _, _, body = self.sdk.item_updates[0]
        self.assertFalse(
            [link for link in body["links"] if link.get("rel") == "preview"]
        )
        self.assertNotIn("description", body["properties"])

    def test_update_published_metadata_noops_when_item_missing(self) -> None:
        self.provider.update_published_metadata(self.dataset)
        self.assertEqual(self.sdk.item_updates, [])

    def test_update_published_metadata_reemits_providers(self) -> None:
        self._seed_published_item()
        edited = self.dataset.model_copy(
            update={"imagerySources": ["Maxar WorldView-3"]}
        )

        self.provider.update_published_metadata(edited)

        _, _, body = self.sdk.item_updates[0]
        providers = body["properties"]["providers"]
        names = {provider["name"] for provider in providers}
        self.assertIn("Vantor", names)

    def test_update_published_metadata_clears_providers_when_empty(
        self,
    ) -> None:
        self._seed_published_item()
        edited = self.dataset.model_copy(update={"imagerySources": []})

        self.provider.update_published_metadata(edited)

        _, _, body = self.sdk.item_updates[0]
        self.assertNotIn("providers", body["properties"])

    def test_update_published_metadata_refreshes_collection_union(
        self,
    ) -> None:
        collection_id, _ = self._seed_published_item()
        self.sdk.collections[collection_id] = {
            "id": collection_id,
            "description": "old",
            "providers": [{"name": "OldSource", "roles": ["producer"]}],
            "haste:datasets": [
                {
                    "id": str(self.dataset.datasetId),
                    "name": "old",
                    "imagery": ["OldSource"],
                }
            ],
        }
        edited = self.dataset.model_copy(
            update={"name": "New name", "imagerySources": ["Planet"]}
        )

        self.provider.update_published_metadata(edited)

        collection = self.sdk.collections[collection_id]
        names = {p["name"] for p in collection.get("providers", [])}
        self.assertIn("Planet Labs PBC", names)
        self.assertNotIn("OldSource", names)
        entry = collection["haste:datasets"][0]
        self.assertEqual(entry["name"], "New name")
        self.assertEqual(entry["imagery"], ["Planet"])

    def test_viewer_url_changes_the_request_fingerprint(self) -> None:
        from hastegeo.core.models.publishing import (
            compute_request_fingerprint,
        )

        base = dict(
            requestId=self.request.requestId,
            projectId=self.request.projectId,
            imageLayerId="layer-1",
            modelId="42",
            name="X",
            target="planetary_computer",
            artifacts=["gpkg"],
        )
        without = compute_request_fingerprint(
            PublishRequest(**base), "user@example.com"
        )
        with_viewer = compute_request_fingerprint(
            PublishRequest(
                **base, interactiveViewerUrl="https://viewer.example.com/a"
            ),
            "user@example.com",
        )
        self.assertNotEqual(without, with_viewer)

    def test_interactive_viewer_url_must_be_https(self) -> None:
        base = dict(
            requestId=self.request.requestId,
            projectId=self.request.projectId,
            imageLayerId="layer-1",
            modelId="42",
            name="X",
            target="planetary_computer",
            artifacts=["gpkg"],
        )
        ok = PublishRequest(
            **base, interactiveViewerUrl="https://viewer.example.com/a"
        )
        self.assertEqual(
            ok.interactiveViewerUrl, "https://viewer.example.com/a"
        )
        # Blank normalizes to None; non-https is rejected.
        self.assertIsNone(
            PublishRequest(**base, interactiveViewerUrl="   ").interactiveViewerUrl
        )
        with self.assertRaises(Exception):
            PublishRequest(**base, interactiveViewerUrl="http://insecure.test")

    def test_valid_mask_crs_is_explicit_and_validated(self) -> None:
        projected = copy.deepcopy(self.valid_mask)
        projected["crs"] = {
            "type": "name",
            "properties": {"name": "EPSG:3857"},
        }

        self.assertEqual(
            self.provider._valid_mask_crs(projected),
            "EPSG:3857",
        )
        with self.assertRaisesRegex(ValueError, "CRS is invalid"):
            self.provider._valid_mask_crs(
                {**projected, "crs": {"type": "name"}}
            )

    def test_verification_rejects_changed_asset_metadata(self) -> None:
        first = self.provider.start_publish(self.dataset, self.bundle)
        current = self._continued(self.dataset, first)
        second = self.provider.continue_publish(current, self.bundle)
        current = self._continued(current, second)
        collection_id = current.providerMetadata["collectionId"]
        item_id = current.providerMetadata["itemIds"][0]
        _, _, pending_body = self.sdk.pending_item
        actual = self.sdk._managed_item(pending_body)
        actual["assets"]["damage"]["type"] = "text/plain"
        self.sdk.items[(collection_id, item_id)] = actual
        self.sdk.materialize_items = False

        with self.assertRaisesRegex(
            PlanetaryComputerProviderError,
            "asset type changed",
        ):
            self.provider.continue_publish(current, self.bundle)

    def test_verification_rejects_uncopied_source_asset(self) -> None:
        first = self.provider.start_publish(self.dataset, self.bundle)
        current = self._continued(self.dataset, first)
        second = self.provider.continue_publish(current, self.bundle)
        current = self._continued(current, second)
        collection_id = current.providerMetadata["collectionId"]
        item_id = current.providerMetadata["itemIds"][0]
        _, _, pending_body = self.sdk.pending_item
        self.sdk.items[(collection_id, item_id)] = copy.deepcopy(pending_body)
        self.sdk.materialize_items = False

        with self.assertRaisesRegex(
            PlanetaryComputerProviderError,
            "did not copy asset",
        ):
            self.provider.continue_publish(current, self.bundle)

    def test_verification_rejects_unsigned_or_wrong_host_asset(self) -> None:
        first = self.provider.start_publish(self.dataset, self.bundle)
        current = self._continued(self.dataset, first)
        second = self.provider.continue_publish(current, self.bundle)
        current = self._continued(current, second)
        collection_id = current.providerMetadata["collectionId"]
        item_id = current.providerMetadata["itemIds"][0]
        _, _, pending_body = self.sdk.pending_item
        actual = self.sdk._managed_item(pending_body)
        actual["assets"]["damage"][
            "href"
        ] = "https://attacker.test/damage.gpkg"
        self.sdk.items[(collection_id, item_id)] = actual
        self.sdk.materialize_items = False

        with self.assertRaisesRegex(
            PlanetaryComputerProviderError,
            "not Azure Blob Storage",
        ):
            self.provider.continue_publish(current, self.bundle)

    def test_verification_rejects_unexpected_asset(self) -> None:
        first = self.provider.start_publish(self.dataset, self.bundle)
        current = self._continued(self.dataset, first)
        second = self.provider.continue_publish(current, self.bundle)
        current = self._continued(current, second)
        collection_id = current.providerMetadata["collectionId"]
        item_id = current.providerMetadata["itemIds"][0]
        _, _, pending_body = self.sdk.pending_item
        actual = self.sdk._managed_item(pending_body)
        actual["assets"]["unexpected"] = {
            "href": "https://managed.blob.core.windows.net/collection/extra",
            "type": "application/octet-stream",
            "roles": ["data"],
        }
        self.sdk.items[(collection_id, item_id)] = actual
        self.sdk.materialize_items = False

        with self.assertRaisesRegex(
            PlanetaryComputerProviderError,
            "selected assets changed",
        ):
            self.provider.continue_publish(current, self.bundle)

    def test_ingestion_source_must_match_haste_container(self) -> None:
        self.sdk.get_ingestion_source = lambda source_id: {
            "id": source_id,
            "kind": "BlobManagedIdentity",
            "connectionInfo": {
                "containerUrl": (
                    "https://other.blob.core.windows.net/container"
                )
            },
        }

        with self.assertRaisesRegex(
            PlanetaryComputerProviderError,
            "does not match HASTE storage",
        ):
            self.provider.start_publish(self.dataset, self.bundle)


if __name__ == "__main__":
    unittest.main()
