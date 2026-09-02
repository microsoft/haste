# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License.
import logging
import math
import os
import re
import tempfile
from enum import Enum
from string import Template
from typing import Dict, NamedTuple, Optional

# ``hastegeo.core.models.compute`` has no dependency back on this module —
# see that module's docstring/``is_deployed_environment`` note — so this is
# a safe, ordinary top-level import with no circular-import risk. This is
# unlike the optional ``azure-ai-ml`` SDK itself, which is never imported
# here or anywhere in this module — see ``hastegeo.core.runners.azure_ml``
# for the lazy-import boundary that keeps a Batch/local-only deployment
# free of it.
from hastegeo.core.models.compute import (
    ComputeBackend,
    ComputeWorkload,
    validate_environment_reference,
)

_logger = logging.getLogger(__name__)

REGISTRY_SERVER_PLACEHOLDER = "<registry-name>.azurecr.io"

_SCHEME_RE = re.compile(r"^https?://", re.IGNORECASE)

# ``COMPUTE_BACKEND_<WORKLOAD>``/``AML_COMPUTE_<WORKLOAD>``/
# ``AML_ENVIRONMENT_<IMAGE>`` env-var suffixes, one entry per
# ``ComputeWorkload`` (data-model.md#configuration-changes). Kept in sync
# with the equivalent private mapping in ``runners/router.py`` — duplicated
# rather than imported because that one is private to the router module and
# this module must not depend on ``hastegeo.core.runners`` (the runners
# package depends on ``config``, not the other way around).
_COMPUTE_WORKLOAD_ENV_SUFFIX: Dict[ComputeWorkload, str] = {
    ComputeWorkload.TRAINING: "TRAINING",
    ComputeWorkload.INFERENCE: "INFERENCE",
    ComputeWorkload.EMBEDDING: "EMBEDDING",
    ComputeWorkload.IMAGERY_PREPARATION: "IMAGERYPREP",
    ComputeWorkload.ARTIFACT_PACKAGING: "ARTIFACTS",
}

# ``AML_ENVIRONMENT_<FAMILY>`` per workload, collapsed to HASTE's two
# container image families (design.md#workload-migration-matrix): the
# training image (training/inference/embedding) and the imagery-prep image
# (imagery preparation/artifact packaging). Unlike
# ``_COMPUTE_WORKLOAD_ENV_SUFFIX``, this is intentionally *not* one setting
# per workload — HASTE has exactly two images, so a per-workload setting
# would just duplicate the same value three times for the training image.
_AML_ENVIRONMENT_FAMILY_ENV: Dict[ComputeWorkload, str] = {
    ComputeWorkload.TRAINING: "AML_ENVIRONMENT_TRAINING",
    ComputeWorkload.INFERENCE: "AML_ENVIRONMENT_TRAINING",
    ComputeWorkload.EMBEDDING: "AML_ENVIRONMENT_TRAINING",
    ComputeWorkload.IMAGERY_PREPARATION: "AML_ENVIRONMENT_IMAGERYPREP",
    ComputeWorkload.ARTIFACT_PACKAGING: "AML_ENVIRONMENT_IMAGERYPREP",
}

# HASTE's two container image families, per workload
# (design.md#workload-migration-matrix). Used to name the neutral
# ``COMPUTE_IMAGE_<FAMILY>`` setting and to pick the legacy
# ``get_azure_batch_config()`` key it falls back to.
_COMPUTE_IMAGE_FAMILY: Dict[ComputeWorkload, str] = {
    ComputeWorkload.TRAINING: "TRAINING",
    ComputeWorkload.INFERENCE: "TRAINING",
    ComputeWorkload.EMBEDDING: "TRAINING",
    ComputeWorkload.IMAGERY_PREPARATION: "IMAGERYPREP",
    ComputeWorkload.ARTIFACT_PACKAGING: "IMAGERYPREP",
}

_COMPUTE_IMAGE_BATCH_KEY: Dict[ComputeWorkload, str] = {
    ComputeWorkload.TRAINING: "docker_image",
    ComputeWorkload.INFERENCE: "docker_image",
    ComputeWorkload.EMBEDDING: "docker_image",
    ComputeWorkload.IMAGERY_PREPARATION: "imageprep_docker_image",
    ComputeWorkload.ARTIFACT_PACKAGING: "imageprep_docker_image",
}

