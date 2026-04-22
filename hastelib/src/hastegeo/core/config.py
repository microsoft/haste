# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License.
import os
import tempfile
from enum import Enum
from string import Template
from typing import NamedTuple


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
    INFERENCE_GPKG = Template("predicted_damage_${modelName}")
    VISUALIZER = Template(
        POST_EVENT_MOSAIC.template + Template("_visualizer").template
    )
    MODEL_ARTIFACTS_ZIP = Template("artifacts_${modelName}")


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
            MODEL_ARTIFACTS = "artifacts_model"
            VISUALIZER = "visualizer_imagery"
            TRAIN_LABELS = "train_labels"
            TRAIN_CHECKPOINT = "train_checkpoint"
            TRAIN_CONFIG = "train_config"
            EXPERIMENT_CONFIG = "experiment_config"
            IMAGERY_CONFIG = "imageryprep_config"
            PROCESSED_IMAGERY = "processed_imagery_post_event_cog"
            RAW_IMAGERY = "raw_imagery"
            PREVIEW_RAW_IMAGERY = "preview_raw_imagery"

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
            "registry_server": os.getenv(
                "AZURE_BATCH_REGISTRY_SERVER",
                "<registry-name>.azurecr.io",
            ),
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
