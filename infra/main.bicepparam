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
