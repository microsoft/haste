# Infrastructure setup

To perform the infrastructure setup, you need to run the `setup_infra.sh` script. This script will create the necessary resources in Azure for the HASTE project. You will need to replace the parameters with your own values for deployment.

If you delete the deployment you cannot use the same prefix or suffix again. You will need to change one of them with a new one or wait for a day or two for the resources to be deleted in the Azure backend.

```bash
cd setup

sh ./setup_infra.sh <YOUR_TENANT_ID> <YOUR_SUBSCRIPTION_ID> <YOUR_PREFIX> <YOUR_REGION> <YOUR_SUFFIX>

```

Example:
```bash
sh ./setup_infra.sh 00000000-0000-0000-0000-000000000000 11111111-1111-1111-1111-111111111111 haste westus2 dev
```

# Azure Container Registry

Add AcrPull RBAC role to the identity created by the setup access to the shared azure container registry.

# Azure Batch Setup

Pool Name: h100-ai4g-pool

Description: AI For Good BDA H100 Pool

Managed Identity: Yes / Add User Assigned Identity created by de setup script 

Node COnfig:

- OS Disk: 1023 GB (1TB) Premium SSD
- VM Size: Standard_NC40ads_H100_v5 - 40 vCPUs, 320 GB Memory
- VM Publisher: microsoft-dsvm
- VM Offer: ubuntu-hpc
- Sku: 22-04

Container config:

Server: {CONTAINER_REGISTRY}.azurecr.io

Managed Identity: Yes / Add User Assigned Identity created by de setup script

Images: 
- {CONTAINER_REGISTRY}.azurecr.io/hastetraining:latest
- {CONTAINER_REGISTRY}.azurecr.io/hasteimageryprep:latest

Scaling config:

- Select autoscale

- Auto scale formula:

```
// Get pending tasks for the past 15 minutes.
$samples = $ActiveTasks.GetSamplePercent(TimeInterval_Minute * 15);
// If we have fewer than 70 percent data points, we use the last sample point, otherwise we use the maximum of last sample point and the history average.
$tasks = $samples < 70 ? max(0, $ActiveTasks.GetSample(1)) : 
max( $ActiveTasks.GetSample(1), avg($ActiveTasks.GetSample(TimeInterval_Minute * 15)));
// If number of pending tasks is not 0, set targetVM to pending tasks, otherwise half of current dedicated.
$targetVMs = $tasks > 0 ? $tasks : max(0, $TargetDedicatedNodes / 2);
// The pool size is capped at 20, if target VM value is more than that, set it to 20. This value should be adjusted according to your use case.
cappedPoolSize = 3;
$TargetDedicatedNodes = max(1, min($targetVMs, cappedPoolSize));
// Set node deallocation mode - keep nodes active only until tasks finish
$NodeDeallocationOption = taskcompletion;

```

VNET Config:
- VNET: add vnet created by setup script



Example config of the pool:

