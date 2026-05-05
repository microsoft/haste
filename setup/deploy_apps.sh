#!/bin/bash
# This script deploys from outside the github pipeline, and is intended for development and testing purposes.
# Important: Add your IPs to the allowed list in the Azure Portal for the Function App before running this script to avoid connectivity issues.
set -e

if [ "$#" -lt 4 ] || [ "$#" -gt 5 ]; then
    echo "Usage: $0 <tenant_id> <subscription_id> <resource_prefix> <location> <random_suffix>"
    exit 1
fi

TENANT_ID=$1
SUBSCRIPTION_ID=$2
RESOURCE_PREFIX=$3
LOCATION=$4
RANDOM_SUFFIX=$5

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

az login --tenant "$TENANT_ID"
az account set --subscription "$SUBSCRIPTION_ID"

DeployFunctionApp=true
DeployStaticWebApp=true


RESOURCE_GROUP="${RESOURCE_PREFIX}-haste-${RANDOM_SUFFIX}-rg"
FUNCTION_API="${RESOURCE_PREFIX}haste${RANDOM_SUFFIX}func"
FUNCTION_TITILER_API="${RESOURCE_PREFIX}hastetitiler${RANDOM_SUFFIX}func"
FUNCTION_QUEUE_API="${RESOURCE_PREFIX}hastequeue${RANDOM_SUFFIX}func"
STATIC_WEB_APP="${RESOURCE_PREFIX}haste${RANDOM_SUFFIX}swa"
API_MANAGEMENT="${RESOURCE_PREFIX}-haste-${RANDOM_SUFFIX}-apim"
STORAGE_ACCOUNT="${RESOURCE_PREFIX}haste${RANDOM_SUFFIX}sa"
BATCH_ACCOUNT="<REPLACE_ME>"
SHARED_RESOURCE_GROUP="<REPLACE_ME>"
USER_MANAGED_IDENTITY="${RESOURCE_PREFIX}-haste-${RANDOM_SUFFIX}-umi"
ACR_NAME="<REPLACE_ME>"
TRAINING_DOCKER_IMAGE=hastetraining:1.4.1
IMAGEPREP_DOCKER_IMAGE=hasteimageryprep:1.4.1
BATCH_POOL_ID="${RESOURCE_PREFIX}-haste-${RANDOM_SUFFIX}-pool"
BATCH_IMAGEPREP_POOL_ID="${RESOURCE_PREFIX}-haste-${RANDOM_SUFFIX}-pool"
LOG_ANALYTICS_WORKSPACE="${RESOURCE_PREFIX}-haste-${RANDOM_SUFFIX}-law"
MAPS_ACCOUNT="${RESOURCE_PREFIX}haste${RANDOM_SUFFIX}maps"
AZ_FUNCTIONAPP_TAGS='tags.project=haste tags.env=dev tags.deployed_version=v1.4.1 tags.created_by=deploy_apps'
AZ_RESOURCE_TAGS='project=haste env=dev deployed_version=v1.4.1 created_by=deploy_apps'

STATIC_APP_DOMAIN=<REPLACE_ME>
EMAIL_CONNECTION_STRING="${EMAIL_CONNECTION_STRING:-}" # Must be provided securely via environment variable
EMAIL_SENDER="DoNotReply@notifications.${STATIC_APP_DOMAIN}"

if [ -z "$EMAIL_CONNECTION_STRING" ]; then
    echo "Error: EMAIL_CONNECTION_STRING is required. Export it as an environment variable before running this script."
    exit 1
fi

