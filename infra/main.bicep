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
// Backend-neutral compute routing (hastegeo.core.config.get_compute_config) —
// see spec/features/aml-compute-backend/ and ADR-0005. Backward-compatible
// default: unset/`azure_batch` reproduces today's Batch-only behavior exactly.
// `RUNNER_TYPE` (below, in functions.bicep) remains the deprecated fallback
// alias the code still reads when COMPUTE_BACKEND_DEFAULT is unset.
// ---------------------------------------------------------------------------

@description('Global fallback compute backend read by hastegeo.core.config.get_compute_config(). Backward-compatible default keeps existing Batch-only behavior; RUNNER_TYPE remains a supported legacy alias when this is unset.')
@allowed([
  'local'
  'azure_batch'
  'azure_ml'
  'auto'
])
param computeBackendDefault string = 'azure_batch'

// ---------------------------------------------------------------------------
// Azure Machine Learning (Disabled/Existing/Create). `amlMode == 'Existing'`
// is HASTE's default/first enablement path: it wires pre-existing,
// platform-owned identifiers supplied by the operator straight into Function
// App settings and creates/mutates NOTHING under
// Microsoft.MachineLearningServices — no workspace, compute, environment,
// datastore, or AML role assignment. `amlMode == 'Create'` is an explicit,
// later opt-in for environments that want HASTE to own its own AML
// workspace/compute/environment/datastore stack (mirroring the Batch
// Create/Existing convention); it is never implied by 'Existing' and is not
// the default. Every Create-mode resource module below is gated exclusively
// on `createAmlWorkspace` (== amlMode == 'Create') — never on `deployAml`
// (which also covers 'Existing') — so 'Existing' can never trigger resource
// creation even by accident.
// ---------------------------------------------------------------------------

@description('AML resource ownership mode. Disabled = no AML app settings emitted. Existing (the default enablement path) = wire pre-existing, platform-owned identifiers into Function App settings; HASTE creates/mutates nothing. Create (explicit, later opt-in) = HASTE also provisions its own workspace, compute clusters, environment versions, and datastore registration.')
@allowed([
  'Disabled'
  'Existing'
  'Create'
])
param amlMode string = 'Disabled'

@description('Name of the existing AML workspace to reference when amlMode == Existing. Ignored when amlMode == Create (HASTE computes its own workspace name then). HASTE never creates, modifies, or manages this workspace in Existing mode.')
param existingAmlWorkspaceName string = ''

@description('Resource group holding the existing AML workspace (amlMode == Existing) or where HASTE creates one (amlMode == Create, always the env RG regardless of this value — mirrors batchAccountMode == Create always using the env RG). Empty => env RG.')
param amlWorkspaceResourceGroup string = ''

@description('Name of the existing AML GPU compute cluster (training/inference/embedding) when amlMode == Existing, already provisioned and owned by the existing AML platform. Ignored when amlMode == Create (HASTE computes and creates its own cluster name then). Empty when amlMode == Disabled.')
param existingAmlGpuComputeName string = ''

@description('Name of the existing AML CPU compute cluster (imagery prep/artifact packaging) when amlMode == Existing, already provisioned and owned by the existing AML platform. Ignored when amlMode == Create. Empty when amlMode == Disabled.')
param existingAmlCpuComputeName string = ''

@description('Name of the existing AML datastore when amlMode == Existing, already registered by the existing AML platform. Ignored when amlMode == Create (HASTE registers its own datastore then). Empty when amlMode == Disabled.')
param existingAmlDatastoreName string = ''

@description('Fully-qualified reference (azureml:<name>:<version>) of the existing, already-registered immutable AML environment version for the training image, when amlMode == Existing. Ignored when amlMode == Create (HASTE registers its own environment version then).')
param existingAmlTrainingEnvironmentReference string = ''

@description('Fully-qualified reference (azureml:<name>:<version>) of the existing, already-registered immutable AML environment version for the imageryprep image, when amlMode == Existing. Ignored when amlMode == Create.')
param existingAmlImageryprepEnvironmentReference string = ''