```json
{
    "id": "h100-arc-pool",
    "displayName": "Pool for American Red cross",
    "url": "/subscriptions/{SUBSCRIPTION_ID}/resourceGroups/{RESOURCE_GROUP}/providers/Microsoft.Batch/batchAccounts/{BATCH_ACCOUNT_NAME}/pools/h100-arc-pool",
    "lastModified": "2025-04-21T15:13:37.947Z",
    "creationTime": "2025-04-21T15:09:27.740Z",
    "state": "active",
    "stateTransitionTime": "2025-04-21T15:09:27.740Z",
    "allocationState": "steady",
    "allocationStateTransitionTime": "2025-04-21T15:14:08.541Z",
    "vmSize": "STANDARD_NC40ads_H100_v5",
    "virtualMachineConfiguration": {
        "imageReference": {
            "publisher": "microsoft-dsvm",
            "offer": "ubuntu-hpc",
            "sku": "2204",
            "version": "latest",
            "virtualMachineImageId": null,
            "exactVersion": "latest"
        },
        "nodeAgentSKUId": "batch.node.ubuntu 22.04",
        "licenseType": null,
        "containerConfiguration": {
            "type": "dockerCompatible",
            "containerImageNames": [
                "{CONTAINER_REGISTRY}.azurecr.io/hastetraining:latest",
                "{CONTAINER_REGISTRY}.azurecr.io/hasteimageryprep:latest"
            ],
            "containerRegistries": [
                {
                    "username": null,
                    "password": null,
                    "registryServer": "{CONTAINER_REGISTRY}.azurecr.io",
                    "identityReference": {
                        "resourceId": "/subscriptions/{SUBSCRIPTION_ID}/resourceGroups/{RESOURCE_GROUP}/providers/Microsoft.ManagedIdentity/userAssignedIdentities/{USER_MANAGED_IDENTITY}"
                    }
                }
            ]
        },
        "diskEncryptionConfiguration": {},
        "nodePlacementConfiguration": {
            "policy": "regional"
        },
        "osDisk": {
            "caching": "none",
            "managedDisk": {
                "storageAccountType": "premium_lrs",
                "securityProfile": {}
            },
            "diskSizeGB": 1023,
            "writeAcceleratorEnabled": null
        }
    },
    "resizeTimeout": "PT15M",
    "currentDedicatedNodes": 1,
    "currentLowPriorityNodes": 0,
    "targetDedicatedNodes": 1,
    "targetLowPriorityNodes": 0,
    "enableAutoScale": true,
    "autoScaleFormula": "// Get pending tasks for the past 15 minutes.\n$samples = $ActiveTasks.GetSamplePercent(TimeInterval_Minute * 15);\n// If we have fewer than 70 percent data points, we use the last sample point, otherwise we use the maximum of last sample point and the history average.\n$tasks = $samples < 70 ? max(0, $ActiveTasks.GetSample(1)) : \nmax( $ActiveTasks.GetSample(1), avg($ActiveTasks.GetSample(TimeInterval_Minute * 15)));\n// If number of pending tasks is not 0, set targetVM to pending tasks, otherwise half of current dedicated.\n$targetVMs = $tasks > 0 ? $tasks : max(0, $TargetDedicatedNodes / 2);\n// The pool size is capped at 20, if target VM value is more than that, set it to 20. This value should be adjusted according to your use case.\ncappedPoolSize = 3;\n$TargetDedicatedNodes = max(1, min($targetVMs, cappedPoolSize));\n// Set node deallocation mode - keep nodes active only until tasks finish\n$NodeDeallocationOption = taskcompletion;",
    "autoScaleEvaluationInterval": "PT5M",
    "autoScaleRun": {
        "timestamp": "2025-04-24T11:34:37.971Z",
        "results": "$TargetDedicatedNodes=1;$TargetLowPriorityNodes=0;$NodeDeallocationOption=taskcompletion;$samples=96.6667;$targetVMs=0.5;$tasks=0;cappedPoolSize=3"
    },
    "enableInterNodeCommunication": false,
    "networkConfiguration": {
        "subnetId": "/subscriptions/{SUBSCRIPTION_ID}/resourceGroups/{NETWORK_RESOURCE_GROUP}/providers/Microsoft.Network/virtualNetworks/{VNET_NAME}/subnets/{SUBNET_NAME}",
        "dynamicVNetAssignmentScope": null,
        "publicIPAddressConfiguration": {
            "provision": "batchmanaged"
        },
        "enableAcceleratedNetworking": false
    },
    "taskSlotsPerNode": 1,
    "taskSchedulingPolicy": {
        "nodeFillType": "pack"
    },
    "identity": {
        "type": "UserAssigned",
        "userAssignedIdentities": [
            {
                "resourceId": "/subscriptions/{SUBSCRIPTION_ID}/resourceGroups/{RESOURCE_GROUP}/providers/Microsoft.ManagedIdentity/userAssignedIdentities/{USER_MANAGED_IDENTITY}",
                "clientId": "{CLIENT_ID_1}",
                "principalId": "{PRINCIPAL_ID_1}"
            },
            {
                "resourceId": "/subscriptions/{SUBSCRIPTION_ID}/resourceGroups/{NETWORK_RESOURCE_GROUP}/providers/Microsoft.ManagedIdentity/userAssignedIdentities/{NETWORK_USER_MANAGED_IDENTITY}",
                "clientId": "{CLIENT_ID_2}",
                "principalId": "{PRINCIPAL_ID_2}"
            }
        ]
    },
    "targetNodeCommunicationMode": "default",
    "currentNodeCommunicationMode": "classic",
    "upgradePolicy": {
        "mode": "Manual",
        "automaticOSUpgradePolicy": {
            "disableAutomaticRollback": false,
            "enableAutomaticOSUpgrade": false,
            "useRollingUpgradePolicy": false,
            "osRollingUpgradeDeferral": false
        },
        "rollingUpgradePolicy": {
            "enableCrossZoneUpgrade": null,
            "maxBatchInstancePercent": 20,
            "maxUnhealthyInstancePercent": 20,
            "maxUnhealthyUpgradedInstancePercent": 20,
            "pauseTimeBetweenBatches": "P0D",
            "prioritizeUnhealthyInstances": null,
            "rollbackFailedInstancesOnPolicyBreach": false
        }
    }
}
```