deploy_function() {
    local FUNCTION_NAME=$1
    local FUNCTION_DIR=$2
    local SET_APPSETTINGS=${3:-true}
    local CONTINUE_ON_ERROR=${4:-false}

    echo "+--------------------------------------------------+"
    echo "Deploying function app: $FUNCTION_NAME"
    echo "+--------------------------------------------------+"

    if [ "${SET_APPSETTINGS:-true}" = "true" ]; then
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
    fi

    az functionapp restart --name "$FUNCTION_NAME" --resource-group "$RESOURCE_GROUP"

    # Enable SCM and FTP basic auth for deployment (required for func CLI publish)
    echo "Enabling basic auth publishing credentials..."
    az resource update --resource-group "$RESOURCE_GROUP" --name scm --namespace Microsoft.Web --resource-type basicPublishingCredentialsPolicies --parent sites/"$FUNCTION_NAME" --set properties.allow=true
    az resource update --resource-group "$RESOURCE_GROUP" --name ftp --namespace Microsoft.Web --resource-type basicPublishingCredentialsPolicies --parent sites/"$FUNCTION_NAME" --set properties.allow=true

    # Add current public IP to SCM site access restrictions.
    # The SCM (Kudu) site used by func CLI has separate restrictions from the main site,
    # so "Allow all traffic" in the Portal does not affect it.
    DEPLOY_IP=$(curl -s https://api.ipify.org)
    echo "Allowing deployer IP ($DEPLOY_IP) on SCM site for $FUNCTION_NAME..."
    az functionapp config access-restriction add \
        --name "$FUNCTION_NAME" \
        --resource-group "$RESOURCE_GROUP" \
        --scm-site \
        --rule-name "LocalDeploy" \
        --action Allow \
        --ip-address "${DEPLOY_IP}/32" \
        --priority 100 2>/dev/null || true

    # Wait for settings to propagate
    echo "Waiting for settings to propagate..."
    sleep 30

    (cd "$FUNCTION_DIR" && func azure functionapp publish "$FUNCTION_NAME" --python --build remote --verbose)
    DEPLOY_EXIT=$?

    # Always clean up the temporary SCM IP rule
    echo "Removing temporary SCM IP restriction for $FUNCTION_NAME..."
    az functionapp config access-restriction remove \
        --name "$FUNCTION_NAME" \
        --resource-group "$RESOURCE_GROUP" \
        --scm-site \
        --rule-name "LocalDeploy" 2>/dev/null || true

    if [ $DEPLOY_EXIT -ne 0 ] && [ "$CONTINUE_ON_ERROR" != true ]; then
        exit 1
    fi

    echo "Setting tags for Function App $FUNCTION_NAME ..."
    az functionapp update --name "$FUNCTION_NAME" --resource-group "$RESOURCE_GROUP" --set $AZ_FUNCTIONAPP_TAGS
}

deploy_static_web_app() {
    MAPS_CLIENT_ID=$(az maps account show --name "$MAPS_ACCOUNT" --resource-group "$RESOURCE_GROUP" --query "properties.uniqueId" -o tsv)
    FUNCTION_API_MASTER_KEY=$(az functionapp keys list --name "$FUNCTION_API" --resource-group "$RESOURCE_GROUP" --query "masterKey" -o tsv)
    STATIC_WEB_APP_URL=$(az staticwebapp show --name "$STATIC_WEB_APP" --resource-group "$RESOURCE_GROUP" --query "defaultHostname" -o tsv | sed 's/^/https:\/\//')

    cd ../ui || { echo "UI directory not found"; exit 1; }

    cat <<EOF > .env
VITE_APP_MASTER_KEY=$FUNCTION_API_MASTER_KEY
VITE_AZURE_MAPS_CLIENT_ID=$MAPS_CLIENT_ID
VITE_API_URL=/api/haste/
VITE_STORAGE_APIM_URL=/api/haste/storage/get-artifacts
VITE_PROJECT_STORAGE_APIM_URL=/api/haste/storage/get-project-artifacts
VITE_REDIRECT_URI=$STATIC_WEB_APP_URL
VITE_AZURE_SUBSCRIPTION_ID=$SUBSCRIPTION_ID
VITE_AZURE_TENANT_ID=$TENANT_ID
EOF

    npm install vite --save-dev
    swa build --auto

    swa deploy --app-location ./dist \
        --app-name "$STATIC_WEB_APP" \
        --tenant-id "$TENANT_ID" \
        --subscription-id "$SUBSCRIPTION_ID" \
        --env Production \
        --deployment-token "$(az staticwebapp secrets list --name "$STATIC_WEB_APP" --resource-group "$RESOURCE_GROUP" --query "properties.apiKey" -o tsv)"

    echo "Setting tags for Static Web App $STATIC_WEB_APP ..."
    az staticwebapp update --name "$STATIC_WEB_APP" --resource-group "$RESOURCE_GROUP" --tags $AZ_RESOURCE_TAGS

}

echo "Deploying Azure Functions..."
if [ "$DeployFunctionApp" = true ]; then
    deploy_function "$FUNCTION_API" "$(dirname "$0")/../api/hastefuncapi" true false
    deploy_function "$FUNCTION_TITILER_API" "$(dirname "$0")/../api/titilerfuncapi" false false
    deploy_function "$FUNCTION_QUEUE_API" "$(dirname "$0")/../api/hastefuncqueues" true false
fi
echo "+--------------------------------------------------+"
echo "Deploying Static Web App..."
echo "+--------------------------------------------------+"

if [ "$DeployStaticWebApp" = true ]; then
    deploy_static_web_app
fi

echo "+--------------------------------------------------+"
echo "Deployment completed successfully."
echo "+--------------------------------------------------+"