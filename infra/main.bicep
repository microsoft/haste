// HASTE infrastructure — subscription-scoped entry point.
// Reproduces the resources created by setup/setup_infra.sh as declarative
// Bicep, orchestrated by azd. See spec/features/infra-iac-migration/.

targetScope = 'subscription'

// ---------------------------------------------------------------------------
// Core parameters (replace the positional CLI args of setup_infra.sh)
// ---------------------------------------------------------------------------

@description('Short prefix used to build every resource name (e.g. "haste").')
param resourcePrefix string

@description('Azure region for the environment resource group and resources.')
param location string

@description('4-digit suffix that disambiguates parallel environments.')
@minLength(1)
param randomSuffix string

@description('Tags applied to the resource group and resources.')
param tags object = {
  project: 'haste'
}

// ---------------------------------------------------------------------------
// Shared / bring-your-own resources
// ---------------------------------------------------------------------------

@description('Resource group holding BYO shared resources (Batch, ACR). Empty => env RG.')
param sharedResourceGroup string = ''

@description('Name of an existing ACR to pull training/imageryprep images from. Empty => no ACR wiring.')
param sharedAcrName string = ''

@description('APIM publisher email.')
param apimPublisherEmail string

@description('APIM publisher organisation name.')
param apimPublisherName string = 'AI For Good Lab'

// ---------------------------------------------------------------------------
// Batch (dual create-vs-BYO)
// ---------------------------------------------------------------------------

@description('Create a new Batch account in the env RG, or reference an existing shared one.')
@allowed([
  'Create'
  'Existing'
])
param batchAccountMode string = 'Create'

@description('Existing Batch account name (required when batchAccountMode == Existing).')
param existingBatchAccountName string = ''

@description('Create the GPU pool, or reference an existing one for app-settings wiring only.')
@allowed([
  'Create'
  'Existing'
])
param batchPoolMode string = 'Create'

@description('Existing Batch pool id (required when batchPoolMode == Existing).')
param existingBatchPoolId string = ''

@description('VM size for the GPU pool.')
param batchPoolVmSize string = 'STANDARD_NC40ads_H100_v5'

@description('Max dedicated nodes for the autoscale formula.')
param batchPoolMaxNodes int = 3

@description('Subnet name (in the env VNet) used by the Batch pool.')
param batchPoolSubnetName string = 'batch-subnet'

@description('Shared hub batch-subnet resource id where the SHARED multi-tenant pools are VNet-injected. Set for shared-pool envs (dev/demo) so this env storage allowlists that subnet; empty for single-tenant prod. See spec/features/batch-compute-expansion/networking.md.')
param sharedBatchSubnetId string = ''

@description('Training container image (tag included).')
param trainingImage string = 'hastetraining:1.4.1'

@description('Imageryprep container image (tag included).')
param imageryprepImage string = 'hasteimageryprep:1.4.1'

// ---------------------------------------------------------------------------
// Email (ACS) sender domain
// ---------------------------------------------------------------------------

@description('Sender-domain mode for the email backend.')
@allowed([
  'AzureManaged'
  'Custom'
])
param emailSenderDomainType string = 'AzureManaged'

@description('Custom sender domain (required when emailSenderDomainType == Custom).')
param emailCustomDomain string = ''

// ---------------------------------------------------------------------------
// Front Door (feature-flagged, default off — preserves EnableFrontDoor=false)
// ---------------------------------------------------------------------------

@description('Provision Front Door + WAF in front of the Static Web App.')
param enableFrontDoor bool = false

@description('Dev-only: api/queues auto-provision any authenticated user as admin and use anonymous auth. Keep false for production.')
param developmentMode bool = false

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

@description('Enable the data publishing feature (Published Datasets section + Publish action). On by default.')
param publishingEnabled bool = true

@description('Register/expose the Planetary Computer publishing provider.')
param pcProviderEnabled bool = false

@description('MPC Pro GeoCatalog base URL (no trailing slash). Operator-provisioned.')
param pcGeocatalogUrl string = ''

@description('GeoCatalog Explorer base URL used to build published-dataset links.')
param pcExplorerUrl string = ''

@description('GeoCatalog ingestion-source name for private HASTE containers. Empty for public containers.')
param pcIngestionSource string = ''