@description('VM size for the AML GPU compute cluster HASTE creates when amlMode == Create. Mirrors the Batch GPU pool tier. Unused when amlMode != Create.')
param amlGpuComputeVmSize string = 'Standard_NC40ads_H100_v5'

@description('Max nodes for the AML GPU compute cluster autoscale when amlMode == Create (min is always 0 — scale-to-zero). Unused when amlMode != Create.')
param amlGpuComputeMaxNodes int = 3

@description('VM size for the AML CPU compute cluster HASTE creates when amlMode == Create (imagery prep/artifact packaging). Unused when amlMode != Create.')
param amlCpuComputeVmSize string = 'Standard_D4s_v5'

@description('Max nodes for the AML CPU compute cluster autoscale when amlMode == Create (min is always 0 — scale-to-zero). Unused when amlMode != Create.')
param amlCpuComputeMaxNodes int = 3

@description('Idle time (ISO 8601 duration) before an AML compute node scales back to zero. Only applies to clusters HASTE creates (amlMode == Create).')
param amlComputeIdleTime string = 'PT30M'

@description('VNet subnet resource id for VNet-injected AML compute HASTE creates (amlMode == Create only, both GPU and CPU clusters). Empty preserves public-compute behavior (no VNet injection) — see design.md Open Questions on AML tenant/network placement, which is not yet resolved.')
param amlComputeSubnetId string = ''

@description('Immutable AML environment version HASTE registers for the training image when amlMode == Create. Defaults to the image tag so bumping the tag registers a new version rather than mutating one. Unused when amlMode != Create.')
param amlTrainingEnvironmentVersion string = split(trainingImage, ':')[1]

@description('Immutable AML environment version HASTE registers for the imageryprep image when amlMode == Create. Defaults to the image tag. Unused when amlMode != Create.')
param amlImageryprepEnvironmentVersion string = split(imageryprepImage, ':')[1]

@description('Default job-execution identity mode surfaced to the AML adapter as AML_IDENTITY_MODE: "user" submits AML jobs using the calling principal (hastefuncqueues) own identity — the security default, since that identity already holds the storage RBAC granted in storage.bicep/functionApp.bicep, needing no additional AML-specific grant. "managed" submits jobs using a specific user-assigned managed identity instead (see amlManagedIdentityResourceId). In Existing mode, granting that identity access on the existing AML platform (workspace RBAC, datastore/storage access, ACR pull) is a prerequisite owned by that platform — this IaC only emits the setting, it does not grant any AML permission. In Create mode, the equivalent HASTE-managed grant is amlRole.bicep (queue app only).')
@allowed([
  'user'
  'managed'
])
param amlIdentityMode string = 'user'

@description('User-assigned managed identity resource id to submit AML jobs as when amlIdentityMode == "managed". Empty (with amlIdentityMode == "managed") defaults to the shared env UMI. Ignored when amlIdentityMode == "user". In Existing mode, the existing AML platform must already grant this identity whatever access it needs — this parameter only names it, it grants nothing there.')
param amlManagedIdentityResourceId string = ''

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

@description('Render a damage classification COG + Explorer visualization config on PC publish.')
param publishExplorerRenderEnabled bool = true

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

@description('Organization operating this deployment, recorded as the STAC "processor" provider on published datasets. Empty = omit.')
param publishingOrganizationName string = ''

@description('URL for the publishing organization (optional companion to publishingOrganizationName).')
param publishingOrganizationUrl string = ''

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

