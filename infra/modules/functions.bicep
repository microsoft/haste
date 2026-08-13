// The three HASTE Flex Consumption function apps (API, TiTiler, Queues),
// each built from functionApp.bicep with its own always-ready instance count
// (matching create_function_app's 10 / 5 / 1).

@description('Azure region.')
param location string

@description('API function app name.')
param functionApiName string

@description('TiTiler function app name.')
param functionTitilerName string

@description('Queue-triggers function app name.')
param functionQueueName string

@description('Functions storage account name.')
param storageAccountName string

@description('Premium file storage account name.')
param fileStorageAccountName string

@description('User-assigned managed identity resource id.')
param umiResourceId string

@description('VNet name.')
param vnetName string

@description('Functions subnet name.')
param functionsSubnetName string

@description('Log Analytics workspace resource id.')
param logAnalyticsId string

// --- hastegeo application config (api + queues; titiler needs none) ---------

@description('Batch account name the apps submit jobs to.')
param batchAccountName string

@description('Batch account location (for the batch service URL).')
param batchAccountLocation string

@description('GPU/imageryprep Batch pool id.')
param batchPoolName string

@description('ACR login server (e.g. myreg.azurecr.io). Empty when no ACR is wired.')
param acrLoginServer string

@description('Training container image (tag included).')
param trainingImage string

@description('Imageryprep container image (tag included).')
param imageryprepImage string

@description('Static Web App name (for the invitation/email flow).')
param staticWebAppName string

@description('Static Web App default hostname (for the invitation/email flow).')
param staticAppDomain string

@description('ACS sender domain (EMAIL_SENDER = DoNotReply@<domain>).')
param emailSenderDomain string

@description('ACS connection string for outbound email.')
@secure()
param emailConnectionString string

@description('Batch account primary key.')
@secure()
param batchAccountKey string

@description('Dev-only: auto-provision any authenticated user as admin and drop function-key auth (anonymous). Must be false for production.')
param developmentMode bool = false

// --- v2.1.0 capacity-aware routing + per-job SAS -----------------------------

@description('Ordered candidate training pool ids (comma-separated). Empty => single training pool.')
param trainingPoolIds string = ''

@description('Ordered candidate inference/embedding pool ids (comma-separated).')
param inferencePoolIds string = ''

@description('Ordered candidate imageryprep/artifacts pool ids (comma-separated).')
param imageryprepPoolIds string = ''

@description('Use per-job user-delegation SAS for Batch blob I/O (multi-tenant shared pools).')
param useSas bool = false

@description('Runner auto-creates/resizes its pool. False for pre-created autoscale pools.')
param managePools bool = true

// --- data publishing ---------------------------------------------------------

@description('Enable the Published Datasets section + Publish action (feature flag). On by default.')
param publishingEnabled bool = true

@description('Register/expose the Planetary Computer publishing provider.')
param pcProviderEnabled bool = false

@description('MPC Pro GeoCatalog base URL (no trailing slash). Operator-provisioned.')
param pcGeocatalogUrl string = ''

@description('GeoCatalog Explorer base URL used to build published-dataset links.')
param pcExplorerUrl string = ''

@description('GeoCatalog ingestion-source name for private HASTE containers (SasToken source). Empty for public containers.')
param pcIngestionSource string = ''

@description('STAC Collection id prefix (one collection per project/event).')
param pcCollectionPrefix string = 'haste-'

@description('STAC license id applied to published PC collections/items (e.g. CC-BY-4.0).')
param pcPublishingLicense string = 'CC-BY-4.0'

@description('Network-reachable storage account URL the GeoCatalog ingests published assets from. Empty = reference assets in place from the primary store.')
param publishStorageAccountUrl string = ''

@description('Blob container (on the publish storage account) that HASTE copies published PC assets into.')
param publishBlobContainer string = ''

@description('Resource tags.')
param tags object = {}

// Storage account (env RG) — used to derive the blob/queue URLs and the
// key-based BLOB_CONNECTION_STRING that hastegeo's utils/blob.py path requires.
resource storageAccount 'Microsoft.Storage/storageAccounts@2023-05-01' existing = {
  name: storageAccountName
}

