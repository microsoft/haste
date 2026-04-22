# !/bin/bash

# Script to set up Azure infrastructure using Azure CLI
# Usage: ./setup_infra.sh <tenant_id> <subscription_id> <resource_prefix> <location>
## Example: sh ./setup_infra.sh <tenant_id> <subscription_id> <resource_prefix> <location> <suffix>
set -e

if [ "$#" -lt 4 ] || [ "$#" -gt 5 ]; then
    echo "Usage: $0 <tenant_id> <subscription_id> <resource_prefix> <location> [random_suffix]"
    exit 1
fi

TENANT_ID=$1
SUBSCRIPTION_ID=$2
RESOURCE_PREFIX=$3
LOCATION=$4
RANDOM_SUFFIX=${5:-$(printf "%04d" $((RANDOM % 10000)))}

check_dependencies() {
    echo "Checking dependencies..."

    # Check for jq
    if ! command -v jq &> /dev/null; then
        echo "jq is not installed. Installing jq..."
        if [[ "$OSTYPE" == "linux-gnu"* ]]; then
            sudo apt-get update && sudo apt-get install -y jq
        elif [[ "$OSTYPE" == "darwin"* ]]; then
            brew install jq
        else
            echo "Unsupported OS. Please install jq manually."
            exit 1
        fi
    else
        echo "jq is installed. Version: $(jq --version)"
    fi

    # Check for npm
    if ! command -v npm &> /dev/null; then
        echo "npm is not installed. Installing npm..."
        if [[ "$OSTYPE" == "linux-gnu"* ]]; then
            sudo apt-get update && sudo apt-get install -y npm
        elif [[ "$OSTYPE" == "darwin"* ]]; then
            brew install npm
        else
            echo "Unsupported OS. Please install npm manually."
            exit 1
        fi
    else
        echo "npm is installed. Version: $(npm --version)"
    fi

    # Check for Azure CLI
    if ! command -v az &> /dev/null; then
        echo "Azure CLI is not installed. Installing Azure CLI..."
        if [[ "$OSTYPE" == "linux-gnu"* ]]; then
            curl -sL https://aka.ms/InstallAzureCLIDeb | sudo bash
        elif [[ "$OSTYPE" == "darwin"* ]]; then
            brew install azure-cli
        else
            echo "Unsupported OS. Please install Azure CLI manually."
            exit 1
        fi
    else
        echo "Azure CLI is installed. Version: $(az --version | head -n 1)"
    fi
    echo "All dependencies are installed."
}

check_dependencies

az config set core.login_experience_v2=off
az config set extension.use_dynamic_install=yes_without_prompt
az config set extension.dynamic_install_allow_preview=true
az config set extension.use_dynamic_install=yes_without_prompt
## Log in to Azure
az login --tenant "$TENANT_ID"
## Set Azure subscription
az account set --subscription "$SUBSCRIPTION_ID"

## Switches for resources to deploy or not based on the switch
## Set the switch variables to true or false
DeployFunctionApp=true
DeployStaticWebApp=true
DeployFunctionAppsToAPIM=true
DeployFunctionAppsOperationsToAPIM=true
UploadAdminSettings=true

EnableFrontDoor=false
## Set Shared services names and RG
SHARED_RESOURCE_GROUP="<REPLACE_ME>"
SHARED_BATCH_ACCOUNT="<REPLACE_ME>"
SHARED_BATCH_POOL_ID=
SHARED_BATCH_POOL_SUBNET="batch-subnet"
SHARED_ACR_NAME="<REPLACE_ME>"
SHARED_TRAINING_IMAGE="hastetraining:1.2.0"
SHARED_IMAGERYPREP_IMAGE="hasteimageryprep:1.2.0"
SHARED_APIM_PUBLISHER_EMAIL=""
SHARED_APIM_PUBLISHER_NAME="AI For Good Lab"
## Generate resource names
RESOURCE_GROUP="${RESOURCE_PREFIX}-haste-${RANDOM_SUFFIX}-rg"
STORAGE_ACCOUNT="${RESOURCE_PREFIX}haste${RANDOM_SUFFIX}sa"
STORAGE_FILE_ACCOUNT="${RESOURCE_PREFIX}haste${RANDOM_SUFFIX}fs"
USER_MANAGED_IDENTITY="${RESOURCE_PREFIX}-haste-${RANDOM_SUFFIX}-umi"
VNET="${RESOURCE_PREFIX}-haste-${RANDOM_SUFFIX}-vnet"
NSG="${RESOURCE_PREFIX}-haste-${RANDOM_SUFFIX}-nsg"
API_MANAGEMENT="${RESOURCE_PREFIX}-haste-${RANDOM_SUFFIX}-apim"
FUNCTION_API="${RESOURCE_PREFIX}haste${RANDOM_SUFFIX}func"
FUNCTION_TITILER_API="${RESOURCE_PREFIX}hastetitiler${RANDOM_SUFFIX}func"
FUNCTION_QUEUE_API="${RESOURCE_PREFIX}hastequeue${RANDOM_SUFFIX}func"
STATIC_WEB_APP="${RESOURCE_PREFIX}haste${RANDOM_SUFFIX}swa"
LOG_ANALYTICS_WORKSPACE="${RESOURCE_PREFIX}-haste-${RANDOM_SUFFIX}-law"
MAPS_ACCOUNT="${RESOURCE_PREFIX}haste${RANDOM_SUFFIX}maps"
WAF_POLICY_NAME="${RESOURCE_PREFIX}haste${RANDOM_SUFFIX}waf"
FRONTDOOR_NAME="${RESOURCE_PREFIX}haste${RANDOM_SUFFIX}fd"
FUNCTIONS_SUBNET="func-subnet"
# Email Comms and User management variables
STATIC_APP_DOMAIN=<REPLACE_ME>
EMAIL_CONNECTION_STRING=''
EMAIL_SENDER="DoNotReply@notifications.${STATIC_APP_DOMAIN}"

if [ -z "$SHARED_PUBLISHER_EMAIL" ]; then
    API_MANAGEMENT_PUBLISHER_EMAIL=$(az ad signed-in-user show --query "mail" -o tsv)
    if [ -z "$API_MANAGEMENT_PUBLISHER_EMAIL" ]; then
        echo "Error: SHARED_PUBLISHER_EMAIL is not set and could not be retrieved from Azure AD."
        exit 1
    fi
else
    API_MANAGEMENT_PUBLISHER_EMAIL="$SHARED_PUBLISHER_EMAIL"
fi
if [ -z "$SHARED_PUBLISHER_NAME" ]; then
    API_MANAGEMENT_PUBLISHER_NAME=$(az ad signed-in-user show --query "displayName" -o tsv)
    if [ -z "$API_MANAGEMENT_PUBLISHER_NAME" ]; then
        echo "Error: SHARED_PUBLISHER_NAME is not set and could not be retrieved from Azure AD."
        exit 1
    fi
else
    API_MANAGEMENT_PUBLISHER_NAME="$SHARED_PUBLISHER_NAME"
fi
## Set the shared variables for batch and acr
if [ -z "$SHARED_BATCH_ACCOUNT" ]; then
    BATCH_ACCOUNT="${RESOURCE_PREFIX}haste${RANDOM_SUFFIX}batch"
else
    BATCH_ACCOUNT="$SHARED_BATCH_ACCOUNT"
fi
if [ -z "$SHARED_BATCH_POOL_ID" ]; then
    BATCH_POOL_ID="$RESOURCE_PREFIX-haste-${RANDOM_SUFFIX}-pool"
else
    BATCH_POOL_ID="$SHARED_BATCH_POOL_ID"
fi
if [ -z "$SHARED_ACR_NAME" ]; then
    ACR_NAME="${RESOURCE_PREFIX}haste${RANDOM_SUFFIX}acr"
else
    ACR_NAME="$SHARED_ACR_NAME"
fi

## Create resource group
echo 'Does resource group exist?'
if [ "$(az group exists --name "$RESOURCE_GROUP")" = "false" ]; then
    az group create --name "$RESOURCE_GROUP" --location "$LOCATION"
else
    echo "Resource group $RESOURCE_GROUP already exists. Skipping creation."
fi

check_resource_exists() {
    local RESOURCE_TYPE=$1
    local RESOURCE_NAME=$2
    local RESOURCE_GROUP=$3
    if az resource list --resource-type "$RESOURCE_TYPE" --name "$RESOURCE_NAME" --resource-group "$RESOURCE_GROUP" --query "[?name=='$RESOURCE_NAME']" -o tsv | grep -q "$RESOURCE_NAME"; then
        echo "exists"
    else
        echo "not_exists"
    fi
}

create_group_and_umi() {
    ## Create user managed identity for communication between resources
    az identity create --name "$USER_MANAGED_IDENTITY" --resource-group "$RESOURCE_GROUP" --location "$LOCATION"
}

if [ "$(check_resource_exists "Microsoft.ManagedIdentity/userAssignedIdentities" "$USER_MANAGED_IDENTITY" "$RESOURCE_GROUP")" = "not_exists" ]; then
    create_group_and_umi
else
    echo "User Managed Identity already exists. Skipping creation."
fi

## Get/Set the API Management resource ID
USER_MANAGED_IDENTITY_ID=$(az identity show --name "$USER_MANAGED_IDENTITY" --resource-group "$RESOURCE_GROUP" --query id -o tsv)
USER_MANAGED_IDENTITY_PRINCIPAL_ID=$(az identity show --name "$USER_MANAGED_IDENTITY" --resource-group "$RESOURCE_GROUP" --query principalId -o tsv)