// AML resolution — mirrors the Batch account Create/Existing resolution
// above. amlMode == 'Disabled' means no AML app settings are emitted at all
// (guarded by deployAml). `createAmlWorkspace` (amlMode == 'Create') is the
// ONLY condition that gates AML resource-module deployment below — the
// default/first-enabled 'Existing' path resolves purely to the operator-
// supplied existingAml* parameter values, with zero HASTE-managed resource.
var deployAml = amlMode != 'Disabled'
var createAmlWorkspace = amlMode == 'Create'
// Mirrors batchAccountRg: Create mode always uses the env RG; Existing mode
// resolves against the operator-supplied amlWorkspaceResourceGroup (empty
// => env RG).
var resolvedAmlWorkspaceRg = createAmlWorkspace ? rgName : (empty(amlWorkspaceResourceGroup) ? rgName : amlWorkspaceResourceGroup)
var createdAmlWorkspaceName = '${resourcePrefix}-haste-${randomSuffix}-aml'
// AML compute cluster names are capped at 24 characters by the service —
// kept compact (no repeated "haste" literal) unlike the friendlier
// hyphenated names above. Only used when createAmlWorkspace (Create mode
// creates and names its own clusters); Existing mode uses the operator-
// supplied existingAmlGpuComputeName/existingAmlCpuComputeName instead.
var amlGpuComputeName = '${resourcePrefix}${randomSuffix}gpu'
var amlCpuComputeName = '${resourcePrefix}${randomSuffix}cpu'
var amlDatastoreName = 'hastedata'
// Deterministic (name, version) so the fully-qualified reference is knowable
// without depending on the amlEnvironment module's output — same
// environment names used in the amlEnvironment module calls below. Only
// used when createAmlWorkspace; Existing mode uses the operator-supplied
// existingAmlTrainingEnvironmentReference/existingAmlImageryprepEnvironmentReference.
var amlTrainingEnvironmentReference = 'azureml:training:${amlTrainingEnvironmentVersion}'
var amlImageryprepEnvironmentReference = 'azureml:imageryprep:${amlImageryprepEnvironmentVersion}'
// AML workspace's own dependent resources (bookkeeping only — never hold a
// HASTE secret or the HASTE datastore itself; see amlWorkspace.bicep). Only
// created when createAmlWorkspace.
var amlStorageAccountName = '${resourcePrefix}haste${randomSuffix}amlsa'
var amlKeyVaultName = '${resourcePrefix}-haste-${randomSuffix}-aml-kv'
var amlAppInsightsName = '${resourcePrefix}-haste-${randomSuffix}-aml-ai'
// Final values passed to functions.bicep: Create mode uses the HASTE-created
// names/references above; Existing mode uses the operator-supplied
// existingAml* parameters directly; Disabled resolves to empty (guarded by
// deployAml at the call site).
var resolvedAmlWorkspaceName = createAmlWorkspace ? createdAmlWorkspaceName : existingAmlWorkspaceName
var resolvedAmlGpuComputeName = createAmlWorkspace ? amlGpuComputeName : existingAmlGpuComputeName
var resolvedAmlCpuComputeName = createAmlWorkspace ? amlCpuComputeName : existingAmlCpuComputeName
var resolvedAmlDatastoreName = createAmlWorkspace ? amlDatastoreName : existingAmlDatastoreName
var resolvedAmlTrainingEnvironmentReference = createAmlWorkspace ? amlTrainingEnvironmentReference : existingAmlTrainingEnvironmentReference
var resolvedAmlImageryprepEnvironmentReference = createAmlWorkspace ? amlImageryprepEnvironmentReference : existingAmlImageryprepEnvironmentReference
// Resolved job-submission identity for AML jobs (AML_MANAGED_IDENTITY_ID
// app setting): only meaningful/populated when amlIdentityMode == 'managed'.
// Defaults to the shared env UMI when the operator doesn't supply a
// different one. Empty in 'user' mode or when AML is Disabled. Naming this
// identity does not grant it anything by itself in Existing mode — any
// access it needs on the existing AML platform is a prerequisite owned by
// that platform (Create mode grants it via amlRole.bicep instead).
var resolvedAmlManagedIdentityResourceId = (deployAml && amlIdentityMode == 'managed')
  ? (empty(amlManagedIdentityResourceId) ? identity.outputs.resourceId : amlManagedIdentityResourceId)
  : ''

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
    computeBackendDefault: computeBackendDefault
    trainingPoolIds: trainingPoolIds
    inferencePoolIds: inferencePoolIds
    imageryprepPoolIds: imageryprepPoolIds
    useSas: useSas
    managePools: managePools
    publishingEnabled: publishingEnabled
    pcProviderEnabled: pcProviderEnabled
    publishExplorerRenderEnabled: publishExplorerRenderEnabled
    pcGeocatalogUrl: pcGeocatalogUrl
    pcExplorerUrl: pcExplorerUrl
    pcIngestionSource: pcIngestionSource
    pcCollectionPrefix: pcCollectionPrefix
    pcPublishingLicense: pcPublishingLicense
    publishingOrganizationName: publishingOrganizationName
    publishingOrganizationUrl: publishingOrganizationUrl
    publishStorageAccountUrl: publishStorageAccountUrl
    publishBlobContainer: publishBlobContainer
    amlMode: amlMode
    amlWorkspaceName: deployAml ? resolvedAmlWorkspaceName : ''
    amlResourceGroup: deployAml ? resolvedAmlWorkspaceRg : ''
    amlDatastoreName: deployAml ? resolvedAmlDatastoreName : ''
    amlGpuComputeName: deployAml ? resolvedAmlGpuComputeName : ''
    amlCpuComputeName: deployAml ? resolvedAmlCpuComputeName : ''
    amlTrainingEnvironmentReference: deployAml ? resolvedAmlTrainingEnvironmentReference : ''
    amlImageryprepEnvironmentReference: deployAml ? resolvedAmlImageryprepEnvironmentReference : ''
    amlIdentityMode: amlIdentityMode
    amlManagedIdentityId: resolvedAmlManagedIdentityResourceId
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

