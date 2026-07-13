// Functions storage account (Standard_LRS) + premium file storage with a `data`
// share, both locked to the env subnets, plus Storage Blob Data Owner for the UMI.
// (Replaces create_storage and the storage-rule portion of networking.)

@description('Azure region.')
param location string

@description('Functions storage account name.')
param storageAccountName string

@description('Premium file storage account name.')
param fileStorageAccountName string

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

@description('Resource tags.')
param tags object = {}

var blobDataOwnerRoleId = subscriptionResourceId(
  'Microsoft.Authorization/roleDefinitions',
  'b7e6dc6d-f1e8-4753-8033-0f276bb0955b'
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
    allowSharedKeyAccess: true
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
        {
          id: batchSubnetId
          action: 'Allow'
        }
      ]
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
    allowSharedKeyAccess: true
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
}

resource umiBlobOwnerOnStorage 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(storageAccount.id, umiPrincipalId, 'blobDataOwner')
  scope: storageAccount
  properties: {
    roleDefinitionId: blobDataOwnerRoleId
    principalId: umiPrincipalId
    principalType: 'ServicePrincipal'
  }
}

resource umiBlobOwnerOnFileStorage 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(fileStorageAccount.id, umiPrincipalId, 'blobDataOwner')
  scope: fileStorageAccount
  properties: {
    roleDefinitionId: blobDataOwnerRoleId
    principalId: umiPrincipalId
    principalType: 'ServicePrincipal'
  }
}

output storageAccountName string = storageAccount.name
output storageAccountId string = storageAccount.id
output fileStorageAccountName string = fileStorageAccount.name
output fileStorageAccountId string = fileStorageAccount.id