create_storage() {
    ## Create functions storage account
    az storage account create --name "$STORAGE_ACCOUNT" --resource-group "$RESOURCE_GROUP" --location "$LOCATION" --sku Standard_LRS --access-tier Hot --kind StorageV2
    ## Create a premium file storage account with a data share
    az storage account create --name "$STORAGE_FILE_ACCOUNT" --resource-group "$RESOURCE_GROUP" --location "$LOCATION" --sku Premium_LRS --kind FileStorage
    az storage share create --name data --account-name "$STORAGE_FILE_ACCOUNT" --quota 1000
    ## Assign the "Storage Blob Data Owner" role to the user managed identity for the storage account
    az role assignment create --assignee-object-id "$USER_MANAGED_IDENTITY_PRINCIPAL_ID" --assignee-principal-type ServicePrincipal --role "Storage Blob Data Owner" --scope "$(az storage account show --name "$STORAGE_ACCOUNT" --resource-group "$RESOURCE_GROUP" --query id -o tsv)"
    ## Assign the "Storage Blob Data Owner" role to the user managed identity for the file storage account
    az role assignment create --assignee-object-id "$USER_MANAGED_IDENTITY_PRINCIPAL_ID" --assignee-principal-type ServicePrincipal --role "Storage Blob Data Owner" --scope "$(az storage account show --name "$STORAGE_FILE_ACCOUNT" --resource-group "$RESOURCE_GROUP" --query id -o tsv)"
}

if [ "$(check_resource_exists "Microsoft.Storage/storageAccounts" "$STORAGE_ACCOUNT" "$RESOURCE_GROUP")" = "not_exists" ]; then
    create_storage
else
    echo "Storage account already exists. Skipping creation."
fi

configure_networking_and_logging() {
    ## Create virtual network and network security group
    az network vnet create --name "$VNET" --resource-group "$RESOURCE_GROUP" --location "$LOCATION" --address-prefixes 10.0.0.0/16 --subnet-name default --subnet-prefixes 10.0.0.0/24
    az network nsg create --name "$NSG" --resource-group "$RESOURCE_GROUP" --location "$LOCATION"
    az network vnet subnet update --vnet-name "$VNET" --name default --resource-group "$RESOURCE_GROUP" --network-security-group "$NSG"
    ## Update the subnet to delegate to Microsoft.Web/serverFarms
    az network vnet subnet update \
        --resource-group "$RESOURCE_GROUP" \
        --vnet-name "$VNET" \
        --name default \
        --delegations 'Microsoft.Web/serverFarms'
    ## Add another subnet for Azure Functions VNet integration
    az network vnet subnet create --name "$FUNCTIONS_SUBNET" --vnet-name "$VNET" --resource-group "$RESOURCE_GROUP" --address-prefixes 10.0.1.0/24 --delegations "Microsoft.Web/serverFarms"
    ## Add another subnet for Azure Batch Pool
    az network vnet subnet create --name "$SHARED_BATCH_POOL_SUBNET" --vnet-name "$VNET" --resource-group "$RESOURCE_GROUP" --address-prefixes 10.0.2.0/24

    ## Enable service endpoint for Microsoft.Storage on the default subnet
    az network vnet subnet update --resource-group "$RESOURCE_GROUP" --vnet-name "$VNET" --name default --service-endpoints Microsoft.Web
    az network vnet subnet update --resource-group "$RESOURCE_GROUP" --vnet-name "$VNET" --name default --service-endpoints Microsoft.Storage
    ## Enable service endpoint for Microsoft.Storage on the functions subnet
    az network vnet subnet update --resource-group "$RESOURCE_GROUP" --vnet-name "$VNET" --name "$FUNCTIONS_SUBNET" --service-endpoints Microsoft.Storage
     ## Enable service endpoint for Microsoft.Storage on the batch subnet
    az network vnet subnet update --resource-group "$RESOURCE_GROUP" --vnet-name "$VNET" --name "$SHARED_BATCH_POOL_SUBNET" --service-endpoints Microsoft.Storage
    ## Restrict storage account access to the default subnet and functions subnet
    az storage account network-rule add --resource-group "$RESOURCE_GROUP" --account-name "$STORAGE_ACCOUNT" --vnet-name "$VNET" --subnet default
    az storage account network-rule add --resource-group "$RESOURCE_GROUP" --account-name "$STORAGE_ACCOUNT" --vnet-name "$VNET" --subnet "$FUNCTIONS_SUBNET"
    az storage account network-rule add --resource-group "$RESOURCE_GROUP" --account-name "$STORAGE_ACCOUNT" --vnet-name "$VNET" --subnet "$SHARED_BATCH_POOL_SUBNET"
    ## Restrict file storage account access to the default subnet and functions subnet
    az storage account network-rule add --resource-group "$RESOURCE_GROUP" --account-name "$STORAGE_FILE_ACCOUNT" --vnet-name "$VNET" --subnet default
    az storage account network-rule add --resource-group "$RESOURCE_GROUP" --account-name "$STORAGE_FILE_ACCOUNT" --vnet-name "$VNET" --subnet "$FUNCTIONS_SUBNET"
    ## Associate the NSG to the functions subnet
    az network vnet subnet update --name "$FUNCTIONS_SUBNET" --vnet-name "$VNET" --resource-group "$RESOURCE_GROUP" --network-security-group "$NSG"
    ## Create Log Analytics workspace
    az monitor log-analytics workspace create --resource-group "$RESOURCE_GROUP" --workspace-name "$LOG_ANALYTICS_WORKSPACE" --location "$LOCATION"
}

if [ "$(check_resource_exists "Microsoft.Network/virtualNetworks" "$VNET" "$RESOURCE_GROUP")" = "not_exists" ]; then
    configure_networking_and_logging
else
    echo "Virtual network and NSG already exist. Skipping creation."
fi

##Get Log Analytics workspace ID
LOG_ANALYTICS_WORKSPACE_ID=$(az monitor log-analytics workspace show --resource-group "$RESOURCE_GROUP" --workspace-name "$LOG_ANALYTICS_WORKSPACE" --query id -o tsv)
## Create API Management resource using ARM template
create_apim() {
    ARM_TEMPLATE=$(cat <<EOF
{
  "\$schema": "https://schema.management.azure.com/schemas/2019-04-01/deploymentTemplate.json#",
  "contentVersion": "1.0.0.0",
  "parameters": {},
  "variables": {},
  "resources": [
    {
      "type": "Microsoft.ApiManagement/service",
      "apiVersion": "2024-06-01-preview",
      "name": "$API_MANAGEMENT",
      "location": "$LOCATION",
      "sku": {
        "name": "StandardV2",
        "capacity": 1
      },
      "identity": {
        "type": "SystemAssigned, UserAssigned",
        "userAssignedIdentities": {
          "/subscriptions/$SUBSCRIPTION_ID/resourceGroups/$RESOURCE_GROUP/providers/Microsoft.ManagedIdentity/userAssignedIdentities/$USER_MANAGED_IDENTITY": {}
        }
      },
      "properties": {
        "publisherEmail": "$API_MANAGEMENT_PUBLISHER_EMAIL",
        "publisherName": "$API_MANAGEMENT_PUBLISHER_NAME",
        "virtualNetworkType": "External",
        "virtualNetworkConfiguration": {
          "subnetResourceId": "/subscriptions/$SUBSCRIPTION_ID/resourceGroups/$RESOURCE_GROUP/providers/Microsoft.Network/virtualNetworks/$VNET/subnets/default"
        },
        "legacyPortalStatus": "Disabled",
        "developerPortalStatus": "Disabled",
        "releaseChannel": "Default"
      }
    }
  ]
}
EOF
    )

    ## Save ARM template to a temporary file
    ARM_TEMPLATE_FILE=$(mktemp)
    echo "$ARM_TEMPLATE" > "$ARM_TEMPLATE_FILE"

    ## Deploy ARM template using Azure CLI
    az deployment group create --resource-group "$RESOURCE_GROUP" --template-file "$ARM_TEMPLATE_FILE"
    ## Clean up temporary file
    rm -f "$ARM_TEMPLATE_FILE"
}

if [ "$(check_resource_exists "Microsoft.ApiManagement/service" "$API_MANAGEMENT" "$RESOURCE_GROUP")" = "not_exists" ]; then
    create_apim
    ### Get the API Management identity and assign roles
    APIM_SYSTEM_ASSIGNED_IDENTITY=$(az apim show --name "$API_MANAGEMENT" --resource-group "$RESOURCE_GROUP" --query "identity.principalId" -o tsv)
    echo "API Management System Assigned Managed Identity: $APIM_SYSTEM_ASSIGNED_IDENTITY"
    az role assignment create --assignee "$APIM_SYSTEM_ASSIGNED_IDENTITY" --role "Storage Blob Data Owner" --scope "$(az storage account show --name "$STORAGE_ACCOUNT" --resource-group "$RESOURCE_GROUP" --query id -o tsv)"
else
    echo "API Management resource already exists. Skipping creation."
fi