// ---------------------------------------------------------------------------
// Azure Machine Learning — Create mode ONLY (explicit, later opt-in; not the
// default and not implied by 'Existing'). Every module below is gated
// exclusively on `createAmlWorkspace` (== amlMode == 'Create'), never on
// `deployAml` — 'Existing' (the default enablement path) never reaches any
// module in this section and creates/mutates nothing under
// Microsoft.MachineLearningServices. See ADR-0005.
// ---------------------------------------------------------------------------

// AML workspace — Create mode only, in the env RG.
module amlWorkspace 'modules/amlWorkspace.bicep' = if (createAmlWorkspace) {
  name: 'amlWorkspace'
  scope: rg
  params: {
    location: location
    workspaceName: createdAmlWorkspaceName
    storageAccountName: amlStorageAccountName
    keyVaultName: amlKeyVaultName
    appInsightsName: amlAppInsightsName
    logAnalyticsId: monitoring.outputs.logAnalyticsId
    umiResourceId: identity.outputs.resourceId
    tags: tags
  }
}

// GPU compute cluster (training/inference/embedding) — Create mode only,
// deployed into the resolved workspace's RG.
module amlGpuCompute 'modules/amlCompute.bicep' = if (createAmlWorkspace) {
  name: 'amlGpuCompute'
  scope: resourceGroup(resolvedAmlWorkspaceRg)
  params: {
    workspaceName: createdAmlWorkspaceName
    location: location
    computeName: amlGpuComputeName
    vmSize: amlGpuComputeVmSize
    maxNodes: amlGpuComputeMaxNodes
    scaleDownIdleTime: amlComputeIdleTime
    umiResourceId: identity.outputs.resourceId
    subnetId: amlComputeSubnetId
  }
  dependsOn: [
    amlWorkspace
  ]
}

