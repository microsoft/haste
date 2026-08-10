// Custom role + assignment letting the API function app issue Static Web App
// user invitations at runtime (reproduces a manually-created role found in the
// as-built inventory). The role is assigned at the SWA scope to the API app's
// SYSTEM-ASSIGNED identity — that is the identity DefaultAzureCredential uses
// for the createUserInvitation call.

@description('Static Web App name to scope the assignment to.')
param staticWebAppName string

@description('Azure Maps account name to grant the API identity read access on.')
param mapsAccountName string

@description('System-assigned principal id of the API function app.')
param functionSystemPrincipalId string

@description('HASTE storage account name (source of publishable artifacts).')
param storageAccountName string

@description('Object (principal) id of the Planetary Computer GeoCatalog managed identity, to grant read access on HASTE storage for asset ingestion. Empty = skip (public containers or SasToken ingestion source).')
param pcGeoCatalogIngestPrincipalId string = ''

resource staticWebApp 'Microsoft.Web/staticSites@2024-04-01' existing = {
  name: staticWebAppName
}

resource invitationRole 'Microsoft.Authorization/roleDefinitions@2022-04-01' = {
  name: guid(resourceGroup().id, 'HasteWebAppUserManager')
  properties: {
    roleName: 'HasteWebAppUserManager-${uniqueString(resourceGroup().id)}'
    description: 'Lets the HASTE API app manage Static Web App users (invitations).'
    type: 'CustomRole'
    permissions: [
      {
        actions: [
          'microsoft.web/staticSites/*'
        ]
        notActions: []
        dataActions: []
        notDataActions: []
      }
    ]
    assignableScopes: [
      resourceGroup().id
    ]
  }
}

resource invitationAssignment 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(staticWebApp.id, functionSystemPrincipalId, 'HasteWebAppUserManager')
  scope: staticWebApp
  properties: {
    roleDefinitionId: invitationRole.id
    principalId: functionSystemPrincipalId
    principalType: 'ServicePrincipal'
  }
}

// The API app reads Azure Maps tiles/data with its system-assigned identity
// via DefaultAzureCredential, so it needs Azure Maps Data Reader on the Maps
// account. (Built-in role 423170ca-a8f6-4b0f-8487-9e4eb8f49bfa.)
resource mapsAccount 'Microsoft.Maps/accounts@2023-06-01' existing = {
  name: mapsAccountName
}

resource mapsDataReaderAssignment 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(mapsAccount.id, functionSystemPrincipalId, 'AzureMapsDataReader')
  scope: mapsAccount
  properties: {
    roleDefinitionId: subscriptionResourceId(
      'Microsoft.Authorization/roleDefinitions',
      '423170ca-a8f6-4b0f-8487-9e4eb8f49bfa'
    )
    principalId: functionSystemPrincipalId
    principalType: 'ServicePrincipal'
  }
}

// Planetary Computer publishing: the GeoCatalog ingests published assets by
// reading them from HASTE blob storage. When ingestion uses the GeoCatalog's
// managed identity (rather than a SasToken ingestion source), that identity
// needs Storage Blob Data Reader on the HASTE storage account. Conditional and
// off by default — supply the GeoCatalog identity's object id to enable it.
// (The complementary grant — the function app's identity on the external
// GeoCatalog data plane — is on the operator-owned GeoCatalog resource and is
// configured out-of-band; verify the exact GeoCatalog RBAC role against a live
// catalog before wiring it here.)
resource storageAccount 'Microsoft.Storage/storageAccounts@2023-05-01' existing = {
  name: storageAccountName
}

resource pcIngestBlobReaderAssignment 'Microsoft.Authorization/roleAssignments@2022-04-01' = if (!empty(pcGeoCatalogIngestPrincipalId)) {
  name: guid(storageAccount.id, pcGeoCatalogIngestPrincipalId, 'StorageBlobDataReader')
  scope: storageAccount
  properties: {
    roleDefinitionId: subscriptionResourceId(
      'Microsoft.Authorization/roleDefinitions',
      '2a2b9908-6ea1-4ae2-8e65-a410df84e7d1'
    )
    principalId: pcGeoCatalogIngestPrincipalId
    principalType: 'ServicePrincipal'
  }
}

output roleDefinitionId string = invitationRole.id