## Create Azure Functions
create_function_app() {
    local FUNCTION_NAME=$1
    local already_instances=$2
    az functionapp create --name "$FUNCTION_NAME" --resource-group "$RESOURCE_GROUP" --storage-account "$STORAGE_ACCOUNT" --flexconsumption-location westus2 --runtime python --runtime-version 3.11 --functions-version 4 --os-type Linux --app-insights-key "$(az monitor app-insights component create --app "$FUNCTION_NAME-ai" --location "$LOCATION" --resource-group "$RESOURCE_GROUP" --query instrumentationKey -o tsv)" --deployment-storage-auth-type "SystemAssignedIdentity" --assign-identity "$USER_MANAGED_IDENTITY_ID" --https-only true --instance-memory 4096 --always-ready-instances http=$already_instances
    echo "Function app $FUNCTION_NAME created. Next steps:"
    echo "1. Configure the function app disable ftps"
    az functionapp config set --name "$FUNCTION_NAME" --resource-group "$RESOURCE_GROUP" --ftps-state Disabled
    echo "2. Configure the function app vnet"
    echo "Enabling VNet access restriction for the function app"
    az functionapp config access-restriction add --name "$FUNCTION_NAME" --resource-group "$RESOURCE_GROUP" --rule-name "AllowVNet" --action Allow --vnet-name "$VNET" --subnet default --priority 100
    az functionapp config access-restriction add --name "$FUNCTION_NAME" --resource-group "$RESOURCE_GROUP" --rule-name "AllowVNet" --action Allow --vnet-name "$VNET" --subnet $FUNCTIONS_SUBNET --priority 200
    echo "Enabling VNet integration for the function app"
    az functionapp vnet-integration add --name "$FUNCTION_NAME" --resource-group "$RESOURCE_GROUP" --vnet "$VNET" --subnet "$FUNCTIONS_SUBNET"
    echo "3. Configure the function app to use the user managed identity"
    FUNCTION_PRINCIPAL_ID=$(az functionapp identity show --name "$FUNCTION_NAME" --resource-group "$RESOURCE_GROUP" --query principalId -o tsv)
    az role assignment create --assignee "$FUNCTION_PRINCIPAL_ID" --role "Storage Blob Data Owner" --scope "$(az storage account show --name "$STORAGE_ACCOUNT" --resource-group "$RESOURCE_GROUP" --query id -o tsv)"
    az role assignment create --assignee "$FUNCTION_PRINCIPAL_ID" --role "Storage Queue Data Contributor" --scope "$(az storage account show --name "$STORAGE_ACCOUNT" --resource-group "$RESOURCE_GROUP" --query id -o tsv)"
    echo "4. Configure the function app to use the storage accoun managed identity"
    az functionapp config appsettings set --name "$FUNCTION_NAME" --resource-group "$RESOURCE_GROUP" --settings "AzureWebJobsStorage__accountName=$STORAGE_ACCOUNT"
    az functionapp config appsettings delete --name "$FUNCTION_NAME" --resource-group "$RESOURCE_GROUP" --setting-names "AzureWebJobsStorage"
    echo "5. Configure app insights workspace"
    az monitor app-insights component update --app "$FUNCTION_NAME-ai" --resource-group "$RESOURCE_GROUP"  --workspace "$LOG_ANALYTICS_WORKSPACE_ID"
    echo "6. mount storage"
    az webapp config storage-account add --name "$FUNCTION_NAME" --resource-group "$RESOURCE_GROUP" --custom-id data --storage-type AzureFiles --account-name "$STORAGE_FILE_ACCOUNT" --share-name data --access-key "$(az storage account keys list --account-name "$STORAGE_FILE_ACCOUNT" --query '[0].value' -o tsv)" --mount-path /data
}


if [ "$(check_resource_exists "Microsoft.Web/sites" "$FUNCTION_API" "$RESOURCE_GROUP")" = "not_exists" ]; then
    create_function_app "$FUNCTION_API" 10
else
    echo "Function API resource already exists. Skipping creation."
fi
if [ "$(check_resource_exists "Microsoft.Web/sites" "$FUNCTION_TITILER_API" "$RESOURCE_GROUP")" = "not_exists" ]; then
    create_function_app "$FUNCTION_TITILER_API" 5
else
    echo "Function Titiler API resource already exists. Skipping creation."
fi
if [ "$(check_resource_exists "Microsoft.Web/sites" "$FUNCTION_QUEUE_API" "$RESOURCE_GROUP")" = "not_exists" ]; then
    create_function_app "$FUNCTION_QUEUE_API" 1
else
    echo "Function Queue API resource already exists. Skipping creation."
fi

create_acr_and_build() {
    ## Create Azure Container Registry currently not supported
    echo "Creating Azure Container Registry is not currently supported. Please create it manually. and set the shared variable: SHARED_ACR_NAME"
}

if [ "$(check_resource_exists "Microsoft.ContainerRegistry/registries" "$ACR_NAME" "$RESOURCE_GROUP")" = "not_exists" ]; then
    if [ "$(check_resource_exists "Microsoft.ContainerRegistry/registries" "$ACR_NAME" "$SHARED_RESOURCE_GROUP")" = "exists" ]; then
        echo "Azure Container Registry exists in the shared resource group. Skipping creation."
        ACR_NAME="$SHARED_ACR_NAME"
    else
        create_acr_and_build
    fi
else
    echo "Azure Container Registry resource already exists. Skipping creation."
fi
# Assign the User Assigned Identity to the Azure Container Registry with AcrPull role
assign_identity_to_acr() {
    ACR_ID=$(az acr show --name "$ACR_NAME" --resource-group "$SHARED_RESOURCE_GROUP" --query "id" -o tsv)
    if [ -z "$ACR_ID" ]; then
        echo "Error: Unable to fetch the ACR ID. Ensure the ACR exists and the name is correct."
        exit 1
    fi
    echo "Checking if the User Managed Identity is already assigned to ACR with AcrPull role..."
    # Check if the role assignment already exists
    if az role assignment list --assignee "$USER_MANAGED_IDENTITY_PRINCIPAL_ID" --scope "$ACR_ID" --role "AcrPull" --query "[].principalId" -o tsv | grep -q "$USER_MANAGED_IDENTITY_PRINCIPAL_ID"; then
        echo "Role assignment for AcrPull already exists for the User Managed Identity. Skipping creation."
    else
        echo "Assigning User Assigned Identity to ACR with AcrPull role..."
        az role assignment create \
            --assignee-object-id "$USER_MANAGED_IDENTITY_PRINCIPAL_ID" \
            --assignee-principal-type "ServicePrincipal" \
            --role "AcrPull" \
            --scope "$ACR_ID"
        echo "Role assignment for AcrPull created successfully."
    fi

    echo "User Assigned Identity is assigned to ACR with AcrPull role."
}

assign_identity_to_acr

create_batch_acct() {
    echo "Creating Azure Batch account is not currently supported. Please create it manually and set the shared variable: SHARED_BATCH_ACCOUNT. Then, try running the script again"
    exit 1
}

if [ "$(check_resource_exists "Microsoft.Batch/batchAccounts" "$BATCH_ACCOUNT" "$RESOURCE_GROUP")" = "not_exists" ]; then
    if [ "$(check_resource_exists "Microsoft.Batch/batchAccounts" "$BATCH_ACCOUNT" "$SHARED_RESOURCE_GROUP")" = "exists" ]; then
        echo "Azure Batch account exists in the shared resource group. Skipping creation."
        BATCH_ACCOUNT="$SHARED_BATCH_ACCOUNT"
        BATCH_ACCOUNT_PRIMARY_KEY=$(az batch account keys list --name "$BATCH_ACCOUNT" --resource-group "$SHARED_RESOURCE_GROUP" --query "primary" -o tsv)
    else
        create_batch_acct
        BATCH_ACCOUNT_PRIMARY_KEY=$(az batch account keys list --name "$BATCH_ACCOUNT" --resource-group "$RESOURCE_GROUP" --query "primary" -o tsv)
    fi
else
    echo "Azure Batch account resource already exists. Skipping creation."
fi

if [ -z "$BATCH_ACCOUNT_PRIMARY_KEY" ]; then
            echo "Error: Failed to retrieve the primary key for the batch account $SHARED_BATCH_ACCOUNT."
            exit 1
fi

echo "Azure Batch account $BATCH_ACCOUNT keys retrieved successfully."