@description('STAC Collection id prefix (one collection per project/event).')
param pcCollectionPrefix string = 'haste-'

@description('STAC license id applied to published PC collections/items (e.g. CC-BY-4.0).')
param pcPublishingLicense string = 'CC-BY-4.0'

@description('Network-reachable storage account URL the GeoCatalog ingests published assets from. Empty = reference assets in place from the primary store.')
param publishStorageAccountUrl string = ''

@description('Blob container (on the publish storage account) that HASTE copies published PC assets into.')
param publishBlobContainer string = ''

@description('Object id of the GeoCatalog managed identity to grant Storage Blob Data Reader on HASTE storage (asset ingestion). Empty = skip.')
param pcGeoCatalogIngestPrincipalId string = ''

// ---------------------------------------------------------------------------
// Computed names — mirror the bash naming scheme exactly.
// ---------------------------------------------------------------------------

var rgName = '${resourcePrefix}-haste-${randomSuffix}-rg'
var storageAccountName = '${resourcePrefix}haste${randomSuffix}sa'
var fileStorageAccountName = '${resourcePrefix}haste${randomSuffix}fs'
var umiName = '${resourcePrefix}-haste-${randomSuffix}-umi'
var vnetName = '${resourcePrefix}-haste-${randomSuffix}-vnet'
var nsgName = '${resourcePrefix}-haste-${randomSuffix}-nsg'
var apimName = '${resourcePrefix}-haste-${randomSuffix}-apim'
var functionApiName = '${resourcePrefix}haste${randomSuffix}func'
var functionTitilerName = '${resourcePrefix}hastetitiler${randomSuffix}func'
var functionQueueName = '${resourcePrefix}hastequeue${randomSuffix}func'
var staticWebAppName = '${resourcePrefix}haste${randomSuffix}swa'
var logAnalyticsName = '${resourcePrefix}-haste-${randomSuffix}-law'
var mapsAccountName = '${resourcePrefix}haste${randomSuffix}maps'
var wafPolicyName = '${resourcePrefix}haste${randomSuffix}waf'
var frontDoorName = '${resourcePrefix}haste${randomSuffix}fd'
var acsName = '${resourcePrefix}-haste-${randomSuffix}-acs'
var emailServiceName = '${resourcePrefix}-haste-${randomSuffix}-email'

var functionsSubnetName = 'func-subnet'

// Batch account resolution.
var createBatchAccount = batchAccountMode == 'Create'
var resolvedSharedRg = empty(sharedResourceGroup) ? rgName : sharedResourceGroup
var createdBatchAccountName = '${resourcePrefix}haste${randomSuffix}batch'
var resolvedBatchAccountName = createBatchAccount ? createdBatchAccountName : existingBatchAccountName
var batchAccountRg = createBatchAccount ? rgName : resolvedSharedRg
var createdBatchPoolName = '${resourcePrefix}-haste-${randomSuffix}-pool'

// AcrPull lives in the shared RG when an external ACR is referenced.
var wireAcr = !empty(sharedAcrName)

// ---------------------------------------------------------------------------
// Resource group
// ---------------------------------------------------------------------------

resource rg 'Microsoft.Resources/resourceGroups@2024-03-01' = {
  name: rgName
  location: location
  tags: tags
}

// ---------------------------------------------------------------------------
// Modules (env RG scope)
// ---------------------------------------------------------------------------

module monitoring 'modules/monitoring.bicep' = {
  name: 'monitoring'
  scope: rg
  params: {
    location: location
    logAnalyticsName: logAnalyticsName
    tags: tags
  }
}

module identity 'modules/identity.bicep' = {
  name: 'identity'
  scope: rg
  params: {
    location: location
    umiName: umiName
    tags: tags
  }
}

module network 'modules/network.bicep' = {
  name: 'network'
  scope: rg
  params: {
    location: location
    vnetName: vnetName
    nsgName: nsgName
    functionsSubnetName: functionsSubnetName
    batchSubnetName: batchPoolSubnetName
    tags: tags
  }
}

