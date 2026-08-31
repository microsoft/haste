# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License.
import logging
import os
import re
import tempfile
from enum import Enum
from string import Template
from typing import NamedTuple

_logger = logging.getLogger(__name__)

REGISTRY_SERVER_PLACEHOLDER = "<registry-name>.azurecr.io"

_SCHEME_RE = re.compile(r"^https?://", re.IGNORECASE)


def _get_bool_env(name, default=False):
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _get_bounded_int_env(name, default, minimum, maximum=None):
    value = int(os.getenv(name, str(default)))
    if value < minimum or (maximum is not None and value > maximum):
        upper = f" and {maximum}" if maximum is not None else ""
        raise ValueError(f"{name} must be between {minimum}{upper}")
    return value


def _strip_scheme(value):
    """Reduce a registry URL to the bare login server.

    Azure Batch's ``ContainerRegistry.registry_server`` expects
    ``myacr.azurecr.io``, but the app setting is frequently supplied as a URL.
    """
    return _SCHEME_RE.sub("", value.strip()).rstrip("/")


def _resolve_registry_server():
    """Resolve the ACR login server used for Batch pool creation.

    ``AZURE_BATCH_REGISTRY_SERVER`` is canonical. Environments provisioned
    before the rename set ``AZURE_BATCH_REGISTRY_SERVER_URL`` instead, so it is
    still honored to keep those deployments working across the upgrade.
    """
    server = os.getenv("AZURE_BATCH_REGISTRY_SERVER")
    if not server:
        legacy = os.getenv("AZURE_BATCH_REGISTRY_SERVER_URL")
        if not legacy:
            return REGISTRY_SERVER_PLACEHOLDER
        _logger.warning(
            "AZURE_BATCH_REGISTRY_SERVER_URL is deprecated and will be "
            "removed in a future release; rename this application setting "
            "to AZURE_BATCH_REGISTRY_SERVER."
        )
        server = legacy
    return _strip_scheme(server)


class StorageType(Enum):
    """Enumeration of supported storage backend types.

    Defines the available storage backends that can be used for metadata
    and artifact storage in the HASTE system.

    Values:
        LOCAL: Local filesystem storage
        BLOB: Azure Blob Storage
        COSMOS: Azure Cosmos DB
        DATALAKE: Azure Data Lake Storage
        POSTGRES: PostgreSQL database
    """

    LOCAL = "local"
    BLOB = "blob"
    COSMOS = "cosmos"
    DATALAKE = "datalake"
    POSTGRES = "postgres"