create_batch_pool() {
local autoscaleFormula=$(cat <<EOF
\$samples = \$ActiveTasks.GetSamplePercent(TimeInterval_Minute * 15);
\$tasks = \$samples < 70 ? max(0, \$ActiveTasks.GetSample(1)) : max(\$ActiveTasks.GetSample(1), avg(\$ActiveTasks.GetSample(TimeInterval_Minute * 15)));
\$targetVMs = \$tasks > 0 ? \$tasks : max(0, \$TargetDedicatedNodes / 2);
\$cappedPoolSize = 3;
\$TargetDedicatedNodes = max(1, min(\$targetVMs, \$cappedPoolSize));
\$NodeDeallocationOption = taskcompletion;
EOF
)
    BICEP_TEMPLATE=$(cat <<EOF
resource batchPool 'Microsoft.Batch/batchAccounts/pools@2024-07-01' = {
    name: '${BATCH_ACCOUNT}/${BATCH_POOL_ID}'
    identity: {
        type: 'UserAssigned'
        userAssignedIdentities: {
            '/subscriptions/${SUBSCRIPTION_ID}/resourceGroups/${RESOURCE_GROUP}/providers/Microsoft.ManagedIdentity/userAssignedIdentities/${USER_MANAGED_IDENTITY}': {}
        }
    }
    properties: {
        vmSize: 'STANDARD_NC40ads_H100_v5'
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
                        '${ACR_NAME}.azurecr.io/${SHARED_TRAINING_IMAGE}'
                        '${ACR_NAME}.azurecr.io/${SHARED_IMAGERYPREP_IMAGE}'
                    ]
                    containerRegistries: [
                        {
                            registryServer: 'https://${ACR_NAME}.azurecr.io'
                            identityReference: {
                                resourceId: '/subscriptions/${SUBSCRIPTION_ID}/resourceGroups/${RESOURCE_GROUP}/providers/Microsoft.ManagedIdentity/userAssignedIdentities/${USER_MANAGED_IDENTITY}'
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
            subnetId: '/subscriptions/${SUBSCRIPTION_ID}/resourceGroups/${RESOURCE_GROUP}/providers/Microsoft.Network/virtualNetworks/${VNET}/subnets/${SHARED_BATCH_POOL_SUBNET}'
            publicIPAddressConfiguration: {
                provision: 'BatchManaged'
            }
            dynamicVnetAssignmentScope: 'None'
            enableAcceleratedNetworking: false
        }
        scaleSettings: {
            autoScale: {
                formula: '''$autoscaleFormula'''
                evaluationInterval: 'PT5M'
            }
        }
    }
}
EOF
    )

    # Save Bicep template to a temporary file
    BICEP_TEMPLATE_FILE=$(mktemp)
    BICEP_TEMPLATE_FILE="${BICEP_TEMPLATE_FILE}.bicep"
    echo "$BICEP_TEMPLATE" > "$BICEP_TEMPLATE_FILE"

    # Deploy Bicep template using Azure CLI
    az deployment group create --resource-group "$SHARED_RESOURCE_GROUP" --template-file "$BICEP_TEMPLATE_FILE"

    # Clean up temporary file
    rm -f "$BICEP_TEMPLATE_FILE"
}

if az batch pool show --account-name "$BATCH_ACCOUNT" --pool-id "$BATCH_POOL_ID" --account-endpoint "$BATCH_ACCOUNT.$LOCATION.batch.azure.com" &> /dev/null; then
    echo "Batch pool $BATCH_POOL_ID already exists. Skipping creation."
else
    echo "Creating Azure Batch pool..."
    create_batch_pool
fi

create_map_account() {
    az maps account create --name "$MAPS_ACCOUNT" --resource-group "$RESOURCE_GROUP" --kind "Gen2" --sku G2 --accept-tos
}
## Check if the Azure Maps account already exist
if [ "$(check_resource_exists "Microsoft.Maps/accounts" "$MAPS_ACCOUNT" "$RESOURCE_GROUP")" = "not_exists" ]; then
    create_map_account
else
    echo "Azure Maps account resource already exists. Skipping creation."
fi

create_static_app() {
    ## Create Azure Static Web App
    az staticwebapp create --name "$STATIC_WEB_APP" --resource-group "$RESOURCE_GROUP" --location "$LOCATION" --sku Standard --api-location "$API_MANAGEMENT"
    ## Associate API Management with Static Web App
    az staticwebapp backends link --name "$STATIC_WEB_APP" --resource-group "$RESOURCE_GROUP" --backend-resource-id "/subscriptions/$SUBSCRIPTION_ID/resourceGroups/$RESOURCE_GROUP/providers/Microsoft.ApiManagement/service/$API_MANAGEMENT"
}
## Check if the Azure Static Web App already exists
if [ "$(check_resource_exists "Microsoft.Web/staticSites" "$STATIC_WEB_APP" "$RESOURCE_GROUP")" = "not_exists" ]; then
    create_static_app
else
    echo "Azure Static Web App resource already exists. Skipping creation."
fi

# Deploy Azure Functions
deploy_function() {
    local FUNCTION_NAME=$1
    local FUNCTION_DIR=$2
    local SET_APPSETTINGS=${3:-true}
    local CONTINUE_ON_ERROR=${4:-false}
    AZ_FUNCTIONAPP_TAGS='tags.project=haste tags.env=prod tags.deployed_version=v1.2.0 tags.created_by=deploy_apps'
    # Check if the switch variable is set to true before setting appsettings
    if [ "${SET_APPSETTINGS:-true}" = "true" ]; then
        echo "Setting application settings for $FUNCTION_NAME"
        az functionapp config appsettings set --name "$FUNCTION_NAME" --resource-group "$RESOURCE_GROUP" --settings \
            "env=prod" \
            "IMAGE_QUEUE_NAME=image-layers-queue" \
            "INFERENCE_QUEUE_NAME=inference-queue" \
            "STATS_QUEUE_NAME=stats-queue" \
            "TRAIN_QUEUE_NAME=train-queue" \
            "ZIP_QUEUE_NAME=zip-queue" \
            "IMAGERY_STORAGE_TYPE=blob" \
            "METADATA_STORAGE_TYPE=blob" \
            "ARTIFACT_STORAGE_TYPE=blob" \
            "RUNNER_TYPE=azure_batch" \
            "TEMP_DATA_PATH=/data" \
            "DATA_PATH=/data" \
            "TITILER_ENDPOINT=/api/titiler/" \
            "QUEUE_ACCOUNT_URL=https://${STORAGE_ACCOUNT}.queue.core.windows.net" \
            "BLOB_ACCOUNT_URL=https://${STORAGE_ACCOUNT}.blob.core.windows.net" \
            "BLOB_CONTAINER=data" \
            "BLOB_CONNECTION_STRING=$(az storage account show-connection-string --name "$STORAGE_ACCOUNT" --resource-group "$RESOURCE_GROUP" --query connectionString -o tsv)" \
            "AZURE_BATCH_ACCOUNT_NAME=$BATCH_ACCOUNT" \
            "AZURE_BATCH_ACCOUNT_KEY=$(az batch account keys list --name "$BATCH_ACCOUNT" --resource-group "$SHARED_RESOURCE_GROUP" --query "primary" -o tsv)" \
            "AZURE_BATCH_IMAGERYPREP_DOCKER_IMAGE=${ACR_NAME}.azurecr.io/${IMAGEPREP_DOCKER_IMAGE}" \
            "AZURE_BATCH_DOCKER_IMAGE=${ACR_NAME}.azurecr.io/${TRAINING_DOCKER_IMAGE}" \
            "AZURE_BATCH_OUTPUT_CONTAINER_URL=https://${STORAGE_ACCOUNT}.blob.core.windows.net/data" \
            "AZURE_BATCH_TRAINING_POOL_ID=${BATCH_POOL_ID}" \
            "AZURE_BATCH_IMAGERYPREP_POOL_ID=${BATCH_IMAGEPREP_POOL_ID}" \
            "AZURE_BATCH_REGISTRY_SERVER_URL=https://${ACR_NAME}.azurecr.io" \
            "AZURE_BATCH_REGISTRY_IMAGE=${ACR_NAME}.azurecr.io/${TRAINING_DOCKER_IMAGE}" \
            "AZURE_BATCH_REGISTRY_IDENTITY_RESOURCE_ID=/subscriptions/$SUBSCRIPTION_ID/resourceGroups/$RESOURCE_GROUP/providers/Microsoft.ManagedIdentity/userAssignedIdentities/$USER_MANAGED_IDENTITY" \
            "STATIC_APP_SUBSCRIPTION_ID=$SUBSCRIPTION_ID" \
            "STATIC_APP_RESOURCE_GROUP=$RESOURCE_GROUP" \
            "STATIC_APP_NAME=$STATIC_WEB_APP" \
            "STATIC_APP_DOMAIN=${STATIC_APP_DOMAIN}" \
            "EMAIL_CONNECTION_STRING=${EMAIL_CONNECTION_STRING}" \
            "EMAIL_SENDER=${EMAIL_SENDER}"
    else
        echo "Skipping application settings for $FUNCTION_NAME as SET_APPSETTINGS is set to false."
    fi
    echo "Restarting Azure Function App $FUNCTION_NAME before deployment to avoid transient lock issues..."
    az functionapp restart --name "$FUNCTION_NAME" --resource-group "$RESOURCE_GROUP"
    (cd "$FUNCTION_DIR" && func azure functionapp publish "$FUNCTION_NAME" --python --build remote --verbose) || {
        if [ "$CONTINUE_ON_ERROR" = true ]; then
            echo "Warning: Deployment encountered an issue. Continuing execution as CONTINUE_ON_ERROR is set to true."
        else
            echo "Error: Deployment encountered an issue. Exiting as CONTINUE_ON_ERROR is not set to true."
            exit 1
        fi
    }
    echo "Setting tags for Function App $FUNCTION_NAME ..."
    az functionapp update --name "$FUNCTION_NAME" --resource-group "$RESOURCE_GROUP" --set $AZ_FUNCTIONAPP_TAGS

}

if [ "$DeployFunctionApp" = true ]; then
    echo "Deploying Function API: $FUNCTION_API"
    deploy_function "$FUNCTION_API" "$(dirname "$0")/../api/hastefuncapi" true true
    echo "Deploying Function Titiler API: $FUNCTION_TITILER_API"
    deploy_function "$FUNCTION_TITILER_API" "$(dirname "$0")/../api/titilerfuncapi" false true
    echo "Deploying Function Queue API: $FUNCTION_QUEUE_API"
    deploy_function "$FUNCTION_QUEUE_API" "$(dirname "$0")/../api/hastefuncqueues" true true
else
    echo "Skipping Function App deployment as DeployFunctionApp is set to false."
fi

## Get the hostname of the Static Web App
STATIC_WEB_APP_HOSTNAME=$(az staticwebapp show --name "$STATIC_WEB_APP" --resource-group "$RESOURCE_GROUP" --query "defaultHostname" -o tsv | cut -d '.' -f 1)
echo "Static Web App hostname: $STATIC_WEB_APP_HOSTNAME"
STATIC_WEB_APP_URL=$(az staticwebapp show --name "$STATIC_WEB_APP" --resource-group "$RESOURCE_GROUP" --query "defaultHostname" -o tsv | sed 's/^/https:\/\//')
echo "Static Web App URL: $STATIC_WEB_APP_URL"
## Add Azure Functions to API Management using ARM template
add_function_to_apim_with_arm() {
    local FUNCTION_NAME=$1
    local APIM_PATH=$2
    local API_SUFFIX=$3
    local API_MASTER_KEY=$4
    local API_LINK_GUID=$5
    local ADD_BACKEND=${6:-true}

    # Generate Bicep template for importing Azure Function into API Management
    BICEP_TEMPLATE=$(cat <<EOF
@description('Name of the Azure Function')
param functionName string = '$FUNCTION_NAME'

@description('Path for the API in API Management')
param apimPath string = '$APIM_PATH'

@description('API link GUID')
param apiLinkGuid string = '$API_LINK_GUID'

@description('Name of the API Management service')
param serviceApimName string = '$API_MANAGEMENT'

@description('Static Web App hostname')
param staticWebAppHost string = '$STATIC_WEB_APP_HOSTNAME'

@description('API suffix for the Azure Function')
param functionApiSuffix string = '$API_SUFFIX'

@description('Master key for the Azure Function')
@secure()
param functionApiMasterKey string = '$API_MASTER_KEY'

@description('Flag to add backend')
param addBackend bool = $ADD_BACKEND

resource api 'Microsoft.ApiManagement/service/apis@2024-06-01-preview' = {
  name: '${API_MANAGEMENT}/${FUNCTION_NAME}'
  properties: {
    displayName: functionName
    apiRevision: '1'
    description: 'Import from "${FUNCTION_NAME}" Function App'
    subscriptionRequired: true
    path: apimPath
    protocols: [
      'https'
    ]
    subscriptionKeyParameterNames: {
      header: 'Ocp-Apim-Subscription-Key'
      query: 'subscription-key'
    }
    isCurrent: true
  }
}

resource backend 'Microsoft.ApiManagement/service/backends@2024-06-01-preview' = if (addBackend) {
  name: '${API_MANAGEMENT}/${FUNCTION_NAME}'
  properties: {
    description: functionName
    url: 'https://${FUNCTION_NAME}.azurewebsites.net${API_SUFFIX}'
    protocol: 'http'
    resourceId: 'https://management.azure.com/subscriptions/$SUBSCRIPTION_ID/resourceGroups/$RESOURCE_GROUP/providers/Microsoft.Web/sites/$FUNCTION_NAME'
    credentials: {
      header: {
        'x-functions-key': [
          functionApiMasterKey
        ]
      }
    }
  }
}

resource productApi 'Microsoft.ApiManagement/service/products/apis@2024-06-01-preview' = {
  name: '${API_MANAGEMENT}/${STATIC_WEB_APP_HOSTNAME}/${FUNCTION_NAME}'
  dependsOn: [
    api
  ]
}
EOF
    )

    # Save Bicep template to a temporary file
    BICEP_TEMPLATE_FILE=$(mktemp)
    BICEP_TEMPLATE_FILE="${BICEP_TEMPLATE_FILE}.bicep"
    echo "$BICEP_TEMPLATE" > "$BICEP_TEMPLATE_FILE"

    # Deploy Bicep template using Azure CLI
    az deployment group create --resource-group "$RESOURCE_GROUP" --template-file "$BICEP_TEMPLATE_FILE"

    # Clean up temporary file
    rm -f "$BICEP_TEMPLATE_FILE"
}

# Get the master key for the FUNCTION_API
FUNCTION_API_MASTER_KEY=$(az functionapp keys list --name "$FUNCTION_API" --resource-group "$RESOURCE_GROUP" --query "masterKey" -o tsv)

if [ -z "$FUNCTION_API_MASTER_KEY" ]; then
    echo "Error: Failed to retrieve the master key for the function app $FUNCTION_API."
    exit 1
fi
echo "Master key for $FUNCTION_API retrieved successfully."

# check if AddFunctionAppsToAPIM is set to true
if [ "$DeployFunctionAppsToAPIM" = true ]; then
    echo "Adding Function API to API Management"
    add_function_to_apim_with_arm "$FUNCTION_API" "api/haste" "/api" "$FUNCTION_API_MASTER_KEY" "67d493043a07b81f689939fe" true  # pragma: allowlist secret
    echo "Adding Function Titiler API to API Management"
    add_function_to_apim_with_arm "$FUNCTION_TITILER_API" "api/titiler" "" "$FUNCTION_API_MASTER_KEY" "6807fb9e26dab60a10d70031" true  # pragma: allowlist secret
    echo "Adding hastestorageapi function to API Management"
    add_function_to_apim_with_arm "hastestorageapi" "api/haste/storage" "" "" "68080a3226dab60a10d70cb7" false  # pragma: allowlist secret
else
    echo "Skipping adding Function Apps to API Management as AddFunctionAppsToAPIM is set to false."
fi

deploy_operations_to_apim() {
    local FUNCTION_NAME=$1

    # List all operations of the FUNCTION_NAME using az functionapp list
    FUNCTION_OPERATIONS=$(az functionapp function list --name "$FUNCTION_NAME" --resource-group "$RESOURCE_GROUP" -o json)

    # Loop through each operation and deploy it to API Management
    echo "$FUNCTION_OPERATIONS" | jq -c '.[]' | while read -r OPERATION; do
        OPERATION_NAME=$(echo "$OPERATION" | jq -r '.config.name // (.id | split("/")[-1])')
        OPERATION_METHOD=$(echo "$OPERATION" | jq -r '.config.bindings[0].methods[0]')
        OPERATION_ROUTE=$(echo "$OPERATION" | jq -r '.config.bindings[0].route')

        echo "Processing operation: $OPERATION_NAME with method: $OPERATION_METHOD and route: $OPERATION_ROUTE"
                # Adjust the operation route if it contains a template with brackets
        case "$OPERATION_ROUTE" in
            *"{*"*"}"*)
                OPERATION_ROUTE=$(echo "$OPERATION_ROUTE" | sed 's/\*//g')
                echo "Operation route contains a template parameter: $OPERATION_ROUTE"
                OPERATION_ROUTE_PARAM=$(echo "$OPERATION_ROUTE" | sed 's/{//g;s/}//g')
                TEMPLATE_PARAMETERS="name=$OPERATION_ROUTE_PARAM required=true type=string"
                echo "Template parameters: $TEMPLATE_PARAMETERS"
                echo "Adjusted operation route: $OPERATION_ROUTE"
                ;;
            *)
                TEMPLATE_PARAMETERS=""
                ;;
        esac

        # Create the operation in API Management using az CLI
        if ! az apim api operation show \
            --resource-group "$RESOURCE_GROUP" \
            --service-name "$API_MANAGEMENT" \
            --api-id "$FUNCTION_NAME" \
            --operation-id "$OPERATION_NAME" > /dev/null 2>&1; then
            az apim api operation create \
            --resource-group "$RESOURCE_GROUP" \
            --service-name "$API_MANAGEMENT" \
            --api-id "$FUNCTION_NAME" \
            --operation-id "$OPERATION_NAME" \
            --display-name "$OPERATION_NAME" \
            --method "$(echo "$OPERATION_METHOD" | tr '[:lower:]' '[:upper:]')" \
            --url-template "/$OPERATION_ROUTE" \
            $( [ -n "$TEMPLATE_PARAMETERS" ] && echo "--template-parameters $TEMPLATE_PARAMETERS" )

            echo "Operation $OPERATION_NAME deployed to API Management."

            # Add operation policy using ARM template
            BICEP_TEMPLATE=$(cat <<EOF
resource operationPolicy 'Microsoft.ApiManagement/service/apis/operations/policies@2024-06-01-preview' = {
  name: '$API_MANAGEMENT/$FUNCTION_NAME/$OPERATION_NAME/policy'
  properties: {
    value: '''
<policies>
  <inbound>
    <base />
    <set-backend-service id="apim-generated-policy" backend-id="$FUNCTION_NAME" />
  </inbound>
  <backend>
    <base />
  </backend>
  <outbound>
    <base />
  </outbound>
  <on-error>
    <base />
  </on-error>
</policies>
'''
    format: 'xml'
  }
}
EOF
            )

            # Save Bicep template to a temporary file
            BICEP_TEMPLATE_FILE=$(mktemp)
            BICEP_TEMPLATE_FILE="${BICEP_TEMPLATE_FILE}.bicep"
            echo "$BICEP_TEMPLATE" > "$BICEP_TEMPLATE_FILE"

            # Deploy Bicep template using Azure CLI
            az deployment group create --resource-group "$RESOURCE_GROUP" --template-file "$BICEP_TEMPLATE_FILE"

            # Clean up temporary file
            rm -f "$BICEP_TEMPLATE_FILE"

            echo "Policy for operation $OPERATION_NAME added to API Management."
        else
            echo "Operation $OPERATION_NAME already exists. Skipping creation."
        fi
    done
}

