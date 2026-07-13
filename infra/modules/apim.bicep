// API Management (StandardV2, VNet-External) — reproduces create_apim's ARM
// template, plus the Storage Blob Data Owner grant to the APIM system identity.
// API operations are imported by the postprovision hook (see plan Phase 3).

@description('Azure region.')
param location string

@description('API Management service name.')
param apimName string

@description('Publisher email.')
param publisherEmail string

@description('Publisher organisation name.')
param publisherName string

@description('User-assigned managed identity resource id.')
param umiResourceId string

@description('VNet name holding the APIM subnet.')
param vnetName string

@description('Subnet name for APIM VNet integration.')
param defaultSubnetName string

@description('Storage account name to grant the APIM identity blob access on.')
param storageAccountName string

@description('Resource tags.')
param tags object = {}

var blobDataOwnerRoleId = subscriptionResourceId(
  'Microsoft.Authorization/roleDefinitions',
  'b7e6dc6d-f1e8-4753-8033-0f276bb0955b'
)

resource apim 'Microsoft.ApiManagement/service@2024-06-01-preview' = {
  name: apimName
  location: location
  tags: tags
  sku: {
    name: 'StandardV2'
    capacity: 1
  }
  identity: {
    type: 'SystemAssigned, UserAssigned'
    userAssignedIdentities: {
      '${umiResourceId}': {}
    }
  }
  properties: {
    publisherEmail: publisherEmail
    publisherName: publisherName
    virtualNetworkType: 'External'
    virtualNetworkConfiguration: {
      subnetResourceId: resourceId('Microsoft.Network/virtualNetworks/subnets', vnetName, defaultSubnetName)
    }
    legacyPortalStatus: 'Disabled'
    developerPortalStatus: 'Disabled'
    releaseChannel: 'Default'
    publicNetworkAccess: 'Enabled'
    natGatewayState: 'Enabled'
    // Disable legacy TLS/SSL on both the client and backend sides.
    customProperties: {
      'Microsoft.WindowsAzure.ApiManagement.Gateway.Security.Protocols.Tls10': 'False'
      'Microsoft.WindowsAzure.ApiManagement.Gateway.Security.Protocols.Tls11': 'False'
      'Microsoft.WindowsAzure.ApiManagement.Gateway.Security.Protocols.Ssl30': 'False'
      'Microsoft.WindowsAzure.ApiManagement.Gateway.Security.Backend.Protocols.Tls10': 'False'
      'Microsoft.WindowsAzure.ApiManagement.Gateway.Security.Backend.Protocols.Tls11': 'False'
      'Microsoft.WindowsAzure.ApiManagement.Gateway.Security.Backend.Protocols.Ssl30': 'False'
    }
  }
}

resource storageAccount 'Microsoft.Storage/storageAccounts@2023-05-01' existing = {
  name: storageAccountName
}

resource apimBlobOwner 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(storageAccount.id, apim.id, 'blobDataOwner')
  scope: storageAccount
  properties: {
    roleDefinitionId: blobDataOwnerRoleId
    principalId: apim.identity.principalId
    principalType: 'ServicePrincipal'
  }
}

output resourceId string = apim.id
output name string = apim.name
output systemPrincipalId string = apim.identity.principalId
