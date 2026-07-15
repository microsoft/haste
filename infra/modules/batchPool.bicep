// Batch GPU pool — reproduces the inline Bicep from create_batch_pool.
// Deployed at the scope of the resolved Batch account's RG. When that account
// is a shared/Existing one in another RG, this is an additive, cross-RG
// deployment that creates ONLY the named pool — it never touches the account
// or sibling pools.

@description('Resolved Batch account name (existing or just-created).')
param batchAccountName string

@description('Pool name.')
param poolName string

@description('Pool VM size.')
param vmSize string

@description('Max nodes (autoscale cap).')
param maxNodes int

@description('Scale mode: Fixed (dev/prod reserved) or Autoscale (shared-demo burst).')
@allowed([
  'Fixed'
  'Autoscale'
])
param scaleMode string = 'Autoscale'

@description('Node cost tier: Dedicated (guaranteed) or LowPriority (spot, preemptible).')
@allowed([
  'Dedicated'
  'LowPriority'
])
param nodeType string = 'Dedicated'

@description('Node count when scaleMode == Fixed.')
param fixedNodeCount int = 1

@description('Autoscale floor. 0 = scale-to-zero when idle (shared-demo burst); 1 keeps the legacy always-on behavior.')
param minNodes int = 1

@description('User-assigned managed identity resource id (for ACR pull).')
param umiResourceId string

@description('VNet subnet resource id for VNet-injected pools. Empty => no VNet injection (BatchManaged public IPs). Shared-demo pools finalize their subnet + per-demo-storage firewall allowlisting before running workloads.')
param subnetId string = ''

@description('Shared ACR name (without .azurecr.io).')
param acrName string

@description('Training container image (tag included).')
param trainingImage string

@description('Imageryprep container image (tag included).')
param imageryprepImage string

var registryServer = '${acrName}.azurecr.io'

// Autoscale targets the node bucket matching nodeType; minNodes=0 => scale-to-zero
// when idle (shared-demo burst preserves scarce GPU quota).
var scaleTargetVar = nodeType == 'LowPriority' ? '$TargetLowPriorityNodes' : '$TargetDedicatedNodes'
var autoscaleFormula = '$samples = $ActiveTasks.GetSamplePercent(TimeInterval_Minute * 15);$tasks = $samples < 70 ? max(0, $ActiveTasks.GetSample(1)) : max($ActiveTasks.GetSample(1), avg($ActiveTasks.GetSample(TimeInterval_Minute * 15)));$targetVMs = $tasks > 0 ? $tasks : ${minNodes};${scaleTargetVar} = max(${minNodes}, min($targetVMs, ${maxNodes}));$NodeDeallocationOption = taskcompletion;'

// Fixed (reserved dev/prod) vs Autoscale (shared-demo burst), targeting the
// Dedicated or LowPriority bucket per nodeType.
var scaleSettings = scaleMode == 'Fixed' ? {
  fixedScale: {
    targetDedicatedNodes: nodeType == 'Dedicated' ? fixedNodeCount : 0
    targetLowPriorityNodes: nodeType == 'LowPriority' ? fixedNodeCount : 0
    resizeTimeout: 'PT15M'
  }
} : {
  autoScale: {
    formula: autoscaleFormula
    evaluationInterval: 'PT5M'
  }
}

resource batchAccount 'Microsoft.Batch/batchAccounts@2024-07-01' existing = {
  name: batchAccountName
}

resource pool 'Microsoft.Batch/batchAccounts/pools@2024-07-01' = {
  parent: batchAccount
  name: poolName
  identity: {
    type: 'UserAssigned'
    userAssignedIdentities: {
      '${umiResourceId}': {}
    }
  }
  properties: {
    vmSize: vmSize
    interNodeCommunication: 'Disabled'
    taskSlotsPerNode: 1
    taskSchedulingPolicy: {
      nodeFillType: 'Pack'
    }
    deploymentConfiguration: {
      virtualMachineConfiguration: {
        imageReference: {
          publisher: 'microsoft-dsvm'
          offer: 'ubuntu-hpc'
          sku: '2204'
          version: 'latest'
        }
        nodeAgentSkuId: 'batch.node.ubuntu 22.04'
        osDisk: {
          caching: 'None'
          diskSizeGB: 1023
          managedDisk: {
            storageAccountType: 'Premium_LRS'
          }
        }
        containerConfiguration: {
          type: 'DockerCompatible'
          containerImageNames: [
            '${registryServer}/${trainingImage}'
            '${registryServer}/${imageryprepImage}'
          ]
          containerRegistries: [
            {
              registryServer: 'https://${registryServer}'
              identityReference: {
                resourceId: umiResourceId
              }
            }
          ]
        }
        nodePlacementConfiguration: {
          policy: 'Regional'
        }
      }
    }
    ...(empty(subnetId) ? {} : {
      networkConfiguration: {
        subnetId: subnetId
        publicIPAddressConfiguration: {
          provision: 'BatchManaged'
        }
        dynamicVnetAssignmentScope: 'none'
        enableAcceleratedNetworking: false
      }
    })
    scaleSettings: scaleSettings
  }
}

output poolName string = pool.name
