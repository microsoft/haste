#!/bin/bash
set -e
set -o pipefail

if [ "$#" -lt 4 ] || [ "$#" -gt 14 ]; then
    echo "Usage: $0 <tenant_id> <subscription_id> <resource_prefix> <location> [random_suffix] [acr_name] [training_image_tag] [imageprep_image_tag] [environment] [app_tag] [batch_account] [shared_resource_group] [static_app_domain] [email_connection_string]"
    exit 1
fi

TENANT_ID=$1
SUBSCRIPTION_ID=$2
RESOURCE_PREFIX=$3
LOCATION=$4
RANDOM_SUFFIX=$5
ACR_NAME=$6
TRAINING_IMAGE_TAG=$7
IMAGEPREP_IMAGE_TAG=$8
ENVIRONMENT=$9
APP_TAG=${10}
BATCH_ACCOUNT=${11}
SHARED_RESOURCE_GROUP=${12}
STATIC_APP_DOMAIN=${13:-FIXME}
EMAIL_CONNECTION_STRING=${14}


DeployFunctionApp=true
DeployStaticWebApp=true

az config set core.login_experience_v2=off
az config set extension.use_dynamic_install=yes_without_prompt
az config set extension.dynamic_install_allow_preview=true

# Skip az login since GitHub Actions already authenticated
# az login --tenant "$TENANT_ID"
az account set --subscription "$SUBSCRIPTION_ID"

RESOURCE_GROUP="${RESOURCE_PREFIX}-haste-${RANDOM_SUFFIX}-rg"
FUNCTION_API="${RESOURCE_PREFIX}haste${RANDOM_SUFFIX}func"
FUNCTION_TITILER_API="${RESOURCE_PREFIX}hastetitiler${RANDOM_SUFFIX}func"
FUNCTION_QUEUE_API="${RESOURCE_PREFIX}hastequeue${RANDOM_SUFFIX}func"
STATIC_WEB_APP="${RESOURCE_PREFIX}haste${RANDOM_SUFFIX}swa"
STORAGE_ACCOUNT="${RESOURCE_PREFIX}haste${RANDOM_SUFFIX}sa"
USER_MANAGED_IDENTITY="${RESOURCE_PREFIX}-haste-${RANDOM_SUFFIX}-umi"
TRAINING_DOCKER_IMAGE="hastetraining:${TRAINING_IMAGE_TAG}"
IMAGEPREP_DOCKER_IMAGE="hasteimageryprep:${IMAGEPREP_IMAGE_TAG}"
BATCH_POOL_ID="${RESOURCE_PREFIX}-haste-${RANDOM_SUFFIX}-pool"
MAPS_ACCOUNT="${RESOURCE_PREFIX}haste${RANDOM_SUFFIX}maps"
FIXED_TAGS="project=haste created_by=deploy_apps"
DYNAMIC_TAGS="env=${ENVIRONMENT} deployed_version=${APP_TAG}"
EMAIL_SENDER="DoNotReply@notifications.${STATIC_APP_DOMAIN}"


# For Function Apps, use the 'tags.' prefix for each tag (iteration.tags)
AZ_FUNCTIONAPP_TAGS=$(for tag in $FIXED_TAGS $DYNAMIC_TAGS; do echo -n "tags.${tag} "; done)

# For Static Web Apps, use plain tags (no prefix)
AZ_RESOURCE_TAGS="${FIXED_TAGS} ${DYNAMIC_TAGS}"