class ArtifactTypes(Enum):
    """Enumeration of artifact types with template-based naming.

    Defines standardized naming templates for various data artifacts
    generated and stored throughout the HASTE workflow. Each template
    uses string substitution for dynamic naming based on project and
    model identifiers.

    Template Variables:
        - ${projectId}: Unique project identifier
        - ${imageLayerId}: Unique image layer identifier
        - ${modelName}: Model identifier/name
        - ${modelId}: Unique model identifier
        - ${version}: Monotonic version number of an edited artifact

    Artifact Categories:
        - PRE_EVENT_*: Pre-disaster imagery and derivatives
        - POST_EVENT_*: Post-disaster imagery and derivatives
        - BUILDING_FOOTPRINTS: Cached Overture Maps building footprints, scoped
          to the image layer's AOI. Generated during imageryprep so the
          inference workflow can reuse the same set across multiple model runs.
        - VALID_AREA_MASK: GeoJSON FeatureCollection of the valid-data polygon
          derived from the post-event mosaic — i.e. the imagery's actual
          AOI excluding nodata. Same polygon used to bbox-filter Overture;
          surfaced as a downloadable artifact for users.
        - INFERENCE_*: Model inference outputs
        - MODEL_*: Model artifacts and checkpoints
        - VISUALIZER: Visualization-ready outputs
        - EDITED_PREDICTIONS_GPKG: Analyst-edited copy of a model's raw
          prediction GeoPackage. Immutable per version, so the raw
          prediction referenced by ``Model.gpkgUrl`` is never overwritten.
        - PREDICTION_ATTRS: Compact per-building prediction attribute
          payload served alongside the footprint vector tiles.
        - LAYER_FOOTPRINT_PMTILES: PMTiles archive of an image layer's
          building footprints (geometry + id only).
    """

    PRE_EVENT_RAW = Template(
        "raw_imagery_pre_event_${projectId}_${imageLayerId}"
    )
    PRE_EVENT_PREVIEW = Template(
        "preview_raw_imagery_pre_event_${projectId}_${imageLayerId}"
    )

    PRE_EVENT_MOSAIC = Template(
        "raw_imagery_pre_event_mosaic_cog_${projectId}_${imageLayerId}"
    )
    PRE_EVENT_PROCESSED_COG = Template(
        "processed_imagery_pre_event_cog_${projectId}_${imageLayerId}"
    )
    POST_EVENT_RAW = Template(
        "raw_imagery_post_event_${projectId}_${imageLayerId}"
    )
    POST_EVENT_PREVIEW = Template(
        "preview_raw_imagery_post_event_${projectId}_${imageLayerId}"
    )
    POST_EVENT_MOSAIC = Template(
        "raw_imagery_post_event_mosaic_cog_${projectId}_${imageLayerId}"
    )
    POST_EVENT_PROCESSED_COG = Template(
        "processed_imagery_post_event_cog_${projectId}_${imageLayerId}"
    )
    BUILDING_FOOTPRINTS = Template(
        "building_footprints_${projectId}_${imageLayerId}"
    )
    VALID_AREA_MASK = Template("valid_area_mask_${projectId}_${imageLayerId}")
    INFERENCE_GPKG = Template("predicted_damage_${modelName}")
    VISUALIZER = Template(
        POST_EVENT_MOSAIC.template + Template("_visualizer").template
    )
    MODEL_ARTIFACTS_ZIP = Template("artifacts_${modelName}")
    TRAINING_ARTIFACTS_ZIP = Template("training_artifacts_${modelName}")
    INFERENCE_ARTIFACTS_ZIP = Template("inference_artifacts_${modelName}")
    # Building labeling workflow: per-building MOSAIKS / DINOv2 embeddings
    # (footprints + f_* feature columns), the binary HFTR sidecar
    # (id -> feature vector), and the per-building predictions written by
    # the interactive labeler. The footprint vector tiles are NOT here:
    # they belong to the image layer (LAYER_FOOTPRINT_PMTILES), shared by
    # every model trained on it.
    BUILDING_EMBEDDINGS = Template("building_embeddings_${modelName}")
    BUILDING_FEATURES_SIDECAR = Template("building_features_${modelName}")
    BUILDING_PREDICTIONS_GPKG = Template("building_predictions_${modelName}")
    # Prediction editing workflow: each save writes a NEW versioned
    # GeoPackage derived from the raw model prediction GeoPackage, plus the
    # attribute payload and footprint tiles the editor renders against.
    EDITED_PREDICTIONS_GPKG = Template(
        "edited_predictions_${modelId}_v${version}"
    )
    # Sidecar of the RAW model output (Model.gpkgUrl).
    PREDICTION_ATTRS = Template("prediction_attrs_${modelId}")
    # Sidecar of ONE saved edited version (Model.editedPredictions[]).
    # Every version gets its own so that rendering a version is the same
    # code path as rendering the raw output with a different URL; a
    # version whose GeoPackage exists without a matching sidecar would
    # silently draw the raw classes.
    PREDICTION_ATTRS_VERSION = Template(
        "prediction_attrs_${modelId}_v${version}"
    )
    LAYER_FOOTPRINT_PMTILES = Template("footprints_${imageLayerId}")


class InviteConfig(NamedTuple):
    STATIC_APP_SUBSCRIPTION_ID: str
    STATIC_APP_RESOURCE_GROUP: str
    STATIC_APP_NAME: str
    STATIC_APP_DOMAIN: str
    EMAIL_CONNECTION_STRING: str
    EMAIL_SENDER: str
    DEFAULT_USER_ROLES: list[str]