// Application settings shared by the api and queues apps. hastegeo's Config()
// (instantiated at import time) reads these, so they must be present or the
// worker cannot index function_app.py. Storage/queue access is identity-based
// (BLOB_ACCOUNT_URL + role grants); only BLOB_CONNECTION_STRING, the Batch key,
// and the ACS string are key-based (per ADR: no Key Vault, deploy-time values).
var appConfigSettings = [
  { name: 'env', value: 'prod' }
  { name: 'DEVELOPMENT_MODE', value: developmentMode ? 'true' : 'false' }
  { name: 'IMAGE_QUEUE_NAME', value: 'image-layers-queue' }
  { name: 'INFERENCE_QUEUE_NAME', value: 'inference-queue' }
  { name: 'STATS_QUEUE_NAME', value: 'stats-queue' }
  { name: 'TRAIN_QUEUE_NAME', value: 'train-queue' }
  { name: 'ZIP_QUEUE_NAME', value: 'zip-queue' }
  { name: 'EMBEDDING_QUEUE_NAME', value: 'embedding-queue' }
  { name: 'PUBLISH_QUEUE_NAME', value: 'publish-queue' }
  { name: 'IMAGERY_STORAGE_TYPE', value: 'blob' }
  { name: 'METADATA_STORAGE_TYPE', value: 'blob' }
  { name: 'ARTIFACT_STORAGE_TYPE', value: 'blob' }
  { name: 'RUNNER_TYPE', value: 'azure_batch' }
  { name: 'TEMP_DATA_PATH', value: '/data' }
  { name: 'DATA_PATH', value: '/data' }
  { name: 'TITILER_ENDPOINT', value: '/api/titiler/' }
  { name: 'BLOB_CONTAINER', value: 'data' }
  { name: 'BLOB_ACCOUNT_URL', value: storageAccount.properties.primaryEndpoints.blob }
  { name: 'QUEUE_ACCOUNT_URL', value: storageAccount.properties.primaryEndpoints.queue }
  {
    name: 'BLOB_CONNECTION_STRING'
    value: 'DefaultEndpointsProtocol=https;AccountName=${storageAccountName};AccountKey=${storageAccount.listKeys().keys[0].value};EndpointSuffix=${environment().suffixes.storage}'
  }
  { name: 'AZURE_BATCH_ACCOUNT_NAME', value: batchAccountName }
  { name: 'AZURE_BATCH_URL', value: 'https://${batchAccountName}.${batchAccountLocation}.batch.azure.com' }
  { name: 'AZURE_BATCH_ACCOUNT_KEY', value: batchAccountKey }
  { name: 'AZURE_BATCH_DOCKER_IMAGE', value: '${acrLoginServer}/${trainingImage}' }
  { name: 'AZURE_BATCH_IMAGERYPREP_DOCKER_IMAGE', value: '${acrLoginServer}/${imageryprepImage}' }
  { name: 'AZURE_BATCH_OUTPUT_CONTAINER_URL', value: '${storageAccount.properties.primaryEndpoints.blob}data' }
  { name: 'AZURE_BATCH_TRAINING_POOL_ID', value: batchPoolName }
  { name: 'AZURE_BATCH_IMAGERYPREP_POOL_ID', value: batchPoolName }
  { name: 'AZURE_BATCH_REGISTRY_SERVER', value: acrLoginServer }
  { name: 'AZURE_BATCH_REGISTRY_IMAGE', value: '${acrLoginServer}/${trainingImage}' }
  { name: 'AZURE_BATCH_REGISTRY_IDENTITY_RESOURCE_ID', value: umiResourceId }
  { name: 'STATIC_APP_SUBSCRIPTION_ID', value: subscription().subscriptionId }
  { name: 'STATIC_APP_RESOURCE_GROUP', value: resourceGroup().name }
  { name: 'STATIC_APP_NAME', value: staticWebAppName }
  { name: 'STATIC_APP_DOMAIN', value: staticAppDomain }
  { name: 'EMAIL_CONNECTION_STRING', value: emailConnectionString }
  { name: 'EMAIL_SENDER', value: 'DoNotReply@${emailSenderDomain}' }
  // v2.1.0: capacity-aware routing candidate lists + per-job SAS toggle. Empty
  // lists / false flags = legacy single-pool, pool-identity behavior.
  { name: 'AZURE_BATCH_TRAINING_POOL_IDS', value: trainingPoolIds }
  { name: 'AZURE_BATCH_INFERENCE_POOL_IDS', value: inferencePoolIds }
  { name: 'AZURE_BATCH_IMAGERYPREP_POOL_IDS', value: imageryprepPoolIds }
  { name: 'AZURE_BATCH_USE_SAS', value: useSas ? 'true' : 'false' }
  { name: 'AZURE_BATCH_MANAGE_POOLS', value: managePools ? 'true' : 'false' }
  // Data publishing feature flag (Local target). The queue + publishing-locks
  // container are auto-created at runtime. Other Local knobs
  // (PUBLISH_MAX_TOTAL_BYTES, PUBLISHED_DOWNLOAD_SAS_MINUTES,
  // PUBLISHING_LOCK_CONTAINER) use code defaults.
  { name: 'PUBLISHING_ENABLED', value: publishingEnabled ? 'true' : 'false' }
  // Planetary Computer target. Auth is managed-identity only (Entra token,
  // scope https://geocatalog.spatio.azure.com/.default); the api-version and
  // token scope are code constants, not settings. PC_INGESTION_SOURCE is only
  // needed for private HASTE containers (SasToken ingestion source).
  { name: 'PC_PROVIDER_ENABLED', value: pcProviderEnabled ? 'true' : 'false' }
  { name: 'PC_GEOCATALOG_URL', value: pcGeocatalogUrl }
  { name: 'PC_EXPLORER_URL', value: pcExplorerUrl }
  { name: 'PC_INGESTION_SOURCE', value: pcIngestionSource }
  { name: 'PC_COLLECTION_PREFIX', value: pcCollectionPrefix }
  { name: 'PC_PUBLISHING_LICENSE', value: pcPublishingLicense }
  { name: 'PUBLISH_STORAGE_ACCOUNT_URL', value: publishStorageAccountUrl }
  { name: 'PUBLISH_BLOB_CONTAINER', value: publishBlobContainer }
]