# Legacy per-workload Azure Batch candidate-pool lists backing the neutral
# ``COMPUTE_TARGETS_<WORKLOAD>`` setting. Mirrors exactly which pool list
# each processor passed to ``UnifiedRunner`` before the compute layer
# existed, so pool routing (batch-compute-expansion) is unchanged: model
# workloads on the training pools, imagery preparation and artifact
# packaging on the imagery-prep (CPU) pools.
_COMPUTE_TARGET_BATCH_KEY: Dict[ComputeWorkload, str] = {
    ComputeWorkload.TRAINING: "training_pool_ids",
    ComputeWorkload.INFERENCE: "inference_pool_ids",
    ComputeWorkload.EMBEDDING: "training_pool_ids",
    ComputeWorkload.IMAGERY_PREPARATION: "imageryprep_pool_ids",
    ComputeWorkload.ARTIFACT_PACKAGING: "imageryprep_pool_ids",
}

# Shared-memory default per workload. 32 GiB matches the
# ``--shm-size=32g`` Azure Batch already passes for every task; the
# CPU-capable workloads leave it unset so a backend that honors the
# request (AML) is not forced to reserve GPU-sized shared memory for them.
_COMPUTE_DEFAULT_SHARED_MEMORY_MB: Dict[ComputeWorkload, Optional[int]] = {
    ComputeWorkload.TRAINING: 32768,
    ComputeWorkload.INFERENCE: 32768,
    ComputeWorkload.EMBEDDING: 32768,
    ComputeWorkload.IMAGERY_PREPARATION: None,
    ComputeWorkload.ARTIFACT_PACKAGING: None,
}

# Wall-clock budget per workload, used by backends that enforce one (AML).
# Azure Batch has never applied a task timeout in HASTE, so these values
# only widen ``ComputeJobSpec``'s 1-hour default to something realistic for
# each workload rather than introducing a new limit on Batch.
_COMPUTE_DEFAULT_TIMEOUT_SECONDS: Dict[ComputeWorkload, int] = {
    ComputeWorkload.TRAINING: 24 * 3600,
    ComputeWorkload.INFERENCE: 12 * 3600,
    ComputeWorkload.EMBEDDING: 12 * 3600,
    ComputeWorkload.IMAGERY_PREPARATION: 12 * 3600,
    ComputeWorkload.ARTIFACT_PACKAGING: 6 * 3600,
}

# Advisory accelerator request. Artifact packaging (and imagery
# preparation) must never require a GPU target
# (design.md#workload-migration-matrix).
_COMPUTE_DEFAULT_ACCELERATOR: Dict[ComputeWorkload, Optional[str]] = {
    ComputeWorkload.TRAINING: "gpu",
    ComputeWorkload.INFERENCE: "gpu",
    ComputeWorkload.EMBEDDING: "gpu",
    ComputeWorkload.IMAGERY_PREPARATION: None,
    ComputeWorkload.ARTIFACT_PACKAGING: None,
}

#: Valid ``AML_MODE`` values. Mirrors the Azure Batch ``Create``/
#: ``Existing`` IaC convention, plus ``Disabled``, but this adapter (Stage
#: 1) never provisions, updates, or deletes an AML workspace/compute/
#: environment/datastore for *either* enabled value — it only ever
#: *consumes* resources named by ``AML_SUBSCRIPTION_ID``/
#: ``AML_RESOURCE_GROUP``/``AML_WORKSPACE_NAME``/``AML_DATASTORE_NAME``/
#: ``AML_COMPUTE_<WORKLOAD>``/``AML_ENVIRONMENT_<FAMILY>``, which must
#: already exist regardless of ``AML_MODE``. ``Existing`` is the
#: supported Stage-1 reference-only path; ``Create`` is accepted (parity
#: with Batch's mode vocabulary, and reserved for a possible future IaC-
#: side provisioning story) but is not distinguished from ``Existing`` by
#: any code in this module or the azure_ml adapter today. ``Disabled``
#: (default) turns the backend off entirely.
AML_MODES = ("Disabled", "Create", "Existing")

#: Valid ``AML_IDENTITY_MODE`` values, aligned with the AML IaC/security
#: model: ``user`` (default) maps to AML's ``UserIdentityConfiguration``
#: (the identity of the submitting principal); ``managed`` maps to
#: ``ManagedIdentityConfiguration(resource_id=AML_MANAGED_IDENTITY_ID)``
#: (the user-assigned managed identity attached to the AML compute/
#: workspace by IaC). See ``hastegeo.core.runners.azure_ml`` for the
#: mapping.
AML_IDENTITY_MODES = ("user", "managed")


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


