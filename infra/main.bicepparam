using './main.bicep'

// Values are sourced from the azd environment (azd sets these as environment
// variables from `azd env set ...`). Defaults keep `az bicep build` / local
// what-if runs working without azd.

param resourcePrefix = readEnvironmentVariable('HASTE_RESOURCE_PREFIX', 'haste')
param location = readEnvironmentVariable('AZURE_LOCATION', 'westus2')
param randomSuffix = readEnvironmentVariable('HASTE_RANDOM_SUFFIX', 'dev1')

param apimPublisherEmail = readEnvironmentVariable('HASTE_APIM_PUBLISHER_EMAIL', '')
param apimPublisherName = readEnvironmentVariable('HASTE_APIM_PUBLISHER_NAME', 'AI For Good Lab')

// Shared / BYO resources.
param sharedResourceGroup = readEnvironmentVariable('HASTE_SHARED_RESOURCE_GROUP', '')
param sharedAcrName = readEnvironmentVariable('HASTE_SHARED_ACR_NAME', '')

// Batch (dual create-vs-BYO).
param batchAccountMode = readEnvironmentVariable('HASTE_BATCH_ACCOUNT_MODE', 'Create')
param existingBatchAccountName = readEnvironmentVariable('HASTE_EXISTING_BATCH_ACCOUNT', '')
param batchPoolMode = readEnvironmentVariable('HASTE_BATCH_POOL_MODE', 'Create')
param existingBatchPoolId = readEnvironmentVariable('HASTE_EXISTING_BATCH_POOL_ID', '')

// Batch container images (tag included) — feed the pool AND the api/queues app
// settings, so they must match the image the (immutable) Batch pool was created
// with. Override per env via HASTE_TRAINING_IMAGE / HASTE_IMAGERYPREP_IMAGE;
// bumping the tag requires recreating the pool (deploymentConfiguration is immutable).
param trainingImage = readEnvironmentVariable('HASTE_TRAINING_IMAGE', 'hastetraining:1.4.1')
param imageryprepImage = readEnvironmentVariable('HASTE_IMAGERYPREP_IMAGE', 'hasteimageryprep:1.4.1')

// Global fallback compute backend (hastegeo.core.config.get_compute_config).
// Default azure_batch reproduces today's Batch-only behavior exactly;
// RUNNER_TYPE (still emitted below in functions.bicep) remains the
// deprecated legacy alias the code reads when this is unset.
param computeBackendDefault = readEnvironmentVariable('HASTE_COMPUTE_BACKEND_DEFAULT', 'azure_batch')

// Azure Machine Learning (Disabled/Existing/Create). Default Disabled — no
// AML app settings emitted, zero behavior change. Existing (the default
// enablement path once turned on) wires pre-existing, platform-owned
// identifiers straight into Function App settings; HASTE creates/mutates
// nothing. Create (explicit, later opt-in) instead has HASTE provision its
// own workspace/compute/environment/datastore stack.
param amlMode = readEnvironmentVariable('HASTE_AML_MODE', 'Disabled')
param existingAmlWorkspaceName = readEnvironmentVariable('HASTE_EXISTING_AML_WORKSPACE_NAME', '')
param amlWorkspaceResourceGroup = readEnvironmentVariable('HASTE_AML_WORKSPACE_RESOURCE_GROUP', '')
// Names of the existing (already-provisioned) GPU/CPU compute clusters.
// Ignored when amlMode == Create.
param existingAmlGpuComputeName = readEnvironmentVariable('HASTE_EXISTING_AML_GPU_COMPUTE_NAME', '')
param existingAmlCpuComputeName = readEnvironmentVariable('HASTE_EXISTING_AML_CPU_COMPUTE_NAME', '')
// Name of the existing (already-registered) AML datastore. Ignored when
// amlMode == Create.
param existingAmlDatastoreName = readEnvironmentVariable('HASTE_EXISTING_AML_DATASTORE_NAME', '')
// Fully-qualified azureml:<name>:<version> references to existing,
// already-registered immutable environment versions. Ignored when amlMode
// == Create.
param existingAmlTrainingEnvironmentReference = readEnvironmentVariable('HASTE_EXISTING_AML_TRAINING_ENVIRONMENT_REFERENCE', '')
param existingAmlImageryprepEnvironmentReference = readEnvironmentVariable('HASTE_EXISTING_AML_IMAGERYPREP_ENVIRONMENT_REFERENCE', '')
// Create-mode-only provisioning knobs (ignored when amlMode != Create).
param amlGpuComputeVmSize = readEnvironmentVariable('HASTE_AML_GPU_COMPUTE_VM_SIZE', 'Standard_NC40ads_H100_v5')
param amlGpuComputeMaxNodes = int(readEnvironmentVariable('HASTE_AML_GPU_COMPUTE_MAX_NODES', '3'))
param amlCpuComputeVmSize = readEnvironmentVariable('HASTE_AML_CPU_COMPUTE_VM_SIZE', 'Standard_D4s_v5')
param amlCpuComputeMaxNodes = int(readEnvironmentVariable('HASTE_AML_CPU_COMPUTE_MAX_NODES', '3'))
param amlComputeIdleTime = readEnvironmentVariable('HASTE_AML_COMPUTE_IDLE_TIME', 'PT30M')
// Empty => no VNet injection (current default/public-compute behavior).
param amlComputeSubnetId = readEnvironmentVariable('HASTE_AML_COMPUTE_SUBNET_ID', '')
// Default job-execution identity mode: 'user' (submit as the calling
// hastefuncqueues principal) or 'managed' (submit as a specific
// user-assigned managed identity). In Existing mode, granting either
// identity access on the existing AML platform is a prerequisite owned by
// that platform; in Create mode HASTE grants the queue app identity itself
// (amlRole.bicep) only when amlIdentityMode == user.
param amlIdentityMode = readEnvironmentVariable('HASTE_AML_IDENTITY_MODE', 'user')
// Only consulted when amlIdentityMode == 'managed'; empty then defaults to
// the shared env UMI.
param amlManagedIdentityResourceId = readEnvironmentVariable('HASTE_AML_MANAGED_IDENTITY_RESOURCE_ID', '')

