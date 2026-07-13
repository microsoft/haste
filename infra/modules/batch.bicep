// Batch account — Create mode only. In Existing mode the account is referenced
// directly by name from main.bicep and this module is not deployed.
// (Fills the gap left by the never-implemented create_batch_acct.)

@description('Azure region.')
param location string

@description('Batch account name.')
param batchAccountName string

@description('Resource tags.')
param tags object = {}

resource batchAccount 'Microsoft.Batch/batchAccounts@2024-07-01' = {
  name: batchAccountName
  location: location
  tags: tags
  properties: {
    poolAllocationMode: 'BatchService'
  }
}

output name string = batchAccount.name
output id string = batchAccount.id