def _get_bounded_float_env(name, default, minimum, maximum=None):
    raw = os.getenv(name, str(default))
    try:
        value = float(raw)
    except (TypeError, ValueError):
        raise ValueError(f"{name} must be a number")
    if not math.isfinite(value):
        raise ValueError(f"{name} must be a finite number")
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
    # (footprints + f_* feature columns), the matching PMTiles vector tiles
    # (geometry + id only), the binary HFTR sidecar (id -> feature vector),
    # and the per-building predictions written by the interactive labeler.
    BUILDING_EMBEDDINGS = Template("building_embeddings_${modelName}")
    BUILDING_PMTILES = Template("building_pmtiles_${modelName}")
    BUILDING_FEATURES_SIDECAR = Template("building_features_${modelName}")
    BUILDING_PREDICTIONS_GPKG = Template("building_predictions_${modelName}")


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
            # Explorer visualization: render a damage-classification COG (our
            # derived output, not source imagery) plus the render/mosaic/tile
            # config the GeoCatalog Explorer requires.
            "publish_explorer_render_enabled": _get_bool_env(
                "PUBLISH_EXPLORER_RENDER_ENABLED", True
            ),
            "publish_damage_raster_meters": _get_bounded_float_env(
                "PUBLISH_DAMAGE_RASTER_METERS", 0.5, 0.01, 100.0
            ),
            "publish_damage_raster_max_pixels": _get_bounded_int_env(
                "PUBLISH_DAMAGE_RASTER_MAX_PIXELS", 8192, 256, 20000
            ),
            "publish_damage_raster_min_zoom": _get_bounded_int_env(
                "PUBLISH_DAMAGE_RASTER_MIN_ZOOM", 13, 0, 24
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
    def get_compute_runtime_config(workload: ComputeWorkload) -> dict:
        """Get the backend-neutral *runtime* settings a workload's
        ``ComputeJobSpec`` builder needs (image, output root, container
        resources, provider target candidates).

        This is the one place that knows both the new, backend-neutral
        ``COMPUTE_*`` application settings and their backward-compatible
        ``AZURE_BATCH_*`` predecessors: processors read this method and
        never an environment-variable name, so the same spec builder works
        on Azure Batch, Azure Machine Learning, and local Docker
        (design.md#workload-migration-matrix, plan.md Phase 8).

        Resolution order is always: neutral ``COMPUTE_*`` setting, then the
        legacy ``AZURE_BATCH_*`` setting it replaces (so an existing
        deployment keeps working untouched), then a built-in default.

        Args:
            workload: The ``ComputeWorkload`` the job runs.

        Returns:
            dict:
                - ``image``: container image reference for the workload's
                  image family — the training image
                  (``COMPUTE_IMAGE_TRAINING`` /
                  ``AZURE_BATCH_DOCKER_IMAGE``) for training/inference/
                  embedding, the imagery-prep image
                  (``COMPUTE_IMAGE_IMAGERYPREP`` /
                  ``AZURE_BATCH_IMAGERYPREP_DOCKER_IMAGE``) for imagery
                  preparation/artifact packaging.
                - ``environment_reference``: immutable Azure Machine
                  Learning environment version for that same image family,
                  or ``None``. Backends that do not use it (Batch, local)
                  ignore it.
                - ``output_container_url``: container URL every output for
                  this workload is written under
                  (``COMPUTE_OUTPUT_CONTAINER_URL`` /
                  ``AZURE_BATCH_OUTPUT_CONTAINER_URL``). HASTE's
                  ``<project-hash>/<task-id>`` prefix is appended by the
                  caller, not here.
                - ``target_candidates``: ordered, provider-specific
                  compute targets the workload may run on (Azure Batch
                  pool ids today — ``COMPUTE_TARGETS_<WORKLOAD>`` /
                  ``AZURE_BATCH_*_POOL_IDS``). Azure ML resolves its own
                  per-workload cluster from ``AML_COMPUTE_<WORKLOAD>``.
                - ``shared_memory_mb``: shared-memory request
                  (``COMPUTE_SHARED_MEMORY_MB_<WORKLOAD>`` /
                  ``COMPUTE_SHARED_MEMORY_MB``); defaults to the 32 GiB
                  Azure Batch already hard-codes for GPU workloads and to
                  ``None`` for the CPU-capable ones.
                - ``timeout_seconds``: wall-clock budget
                  (``COMPUTE_TIMEOUT_SECONDS_<WORKLOAD>`` /
                  ``COMPUTE_TIMEOUT_SECONDS``). Azure Batch does not apply
                  it (parity with today's behavior); AML does.
                - ``accelerator``: ``"gpu"`` for the model workloads,
                  ``None`` for imagery preparation and artifact packaging
                  so neither is pinned to a GPU target
                  (design.md#workload-migration-matrix).
        """
        suffix = _COMPUTE_WORKLOAD_ENV_SUFFIX[workload]
        batch_config = Config.get_azure_batch_config()
        image_family = _COMPUTE_IMAGE_FAMILY[workload]

        def _first_set(*values, default=None):
            for value in values:
                if value is not None and str(value).strip():
                    return value
            return default

        image = _first_set(
            os.getenv(f"COMPUTE_IMAGE_{image_family}"),
            batch_config[_COMPUTE_IMAGE_BATCH_KEY[workload]],
        )
        output_container_url = _first_set(
            os.getenv("COMPUTE_OUTPUT_CONTAINER_URL"),
            batch_config["output_container_url"],
        )
        raw_targets = os.getenv(f"COMPUTE_TARGETS_{suffix}")
        if raw_targets and raw_targets.strip():
            target_candidates = [
                token.strip()
                for token in raw_targets.split(",")
                if token.strip()
            ]
        else:
            target_candidates = list(
                batch_config[_COMPUTE_TARGET_BATCH_KEY[workload]]
            )

        shared_memory_raw = _first_set(
            os.getenv(f"COMPUTE_SHARED_MEMORY_MB_{suffix}"),
            os.getenv("COMPUTE_SHARED_MEMORY_MB"),
        )
        if shared_memory_raw is None:
            shared_memory_mb = _COMPUTE_DEFAULT_SHARED_MEMORY_MB[workload]
        else:
            shared_memory_mb = int(shared_memory_raw)
            if shared_memory_mb < 0:
                raise ValueError(
                    "COMPUTE_SHARED_MEMORY_MB must not be negative"
                )

        timeout_raw = _first_set(
            os.getenv(f"COMPUTE_TIMEOUT_SECONDS_{suffix}"),
            os.getenv("COMPUTE_TIMEOUT_SECONDS"),
        )
        if timeout_raw is None:
            timeout_seconds = _COMPUTE_DEFAULT_TIMEOUT_SECONDS[workload]
        else:
            timeout_seconds = int(timeout_raw)
            if timeout_seconds <= 0:
                raise ValueError(
                    "COMPUTE_TIMEOUT_SECONDS must be a positive number of "
                    "seconds"
                )

        return {
            "image": image,
            "environment_reference": (
                Config.get_aml_environment_reference_for_workload(workload)
            ),
            "output_container_url": output_container_url,
            "target_candidates": target_candidates,
            "shared_memory_mb": shared_memory_mb,
            "timeout_seconds": timeout_seconds,
            "accelerator": _COMPUTE_DEFAULT_ACCELERATOR[workload],
        }

    @staticmethod
    def get_compute_config() -> dict:
        """Get backend-neutral compute routing configuration.

        Reads ``COMPUTE_BACKEND_DEFAULT``/``COMPUTE_BACKEND_<WORKLOAD>``
        (data-model.md#configuration-changes) and the deprecated
        ``RUNNER_TYPE`` alias. Unlike ``get_azure_batch_config()``, an
        unrecognized backend name is a hard ``ValueError`` rather than a
        silently-accepted placeholder: a misspelled backend name must never
        resolve to a working (if wrong) default.

        Per-workload ``auto`` candidate/weight configuration
        (``COMPUTE_AUTO_CANDIDATES_<WORKLOAD>``/``COMPUTE_AUTO_WEIGHTS_
        <WORKLOAD>``) is read directly by ``hastegeo.core.runners.router``,
        not duplicated here.

        Returns:
            dict: ``default_backend`` (``ComputeBackend``),
                ``backend_overrides`` (``dict[ComputeWorkload,
                ComputeBackend]``, only workloads with an explicit
                override), ``follow_on_inherits_backend`` (bool), and
                ``runner_type_alias_used`` (bool, true when
                ``COMPUTE_BACKEND_DEFAULT`` is unset and the deprecated
                ``RUNNER_TYPE`` supplied the default instead).

        Raises:
            ValueError: ``COMPUTE_BACKEND_DEFAULT``/``RUNNER_TYPE``/any
                ``COMPUTE_BACKEND_<WORKLOAD>`` names a backend
                ``ComputeBackend`` does not recognize.
        """

        def _parse_backend(raw: Optional[str], *, env_name: str):
            if raw is None or not raw.strip():
                return None
            try:
                return ComputeBackend(raw.strip().lower())
            except ValueError as exc:
                valid = ", ".join(b.value for b in ComputeBackend)
                raise ValueError(
                    f"{env_name}={raw!r} is not a recognized compute "
                    f"backend; expected one of: {valid}"
                ) from exc

        runner_type_alias = os.getenv("RUNNER_TYPE")
        default_raw = os.getenv("COMPUTE_BACKEND_DEFAULT")
        runner_type_alias_used = bool(runner_type_alias) and not default_raw
        default_backend = _parse_backend(
            default_raw, env_name="COMPUTE_BACKEND_DEFAULT"
        ) or _parse_backend(runner_type_alias, env_name="RUNNER_TYPE")
        if default_backend is None:
            default_backend = ComputeBackend.AZURE_BATCH

        backend_overrides: Dict[ComputeWorkload, ComputeBackend] = {}
        for workload, suffix in _COMPUTE_WORKLOAD_ENV_SUFFIX.items():
            env_name = f"COMPUTE_BACKEND_{suffix}"
            backend = _parse_backend(os.getenv(env_name), env_name=env_name)
            if backend is not None:
                backend_overrides[workload] = backend

        return {
            "default_backend": default_backend,
            "backend_overrides": backend_overrides,
            "follow_on_inherits_backend": _get_bool_env(
                "COMPUTE_FOLLOW_ON_INHERITS_BACKEND", True
            ),
            "runner_type_alias_used": runner_type_alias_used,
        }

    @staticmethod
    def aml_environment_env_var_name_for_workload(
        workload: ComputeWorkload,
    ) -> str:
        """Return the ``AML_ENVIRONMENT_<FAMILY>`` application-setting name
        that resolves the immutable AML environment version for
        ``workload``'s container image *family*.

        HASTE has exactly two container images (design.md#workload-
        migration-matrix): the training image, shared by
        ``training``/``inference``/``embedding``, and the imagery-prep
        image, shared by ``imagery_preparation``/``artifact_packaging``.
        This is a fallback only — a ``ComputeJobSpec`` that already
        carries an explicit ``container.environmentReference`` (adapter- or
        caller-populated) takes precedence over it; see
        ``hastegeo.core.runners.azure_ml``.
        """
        return _AML_ENVIRONMENT_FAMILY_ENV[workload]

    @staticmethod
    def get_aml_environment_reference_for_workload(
        workload: ComputeWorkload,
    ) -> Optional[str]:
        """Return the configured immutable AML environment version for
        ``workload``'s image family (``AML_ENVIRONMENT_TRAINING`` or
        ``AML_ENVIRONMENT_IMAGERYPREP``), or ``None`` if unset.
        """
        return os.getenv(
            Config.aml_environment_env_var_name_for_workload(workload)
        )

    @staticmethod
    def get_aml_config() -> dict:
        """Get Azure Machine Learning backend configuration.

        Unlike ``get_azure_batch_config()``, settings are returned exactly
        as configured (``None`` when unset) rather than filled with
        ``<placeholder>`` defaults: AML configuration is only required when
        ``AML_MODE != Disabled`` or a job explicitly requests ``azure_ml``
        (data-model.md#configuration-changes), so this method never raises
        for an all-``Disabled`` (default) deployment — required-setting
        validation is the azure_ml adapter's responsibility
        (``hastegeo.core.runners.azure_ml``), invoked only when that backend
        is actually selected.

        Returns:
            dict: ``mode`` (one of ``AML_MODES``), ``subscription_id``,
                ``resource_group``, ``workspace_name``, ``datastore_name``,
                ``compute_by_workload`` (``dict[ComputeWorkload,
                Optional[str]]``), ``environment_by_workload``
                (``dict[ComputeWorkload, Optional[str]]``, collapsed to the
                two image families — see
                ``get_aml_environment_reference_for_workload``),
                ``identity_mode`` (one of ``AML_IDENTITY_MODES``,
                lowercased), ``managed_identity_id``, ``experiment_prefix``,
                ``submission_timeout_seconds`` (int).

        Raises:
            ValueError: ``AML_MODE`` is set to something other than
                ``Disabled``/``Create``/``Existing``. Note that
                ``Create``/``Existing`` are not distinguished by any
                behavior in this module or the azure_ml adapter today —
                both require the same set of already-existing resource
                identifiers below; ``Existing`` is the supported Stage-1
                path.
        """
        mode = os.getenv("AML_MODE", "Disabled").strip()
        if mode not in AML_MODES:
            raise ValueError(f"AML_MODE={mode!r} must be one of {AML_MODES}")

        compute_by_workload: Dict[ComputeWorkload, Optional[str]] = {
            workload: os.getenv(f"AML_COMPUTE_{suffix}")
            for workload, suffix in _COMPUTE_WORKLOAD_ENV_SUFFIX.items()
        }
        environment_by_workload: Dict[ComputeWorkload, Optional[str]] = {
            workload: Config.get_aml_environment_reference_for_workload(
                workload
            )
            for workload in ComputeWorkload
        }

        return {
            "mode": mode,
            "subscription_id": os.getenv("AML_SUBSCRIPTION_ID"),
            "resource_group": os.getenv("AML_RESOURCE_GROUP"),
            "workspace_name": os.getenv("AML_WORKSPACE_NAME"),
            "datastore_name": os.getenv("AML_DATASTORE_NAME"),
            "compute_by_workload": compute_by_workload,
            "environment_by_workload": environment_by_workload,
            "identity_mode": os.getenv("AML_IDENTITY_MODE", "user")
            .strip()
            .lower(),
            "managed_identity_id": os.getenv("AML_MANAGED_IDENTITY_ID"),
            "experiment_prefix": os.getenv("AML_EXPERIMENT_PREFIX", "haste"),
            "submission_timeout_seconds": _get_bounded_int_env(
                "AML_SUBMISSION_TIMEOUT_SECONDS", 120, 1, 3600
            ),
        }

    @staticmethod
    def validate_aml_config(
        aml_config: dict,
        *,
        workload: Optional[ComputeWorkload] = None,
        environment_reference: Optional[str] = None,
    ) -> None:
        """Validate deterministic AML settings without importing the SDK.

        ``workload`` is supplied at API boundaries that must verify a
        complete target and environment before queueing. The adapter omits
        it for its base validation, then applies target overrides and
        explicit ``container.environmentReference`` values from the spec.
        """
        mode = aml_config["mode"]
        if mode not in AML_MODES:
            raise ValueError(f"AML_MODE={mode!r} must be one of {AML_MODES}")
        if mode == "Disabled":
            raise ValueError(
                "Azure Machine Learning is disabled (AML_MODE=Disabled)"
            )

        missing = [
            env_name
            for key, env_name in (
                ("subscription_id", "AML_SUBSCRIPTION_ID"),
                ("resource_group", "AML_RESOURCE_GROUP"),
                ("workspace_name", "AML_WORKSPACE_NAME"),
                ("datastore_name", "AML_DATASTORE_NAME"),
            )
            if not aml_config.get(key)
        ]
        identity_mode = aml_config["identity_mode"]
        if identity_mode not in AML_IDENTITY_MODES:
            raise ValueError(
                f"AML_IDENTITY_MODE={identity_mode!r} must be one of "
                f"{AML_IDENTITY_MODES}"
            )
        if identity_mode == "managed" and not aml_config.get(
            "managed_identity_id"
        ):
            missing.append("AML_MANAGED_IDENTITY_ID")

        experiment_prefix = (aml_config.get("experiment_prefix") or "").strip()
        if not experiment_prefix or not re.fullmatch(
            r"[A-Za-z0-9_-]+", experiment_prefix
        ):
            raise ValueError(
                "AML_EXPERIMENT_PREFIX must contain only letters, digits, "
                "'_' or '-'"
            )

        if workload is not None:
            if not aml_config["compute_by_workload"].get(workload):
                missing.append(
                    f"AML_COMPUTE_{_COMPUTE_WORKLOAD_ENV_SUFFIX[workload]}"
                )
            resolved_environment = environment_reference or aml_config[
                "environment_by_workload"
            ].get(workload)
            if not resolved_environment:
                missing.append(
                    Config.aml_environment_env_var_name_for_workload(workload)
                )
            else:
                validate_environment_reference(resolved_environment)

        if missing:
            raise ValueError(
                "Azure Machine Learning is not configured. Missing "
                "application settings: " + ", ".join(missing)
            )

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