// Email sender domain.
param emailSenderDomainType = readEnvironmentVariable('HASTE_EMAIL_SENDER_DOMAIN_TYPE', 'AzureManaged')
param emailCustomDomain = readEnvironmentVariable('HASTE_EMAIL_CUSTOM_DOMAIN', '')

// Front Door (default off).
param enableFrontDoor = bool(readEnvironmentVariable('HASTE_ENABLE_FRONT_DOOR', 'false'))

// Dev-only auto-provisioning + anonymous auth (never true for production).
param developmentMode = bool(readEnvironmentVariable('HASTE_DEVELOPMENT_MODE', 'false'))

// v2.1.0 capacity-aware routing + per-job SAS (default = legacy single-pool).
param trainingPoolIds = readEnvironmentVariable('HASTE_BATCH_TRAINING_POOL_IDS', '')
param inferencePoolIds = readEnvironmentVariable('HASTE_BATCH_INFERENCE_POOL_IDS', '')
param imageryprepPoolIds = readEnvironmentVariable('HASTE_BATCH_IMAGERYPREP_POOL_IDS', '')
param useSas = bool(readEnvironmentVariable('HASTE_BATCH_USE_SAS', 'false'))
param managePools = bool(readEnvironmentVariable('HASTE_BATCH_MANAGE_POOLS', 'true'))

// Data publishing feature flag (Local target). On by default; override with
// HASTE_PUBLISHING_ENABLED=false to disable.
param publishingEnabled = bool(readEnvironmentVariable('HASTE_PUBLISHING_ENABLED', 'true'))

// Planetary Computer publishing target. Provisioned/owned by the operator; the
// GeoCatalog is external to this template. Default off / unset.
param pcProviderEnabled = bool(readEnvironmentVariable('HASTE_PC_PROVIDER_ENABLED', 'false'))
param publishExplorerRenderEnabled = bool(readEnvironmentVariable('HASTE_PUBLISH_EXPLORER_RENDER_ENABLED', 'true'))
param pcGeocatalogUrl = readEnvironmentVariable('HASTE_PC_GEOCATALOG_URL', '')
param pcExplorerUrl = readEnvironmentVariable('HASTE_PC_EXPLORER_URL', '')
param pcIngestionSource = readEnvironmentVariable('HASTE_PC_INGESTION_SOURCE', '')
param pcCollectionPrefix = readEnvironmentVariable('HASTE_PC_COLLECTION_PREFIX', 'haste-')
param pcPublishingLicense = readEnvironmentVariable('HASTE_PC_PUBLISHING_LICENSE', 'CC-BY-4.0')
// STAC processor attribution (the organization operating this deployment).
param publishingOrganizationName = readEnvironmentVariable('HASTE_PUBLISHING_ORGANIZATION_NAME', '')
param publishingOrganizationUrl = readEnvironmentVariable('HASTE_PUBLISHING_ORGANIZATION_URL', '')
param publishStorageAccountUrl = readEnvironmentVariable('HASTE_PUBLISH_STORAGE_ACCOUNT_URL', '')
param publishBlobContainer = readEnvironmentVariable('HASTE_PUBLISH_BLOB_CONTAINER', '')
param pcGeoCatalogIngestPrincipalId = readEnvironmentVariable('HASTE_PC_GEOCATALOG_INGEST_PRINCIPAL_ID', '')

// Shared hub batch-subnet the multi-tenant pools live in; this env's storage
// allowlists it so those pools can reach its blobs. Empty for single-tenant prod.
param sharedBatchSubnetId = readEnvironmentVariable('HASTE_SHARED_BATCH_SUBNET_ID', '')
