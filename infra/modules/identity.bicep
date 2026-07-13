// User-assigned managed identity shared across the function apps, APIM, and the
// Batch pool (replaces create_group_and_umi).

@description('Azure region.')
param location string

@description('User-assigned managed identity name.')
param umiName string

@description('Resource tags.')
param tags object = {}

resource umi 'Microsoft.ManagedIdentity/userAssignedIdentities@2023-01-31' = {
  name: umiName
  location: location
  tags: tags
}

output resourceId string = umi.id
output principalId string = umi.properties.principalId
output clientId string = umi.properties.clientId
output name string = umi.name
