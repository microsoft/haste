// Azure Machine Learning workspace — Create mode only, gated exclusively on
// `createAmlWorkspace` in main.bicep. HASTE's default/first enablement path
// is `amlMode == 'Existing'`, which never deploys this (or any other AML)
// module — it only wires pre-existing, platform-owned identifiers into
// Function App settings (see main.bicep/functions.bicep). Create mode is an
// explicit, later opt-in for environments that want HASTE to own its own
// AML workspace/compute/environment/datastore stack instead of referencing
// one; it is not enabled by anything in this file. Provisions the
// workspace's own required dependencies (storage account, key vault, App
// Insights) — these back the workspace's internal bookkeeping only; HASTE's
// own data lives in the separate identity-based datastore registered by
// amlDatastore.bicep (Create mode only), and no key from any of these
// dependencies is ever surfaced as a HASTE application setting. See
// spec/features/aml-compute-backend/design.md#infrastructure and ADR-0005.

@description('Azure region.')
param location string

@description('AML workspace name.')
param workspaceName string

@description('Dependent storage account name (workspace bookkeeping only, not the HASTE datastore).')
param storageAccountName string

@description('Dependent Key Vault name (required by the workspace resource type; RBAC-authorized, no HASTE secrets stored here).')
param keyVaultName string

@description('Dependent Application Insights name.')
param appInsightsName string

@description('Log Analytics workspace resource id to link Application Insights to.')
param logAnalyticsId string

@description('User-assigned managed identity resource id — used as the workspace identity (keyless; no standing workspace secrets).')
param umiResourceId string

@description('Object id of the user-assigned managed identity used as the workspace identity.')
param umiPrincipalId string

@description('Resource tags.')
param tags object = {}

var contributorRoleId = subscriptionResourceId(
  'Microsoft.Authorization/roleDefinitions',
  'b24988ac-6180-42a0-ab88-20f7382dd24c'
)
var storageBlobDataContributorRoleId = subscriptionResourceId(
  'Microsoft.Authorization/roleDefinitions',
  'ba92f5b4-2d11-453d-a403-e96b0029c9fe'
)
var storageFileDataPrivilegedContributorRoleId = subscriptionResourceId(
  'Microsoft.Authorization/roleDefinitions',
  '69566ab7-960f-475b-8e7c-b3118f30c6bd'
)
var keyVaultAdministratorRoleId = subscriptionResourceId(
  'Microsoft.Authorization/roleDefinitions',
  '00482a5a-887f-4fb3-b363-3b7fe8e74483'
)

resource storageAccount 'Microsoft.Storage/storageAccounts@2023-05-01' = {
  name: storageAccountName
  location: location
  tags: tags
  sku: {
    name: 'Standard_LRS'
  }
  kind: 'StorageV2'
  properties: {
    accessTier: 'Hot'
    // Keyless: the workspace itself talks to this dependent storage account
    // via its managed identity (systemDatastoresAuthMode below), not a key.
    allowSharedKeyAccess: false
    allowBlobPublicAccess: false
    minimumTlsVersion: 'TLS1_2'
    supportsHttpsTrafficOnly: true
    publicNetworkAccess: 'Enabled'
    networkAcls: {
      bypass: 'AzureServices'
      defaultAction: 'Deny'
      ipRules: []
      virtualNetworkRules: []
    }
  }
}

resource keyVault 'Microsoft.KeyVault/vaults@2023-07-01' = {
  name: keyVaultName
  location: location
  tags: tags
  properties: {
    sku: {
      family: 'A'
      name: 'standard'
    }
    tenantId: subscription().tenantId
    // RBAC-authorized, no access policies / no HASTE secrets are ever
    // written here — this vault exists only to satisfy the workspace
    // resource type's required dependency.
    enableRbacAuthorization: true
    accessPolicies: []
    publicNetworkAccess: 'Enabled'
    networkAcls: {
      bypass: 'AzureServices'
      defaultAction: 'Deny'
      ipRules: []
      virtualNetworkRules: []
    }
    enableSoftDelete: true
    softDeleteRetentionInDays: 7
  }
}

resource appInsights 'Microsoft.Insights/components@2020-02-02' = {
  name: appInsightsName
  location: location
  kind: 'web'
  tags: tags
  properties: {
    Application_Type: 'web'
    WorkspaceResourceId: logAnalyticsId
  }
}

// A workspace that uses a primary user-assigned identity must receive access
// to its associated resources before the workspace is created. These grants
// follow Microsoft Learn's identity-based workspace requirements and apply
// only in the parent module's explicit Create mode.
resource umiStorageContributor 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(storageAccount.id, umiPrincipalId, 'Contributor')
  scope: storageAccount
  properties: {
    roleDefinitionId: contributorRoleId
    principalId: umiPrincipalId
    principalType: 'ServicePrincipal'
  }
}

resource umiStorageBlobDataContributor 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(storageAccount.id, umiPrincipalId, 'StorageBlobDataContributor')
  scope: storageAccount
  properties: {
    roleDefinitionId: storageBlobDataContributorRoleId
    principalId: umiPrincipalId
    principalType: 'ServicePrincipal'
  }
}

resource umiStorageFileDataContributor 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(storageAccount.id, umiPrincipalId, 'StorageFileDataPrivilegedContributor')
  scope: storageAccount
  properties: {
    roleDefinitionId: storageFileDataPrivilegedContributorRoleId
    principalId: umiPrincipalId
    principalType: 'ServicePrincipal'
  }
}

resource umiKeyVaultContributor 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(keyVault.id, umiPrincipalId, 'Contributor')
  scope: keyVault
  properties: {
    roleDefinitionId: contributorRoleId
    principalId: umiPrincipalId
    principalType: 'ServicePrincipal'
  }
}

resource umiKeyVaultAdministrator 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(keyVault.id, umiPrincipalId, 'KeyVaultAdministrator')
  scope: keyVault
  properties: {
    roleDefinitionId: keyVaultAdministratorRoleId
    principalId: umiPrincipalId
    principalType: 'ServicePrincipal'
  }
}

resource umiAppInsightsContributor 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(appInsights.id, umiPrincipalId, 'Contributor')
  scope: appInsights
  properties: {
    roleDefinitionId: contributorRoleId
    principalId: umiPrincipalId
    principalType: 'ServicePrincipal'
  }
}

resource workspace 'Microsoft.MachineLearningServices/workspaces@2025-06-01' = {
  name: workspaceName
  location: location
  tags: tags
  identity: {
    type: 'UserAssigned'
    userAssignedIdentities: {
      '${umiResourceId}': {}
    }
  }
  properties: {
    friendlyName: workspaceName
    storageAccount: storageAccount.id
    keyVault: keyVault.id
    applicationInsights: appInsights.id
    primaryUserAssignedIdentity: umiResourceId
    // Keyless dependent-storage access from the workspace's own identity —
    // no storage account key is ever read or surfaced by HASTE.
    systemDatastoresAuthMode: 'identity'
    hbiWorkspace: false
    v1LegacyMode: false
    publicNetworkAccess: 'Enabled'
  }
  dependsOn: [
    umiStorageContributor
    umiStorageBlobDataContributor
    umiStorageFileDataContributor
    umiKeyVaultContributor
    umiKeyVaultAdministrator
    umiAppInsightsContributor
  ]
}

resource umiWorkspaceContributor 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(workspace.id, umiPrincipalId, 'Contributor')
  scope: workspace
  properties: {
    roleDefinitionId: contributorRoleId
    principalId: umiPrincipalId
    principalType: 'ServicePrincipal'
  }
}

output id string = workspace.id
output name string = workspace.name