module apiApp 'functionApp.bicep' = {
  name: 'fn-api'
  params: {
    location: location
    name: functionApiName
    planName: '${functionApiName}-plan'
    alwaysReadyCount: 10
    storageAccountName: storageAccountName
    fileStorageAccountName: fileStorageAccountName
    umiResourceId: umiResourceId
    vnetName: vnetName
    functionsSubnetName: functionsSubnetName
    logAnalyticsId: logAnalyticsId
    // Unique host id per app so the publishing reconciler TimerTrigger's
    // host-scoped Singleton lock doesn't collide across apps sharing storage.
    appSettings: concat(appConfigSettings, [
      {
        name: 'AzureFunctionsWebHost__hostId'
        value: toLower(substring(functionApiName, 0, min(32, length(functionApiName))))
      }
    ])
    tags: tags
  }
}

module titilerApp 'functionApp.bicep' = {
  name: 'fn-titiler'
  params: {
    location: location
    name: functionTitilerName
    planName: '${functionTitilerName}-plan'
    alwaysReadyCount: 5
    storageAccountName: storageAccountName
    fileStorageAccountName: fileStorageAccountName
    umiResourceId: umiResourceId
    vnetName: vnetName
    functionsSubnetName: functionsSubnetName
    logAnalyticsId: logAnalyticsId
    tags: tags
  }
  // All three apps integrate with the same func-subnet. A subnet's
  // ServiceAssociationLink lease is single-writer, so the integrations must be
  // serialized — otherwise concurrent deployments fail with a SAL lease conflict.
  dependsOn: [
    apiApp
  ]
}

module queueApp 'functionApp.bicep' = {
  name: 'fn-queue'
  params: {
    location: location
    name: functionQueueName
    planName: '${functionQueueName}-plan'
    alwaysReadyCount: 1
    storageAccountName: storageAccountName
    fileStorageAccountName: fileStorageAccountName
    umiResourceId: umiResourceId
    vnetName: vnetName
    functionsSubnetName: functionsSubnetName
    logAnalyticsId: logAnalyticsId
    appSettings: concat(appConfigSettings, [
      {
        name: 'AzureFunctionsWebHost__hostId'
        value: toLower(substring(functionQueueName, 0, min(32, length(functionQueueName))))
      }
    ])
    tags: tags
  }
  dependsOn: [
    titilerApp
  ]
}

// Used by roles.bicep to grant the SWA invitation role to the API app's
// system-assigned identity.
output apiSystemPrincipalId string = apiApp.outputs.systemPrincipalId
output apiName string = apiApp.outputs.name
output titilerName string = titilerApp.outputs.name
output queueName string = queueApp.outputs.name
