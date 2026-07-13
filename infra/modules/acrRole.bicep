// AcrPull for the env UMI on a (typically shared) ACR. Deployed at the scope of
// the ACR's resource group — cross-RG and additive-only when the registry is
// shared. (Reproduces assign_identity_to_acr.)

@description('ACR name (without .azurecr.io).')
param acrName string

@description('Principal id of the user-assigned managed identity.')
param umiPrincipalId string

var acrPullRoleId = subscriptionResourceId(
  'Microsoft.Authorization/roleDefinitions',
  '7f951dda-4ed3-4680-a7ca-43fe172d538d'
)

resource acr 'Microsoft.ContainerRegistry/registries@2023-11-01-preview' existing = {
  name: acrName
}

resource acrPull 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(acr.id, umiPrincipalId, 'AcrPull')
  scope: acr
  properties: {
    roleDefinitionId: acrPullRoleId
    principalId: umiPrincipalId
    principalType: 'ServicePrincipal'
  }
}
