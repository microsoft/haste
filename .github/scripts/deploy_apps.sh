#!/bin/bash
set -e
set -o pipefail

if [ "$#" -lt 4 ] || [ "$#" -gt 15 ]; then
    echo "Usage: $0 <tenant_id> <subscription_id> <resource_prefix> <location> [random_suffix] [acr_name] [training_image_tag] [imageprep_image_tag] [environment] [app_tag] [batch_account] [shared_resource_group] [static_app_domain] [email_connection_string] [component]"
    echo "  component: all (default) | funcapi | funcqueue | titiler | swa"
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
COMPONENT=${15:-all}

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
# Batch pool wiring. Defaults reproduce the legacy single-pool behavior; set the
# corresponding GitHub Environment variables to point an environment at
# pre-created shared pools (see docs/configuration.md).
#   *_POOL_ID   - the pool used when no candidate list is supplied. It is also
#                 the default Batch *job* id, so it must be identical across the
#                 api and queues apps or status lookups miss the job.
#   *_POOL_IDS  - ordered candidate lists for capacity-aware routing.
BATCH_TRAINING_POOL_ID="${BATCH_TRAINING_POOL_ID:-$BATCH_POOL_ID}"
BATCH_IMAGERYPREP_POOL_ID="${BATCH_IMAGERYPREP_POOL_ID:-$BATCH_POOL_ID}"
BATCH_TRAINING_POOL_IDS="${BATCH_TRAINING_POOL_IDS:-}"
BATCH_INFERENCE_POOL_IDS="${BATCH_INFERENCE_POOL_IDS:-}"
BATCH_IMAGERYPREP_POOL_IDS="${BATCH_IMAGERYPREP_POOL_IDS:-}"
BATCH_USE_SAS="${BATCH_USE_SAS:-false}"
BATCH_MANAGE_POOLS="${BATCH_MANAGE_POOLS:-true}"
DINOV3_SAT_MODEL_BLOB_PREFIX="${DINOV3_SAT_MODEL_BLOB_PREFIX:-}"
DINOV3_SAT_MODEL_CONTAINER_URL="${DINOV3_SAT_MODEL_CONTAINER_URL:-}"
MAPS_ACCOUNT="${RESOURCE_PREFIX}haste${RANDOM_SUFFIX}maps"
API_MANAGEMENT="${RESOURCE_PREFIX}-haste-${RANDOM_SUFFIX}-apim"
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
            "EMBEDDING_QUEUE_NAME=embedding-queue" \
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
            "AZURE_BATCH_TRAINING_POOL_ID=${BATCH_TRAINING_POOL_ID}" \
            "AZURE_BATCH_IMAGERYPREP_POOL_ID=${BATCH_IMAGERYPREP_POOL_ID}" \
            "AZURE_BATCH_TRAINING_POOL_IDS=${BATCH_TRAINING_POOL_IDS}" \
            "AZURE_BATCH_INFERENCE_POOL_IDS=${BATCH_INFERENCE_POOL_IDS}" \
            "AZURE_BATCH_IMAGERYPREP_POOL_IDS=${BATCH_IMAGERYPREP_POOL_IDS}" \
            "AZURE_BATCH_USE_SAS=${BATCH_USE_SAS}" \
            "AZURE_BATCH_MANAGE_POOLS=${BATCH_MANAGE_POOLS}" \
            "DINOV3_SAT_MODEL_BLOB_PREFIX=${DINOV3_SAT_MODEL_BLOB_PREFIX}" \
            "DINOV3_SAT_MODEL_CONTAINER_URL=${DINOV3_SAT_MODEL_CONTAINER_URL}" \
            "AZURE_BATCH_REGISTRY_SERVER=${ACR_NAME}.azurecr.io" \
            "AZURE_BATCH_REGISTRY_IMAGE=${ACR_NAME}.azurecr.io/${TRAINING_DOCKER_IMAGE}" \
            "AZURE_BATCH_REGISTRY_IDENTITY_RESOURCE_ID=/subscriptions/$SUBSCRIPTION_ID/resourceGroups/$RESOURCE_GROUP/providers/Microsoft.ManagedIdentity/userAssignedIdentities/$USER_MANAGED_IDENTITY" \
            "STATIC_APP_SUBSCRIPTION_ID=$SUBSCRIPTION_ID" \
            "STATIC_APP_RESOURCE_GROUP=$RESOURCE_GROUP" \
            "STATIC_APP_NAME=$STATIC_WEB_APP" \
            "STATIC_APP_DOMAIN=${STATIC_APP_DOMAIN}" \
            "EMAIL_CONNECTION_STRING=${EMAIL_CONNECTION_STRING}" \
            "EMAIL_SENDER=${EMAIL_SENDER}" \
            --output none
    fi

    az functionapp restart --name "$FUNCTION_NAME" --resource-group "$RESOURCE_GROUP"

    # Function apps publish via `func` -> remote pip install on Azure, so the
    # editable hastegeo default in requirements.txt (used by docker-compose)
    # must be swapped for the published wheel. Apps without a hastegeo line
    # (e.g. titiler) are left untouched.
    if [ -n "${HASTEGEO_WHEEL_URL:-}" ] && grep -qE '^[[:space:]]*#?[[:space:]]*(-e[[:space:]]+[^[:space:]]*hastelib|hastegeo[[:space:]]*@)' "$FUNCTION_DIR/requirements.txt" 2>/dev/null; then
        echo "Pinning hastegeo wheel for $FUNCTION_NAME: $HASTEGEO_WHEEL_URL"
        python3 "$(dirname "$0")/set_hastegeo_source.py" --mode wheel --url "$HASTEGEO_WHEEL_URL" "$FUNCTION_DIR/requirements.txt"
    fi

    echo "Deploying function code..."
    # A non-zero exit can represent a package/build/deployment failure. Do not
    # convert it into a success-shaped warning: set -e propagates the failure.
    (
        cd "$FUNCTION_DIR"
        func azure functionapp publish "$FUNCTION_NAME" \
            --python \
            --build remote \
            --verbose
    )
    echo "Function deployment completed successfully."

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
VITE_SHOW_FOOTER=${VITE_SHOW_FOOTER:-false}
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