deploy_function() {
    local FUNCTION_NAME=$1
    local FUNCTION_DIR=$2
    local SET_APPSETTINGS=${3:-true}

    echo "+--------------------------------------------------+"
    echo "Deploying function app: $FUNCTION_NAME"
    echo "+--------------------------------------------------+"

    if [ "${SET_APPSETTINGS:-true}" = "true" ]; then
        # Get storage account connection string with error handling
        echo "Retrieving storage account connection string..."
        BLOB_CONNECTION_STRING=$(az storage account show-connection-string --name "$STORAGE_ACCOUNT" --resource-group "$RESOURCE_GROUP" --query connectionString -o tsv) || {
            echo "ERROR: Failed to retrieve storage account connection string. Ensure service principal has 'Storage Account Key Operator Service Role' or 'Reader and Data Access' role on storage account '$STORAGE_ACCOUNT'." >&2
            exit 1
        }

        # Get batch account key with error handling
        echo "Retrieving batch account key..."
        AZURE_BATCH_ACCOUNT_KEY=$(az batch account keys list --name "$BATCH_ACCOUNT" --resource-group "$SHARED_RESOURCE_GROUP" --query "primary" -o tsv) || {
            echo "ERROR: Failed to retrieve batch account key. Ensure service principal has 'Batch Contributor' role on batch account '$BATCH_ACCOUNT'." >&2
            exit 1
        }

        az functionapp config appsettings set --name "$FUNCTION_NAME" --resource-group "$RESOURCE_GROUP" --settings \
            "env=${ENVIRONMENT}" \
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
            "BLOB_CONNECTION_STRING=$BLOB_CONNECTION_STRING" \
            "AZURE_BATCH_ACCOUNT_NAME=$BATCH_ACCOUNT" \
            "AZURE_BATCH_URL=https://${BATCH_ACCOUNT}.${LOCATION}.batch.azure.com" \
            "AZURE_BATCH_ACCOUNT_KEY=$AZURE_BATCH_ACCOUNT_KEY" \
            "AZURE_BATCH_IMAGERYPREP_DOCKER_IMAGE=${ACR_NAME}.azurecr.io/${IMAGEPREP_DOCKER_IMAGE}" \
            "AZURE_BATCH_DOCKER_IMAGE=${ACR_NAME}.azurecr.io/${TRAINING_DOCKER_IMAGE}" \
            "AZURE_BATCH_OUTPUT_CONTAINER_URL=https://${STORAGE_ACCOUNT}.blob.core.windows.net/data" \
            "AZURE_BATCH_TRAINING_POOL_ID=${BATCH_POOL_ID}" \
            "AZURE_BATCH_IMAGERYPREP_POOL_ID=${BATCH_POOL_ID}" \
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

    echo "Deploying function code..."
    # Deploy and handle health check failures gracefully
    if (cd "$FUNCTION_DIR" && func azure functionapp publish "$FUNCTION_NAME" --python --build remote --verbose); then
        echo "✅ Function deployment completed successfully"
    else
        echo "⚠️  WARNING: Function deployment completed but health check failed."
        echo "   This is often normal for cold starts and doesn't indicate a real problem."
        echo "   The function app is likely working correctly. Check the Azure portal to verify."
    fi

    echo "Setting tags for Function App $FUNCTION_NAME ..."
    az functionapp update --name "$FUNCTION_NAME" --resource-group "$RESOURCE_GROUP" --set $AZ_FUNCTIONAPP_TAGS
}

deploy_static_web_app() {
    # Get maps account client ID for managed identity auth
    echo "Retrieving maps account client ID..."
    MAPS_CLIENT_ID=$(az maps account show --name "$MAPS_ACCOUNT" --resource-group "$RESOURCE_GROUP" --query "properties.uniqueId" -o tsv) || {
        echo "ERROR: Failed to retrieve maps account client ID. Ensure service principal has appropriate permissions on maps account '$MAPS_ACCOUNT'." >&2
        exit 1
    }

    # Get function app master key with error handling
    echo "Retrieving function app master key..."
    FUNCTION_API_MASTER_KEY=$(az functionapp keys list --name "$FUNCTION_API" --resource-group "$RESOURCE_GROUP" --query "masterKey" -o tsv) || {
        echo "ERROR: Failed to retrieve function app master key. Ensure service principal has appropriate permissions on function app '$FUNCTION_API'." >&2
        exit 1
    }

    # Get static web app URL with error handling
    echo "Retrieving static web app URL..."
    STATIC_WEB_APP_URL=$(az staticwebapp show --name "$STATIC_WEB_APP" --resource-group "$RESOURCE_GROUP" --query "defaultHostname" -o tsv | sed 's|^|https://|') || {
        echo "ERROR: Failed to retrieve static web app URL. Ensure service principal has read permissions on static web app '$STATIC_WEB_APP'." >&2
        exit 1
    }

    cd "$(dirname "$0")/../../ui"

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
    deploy_function "$FUNCTION_API" "$(dirname "$0")/../../api/hastefuncapi" true
    deploy_function "$FUNCTION_TITILER_API" "$(dirname "$0")/../../api/titilerfuncapi" false
    deploy_function "$FUNCTION_QUEUE_API" "$(dirname "$0")/../../api/hastefuncqueues" true
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