## Call the function for both FUNCTION_API and FUNCTION_TITILER_API
if [ "$DeployFunctionAppsOperationsToAPIM" = true ]; then
    echo "Deploying operations for Function API to API Management"
    deploy_operations_to_apim "$FUNCTION_API"
    deploy_operations_to_apim "$FUNCTION_TITILER_API"
else
    echo "Skipping deployment of operations for Function API to API Management as DeployFunctionAppsOperationsToAPIM is set to false."
fi

deploy_titiler_tiles_operation() {
    local API_ID=$1
    local OPERATION_NAME="get-tiles"
    local METHOD="GET"
    local URL_TEMPLATE="/cog/tiles/WebMercatorQuad/{z}/{x}/{y}"
    local POLICY_VALUE="<policies>
  <inbound>
    <base />
    <set-backend-service id=\"apim-generated-policy\" backend-id=\"$API_ID\" />
  </inbound>
  <backend>
    <base />
  </backend>
  <outbound>
    <base />
  </outbound>
  <on-error>
    <base />
  </on-error>
</policies>"

    # Check if the operation already exists
    if ! az apim api operation show \
        --resource-group "$RESOURCE_GROUP" \
        --service-name "$API_MANAGEMENT" \
        --api-id "$API_ID" \
        --operation-id "$OPERATION_NAME" > /dev/null 2>&1; then

        # Deploy the operation
        echo "Deploying titiler tiles operation to API Management"
        echo "Deploying operation $OPERATION_NAME for API $API_ID to API Management..."

        az apim api operation create \
            --resource-group "$RESOURCE_GROUP" \
            --service-name "$API_MANAGEMENT" \
            --api-id "$API_ID" \
            --operation-id "$OPERATION_NAME" \
            --display-name "$OPERATION_NAME" \
            --method "$METHOD" \
            --url-template "$URL_TEMPLATE" \
            --template-parameters name=z required=true type=string \
            --template-parameters name=x required=true type=string \
            --template-parameters name=y required=true type=string

        echo "Operation $OPERATION_NAME created successfully."

        # Deploy the policy using Bicep
        BICEP_TEMPLATE=$(cat <<EOF
resource operationPolicy 'Microsoft.ApiManagement/service/apis/operations/policies@2024-06-01-preview' = {
  name: '$API_MANAGEMENT/$API_ID/$OPERATION_NAME/policy'
  properties: {
    value: '''
$POLICY_VALUE
'''
    format: 'xml'
  }
}
EOF
        )

        # Save Bicep template to a temporary file
        BICEP_TEMPLATE_FILE=$(mktemp)
        BICEP_TEMPLATE_FILE="${BICEP_TEMPLATE_FILE}.bicep"
        echo "$BICEP_TEMPLATE" > "$BICEP_TEMPLATE_FILE"

        # Deploy Bicep template using Azure CLI
        az deployment group create --resource-group "$RESOURCE_GROUP" --template-file "$BICEP_TEMPLATE_FILE"

        # Clean up temporary file
        rm -f "$BICEP_TEMPLATE_FILE"

        echo "Policy for operation $OPERATION_NAME added successfully using Bicep."
    else
        echo "Operation $OPERATION_NAME already exists. Skipping creation."
    fi
}

