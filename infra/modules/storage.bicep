// Functions storage account (Standard_LRS) + premium file storage with a `data`
// share, both locked to the env subnets. The UMI gets container-scoped Blob Data
// Contributor and account-scoped delegation only; retire legacy Owner grants
// explicitly after verifying the replacement roles (incremental IaC retains them).
// (Replaces create_storage and the storage-rule portion of networking.)

@description('Azure region.')
param location string

@description('Functions storage account name.')
param storageAccountName string

@description('Premium file storage account name.')
param fileStorageAccountName string

@description('TiTiler host storage account name (its AzureWebJobsStorage and deployment package only).')
param titilerStorageAccountName string

@description('Principal id of the user-assigned managed identity.')
param umiPrincipalId string

@description('VNet name holding the allowed subnets.')
param vnetName string

@description('Default subnet name.')
param defaultSubnetName string

@description('Functions subnet name.')
param functionsSubnetName string

@description('Batch subnet name.')
param batchSubnetName string

@description('Shared hub batch-subnet resource id (where the SHARED multi-tenant pools are VNet-injected). Empty for single-tenant envs (prod) that run their own in-env pool. See spec/features/batch-compute-expansion/networking.md.')
param sharedBatchSubnetId string = ''

@description('Resource tags.')
param tags object = {}

@description('Compatibility gate: set false only after keyless application validation.')
param allowMainSharedKeyAccess bool = true

@description('Compatibility gate: set false only after retiring all File-key consumers.')
param allowFileSharedKeyAccess bool = true

var blobDataContributorRoleId = subscriptionResourceId(
  'Microsoft.Authorization/roleDefinitions',
  'ba92f5b4-2d11-453d-a403-e96b0029c9fe'
)
var blobDelegatorRoleId = subscriptionResourceId(
  'Microsoft.Authorization/roleDefinitions',
  'db58b8e5-c6ad-4a2a-8342-4190687cbf4a'
)

var defaultSubnetId = resourceId('Microsoft.Network/virtualNetworks/subnets', vnetName, defaultSubnetName)
var functionsSubnetId = resourceId('Microsoft.Network/virtualNetworks/subnets', vnetName, functionsSubnetName)
var batchSubnetId = resourceId('Microsoft.Network/virtualNetworks/subnets', vnetName, batchSubnetName)

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
    allowSharedKeyAccess: allowMainSharedKeyAccess
    allowBlobPublicAccess: false
    allowCrossTenantReplication: false
    defaultToOAuthAuthentication: true
    minimumTlsVersion: 'TLS1_2'
    supportsHttpsTrafficOnly: true
    networkAcls: {
      bypass: 'Logging, Metrics, AzureServices'
      defaultAction: 'Deny'
      // The env's own subnets, plus (for shared-pool envs) the shared hub
      // batch-subnet so the multi-tenant pools can reach this tenant's blobs
      // over the Microsoft.Storage service endpoint. Adding a demo env = this
      // one rule; no shared-pool change (see networking.md).
      virtualNetworkRules: concat([
        {
          id: defaultSubnetId
          action: 'Allow'
        }
        {
          id: functionsSubnetId
          action: 'Allow'
        }
        {
          id: batchSubnetId
          action: 'Allow'
        }
      ], empty(sharedBatchSubnetId) ? [] : [
        {
          id: sharedBatchSubnetId
          action: 'Allow'
        }
      ])
    }
  }
}

resource fileStorageAccount 'Microsoft.Storage/storageAccounts@2023-05-01' = {
  name: fileStorageAccountName
  location: location
  tags: tags
  sku: {
    name: 'Premium_LRS'
  }
  kind: 'FileStorage'
  properties: {
    allowSharedKeyAccess: allowFileSharedKeyAccess
    allowBlobPublicAccess: false
    minimumTlsVersion: 'TLS1_2'
    supportsHttpsTrafficOnly: true
    networkAcls: {
      bypass: 'Logging, Metrics, AzureServices'
      defaultAction: 'Deny'
      virtualNetworkRules: [
        {
          id: defaultSubnetId
          action: 'Allow'
        }
        {
          id: functionsSubnetId
          action: 'Allow'
        }
      ]
    }
  }
}

// TiTiler's own host state and deployment package. Kept apart from the shared
// account so the tile server's identity has no data-plane rights on HASTE
// imagery, metadata, other apps' packages or other apps' host keys. Identity
// auth only, reachable only from the functions subnet. The shared
// user-assigned identity is deliberately not granted anything here.
resource titilerStorageAccount 'Microsoft.Storage/storageAccounts@2023-05-01' = {
  name: titilerStorageAccountName
  location: location
  tags: tags
  sku: {
    name: 'Standard_LRS'
  }
  kind: 'StorageV2'
  properties: {
    accessTier: 'Hot'
    allowBlobPublicAccess: false
    allowSharedKeyAccess: false
    minimumTlsVersion: 'TLS1_2'
    supportsHttpsTrafficOnly: true
    networkAcls: {
      bypass: 'Logging, Metrics, AzureServices'
      defaultAction: 'Deny'
      virtualNetworkRules: [
        {
          id: functionsSubnetId
          action: 'Allow'
        }
      ]
    }
  }
}

resource fileServices 'Microsoft.Storage/storageAccounts/fileServices@2023-05-01' = {
  parent: fileStorageAccount
  name: 'default'
}

resource dataShare 'Microsoft.Storage/storageAccounts/fileServices/shares@2023-05-01' = {
  parent: fileServices
  name: 'data'
  properties: {
    shareQuota: 1000
  }
}

resource blobShare 'Microsoft.Storage/storageAccounts/blobServices@2023-05-01' = {
  parent: storageAccount
  name: 'default'
}

resource dataContainer 'Microsoft.Storage/storageAccounts/blobServices/containers@2023-05-01' = {
  parent: blobShare
  name: 'data'
  properties: {
    publicAccess: 'None'
  }
}

resource umiBlobContributorOnData 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(dataContainer.id, umiPrincipalId, 'blobDataContributor')
  scope: dataContainer
  properties: {
    roleDefinitionId: blobDataContributorRoleId
    principalId: umiPrincipalId
    principalType: 'ServicePrincipal'
  }
}

resource umiBlobDelegatorOnStorage 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(storageAccount.id, umiPrincipalId, 'blobDelegator')
  scope: storageAccount
  properties: {
    roleDefinitionId: blobDelegatorRoleId
    principalId: umiPrincipalId
    principalType: 'ServicePrincipal'
  }
}

output storageAccountName string = storageAccount.name
output storageAccountId string = storageAccount.id
output fileStorageAccountName string = fileStorageAccount.name
output titilerStorageAccountName string = titilerStorageAccount.name
output fileStorageAccountId string = fileStorageAccount.id
