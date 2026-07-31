// One Flex Consumption Python function app with: per-app plan, App Insights
// linked to Log Analytics, system + user-assigned identity, VNet integration,
// identity-based AzureWebJobsStorage, the /data file-share mount, and the
// blob/queue role grants for its system identity. (Reproduces one iteration of
// create_function_app.)

@description('Azure region.')
param location string

@description('Function app name.')
param name string

@description('App Service (Flex Consumption) plan name.')
param planName string

@description('Always-ready HTTP instance count.')
param alwaysReadyCount int

@description('Functions storage account name.')
param storageAccountName string

@description('Premium file storage account name (mounted at /data).')
param fileStorageAccountName string

@description('User-assigned managed identity resource id.')
param umiResourceId string

@description('VNet name for VNet integration.')
param vnetName string

@description('Functions subnet name.')
param functionsSubnetName string

@description('Log Analytics workspace resource id.')
param logAnalyticsId string

@description('Extra application settings (name/value pairs) merged after the base settings. api/queues pass the hastegeo app config here; titiler passes none.')
param appSettings array = []

@description('Resource tags.')
param tags object = {}

var blobDataOwnerRoleId = subscriptionResourceId(
  'Microsoft.Authorization/roleDefinitions',
  'b7e6dc6d-f1e8-4753-8033-0f276bb0955b'
)
var queueDataContributorRoleId = subscriptionResourceId(
  'Microsoft.Authorization/roleDefinitions',
  '974c5e8b-45b9-4653-ba55-5f855dd0fb88'
)
// Storage Blob Delegator: lets the app mint user-delegation SAS (v2.1.0 per-job
// SAS for multi-tenant shared Batch pools). Not included in Blob Data Owner.
var blobDelegatorRoleId = subscriptionResourceId(
  'Microsoft.Authorization/roleDefinitions',
  'db58b8e5-c6ad-4a2a-8342-4190687cbf4a'
)

var deploymentContainerName = 'app-package-${name}'

resource storageAccount 'Microsoft.Storage/storageAccounts@2023-05-01' existing = {
  name: storageAccountName
}

resource fileStorageAccount 'Microsoft.Storage/storageAccounts@2023-05-01' existing = {
  name: fileStorageAccountName
}

resource blobService 'Microsoft.Storage/storageAccounts/blobServices@2023-05-01' existing = {
  parent: storageAccount
  name: 'default'
}

resource deploymentContainer 'Microsoft.Storage/storageAccounts/blobServices/containers@2023-05-01' = {
  parent: blobService
  name: deploymentContainerName
}

resource appInsights 'Microsoft.Insights/components@2020-02-02' = {
  name: '${name}-ai'
  location: location
  kind: 'web'
  tags: tags
  properties: {
    Application_Type: 'web'
    WorkspaceResourceId: logAnalyticsId
  }
}

resource plan 'Microsoft.Web/serverfarms@2023-12-01' = {
  name: planName
  location: location
  tags: tags
  sku: {
    tier: 'FlexConsumption'
    name: 'FC1'
  }
  kind: 'functionapp'
  properties: {
    reserved: true
  }
}

resource site 'Microsoft.Web/sites@2023-12-01' = {
  name: name
  location: location
  kind: 'functionapp,linux'
  tags: tags
  identity: {
    type: 'SystemAssigned, UserAssigned'
    userAssignedIdentities: {
      '${umiResourceId}': {}
    }
  }
  properties: {
    serverFarmId: plan.id
    httpsOnly: true
    virtualNetworkSubnetId: resourceId('Microsoft.Network/virtualNetworks/subnets', vnetName, functionsSubnetName)
    functionAppConfig: {
      deployment: {
        storage: {
          type: 'blobContainer'
          value: '${storageAccount.properties.primaryEndpoints.blob}${deploymentContainerName}'
          authentication: {
            type: 'SystemAssignedIdentity'
          }
        }
      }
      scaleAndConcurrency: {
        maximumInstanceCount: 100
        instanceMemoryMB: 4096
        alwaysReady: [
          {
            name: 'http'
            instanceCount: alwaysReadyCount
          }
        ]
      }
      runtime: {
        name: 'python'
        version: '3.11'
      }
    }
    siteConfig: {
      ftpsState: 'Disabled'
      appSettings: concat([
        {
          name: 'AzureWebJobsStorage__accountName'
          value: storageAccountName
        }
        {
          name: 'AzureWebJobsStorage__blobServiceUri'
          value: storageAccount.properties.primaryEndpoints.blob
        }
        {
          name: 'AzureWebJobsStorage__queueServiceUri'
          value: storageAccount.properties.primaryEndpoints.queue
        }
        {
          name: 'APPLICATIONINSIGHTS_CONNECTION_STRING'
          value: appInsights.properties.ConnectionString
        }
      ], appSettings)
    }
  }
}

resource storageMount 'Microsoft.Web/sites/config@2023-12-01' = {
  parent: site
  name: 'azurestorageaccounts'
  properties: {
    data: {
      type: 'AzureFiles'
      accountName: fileStorageAccountName
      shareName: 'data'
      mountPath: '/data'
      accessKey: fileStorageAccount.listKeys().keys[0].value
    }
  }
}

resource siteBlobOwner 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(storageAccount.id, site.id, 'blobDataOwner')
  scope: storageAccount
  properties: {
    roleDefinitionId: blobDataOwnerRoleId
    principalId: site.identity.principalId
    principalType: 'ServicePrincipal'
  }
}

resource siteQueueContributor 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(storageAccount.id, site.id, 'queueDataContributor')
  scope: storageAccount
  properties: {
    roleDefinitionId: queueDataContributorRoleId
    principalId: site.identity.principalId
    principalType: 'ServicePrincipal'
  }
}

resource siteBlobDelegator 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(storageAccount.id, site.id, 'blobDelegator')
  scope: storageAccount
  properties: {
    roleDefinitionId: blobDelegatorRoleId
    principalId: site.identity.principalId
    principalType: 'ServicePrincipal'
  }
}

output name string = site.name
output defaultHostName string = site.properties.defaultHostName
output systemPrincipalId string = site.identity.principalId