# Detect the HTTP endpoints currently exposed by a deployed Function App and
# create a matching APIM operation (plus a set-backend-service policy) for any
# that don't already exist. Existing operations are left untouched, so this only
# ever *adds* newly introduced endpoints - making it safe to run on every deploy.
#
# The APIM service and the base API (whose api-id matches the function app name)
# are provisioned by setup/setup_infra.sh. If either is missing we warn and skip
# rather than fail, so a code-only deploy to an environment without APIM still
# succeeds.
sync_apim_operations() {
    local FUNCTION_NAME=$1

    echo "+--------------------------------------------------+"
    echo "Syncing APIM operations for function app: $FUNCTION_NAME"
    echo "+--------------------------------------------------+"

    # The APIM service must exist before we can add operations to it.
    if ! az apim show --name "$API_MANAGEMENT" --resource-group "$RESOURCE_GROUP" > /dev/null 2>&1; then
        echo "⚠️  WARNING: API Management service '$API_MANAGEMENT' not found in '$RESOURCE_GROUP'. Skipping APIM operation sync."
        echo "   Provision APIM and the base API via setup/setup_infra.sh before syncing operations."
        return 0
    fi

    # The base API (api-id == function app name) must already be imported into
    # APIM; new endpoints can only be added to an existing API.
    if ! az apim api show --resource-group "$RESOURCE_GROUP" --service-name "$API_MANAGEMENT" --api-id "$FUNCTION_NAME" > /dev/null 2>&1; then
        echo "⚠️  WARNING: APIM API '$FUNCTION_NAME' not found in '$API_MANAGEMENT'. Skipping APIM operation sync."
        echo "   The base API is created by setup/setup_infra.sh; run it once before relying on incremental endpoint sync."
        return 0
    fi

    # Enumerate the function app's endpoints from Azure.
    local FUNCTION_OPERATIONS
    FUNCTION_OPERATIONS=$(az functionapp function list --name "$FUNCTION_NAME" --resource-group "$RESOURCE_GROUP" -o json) || {
        echo "⚠️  WARNING: Failed to list functions for '$FUNCTION_NAME'. Skipping APIM operation sync."
        return 0
    }

    while read -r OPERATION; do
        local OPERATION_NAME OPERATION_METHOD OPERATION_ROUTE TEMPLATE_PARAMETERS
        OPERATION_NAME=$(echo "$OPERATION" | jq -r '.config.name // (.id | split("/")[-1])')
        OPERATION_METHOD=$(echo "$OPERATION" | jq -r '.config.bindings[0].methods[0] // empty')
        OPERATION_ROUTE=$(echo "$OPERATION" | jq -r '.config.bindings[0].route // .config.name')

        # Skip non-HTTP triggers (queue/timer/blob triggers have no HTTP method).
        if [ -z "$OPERATION_METHOD" ] || [ "$OPERATION_METHOD" = "null" ]; then
            echo "Skipping '$OPERATION_NAME' (no HTTP method - not an HTTP endpoint)."
            continue
        fi

        echo "Processing endpoint: $OPERATION_NAME [method: $OPERATION_METHOD, route: $OPERATION_ROUTE]"

        # Translate route template parameters (e.g. options/{*path}) into the
        # named template parameter APIM expects.
        TEMPLATE_PARAMETERS=""
        case "$OPERATION_ROUTE" in
            *"{"*"}"*)
                OPERATION_ROUTE=$(echo "$OPERATION_ROUTE" | sed 's/\*//g')
                # Extract just the placeholder name from inside the braces so the
                # declared parameter matches the {param} in the url-template
                # (e.g. options/{*path} -> url-template options/{path}, param "path").
                OPERATION_ROUTE_PARAM=$(echo "$OPERATION_ROUTE" | sed -n 's/.*{\([^}]*\)}.*/\1/p')
                TEMPLATE_PARAMETERS="name=$OPERATION_ROUTE_PARAM required=true type=string"
                echo "  template parameter detected -> $OPERATION_ROUTE_PARAM"
                ;;
        esac

        # Only create operations that don't already exist - this is the "new
        # endpoint detection" step.
        if az apim api operation show \
            --resource-group "$RESOURCE_GROUP" \
            --service-name "$API_MANAGEMENT" \
            --api-id "$FUNCTION_NAME" \
            --operation-id "$OPERATION_NAME" > /dev/null 2>&1; then
            echo "  operation '$OPERATION_NAME' already exists in APIM. Skipping."
            continue
        fi

        echo "  creating new APIM operation '$OPERATION_NAME'..."
        # shellcheck disable=SC2046
        az apim api operation create \
            --resource-group "$RESOURCE_GROUP" \
            --service-name "$API_MANAGEMENT" \
            --api-id "$FUNCTION_NAME" \
            --operation-id "$OPERATION_NAME" \
            --display-name "$OPERATION_NAME" \
            --method "$(echo "$OPERATION_METHOD" | tr '[:lower:]' '[:upper:]')" \
            --url-template "/$OPERATION_ROUTE" \
            $( [ -n "$TEMPLATE_PARAMETERS" ] && echo "--template-parameters $TEMPLATE_PARAMETERS" ) || {
            echo "⚠️  WARNING: Failed to create operation '$OPERATION_NAME'. Continuing with remaining endpoints."
            continue
        }

        # Route the new operation to the function app backend via policy.
        local BICEP_TEMPLATE BICEP_TEMPLATE_FILE
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
        BICEP_TEMPLATE_FILE=$(mktemp).bicep
        echo "$BICEP_TEMPLATE" > "$BICEP_TEMPLATE_FILE"
        if az deployment group create --resource-group "$RESOURCE_GROUP" --template-file "$BICEP_TEMPLATE_FILE"; then
            echo "✅ Operation '$OPERATION_NAME' added to APIM and routed to '$FUNCTION_NAME'."
        else
            echo "⚠️  WARNING: Failed to set backend policy for '$OPERATION_NAME'."
        fi
        rm -f "$BICEP_TEMPLATE_FILE"
    done < <(echo "$FUNCTION_OPERATIONS" | jq -c '.[]')

    echo "APIM operation sync complete for '$FUNCTION_NAME'."
}

