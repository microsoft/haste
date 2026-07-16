// Deployment config for shared-pools.bicep. The template stays generic (prefix
// defaults to the neutral 'haste'); values are supplied per deployment from
// environment variables — mirroring main.bicepparam — so NO partner-specific
// subscription/account details are committed. Set these before deploying:
//   HASTE_RESOURCE_PREFIX        resource-name prefix (e.g. your org's prefix)
//   HASTE_SHARED_GROUP           dev | demo | ...              (default: dev)
//   HASTE_EXISTING_BATCH_ACCOUNT shared Batch account name
//   HASTE_SHARED_ACR_NAME        shared ACR name (without .azurecr.io)
//   HASTE_SHARED_UMI_ID          resource id of the ACR-pull-only identity
//
// Pool names: ${prefix}-shared-${group}-{h100,t4}-pool
//
// Deploy: az deployment group create -g <shared-rg> \
//   --parameters infra/shared-pools.bicepparam

using './shared-pools.bicep'

param sharedPrefix = readEnvironmentVariable('HASTE_RESOURCE_PREFIX', 'haste')
param sharedGroup = readEnvironmentVariable('HASTE_SHARED_GROUP', 'dev')
param sharedNodeType = readEnvironmentVariable('HASTE_SHARED_NODE_TYPE', 'Dedicated')
param h100ScaleMode = readEnvironmentVariable('HASTE_SHARED_H100_SCALE_MODE', 'Autoscale')
param h100MinNodes = int(readEnvironmentVariable('HASTE_SHARED_H100_MIN_NODES', '0'))
param t4MinNodes = int(readEnvironmentVariable('HASTE_SHARED_T4_MIN_NODES', '0'))
param t4MaxNodes = int(readEnvironmentVariable('HASTE_SHARED_T4_MAX_NODES', '2'))
param sharedBatchSubnetId = readEnvironmentVariable('HASTE_SHARED_BATCH_SUBNET_ID', '')
param batchAccountName = readEnvironmentVariable('HASTE_EXISTING_BATCH_ACCOUNT', '')
param acrName = readEnvironmentVariable('HASTE_SHARED_ACR_NAME', '')
param umiResourceId = readEnvironmentVariable('HASTE_SHARED_UMI_ID', '')