class Config:
    """Configuration class with environment-specific settings.

    The Config class manages all configuration settings for the HASTE application,
    including storage backends, queue configurations, and environment-specific
    parameters. It loads settings from environment variables and provides
    typed access to configuration values.

    Args:
        env (str, optional): Environment name ('dev', 'test', 'prod').
            Defaults to value from ENV environment variable or 'dev'.

    Attributes:
        env (str): Current environment name.
        DEBUG (bool): True if running in development environment.
        TESTING (bool): True if running in test environment.
        DATA_DIR (str): Primary data directory path.
        TEMP_DIR (str): Temporary data directory path.
        storage_type (str): Type of metadata storage backend.
        artifact_storage_type (str): Type of artifact storage backend.
        runner_type (str): Type of task runner backend ('azure_batch').

    Example:
        >>> config = Config('prod')
        >>> data_types = config.get_metadata_types()
        >>> storage_config = config.storage_config
    """

    @property
    def INVITE(self):
        return InviteConfig(
            os.getenv("STATIC_APP_SUBSCRIPTION_ID"),
            os.getenv("STATIC_APP_RESOURCE_GROUP"),
            os.getenv("STATIC_APP_NAME"),
            os.getenv("STATIC_APP_DOMAIN"),
            os.getenv("EMAIL_CONNECTION_STRING"),
            os.getenv("EMAIL_SENDER"),
            os.getenv("DEFAULT_USER_ROLES", "contributors").split(","),
        )

    def __init__(self, env=None):
        """Initialize configuration with environment-specific settings.

        Args:
            env (str, optional): Environment name. Defaults to ENV
                environment variable or 'dev'.
        """
        self.env = env or os.getenv("env", "dev")
        self.DEBUG = self.env == "dev"
        self.TESTING = self.env == "test"
        self.TEMP_DIR = os.environ.get("TEMP_DATA_PATH", tempfile.gettempdir())
        self.DATA_DIR = os.environ.get("DATA_PATH")
        # TiTiler endpoints: internal for server-to-server, public for client responses
        # In local dev: internal=http://titiler:8000/, public=http://localhost:7071/api/titiler/
        # In production: both default to the same Azure Functions URL
        self.titiler_internal_endpoint = os.environ.get(
            "TITILER_ENDPOINT",
            "https://<titiler-function-app>.azurewebsites.net/",
        )
        self.titiler_endpoint = os.environ.get(
            "TITILER_PUBLIC_ENDPOINT", self.titiler_internal_endpoint
        )
        self.titiler_tileSize = int(os.environ.get("TITILER_TILESIZE", 256))
        self.gdal_warp_params = os.environ.get(
            "GDAL_WARP_PARAMS",
            "-co BIGTIFF=YES -co NUM_THREADS=ALL_CPUS -co COMPRESS=DEFLATE -co PREDICTOR=2 -of COG",
        )
        self.gdal_translate_params = os.environ.get(
            "GDAL_TRANSLATE_PARAMS",
            "BIGTIFF=YES NUM_THREADS=ALL_CPUS COMPRESS=DEFLATE PREDICTOR=2",
        )
        self.STORAGE_CONFIGS = {
            StorageType.LOCAL: {"directory": self.DATA_DIR},
            StorageType.BLOB: {
                "account_url": os.getenv("BLOB_ACCOUNT_URL"),
                "container": os.getenv("BLOB_CONTAINER", "data"),
                "connection_string": os.getenv("BLOB_CONNECTION_STRING"),
                "container_read_policy_name": os.getenv(
                    "BLOB_CONTAINER_READ_POLICY", "image-layer-r-policy"
                ),
            },
            StorageType.COSMOS: {
                "endpoint": os.getenv("COSMOS_ENDPOINT"),
                "database": os.getenv("COSMOS_DATABASE", "mydatabase"),
                "container": os.getenv("COSMOS_CONTAINER", "mycontainer"),
            },
            StorageType.DATALAKE: {
                "account_url": os.getenv("DATALAKE_ACCOUNT_URL"),
                "file_system": os.getenv("DATALAKE_FILESYSTEM", "data"),
            },
            StorageType.POSTGRES: {
                "host": os.getenv("POSTGRES_HOST", "localhost"),
                "table": os.getenv("POSTGRES_TABLE", "mytable"),
                "port": os.getenv("POSTGRES_PORT", "5432"),
                "database": os.getenv("POSTGRES_DATABASE", "mydatabase"),
                "user": os.getenv("POSTGRES_USER", "myuser"),
                "password": os.getenv("POSTGRES_PASSWORD"),
            },
        }
        self.queue_config = self.get_queue_config()
        self.publishing_config = self.get_publishing_config()
        self.storage_type = os.getenv("METADATA_STORAGE_TYPE", "local").lower()
        self.artifact_storage_type = os.getenv(
            "ARTIFACT_STORAGE_TYPE", "local"
        ).lower()
        self.runner_type = os.getenv("RUNNER_TYPE", "azure_batch").lower()
        self.storage_config = self._get_storage_config(self.storage_type)
        self.artifact_storage_config = self._get_storage_config(
            self.artifact_storage_type
        )

    def _get_storage_config(self, storage_type=None):
        """Get storage configuration for the specified storage type.

        Args:
            storage_type (str, optional): Type of storage backend.
                Defaults to None.

        Returns:
            dict: Configuration dictionary for the specified storage type.

        Raises:
            ValueError: If the storage type is not recognized.
        """
        try:
            storage_enum = StorageType(storage_type)
            return self.STORAGE_CONFIGS.get(storage_enum, {})
        except ValueError as e:
            raise ValueError(f"Unknown storage type: {storage_type}") from e

    @staticmethod
    def get_queue_config():
        """Get Azure Queue Storage configuration from environment variables.

        Returns:
            dict: Queue configuration including connection strings and queue names.
                Contains keys for various queues (image, train, inference, stats, zip).
        """
        return {
            "queue_connection_string": os.getenv("BLOB_CONNECTION_STRING"),
            "queue_account_url": os.getenv("QUEUE_ACCOUNT_URL"),
            "image_queue_name": os.getenv(
                "IMAGE_QUEUE_NAME", "image-layers-queue"
            ),
            "train_queue_name": os.getenv("TRAIN_QUEUE_NAME", "train-queue"),
            "inference_queue_name": os.getenv(
                "INFERENCE_QUEUE_NAME", "inference-queue"
            ),
            "stats_queue_name": os.getenv("STATS_QUEUE_NAME", "stats-queue"),
            "zip_queue_name": os.getenv("ZIP_QUEUE_NAME", "zip-queue"),
            "embedding_queue_name": os.getenv(
                "EMBEDDING_QUEUE_NAME", "embedding-queue"
            ),
            "publish_queue_name": os.getenv(
                "PUBLISH_QUEUE_NAME", "publish-queue"
            ),
            # Prediction editing: footprint PMTiles + per-model attribute
            # sidecar generation. Runs in the training container because
            # tippecanoe only ships in that image.
            "prediction_edit_prep_queue_name": os.getenv(
                "PREDICTION_EDIT_PREP_QUEUE_NAME",
                "prediction-edit-prep-queue",
            ),
        }

    @staticmethod
    def get_publishing_config():
        """Get publishing feature and provider configuration."""
        return {
            "publishing_enabled": _get_bool_env("PUBLISHING_ENABLED", True),
            "pc_provider_enabled": _get_bool_env("PC_PROVIDER_ENABLED", False),
            "max_total_bytes": _get_bounded_int_env(
                "PUBLISH_MAX_TOTAL_BYTES", 5 * 1024**3, 1
            ),
            "download_sas_minutes": _get_bounded_int_env(
                "PUBLISHED_DOWNLOAD_SAS_MINUTES", 15, 5, 60
            ),
            "pc_geocatalog_url": os.getenv("PC_GEOCATALOG_URL", ""),
            "pc_ingestion_source": os.getenv("PC_INGESTION_SOURCE", ""),
            "pc_collection_prefix": os.getenv(
                "PC_COLLECTION_PREFIX", "haste-"
            ),
            "pc_explorer_url": os.getenv("PC_EXPLORER_URL", ""),
            "pc_publishing_license": os.getenv(
                "PC_PUBLISHING_LICENSE", "CC-BY-4.0"
            ),
            # Attribution: the organization operating this deployment, recorded
            # as the STAC "processor" provider on published datasets. Empty =
            # omit the provider (no default org for the open-source build).
            "publishing_organization_name": os.getenv(
                "PUBLISHING_ORGANIZATION_NAME", ""
            ),
            "publishing_organization_url": os.getenv(
                "PUBLISHING_ORGANIZATION_URL", ""
            ),
            # Network-reachable container the GeoCatalog ingests from. When set,
            # the PC provider copies published assets here (out of the
            # firewalled data store) and points STAC hrefs at it. Empty =
            # reference assets in place from the primary artifact store.
            "publish_storage_account_url": os.getenv(
                "PUBLISH_STORAGE_ACCOUNT_URL", ""
            ),
            "publish_blob_container": os.getenv("PUBLISH_BLOB_CONTAINER", ""),
            "pc_verify_attempts": _get_bounded_int_env(
                "PC_VERIFY_ATTEMPTS", 20, 1, 60
            ),
            "lease_connection_string": os.getenv("AzureWebJobsStorage"),
            "lease_account_url": os.getenv("BLOB_ACCOUNT_URL"),
            "lease_container": os.getenv(
                "PUBLISHING_LOCK_CONTAINER", "publishing-locks"
            ),
        }

    @staticmethod
    def get_metadata_types():
        """Get enumeration of available metadata types.

        Returns:
            Enum: DataTypes enumeration containing all supported metadata types
                including PROJECT, IMAGELAYER, LABELS, USERS, CONFIG, MODEL, etc.

        Example:
            >>> types = Config.get_metadata_types()
            >>> project_type = types.PROJECT.value  # 'project'
        """

        class DataTypes(Enum):
            PROJECT = "project"
            IMAGELAYER = "imagelayer"
            LABELS = "labels"
            USERS = "users"
            CONFIG = "config"
            MODEL = "model"
            MODEL_CATALOG = "model_catalog"
            PUBLISHED_DATASET = "published_dataset"
            MODEL_ARTIFACTS = "artifacts_model"
            VISUALIZER = "visualizer_imagery"
            TRAIN_LABELS = "train_labels"
            TRAIN_CHECKPOINT = "train_checkpoint"
            TRAIN_CONFIG = "train_config"
            EXPERIMENT_CONFIG = "experiment_config"
            IMAGERY_CONFIG = "imageryprep_config"
            EMBEDDING_CONFIG = "embedding_config"
            PREDICTION_TILES_CONFIG = "prediction_tiles_config"
            PROCESSED_IMAGERY = "processed_imagery_post_event_cog"
            RAW_IMAGERY = "raw_imagery"
            PREVIEW_RAW_IMAGERY = "preview_raw_imagery"
            VALIDATION = "validation"
            # Per-embedding-model labels from the interactive labeler — kept
            # separate from the layer-scoped Building Validation (VALIDATION)
            # store so the two workflows don't overwrite each other.
            INTERACTIVE_VALIDATION = "interactive_validation"

        return DataTypes

    @staticmethod
    def get_artifact_types():
        """Get enumeration of available artifact types.

        Returns:
            ArtifactTypes: Enumeration containing template-based artifact type
                definitions for various data artifacts (raw imagery, mosaics,
                model artifacts, etc.).
        """
        return ArtifactTypes

    @staticmethod
    def get_data_formats():
        """Get enumeration of supported data formats.

        Returns:
            Enum: DataFormats enumeration containing supported file formats
                (JSON, TIF, TIFF).
        """

        class DataFormats(Enum):
            JSON = "json"
            TIF = "tif"
            TIFF = "tif"
            GPKG = "gpkg"

        return DataFormats

    @staticmethod
    def get_user_roles():
        """Get enumeration of supported user roles.

        Returns:
            Enum: UserRoles enumeration containing supported user roles
                (ADMIN, CONTRIBUTOR, VIEWER).
        """

        class UserRoles(Enum):
            ADMIN = "administrators"
            CONTRIBUTOR = "contributors"

        return UserRoles

    @staticmethod
    def get_user_statuses():
        """Get enumeration of supported user status types.

        Returns:
            Enum: UserStatus enumeration containing supported user status types
                (ACTIVE, PENDING, DELETED).
        """

        class UserStatus(Enum):
            ACTIVE = "Active"
            PENDING = "PendingAcceptance"
            INACTIVE = "Inactive"

        return UserStatus

    @staticmethod
    def get_azure_batch_config():
        """Get Azure Batch configuration for training and inference workloads.

        This method provides environment-specific Azure Batch configuration including
        VM specifications, container registry settings, and pool configurations.
        The configuration varies between development and production environments,
        with different VM sizes and operating system images optimized for each.

        Returns:
            dict: Azure Batch configuration containing:
                - account_name: Azure Batch account name
                - batch_url: Azure Batch service URL
                - vm_size: Virtual machine size (GPU-enabled for ML workloads)
                - pool_id: Batch pool identifiers for training and imagery processing
                - registry_server: Container registry server URL
                - docker_image: Docker image for containerized workloads
                - And other batch-specific configuration parameters

        Environment Variables:
            - AZURE_BATCH_ACCOUNT_NAME: Batch account name
            - AZURE_BATCH_ACCOUNT_KEY: Batch account access key
            - AZURE_BATCH_VM_SIZE: Override default VM size
            - env: Environment type ('dev' uses NC6S_V3, 'prod' uses A100)

        Note:
            Development environment uses Ubuntu 20.04 with Standard_NC6S_V3 VMs,
            while production uses Ubuntu 22.04 with Standard_NC24ads_A100_v4 VMs
            that have pre-installed GPU drivers.
        """
        # Dev resources will use the Nc6 with Ubuntu 20 because the NC6s_v3 do not come with GPU drivers,
        # they have to be added by a suitable node image or a custom one. The ubuntu 22 image does not include GPU drivers.
        # Prod resources can use Ubuntu22 image on the A100 machines, because those come with GPU drivers pre-installed.
        vm_config_map = {
            "dev": {
                "vm_size": "Standard_NC6S_V3",
                "vm_publisher": "microsoft-azure-batch",
                "vm_offer": "ubuntu-server-container",
                "vm_sku": "20-04-lts",
                "vm_version": "latest",
                "node_agent_sku_id": "batch.node.ubuntu 20.04",
            },
            "prod": {
                "vm_size": "Standard_NC24ads_A100_v4",
                "vm_publisher": "microsoft-dsvm",
                "vm_offer": "ubuntu-hpc",
                "vm_sku": "2204",
                "vm_version": "latest",
                "node_agent_sku_id": "batch.node.ubuntu 22.04",
            },
        }
        env_type = os.getenv("env", "dev")
        training_pool_id = os.getenv(
            "AZURE_BATCH_TRAINING_POOL_ID", "training-pool"
        )
        imageryprep_pool_id = os.getenv(
            "AZURE_BATCH_IMAGERYPREP_POOL_ID", "imageryprep-pool"
        )

        def _split_ids(raw, fallback):
            # Ordered candidate pool ids for capacity-aware routing (v2.1.0).
            # Comma-separated env override; fall back to the single legacy id.
            if raw:
                ids = [p.strip() for p in raw.split(",") if p.strip()]
                if ids:
                    return ids
            return [fallback]

        return {
            "account_name": os.getenv(
                "AZURE_BATCH_ACCOUNT_NAME", "<batch-account-name>"
            ),
            "account_key": os.getenv("AZURE_BATCH_ACCOUNT_KEY"),
            "batch_url": os.getenv(
                "AZURE_BATCH_URL",
                "https://<batch-account-name>.<region>.batch.azure.com",
            ),
            "training_pool_id": os.getenv(
                "AZURE_BATCH_TRAINING_POOL_ID", "training-pool"
            ),
            "imageprep_pool_id": os.getenv(
                "AZURE_BATCH_IMAGERYPREP_POOL_ID", "imageryprep-pool"
            ),
            # Ordered candidate pools per workload (v2.1.0 capacity-aware
            # routing): preference-first, spillover-second
            # (e.g. AZURE_BATCH_TRAINING_POOL_IDS="h100-pool,t4-pool").
            "training_pool_ids": _split_ids(
                os.getenv("AZURE_BATCH_TRAINING_POOL_IDS"), training_pool_id
            ),
            "inference_pool_ids": _split_ids(
                os.getenv("AZURE_BATCH_INFERENCE_POOL_IDS"), training_pool_id
            ),
            "imageryprep_pool_ids": _split_ids(
                os.getenv("AZURE_BATCH_IMAGERYPREP_POOL_IDS"),
                imageryprep_pool_id,
            ),
            # Per-job user-delegation SAS instead of pool-identity for blob I/O
            # (required for multi-tenant shared pools). Default off = legacy
            # identity_reference path.
            "use_sas": os.getenv("AZURE_BATCH_USE_SAS", "false").lower()
            == "true",
            # Whether the runner auto-creates/resizes its pool. Off for
            # pre-created IaC/autoscale pools (resize fails on autoscale).
            "manage_pools": os.getenv(
                "AZURE_BATCH_MANAGE_POOLS", "true"
            ).lower()
            == "true",
            "registry_server": _resolve_registry_server(),
            "registry_image": os.getenv(
                "AZURE_BATCH_REGISTRY_IMAGE",
                "<registry-name>.azurecr.io/<training-image>:latest",
            ),
            "user_assigned_identity_resource_id": os.getenv(
                "AZURE_BATCH_REGISTRY_IDENTITY_RESOURCE_ID",
                "/subscriptions/<subscription-id>/resourceGroups/<resource-group>/providers/Microsoft.ManagedIdentity/userAssignedIdentities/<identity-name>",
            ),
            "vm_size": os.getenv(
                "AZURE_BATCH_VM_SIZE",
                vm_config_map.get(env_type).get("vm_size"),
            ),
            "vm_publisher": os.getenv(
                "AZURE_BATCH_VM_PUBLISHER",
                vm_config_map.get(env_type).get("vm_publisher"),
            ),
            "vm_offer": os.getenv(
                "AZURE_BATCH_VM_OFFER",
                vm_config_map.get(env_type).get("vm_offer"),
            ),
            "vm_sku": os.getenv(
                "AZURE_BATCH_VM_SKU", vm_config_map.get(env_type).get("vm_sku")
            ),
            "vm_version": os.getenv(
                "AZURE_BATCH_VM_VERSION",
                vm_config_map.get(env_type).get("vm_version"),
            ),
            "node_agent_sku_id": os.getenv(
                "AZURE_BATCH_NODE_AGENT_SKU_ID",
                vm_config_map.get(env_type).get("node_agent_sku_id"),
            ),
            "target_dedicated_nodes": os.getenv(
                "AZURE_BATCH_TARGET_DEDICATED_NODES", 1
            ),
            "target_low_priority_nodes": os.getenv(
                "AZURE_BATCH_TARGET_LOW_PRIORITY_NODES", 0
            ),
            "docker_image": os.getenv(
                "AZURE_BATCH_DOCKER_IMAGE",
                "<registry-name>.azurecr.io/<training-image>:latest",
            ),
            "docker_container_work_dir": os.getenv(
                "AZURE_BATCH_DOCKER_CONTAINER_WORK_DIR", "/app"
            ),
            "command": os.getenv("AZURE_BATCH_COMMAND", "python script.py"),
            "arguments": os.getenv("AZURE_BATCH_ARGUMENTS", ["--overwrite"]),
            "output_container_url": os.getenv(
                "AZURE_BATCH_OUTPUT_CONTAINER_URL",
                "https://<storage-account>.blob.core.windows.net/<container>",
            ),
            "imageprep_docker_image": os.getenv(
                "AZURE_BATCH_IMAGERYPREP_DOCKER_IMAGE",
                "<registry-name>.azurecr.io/<imageryprep-image>:latest",
            ),
            "task_retention_time": os.getenv(
                "AZURE_BATCH_TASK_RETENTION_TIME", "P2D"
            ),
            "training_batch_job_id": os.getenv(
                "TRAINING_BATCH_JOB_ID", training_pool_id
            ),
            "imageryprep_batch_job_id": os.getenv(
                "IMAGERYPREP_BATCH_JOB_ID", imageryprep_pool_id
            ),
            "inference_batch_job_id": os.getenv(
                "INFERENCE_BATCH_JOB_ID", training_pool_id
            ),
            "artifact_batch_job_id": os.getenv(
                "ARTIFACT_BATCH_JOB_ID", imageryprep_pool_id
            ),
        }

    @staticmethod
    def get_status_types():
        """Get enumeration of available status types for jobs and tasks.

        Returns:
            Enum: StatusTypes enumeration containing standard status values
                used throughout the HASTE system for tracking job and task states.

                Available statuses:
                - PENDING: Job is queued and waiting to start
                - IN_PROGRESS: Job is currently executing
                - COMPLETED: Job finished successfully
                - FAILED: Job encountered an error and failed
                - CANCELLED: Job was cancelled by user or system

        Example:
            >>> status_types = Config.get_status_types()
            >>> current_status = status_types.IN_PROGRESS.value  # 'InProgress'
        """

        class StatusTypes(Enum):
            PENDING = "Queued"
            IN_PROGRESS = "InProgress"
            COMPLETED = "Processed"
            FAILED = "Failed"
            CANCELLED = "Cancelled"

        return StatusTypes