echo "Deploying component: $COMPONENT"

case "$COMPONENT" in
    all)
        deploy_function "$FUNCTION_API" "$(dirname "$0")/../../api/hastefuncapi" true
        sync_apim_operations "$FUNCTION_API"
        deploy_function "$FUNCTION_TITILER_API" "$(dirname "$0")/../../api/titilerfuncapi" false
        deploy_function "$FUNCTION_QUEUE_API" "$(dirname "$0")/../../api/hastefuncqueues" true
        deploy_static_web_app
        ;;
    funcapi)
        deploy_function "$FUNCTION_API" "$(dirname "$0")/../../api/hastefuncapi" true
        sync_apim_operations "$FUNCTION_API"
        ;;
    funcqueue)
        deploy_function "$FUNCTION_QUEUE_API" "$(dirname "$0")/../../api/hastefuncqueues" true
        ;;
    titiler)
        deploy_function "$FUNCTION_TITILER_API" "$(dirname "$0")/../../api/titilerfuncapi" false
        ;;
    swa)
        deploy_static_web_app
        ;;
    *)
        echo "ERROR: Unknown component '$COMPONENT'. Must be one of: all, funcapi, funcqueue, titiler, swa." >&2
        exit 1
        ;;
esac

echo "+--------------------------------------------------+"
echo "Deployment completed successfully."
echo "+--------------------------------------------------+"
