// AML compute cluster (AmlCompute) — scale-to-zero GPU or CPU tier, one per
// workload tier (mirrors Batch's single-pool-per-tier convention in
// batchPool.bicep). Deployed ONLY in Create mode (gated exclusively on
// `createAmlWorkspace` in main.bicep) — HASTE's default/first enablement
// path, `amlMode == 'Existing'`, never deploys this module; it references an
// already-provisioned cluster by name instead (existingAmlGpuComputeName/
// existingAmlCpuComputeName in main.bicep). Create mode is an explicit,
// later opt-in. When deployed, this is additive-only against the resolved
// workspace, same convention as batchPool.bicep being deployed additively
// into a possibly-shared Batch account.

@description('Resolved AML workspace name (existing or just-created).')
param workspaceName string

@description('Azure region (must match the workspace region).')
param location string

@description('Compute cluster name. Kept short: AmlCompute names are capped at 24 characters by the service.')
@maxLength(24)
param computeName string

@description('VM size for this cluster (e.g. an H100 SKU for GPU, a general-purpose SKU for CPU).')
param vmSize string

@description('Autoscale floor. 0 = scale-to-zero when idle.')
param minNodes int = 0

@description('Autoscale cap.')
param maxNodes int

@description('Idle time (ISO 8601 duration) before an unused node scales back to zero.')
param scaleDownIdleTime string = 'PT30M'

@description('User-assigned managed identity resource id attached to the compute cluster resource itself — used for control-plane operations such as resolving/pulling the registered environment image from a private ACR. This is independent of AML_IDENTITY_MODE, which controls the per-job data-access identity a submitted job runs as (see amlDatastore.bicep and main.bicep); it does not imply every job uses this identity.')
param umiResourceId string

@description('VNet subnet resource id for VNet-injected compute. Empty => no VNet injection (public compute) — main.bicep wires this from its amlComputeSubnetId parameter for both the GPU and CPU clusters; empty preserves the current public-compute default. See design.md Open Questions on final AML tenant/network placement.')
param subnetId string = ''

resource workspace 'Microsoft.MachineLearningServices/workspaces@2025-06-01' existing = {
  name: workspaceName
}

resource compute 'Microsoft.MachineLearningServices/workspaces/computes@2025-06-01' = {
  parent: workspace
  name: computeName
  location: location
  identity: {
    type: 'UserAssigned'
    userAssignedIdentities: {
      '${umiResourceId}': {}
    }
  }
  properties: {
    computeType: 'AmlCompute'
    properties: {
      vmSize: vmSize
      remoteLoginPortPublicAccess: 'Disabled'
      // No VNet => the node needs a public IP to reach the AML control
      // plane; VNet-injected clusters (subnetId set) disable it.
      enableNodePublicIp: empty(subnetId)
      ...(empty(subnetId) ? {} : {
        subnet: {
          id: subnetId
        }
      })
      scaleSettings: {
        minNodeCount: minNodes
        maxNodeCount: maxNodes
        nodeIdleTimeBeforeScaleDown: scaleDownIdleTime
      }
    }
  }
}

output name string = compute.name