deploy_titiler_tiles_operation "$FUNCTION_TITILER_API"

deploy_storage_operations() {
    # First operation: get-artifacts
    local API_ID="hastestorageapi"
    local OPERATION_NAME="get-artifacts"
    local METHOD="GET"
    local URL_TEMPLATE="/get-artifacts/{container}/{projectDir}/{modelDir}/{fileName}"
    local POLICY_VALUE="<policies>
  <inbound>
    <send-request mode=\"new\" timeout=\"20\" response-variable-name=\"blobdata\" ignore-error=\"false\">
      <set-url>@{ return \"https://${STORAGE_ACCOUNT}.blob.core.windows.net/\" + (string)context.Request.MatchedParameters[\"container\"] + \"/\" + (string)context.Request.MatchedParameters[\"projectDir\"] + \"/\" + (string)context.Request.MatchedParameters[\"modelDir\"]+ \"/\" + (string)context.Request.MatchedParameters[\"fileName\"]; }</set-url>
      <set-method>GET</set-method>
      <set-header name=\"x-ms-version\" exists-action=\"override\">
        <value>2019-07-07</value>
      </set-header>
      <authentication-managed-identity resource=\"https://storage.azure.com\" />
    </send-request>
    <return-response response-variable-name=\"blobdata\" />
    <base />
  </inbound>
  <backend>
    <base />
  </backend>
  <outbound>
    <base />
  </outbound>
  <on-error>
    <base />
  </on-error>
</policies>"

    # Check if the operation already exists
    if ! az apim api operation show \
        --resource-group "$RESOURCE_GROUP" \
        --service-name "$API_MANAGEMENT" \
        --api-id "$API_ID" \
        --operation-id "$OPERATION_NAME" > /dev/null 2>&1; then

        # Deploy the operation
        echo "Deploying operation $OPERATION_NAME for API $API_ID to API Management..."
        az apim api operation create \
            --resource-group "$RESOURCE_GROUP" \
            --service-name "$API_MANAGEMENT" \
            --api-id "$API_ID" \
            --operation-id "$OPERATION_NAME" \
            --display-name "$OPERATION_NAME" \
            --method "$METHOD" \
            --url-template "$URL_TEMPLATE" \
            --template-parameters name=container required=true type=string \
            --template-parameters name=projectDir required=true type=string \
            --template-parameters name=modelDir required=true type=string \
            --template-parameters name=fileName required=true type=string

        echo "Operation $OPERATION_NAME created successfully."

        # Deploy the policy using Bicep
        BICEP_TEMPLATE=$(cat <<EOF
resource operationPolicy 'Microsoft.ApiManagement/service/apis/operations/policies@2024-06-01-preview' = {
  name: '$API_MANAGEMENT/$API_ID/$OPERATION_NAME/policy'
  properties: {
    value: '''
$POLICY_VALUE
'''
    format: 'xml'
  }
}
EOF
        )

        # Save Bicep template to a temporary file
        BICEP_TEMPLATE_FILE=$(mktemp)
        BICEP_TEMPLATE_FILE="${BICEP_TEMPLATE_FILE}.bicep"
        echo "$BICEP_TEMPLATE" > "$BICEP_TEMPLATE_FILE"

        # Deploy Bicep template using Azure CLI
        az deployment group create --resource-group "$RESOURCE_GROUP" --template-file "$BICEP_TEMPLATE_FILE"

        # Clean up temporary file
        rm -f "$BICEP_TEMPLATE_FILE"

        echo "Policy for operation $OPERATION_NAME added successfully using Bicep."
    else
        echo "Operation $OPERATION_NAME already exists. Skipping creation."
    fi

    # Second operation: get-project-artifacts (duplicate of get-artifacts)
    local OPERATION_NAME_2="get-project-artifacts"
    local URL_TEMPLATE_2="/get-project-artifacts/{container}/{projectDir}/{fileName}"

    local POLICY_VALUE_2="<policies>
  <inbound>
    <send-request mode=\"new\" timeout=\"20\" response-variable-name=\"blobdata\" ignore-error=\"false\">
      <set-url>@{ return \"https://${STORAGE_ACCOUNT}.blob.core.windows.net/\" + (string)context.Request.MatchedParameters[\"container\"] + \"/\" + (string)context.Request.MatchedParameters[\"projectDir\"] + \"/\" + (string)context.Request.MatchedParameters[\"fileName\"]; }</set-url>
      <set-method>GET</set-method>
      <set-header name=\"x-ms-version\" exists-action=\"override\">
        <value>2019-07-07</value>
      </set-header>
      <authentication-managed-identity resource=\"https://storage.azure.com\" />
    </send-request>
    <return-response response-variable-name=\"blobdata\" />
    <base />
  </inbound>
  <backend>
    <base />
  </backend>
  <outbound>
    <base />
  </outbound>
  <on-error>
    <base />
  </on-error>
</policies>"

    # Check if the second operation already exists
    if ! az apim api operation show \
        --resource-group "$RESOURCE_GROUP" \
        --service-name "$API_MANAGEMENT" \
        --api-id "$API_ID" \
        --operation-id "$OPERATION_NAME_2" > /dev/null 2>&1; then

        # Deploy the second operation
        echo "Deploying operation $OPERATION_NAME_2 for API $API_ID to API Management..."
        az apim api operation create \
            --resource-group "$RESOURCE_GROUP" \
            --service-name "$API_MANAGEMENT" \
            --api-id "$API_ID" \
            --operation-id "$OPERATION_NAME_2" \
            --display-name "$OPERATION_NAME_2" \
            --method "$METHOD" \
            --url-template "$URL_TEMPLATE_2" \
            --template-parameters name=container required=true type=string \
            --template-parameters name=projectDir required=true type=string \
            --template-parameters name=fileName required=true type=string

        echo "Operation $OPERATION_NAME_2 created successfully."

        # Deploy the policy using Bicep (reusing the same policy)
        BICEP_TEMPLATE_2=$(cat <<EOF
resource operationPolicy 'Microsoft.ApiManagement/service/apis/operations/policies@2024-06-01-preview' = {
  name: '$API_MANAGEMENT/$API_ID/$OPERATION_NAME_2/policy'
  properties: {
    value: '''
$POLICY_VALUE_2
'''
    format: 'xml'
  }
}
EOF
        )

        # Save Bicep template to a temporary file
        BICEP_TEMPLATE_FILE_2=$(mktemp)
        BICEP_TEMPLATE_FILE_2="${BICEP_TEMPLATE_FILE_2}.bicep"
        echo "$BICEP_TEMPLATE_2" > "$BICEP_TEMPLATE_FILE_2"

        # Deploy Bicep template using Azure CLI
        az deployment group create --resource-group "$RESOURCE_GROUP" --template-file "$BICEP_TEMPLATE_FILE_2"

        # Clean up temporary file
        rm -f "$BICEP_TEMPLATE_FILE_2"

        echo "Policy for operation $OPERATION_NAME_2 added successfully using Bicep."
    else
        echo "Operation $OPERATION_NAME_2 already exists. Skipping creation."
    fi
}

deploy_storage_operations

set_cors_for_functions() {
    local FUNCTION_NAME=$1
    local STATIC_APP_HOST=$STATIC_WEB_APP_URL
    local CORS_ALLOWED_ORIGINS="https://portal.azure.com ${STATIC_APP_HOST} https://${API_MANAGEMENT}.azure-api.net"

    echo "Setting CORS for $FUNCTION_NAME with allowed origins: $CORS_ALLOWED_ORIGINS"

    # Check if the origin already exists
    EXISTING_CORS=$(az functionapp cors show --name "$FUNCTION_NAME" --resource-group "$RESOURCE_GROUP" --query "allowedOrigins" -o tsv)

    if echo "$EXISTING_CORS" | grep -q "$STATIC_APP_HOST"; then
        echo "CORS origin $STATIC_APP_HOST already exists for $FUNCTION_NAME. Skipping addition."
    else
        echo "Adding CORS origin $STATIC_APP_HOST to $FUNCTION_NAME."
        az functionapp cors add --name "$FUNCTION_NAME" --resource-group "$RESOURCE_GROUP" --allowed-origins "$STATIC_APP_HOST"
    fi

    az functionapp cors add --name "$FUNCTION_NAME" --resource-group "$RESOURCE_GROUP" --allowed-origins $CORS_ALLOWED_ORIGINS
}

set_cors_for_functions "$FUNCTION_API"
set_cors_for_functions "$FUNCTION_TITILER_API"
set_cors_for_functions "$FUNCTION_QUEUE_API"

upload_admin_settings() {
    local FILE_NAME="config_admin_settings.json"

    echo "disabling storage network restrictions.."

    az storage account update --name "$STORAGE_ACCOUNT" --resource-group "$RESOURCE_GROUP" --bypass Logging Metrics AzureServices --default-action Allow --allow-shared-key-access true

    echo "Checking if the container 'data' exists in the storage account..."
    if ! az storage container exists --name "data" --account-name "$STORAGE_ACCOUNT" --query "exists" -o tsv | grep -q "true"; then
        echo "Creating a container named 'data' in the storage account..."
        az storage container create --name "data" --account-name "$STORAGE_ACCOUNT" --resource-group "$RESOURCE_GROUP"
        echo "Container 'data' created successfully."
    else
        echo "Container 'data' already exists. Skipping creation."
    fi

    echo "waiting for 10 seconds to allow network restrictions to be disabled..."
    sleep 10
    echo "Checking if $FILE_NAME exists in the blob storage..."
    if ! az storage blob exists --account-name "$STORAGE_ACCOUNT" --container-name "data" --name "$FILE_NAME" --query "exists" -o tsv | grep -q "true"; then
        echo "Uploading admin settings to blob storage..."
        az storage blob upload --account-name "$STORAGE_ACCOUNT" --container-name "data" --name "$FILE_NAME" --file "$FILE_NAME" --overwrite
        echo "$FILE_NAME generated and uploaded successfully."
    else
        echo "$FILE_NAME already exists in the blob storage. Skipping generation and upload."
    fi
}

if [ "$UploadAdminSettings" = true ]; then
    upload_admin_settings
else
    echo "Skipping upload of admin settings as UploadAdminSettings is set to false."
fi

echo "Enabling access restriction for the storage account and allowing logging, metrics, and Azure trusted services bypass..."

az storage account update --name "$STORAGE_ACCOUNT" --resource-group "$RESOURCE_GROUP" --bypass Logging Metrics AzureServices --default-action Deny --allow-shared-key-access true
az storage account update --name "$STORAGE_FILE_ACCOUNT" --resource-group "$RESOURCE_GROUP" --bypass Logging Metrics AzureServices --default-action Deny --allow-shared-key-access true


create_frontdoor_and_waf() {
    # Create WAF policy if it doesn't exist
    if [ "$(check_resource_exists "Microsoft.Network/frontDoorWebApplicationFirewallPolicies" "$WAF_POLICY_NAME" "$RESOURCE_GROUP")" = "not_exists" ]; then
        echo "Creating WAF policy $WAF_POLICY_NAME..."
        az network front-door waf-policy create \
            --name "$WAF_POLICY_NAME" \
            --resource-group "$RESOURCE_GROUP" \
            --mode Prevention

        # Add managed rule set to WAF policy
        az network front-door waf-policy managed-rules add --policy-name "$WAF_POLICY_NAME" --resource-group "$RESOURCE_GROUP" --type DefaultRuleSet --version 1.0
        az network front-door waf-policy managed-rules add --policy-name "$WAF_POLICY_NAME" --resource-group "$RESOURCE_GROUP" --type Microsoft_BotManagerRuleSet --version 1.0
    else
        echo "WAF policy $WAF_POLICY_NAME already exists. Skipping creation."
    fi
    # Create Front Door if it doesn't exist
    if [ "$(check_resource_exists "Microsoft.Cdn/profiles" "$FRONTDOOR_NAME" "$RESOURCE_GROUP")" = "not_exists" ]; then
        echo "Creating Front Door $FRONTDOOR_NAME..."
        STATIC_WEB_APP_HOSTNAME=$(az staticwebapp show --name "$STATIC_WEB_APP" --resource-group "$RESOURCE_GROUP" --query "defaultHostname" -o tsv)
        WAF_POLICY_ID=$(az network front-door waf-policy show --name "$WAF_POLICY_NAME" --resource-group "$RESOURCE_GROUP" --query "id" -o tsv)
        echo "WAF Policy ID: $WAF_POLICY_ID"
        az afd profile create \
            --resource-group "$RESOURCE_GROUP" \
            --profile-name "$FRONTDOOR_NAME" \
            --sku Premium_AzureFrontDoor \
            --identity-type SystemAssigned
        # Create an endpoint for the Front Door
        # Create the origin group
        az afd origin-group create \
            --name "${FRONTDOOR_NAME}-origin-group" \
            --profile-name "$FRONTDOOR_NAME" \
            --resource-group "$RESOURCE_GROUP" \
            --probe-path "/" \
            --enable-health-probe  1 \
            --probe-protocol Https \
            --probe-request-type GET \
            --probe-interval-in-seconds 30 \
            --sample-size 4 \
            --successful-samples-required 3 \
            --additional-latency-in-milliseconds 50

        # Create the origin
        az afd origin create \
            --name "${FRONTDOOR_NAME}-origin" \
            --origin-group-name "${FRONTDOOR_NAME}-origin-group" \
            --profile-name "$FRONTDOOR_NAME" \
            --resource-group "$RESOURCE_GROUP" \
            --host-name "$STATIC_WEB_APP_HOSTNAME" \
            --enabled-state Enabled \
            --origin-host-header "$STATIC_WEB_APP_HOSTNAME"

        # Create the endpoint
        az afd endpoint create \
            --resource-group "$RESOURCE_GROUP" \
            --profile-name "$FRONTDOOR_NAME" \
            --endpoint-name "${FRONTDOOR_NAME}-endpoint" \
            --enabled-state Enabled
        # Add a route for the endpoint
        az afd route create \
            --resource-group "$RESOURCE_GROUP" \
            --profile-name "$FRONTDOOR_NAME" \
            --endpoint-name "${FRONTDOOR_NAME}-endpoint" \
            --name "default-route" \
            --origin-group "${FRONTDOOR_NAME}-origin-group" \
            --patterns-to-match "/*" \
            --forwarding-protocol MatchRequest \
            --https-redirect Enabled \
            --enabled-state Enabled \
            --link-to-default-domain Enabled \
            --enable-caching 1 \
            --enable-compression 1 \
            --query-string-cache-behavior UseQueryString
        # Create a rule set and a rule for Front Door
        create_rule_set_and_rule() {
            az afd rule-set create \
                --resource-group "$RESOURCE_GROUP" \
                --profile-name "$FRONTDOOR_NAME" \
                --rule-set-name "Security"
            # Add a rule to the rule set
            az afd rule create \
                --name "NoCacheAuthRequests" \
                --resource-group "$RESOURCE_GROUP" \
                --profile-name "$FRONTDOOR_NAME" \
                --rule-set-name "Security" \
                --action-name "RouteConfigurationOverride" \
                --cache-behavior "BypassCache" \
                --match-processing-behavior "Continue" \
                --match-variable "RequestPath" \
                --operator "BeginsWith" \
                --match-values "/.auth" \
                --order 1

            # Associate the rule set with the route
            az afd route update \
                --resource-group "$RESOURCE_GROUP" \
                --profile-name "$FRONTDOOR_NAME" \
                --endpoint-name "${FRONTDOOR_NAME}-endpoint" \
                --name "default-route" \
                --rule-sets "Security"

            echo "Rule set and rule created and associated with the route successfully."
        }

        create_rule_set_and_rule

        az afd security-policy create \
            --resource-group "$RESOURCE_GROUP" \
            --profile-name "$FRONTDOOR_NAME" \
            --name "${FRONTDOOR_NAME}-security-policy" \
            --domains "/subscriptions/$SUBSCRIPTION_ID/resourceGroups/$RESOURCE_GROUP/providers/Microsoft.Cdn/profiles/$FRONTDOOR_NAME/afdEndpoints/${FRONTDOOR_NAME}-endpoint" \
            --waf-policy "$WAF_POLICY_ID"
    else
        echo "Front Door $FRONTDOOR_NAME already exists. Skipping creation."
    fi
    echo "Azure Front Door and WAF policy setup completed successfully."
}

if [ "$EnableFrontDoor" = true ]; then
    create_frontdoor_and_waf
else
    echo "Skipping Front Door and WAF creation as EnableFrontDoor is set to false."
fi

deploy_static_web_app() {
    echo "Deploying Static Web App..."
    AZ_RESOURCE_TAGS='project=haste env=prod deployed_version=v1.2.0 created_by=deploy_apps'
    ## Get the primary key for the Azure Maps account
    MAPS_ACCOUNT_KEY=$(az maps account keys list --name "$MAPS_ACCOUNT" --resource-group "$RESOURCE_GROUP" --query primaryKey -o tsv)
    echo "Azure Maps account $MAPS_ACCOUNT created successfully with key $MAPS_ACCOUNT_KEY."


    # Navigate to the UI directory
    cd ../ui || { echo "UI directory not found"; exit 1; }

    # Create the .env file with the required content
    cat <<EOF > .env
VITE_APP_MASTER_KEY=$FUNCTION_API_MASTER_KEY
VITE_AZURE_MAPS_KEY=$MAPS_ACCOUNT_KEY
VITE_API_URL=/api/haste/
VITE_STORAGE_APIM_URL=/api/haste/storage/get-artifacts
VITE_PROJECT_STORAGE_APIM_URL=/api/haste/storage/get-project-artifacts
VITE_REDIRECT_URI=$STATIC_WEB_APP_URL
VITE_AZURE_SUBSCRIPTION_ID=$SUBSCRIPTION_ID
VITE_AZURE_TENANT_ID=$TENANT_ID
EOF
    npm install vite --save-dev
    # Build the UI
    swa build --auto

    # Read the content of staticwebapp.config.json
    STATIC_WEBAPP_CONFIG_FILE="./dist/staticwebapp.config.json"
    if [ -f "$STATIC_WEBAPP_CONFIG_FILE" ]; then
        echo "Reading staticwebapp.config.json..."
        STATIC_WEBAPP_CONFIG=$(cat "$STATIC_WEBAPP_CONFIG_FILE")
    else
        echo "Error: staticwebapp.config.json not found in ./dist directory."
        exit 1
    fi

    if [ "$EnableFrontDoor" = true ]; then
        # Add networking and forwardingGateway configurations
        FRONT_DOOR_ID=$(az afd profile show --resource-group "$RESOURCE_GROUP" --profile-name "$FRONTDOOR_NAME" --query "frontDoorId" -o tsv)
        FRONT_DOOR_HOST=$(az afd endpoint show --resource-group "$RESOURCE_GROUP" --profile-name "$FRONTDOOR_NAME" --endpoint-name "${FRONTDOOR_NAME}-endpoint" --query "hostName" -o tsv)

        UPDATED_CONFIG=$(echo "$STATIC_WEBAPP_CONFIG" | jq \
            --arg fdid "$FRONT_DOOR_ID" \
            --arg fdhost "$FRONT_DOOR_HOST" \
            '. + {
                networking: {
                    allowedIpRanges: ["AzureFrontDoor.Backend"]
                },
                forwardingGateway: {
                    requiredHeaders: {
                        "X-Azure-FDID": $fdid
                    },
                    allowedForwardedHosts: [$fdhost]
                }
            }')
        # Write the updated configuration back to the file
        echo "$UPDATED_CONFIG" > "$STATIC_WEBAPP_CONFIG_FILE"
        echo "Updated staticwebapp.config.json with networking and forwardingGateway configurations."
        # Display the content of the staticwebapp.config.json file
        echo "Content of staticwebapp.config.json:"
        cat "$STATIC_WEBAPP_CONFIG_FILE"
    fi
    # Deploy the Static Web App
    swa deploy --app-location ./dist \
        --app-name "$STATIC_WEB_APP" \
        --tenant-id "$TENANT_ID" \
        --subscription-id "$SUBSCRIPTION_ID" \
        --env Production \
        --deployment-token "$(az staticwebapp secrets list --name "$STATIC_WEB_APP" --resource-group "$RESOURCE_GROUP" --query "properties.apiKey" -o tsv)"

    echo "Static Web App deployed successfully."
    echo "Setting tags for Static Web App $STATIC_WEB_APP ..."
    az staticwebapp update --name "$STATIC_WEB_APP" --resource-group "$RESOURCE_GROUP" --tags $AZ_RESOURCE_TAGS
}

if [ "$DeployStaticWebApp" = true ]; then
    echo "Deploying Static Web App: $STATIC_WEB_APP"
    deploy_static_web_app
else
    echo "Skipping Static Web App deployment as DeployStaticWebApp is set to false."
fi

echo "Azure infrastructure setup completed successfully."
echo "----------------------------------------------------"

get_user_email() {
    echo "Fetching the email of the user principal executing the Azure CLI commands..."
    USER_EMAIL=$(az ad signed-in-user show --query "mail" -o tsv)
    if [ -z "$USER_EMAIL" ]; then
        echo "Error: Unable to fetch the user email. Ensure you are logged in with a valid Azure AD account."
        exit 1
    fi
    echo "User email: $USER_EMAIL"
}

create_user_invitation() {
    local STATIC_WEB_APP_DOMAIN=$(az staticwebapp show --name "$STATIC_WEB_APP" --resource-group "$RESOURCE_GROUP" --query "defaultHostname" -o tsv)
    if [ -z "$STATIC_WEB_APP_DOMAIN" ]; then
        echo "Error: Unable to fetch the Static Web App domain."
        exit 1
    else
         echo "Retrieved Static Web App domain: $STATIC_WEB_APP_DOMAIN"
    fi
    echo "Checking if the user email already exists in the Static Web App..."
    EXISTING_USERS=$(az rest --method POST \
        --uri "https://management.azure.com/subscriptions/$SUBSCRIPTION_ID/resourceGroups/$RESOURCE_GROUP/providers/Microsoft.Web/staticSites/$STATIC_WEB_APP/authproviders/all/listUsers?api-version=2024-04-01" \
        --body "{}" | jq -r '.value[]?.properties.displayName')

    echo "Existing users in the Static Web App: $EXISTING_USERS"

    if echo "$EXISTING_USERS" | grep -q "$USER_EMAIL"; then
        echo "User email $USER_EMAIL already exists in the Static Web App. Skipping invitation creation."
        echo "\033[0;32mGo to the Static Web App URL: $STATIC_WEB_APP_URL\033[0m"
        return
    fi
    echo "Creating an invitation for the user to access the Static Web App..."
    RESPONSE=$(az rest --method POST \
        --uri "https://management.azure.com/subscriptions/$SUBSCRIPTION_ID/resourceGroups/$RESOURCE_GROUP/providers/Microsoft.Web/staticSites/$STATIC_WEB_APP/createUserInvitation?api-version=2024-04-01" \
        --body "{
            \"properties\": {
                \"domain\": \"$STATIC_WEB_APP_DOMAIN\",
                \"provider\": \"aad\",
                \"userDetails\": \"$USER_EMAIL\",
                \"roles\": \"administrators,contributors\",
                \"numHoursToExpiration\": 1
            }
        }")
    echo "User invitation created successfully. Click on the invitation to accept it, you have 1 hour:"
    INVITATION_URL=$(echo "$RESPONSE" | jq -r '.properties.invitationUrl')
    if [ -n "$INVITATION_URL" ]; then
        echo "\033[0;32mGo to Invitation URL: $INVITATION_URL\033[0m"
    else
        echo "Failed to parse the invitation URL from the response:"
        echo $RESPONSE
    fi
}

## Fetch the user email and create the invitation
get_user_email
create_user_invitation

if [ "$EnableFrontDoor" = true ]; then
    FRONTDOOR_URL=$(az afd endpoint show -g "$RESOURCE_GROUP" --profile-name "$FRONTDOOR_NAME" --endpoint-name ${FRONTDOOR_NAME}-endpoint --query "hostName" -o tsv | sed 's/^/https:\/\//')
    echo "Use Front Door URL to access the app: $FRONTDOOR_URL"
fi


