// Shared multi-tenant Batch pools (H100 + T4) for a group of envs (e.g. dev, demo),
// created in the shared Batch account's resource group.
// Multi-tenant: data isolation is per-job user-delegation SAS (see
// spec/features/batch-compute-expansion/). ACR pull uses ONLY the shared UMI (no
// per-tenant identity, no storage grants). Autoscale low-priority, scale-to-zero
// when idle to preserve scarce dedicated GPU quota.
//
// Names: ${sharedPrefix}-shared-${sharedGroup}-{h100,t4}-pool
//   e.g. group=dev  -> <prefix>-shared-dev-{h100,t4}-pool
//
// Deploy (values come from env vars via shared-pools.bicepparam):
//   az deployment group create -g <shared-rg> \
//     --parameters infra/shared-pools.bicepparam

@description('Resource-name prefix. Generic default; override per deployment.')
param sharedPrefix string = 'haste'

@description('Shared group these pools serve (e.g. dev, demo).')
param sharedGroup string

@description('Existing shared Batch account name (BYO — no generic default).')
param batchAccountName string

@description('Shared ACR-pull UMI resource id.')
param umiResourceId string

@description('Existing shared ACR name, without .azurecr.io (BYO — no generic default).')
param acrName string

@description('Training image (H100 tier + spillover).')
param trainingImage string = 'hastetraining:2.0.0'

@description('Imageryprep image (T4 tier + spillover).')
param imageryprepImage string = 'hasteimageryprep:2.0.0'

@description('H100 autoscale max nodes (formula cap).')
param h100MaxNodes int = 2

@description('T4 autoscale max nodes (formula cap).')
param t4MaxNodes int = 2

@description('Node cost tier. Dedicated (draws from the account dedicated-core quota). Set LowPriority only where low-priority GPU quota is available (cheaper, preemptible).')
@allowed([
  'Dedicated'
  'LowPriority'
])
param sharedNodeType string = 'Dedicated'

module h100Pool 'modules/batchPool.bicep' = {
  name: 'shared-${sharedGroup}-h100'
  params: {
    batchAccountName: batchAccountName
    poolName: '${sharedPrefix}-shared-${sharedGroup}-h100-pool'
    vmSize: 'Standard_NC40ads_H100_v5'
    scaleMode: 'Autoscale'
    nodeType: sharedNodeType
    minNodes: 0
    maxNodes: h100MaxNodes
    umiResourceId: umiResourceId
    acrName: acrName
    trainingImage: trainingImage
    imageryprepImage: imageryprepImage
    // subnetId omitted => no VNet injection yet; finalize subnet + per-tenant
    // storage firewall allowlisting before running real workloads.
  }
}

module t4Pool 'modules/batchPool.bicep' = {
  name: 'shared-${sharedGroup}-t4'
  params: {
    batchAccountName: batchAccountName
    poolName: '${sharedPrefix}-shared-${sharedGroup}-t4-pool'
    vmSize: 'Standard_NC16as_T4_v3'
    scaleMode: 'Autoscale'
    nodeType: sharedNodeType
    minNodes: 0
    maxNodes: t4MaxNodes
    umiResourceId: umiResourceId
    acrName: acrName
    trainingImage: trainingImage
    imageryprepImage: imageryprepImage
  }
}

output h100PoolName string = h100Pool.outputs.poolName
output t4PoolName string = t4Pool.outputs.poolName
