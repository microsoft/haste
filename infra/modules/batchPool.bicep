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

@description('Max dedicated nodes (autoscale cap).')
param maxNodes int

@description('User-assigned managed identity resource id (for ACR pull).')
param umiResourceId string

@description('Resource id of the env VNet subnet for the pool.')
param subnetId string

@description('Shared ACR name (without .azurecr.io).')
param acrName string

@description('Training container image (tag included).')
param trainingImage string

@description('Imageryprep container image (tag included).')
param imageryprepImage string

var registryServer = '${acrName}.azurecr.io'

var autoscaleFormula = '$samples = $ActiveTasks.GetSamplePercent(TimeInterval_Minute * 15);$tasks = $samples < 70 ? max(0, $ActiveTasks.GetSample(1)) : max($ActiveTasks.GetSample(1), avg($ActiveTasks.GetSample(TimeInterval_Minute * 15)));$targetVMs = $tasks > 0 ? $tasks : max(0, $TargetDedicatedNodes / 2);$cappedPoolSize = ${maxNodes};$TargetDedicatedNodes = max(1, min($targetVMs, $cappedPoolSize));$NodeDeallocationOption = taskcompletion;'

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
    networkConfiguration: {
      subnetId: subnetId
      publicIPAddressConfiguration: {
        provision: 'BatchManaged'
      }
      dynamicVnetAssignmentScope: 'none'
      enableAcceleratedNetworking: false
    }
    scaleSettings: {
      autoScale: {
        formula: autoscaleFormula
        evaluationInterval: 'PT5M'
      }
    }
  }
}

output poolName string = pool.name
