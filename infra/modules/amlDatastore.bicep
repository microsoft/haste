// AML datastore registration — identity-based access to the existing HASTE
// storage account (`credentialsType: 'None'`). Deployed ONLY in Create mode
// (gated exclusively on `createAmlWorkspace` in main.bicep) — HASTE's
// default/first enablement path, `amlMode == 'Existing'`, never deploys this
// module; it references an already-registered datastore by name instead
// (existingAmlDatastoreName in main.bicep). Create mode is an explicit,
// later opt-in. No account key, SAS, or connection string is ever
// registered when this module runs. Which identity a given AML job actually
// uses to read/write through this datastore at runtime (the calling
// principal's own identity, or a specific user-assigned managed identity) is
// a per-job AML setting controlled by AML_IDENTITY_MODE / AML_MANAGED_IDENTITY_ID
// (see main.bicep/functions.bicep) and implemented by the AML adapter — this
// module does not assume or depend on one option over the other. Mirrors the
// "no standing secrets" requirement in ADR-0005 and design.md#security.

@description('Resolved AML workspace name (existing or just-created).')
param workspaceName string

@description('Datastore name.')
param datastoreName string

@description('HASTE storage account name (existing).')
param storageAccountName string

@description('Blob container to register (the existing HASTE "data" container).')
param containerName string = 'data'

@description('Resource group holding the HASTE storage account.')
param storageResourceGroup string

@description('Subscription id holding the HASTE storage account.')
param storageSubscriptionId string = subscription().subscriptionId

resource workspace 'Microsoft.MachineLearningServices/workspaces@2025-06-01' existing = {
  name: workspaceName
}

resource datastore 'Microsoft.MachineLearningServices/workspaces/datastores@2025-06-01' = {
  parent: workspace
  name: datastoreName
  properties: {
    datastoreType: 'AzureBlob'
    accountName: storageAccountName
    containerName: containerName
    resourceGroup: storageResourceGroup
    subscriptionId: storageSubscriptionId
    credentials: {
      credentialsType: 'None'
    }
  }
}

output name string = datastore.name