module storage 'modules/storage.bicep' = {
  name: 'storage'
  scope: rg
  params: {
    location: location
    storageAccountName: storageAccountName
    fileStorageAccountName: fileStorageAccountName
    umiPrincipalId: identity.outputs.principalId
    vnetName: vnetName
    defaultSubnetName: 'default'
    functionsSubnetName: functionsSubnetName
    batchSubnetName: batchPoolSubnetName
    sharedBatchSubnetId: sharedBatchSubnetId
    tags: tags
  }
  dependsOn: [
    network
  ]
}

module communication 'modules/communication.bicep' = {
  name: 'communication'
  scope: rg
  params: {
    acsName: acsName
    emailServiceName: emailServiceName
    emailSenderDomainType: emailSenderDomainType
    emailCustomDomain: emailCustomDomain
    tags: tags
  }
}

module apim 'modules/apim.bicep' = {
  name: 'apim'
  scope: rg
  params: {
    location: location
    apimName: apimName
    publisherEmail: apimPublisherEmail
    publisherName: apimPublisherName
    umiResourceId: identity.outputs.resourceId
    vnetName: vnetName
    defaultSubnetName: 'default'
    storageAccountName: storageAccountName
    tags: tags
  }
  dependsOn: [
    network
    storage
  ]
}

// Existing reference to the resolved Batch account (env RG for Create, shared RG
// for Existing) — used to read the primary key for the api/queues app settings.
resource batchAccountRef 'Microsoft.Batch/batchAccounts@2024-07-01' existing = {
  name: resolvedBatchAccountName
  scope: resourceGroup(batchAccountRg)
}

module functions 'modules/functions.bicep' = {
  name: 'functions'
  scope: rg
  params: {
    location: location
    functionApiName: functionApiName
    functionTitilerName: functionTitilerName
    functionQueueName: functionQueueName
    storageAccountName: storageAccountName
    fileStorageAccountName: fileStorageAccountName
    umiResourceId: identity.outputs.resourceId
    vnetName: vnetName
    functionsSubnetName: functionsSubnetName
    logAnalyticsId: monitoring.outputs.logAnalyticsId
    // hastegeo application config (api + queues; titiler needs none).
    batchAccountName: resolvedBatchAccountName
    batchAccountLocation: location
    batchPoolName: batchPoolMode == 'Create' ? createdBatchPoolName : existingBatchPoolId
    acrLoginServer: wireAcr ? '${sharedAcrName}.azurecr.io' : ''
    trainingImage: trainingImage
    imageryprepImage: imageryprepImage
    staticWebAppName: staticWebAppName
    staticAppDomain: frontend.outputs.staticWebAppHostName
    emailSenderDomain: communication.outputs.senderDomain
    emailConnectionString: communication.outputs.connectionString
    batchAccountKey: batchAccountRef.listKeys().primary
    developmentMode: developmentMode
    trainingPoolIds: trainingPoolIds
    inferencePoolIds: inferencePoolIds
    imageryprepPoolIds: imageryprepPoolIds
    useSas: useSas
    managePools: managePools
    publishingEnabled: publishingEnabled
    pcProviderEnabled: pcProviderEnabled
    pcGeocatalogUrl: pcGeocatalogUrl
    pcExplorerUrl: pcExplorerUrl
    pcIngestionSource: pcIngestionSource
    pcCollectionPrefix: pcCollectionPrefix
    pcPublishingLicense: pcPublishingLicense
    publishStorageAccountUrl: publishStorageAccountUrl
    publishBlobContainer: publishBlobContainer
    tags: tags
  }
  dependsOn: [
    storage
    network
    batchAccount
  ]
}

module frontend 'modules/frontend.bicep' = {
  name: 'frontend'
  scope: rg
  params: {
    location: location
    staticWebAppName: staticWebAppName
    mapsAccountName: mapsAccountName
    apimResourceId: apim.outputs.resourceId
    tags: tags
  }
}

// APIM base APIs + backends + product links + hardcoded ops. Needs the SWA's
// linked-backend product (frontend, via staticWebAppHostName) and the function
// apps (functions, for backend URLs + host keys). Per-endpoint operations are
// added by the postdeploy hook (hooks/sync-apim-operations.ps1).
module apimApis 'modules/apimApis.bicep' = {
  name: 'apimApis'
  scope: rg
  params: {
    apimName: apimName
    functionApiName: functionApiName
    functionTitilerName: functionTitilerName
    staticWebAppHostName: frontend.outputs.staticWebAppHostName
    storageAccountName: storageAccountName
  }
  // apim is ordered transitively (apimApis -> frontend -> apim). functions has no
  // implicit edge (backends reference the apps by name / listKeys), so keep it.
  dependsOn: [
    functions
  ]
}