// CPU compute cluster (imagery prep/artifact packaging) — Create mode only.
module amlCpuCompute 'modules/amlCompute.bicep' = if (createAmlWorkspace) {
  name: 'amlCpuCompute'
  scope: resourceGroup(resolvedAmlWorkspaceRg)
  params: {
    workspaceName: createdAmlWorkspaceName
    location: location
    computeName: amlCpuComputeName
    vmSize: amlCpuComputeVmSize
    maxNodes: amlCpuComputeMaxNodes
    scaleDownIdleTime: amlComputeIdleTime
    umiResourceId: identity.outputs.resourceId
    subnetId: amlComputeSubnetId
  }
  dependsOn: [
    amlWorkspace
  ]
}

// Immutable environment version bound to the training image — Create mode
// only (used by training/inference/embedding jobs).
module amlTrainingEnvironment 'modules/amlEnvironment.bicep' = if (createAmlWorkspace) {
  name: 'amlTrainingEnvironment'
  scope: resourceGroup(resolvedAmlWorkspaceRg)
  params: {
    workspaceName: createdAmlWorkspaceName
    environmentName: 'training'
    environmentVersion: amlTrainingEnvironmentVersion
    image: wireAcr ? '${sharedAcrName}.azurecr.io/${trainingImage}' : trainingImage
    environmentDescription: 'HASTE training image (training/inference/embedding workloads).'
  }
  dependsOn: [
    amlWorkspace
  ]
}

// Immutable environment version bound to the imageryprep image — Create
// mode only (used by imagery preparation/artifact packaging jobs).
module amlImageryprepEnvironment 'modules/amlEnvironment.bicep' = if (createAmlWorkspace) {
  name: 'amlImageryprepEnvironment'
  scope: resourceGroup(resolvedAmlWorkspaceRg)
  params: {
    workspaceName: createdAmlWorkspaceName
    environmentName: 'imageryprep'
    environmentVersion: amlImageryprepEnvironmentVersion
    image: wireAcr ? '${sharedAcrName}.azurecr.io/${imageryprepImage}' : imageryprepImage
    environmentDescription: 'HASTE imageryprep image (imagery preparation/artifact packaging workloads).'
  }
  dependsOn: [
    amlWorkspace
  ]
}

// Identity-based (keyless) registration of the existing HASTE storage
// account as an AML datastore — Create mode only.
module amlDatastore 'modules/amlDatastore.bicep' = if (createAmlWorkspace) {
  name: 'amlDatastore'
  scope: resourceGroup(resolvedAmlWorkspaceRg)
  params: {
    workspaceName: createdAmlWorkspaceName
    datastoreName: amlDatastoreName
    storageAccountName: storageAccountName
    containerName: 'data'
    storageResourceGroup: rgName
  }
  dependsOn: [
    amlWorkspace
    storage
  ]
}

// Least-privilege AML RBAC (AzureML Data Scientist) for the queue app
// identity only — hastefuncqueues is the only app that submits/polls/cancels
// AML compute jobs. hastefuncapi does not talk to AML directly today, so it
// does not get this grant (least privilege). Create mode only — in Existing
// mode, RBAC on the referenced workspace is a prerequisite owned by the
// existing platform, not something this IaC grants. A plain resource inside
// functionApp.bicep cannot express this cross-RG grant (Bicep requires a
// module for any resource deployed outside its file's own scope), hence the
// small dedicated module — see amlRole.bicep.
module amlRoleQueue 'modules/amlRole.bicep' = if (createAmlWorkspace) {
  name: 'amlRoleQueue'
  scope: resourceGroup(resolvedAmlWorkspaceRg)
  params: {
    amlWorkspaceName: createdAmlWorkspaceName
    principalId: functions.outputs.queueSystemPrincipalId
  }
  dependsOn: [
    amlWorkspace
  ]
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
output AML_MODE string = amlMode
output AML_WORKSPACE_NAME string = deployAml ? resolvedAmlWorkspaceName : ''
output AML_RESOURCE_GROUP string = deployAml ? resolvedAmlWorkspaceRg : ''
@secure()
output ACS_CONNECTION_STRING string = communication.outputs.connectionString
output EMAIL_SENDER_DOMAIN string = communication.outputs.senderDomain