// Custom SWA invitation role assigned to the API app's system-assigned identity.
module roles 'modules/roles.bicep' = {
  name: 'roles'
  scope: rg
  params: {
    staticWebAppName: staticWebAppName
    mapsAccountName: mapsAccountName
    functionSystemPrincipalId: functions.outputs.apiSystemPrincipalId
    storageAccountName: storageAccountName
    pcGeoCatalogIngestPrincipalId: pcGeoCatalogIngestPrincipalId
  }
  // frontend is ordered before roles transitively (roles -> functions ->
  // frontend, since functions reads the SWA hostname for STATIC_APP_DOMAIN).
}

// Batch account (Create mode only) in the env RG.
module batchAccount 'modules/batch.bicep' = if (createBatchAccount) {
  name: 'batchAccount'
  scope: rg
  params: {
    location: location
    batchAccountName: createdBatchAccountName
    tags: tags
  }
}

// Batch pool (Create mode) — deployed into the resolved account's RG.
// When the account is shared/Existing in another RG, this is a cross-RG,
// additive-only deployment (creates only the named pool).
module batchPool 'modules/batchPool.bicep' = if (batchPoolMode == 'Create') {
  name: 'batchPool'
  scope: resourceGroup(batchAccountRg)
  params: {
    batchAccountName: resolvedBatchAccountName
    poolName: createdBatchPoolName
    vmSize: batchPoolVmSize
    maxNodes: batchPoolMaxNodes
    umiResourceId: identity.outputs.resourceId
    subnetId: resourceId(
      subscription().subscriptionId,
      rgName,
      'Microsoft.Network/virtualNetworks/subnets',
      vnetName,
      batchPoolSubnetName
    )
    acrName: sharedAcrName
    trainingImage: trainingImage
    imageryprepImage: imageryprepImage
  }
  dependsOn: [
    network
    batchAccount
  ]
}

// AcrPull for the env UMI on a shared ACR (cross-RG when the ACR is shared).
module acrRole 'modules/acrRole.bicep' = if (wireAcr) {
  name: 'acrRole'
  scope: resourceGroup(resolvedSharedRg)
  params: {
    acrName: sharedAcrName
    umiPrincipalId: identity.outputs.principalId
  }
}

// Front Door + WAF (feature-flagged).
module frontDoor 'modules/frontdoor.bicep' = if (enableFrontDoor) {
  name: 'frontDoor'
  scope: rg
  params: {
    frontDoorName: frontDoorName
    wafPolicyName: wafPolicyName
    staticWebAppName: staticWebAppName
  }
  dependsOn: [
    frontend
  ]
}

// ---------------------------------------------------------------------------
// Outputs consumed by azd service targets and the postprovision/postdeploy hooks.
// ---------------------------------------------------------------------------

output AZURE_RESOURCE_GROUP string = rgName
output AZURE_LOCATION string = location
output FUNCTION_API_NAME string = functionApiName
output FUNCTION_TITILER_NAME string = functionTitilerName
output FUNCTION_QUEUE_NAME string = functionQueueName
output STATIC_WEB_APP_NAME string = staticWebAppName
// Consumed by the `web` service prebuild hook to embed VITE_AZURE_MAPS_CLIENT_ID
// in the SWA build (see azure.yaml / ui/.env.production).
output VITE_AZURE_MAPS_CLIENT_ID string = frontend.outputs.mapsClientId
output APIM_NAME string = apimName
output STORAGE_ACCOUNT_NAME string = storageAccountName
output BATCH_ACCOUNT_NAME string = resolvedBatchAccountName
output BATCH_POOL_NAME string = batchPoolMode == 'Create' ? createdBatchPoolName : existingBatchPoolId
@secure()
output ACS_CONNECTION_STRING string = communication.outputs.connectionString
output EMAIL_SENDER_DOMAIN string = communication.outputs.senderDomain
