// APIM base APIs, backends, product links, and hardcoded operations — reproduces
// setup_infra.sh's add_function_to_apim_with_arm + deploy_titiler_tiles_operation
// + deploy_storage_operations. The per-endpoint operations for the api/titiler
// apps are added additively by the postdeploy hook (hooks/sync-apim-operations.ps1),
// since they're derived from the deployed function list.
//
// Depends on: the APIM service (apim.bicep), the function apps (functions.bicep,
// for backend URLs + host master keys), and the Static Web App (frontend.bicep,
// whose linked backend creates the APIM product these APIs are linked into).

@description('API Management service name.')
param apimName string

@description('API function app name (api-id + backend).')
param functionApiName string

@description('TiTiler function app name (api-id + backend).')
param functionTitilerName string

@description('Static Web App default hostname; its first label is the generated APIM product id.')
param staticWebAppHostName string

@description('Storage account name backing the storage-proxy operations.')
param storageAccountName string

// The APIM product the SWA linked-backend generated (named after the SWA host's
// first label, e.g. "agreeable-smoke-06273c21e").
var swaProductId = split(staticWebAppHostName, '.')[0]

resource apim 'Microsoft.ApiManagement/service@2024-06-01-preview' existing = {
  name: apimName
}

resource swaProduct 'Microsoft.ApiManagement/service/products@2024-06-01-preview' existing = {
  parent: apim
  name: swaProductId
}

// NB: the backends are created WITHOUT the x-functions-key credential. The func
// host master key (listKeys on Microsoft.Web/sites/host) is unavailable at
// provision time — on a fresh env the apps have no code deployed, so the host
// runtime isn't running and listKeys returns InternalServerError. The postdeploy
// hook (hooks/sync-apim-operations.ps1) injects the key once the host is up.
// Under DEVELOPMENT_MODE the functions are anonymous, so no key is needed at all.

var subscriptionKeyParameterNames = {
  header: 'Ocp-Apim-Subscription-Key'
  query: 'subscription-key'
}

// ---------------------------------------------------------------------------
// hastefuncapi — path api/haste, backend -> <func>/api
// ---------------------------------------------------------------------------
resource apiHaste 'Microsoft.ApiManagement/service/apis@2024-06-01-preview' = {
  parent: apim
  name: functionApiName
  properties: {
    displayName: functionApiName
    apiRevision: '1'
    description: 'Import from "${functionApiName}" Function App'
    subscriptionRequired: true
    path: 'api/haste'
    protocols: [ 'https' ]
    subscriptionKeyParameterNames: subscriptionKeyParameterNames
    isCurrent: true
  }
}

resource backendHaste 'Microsoft.ApiManagement/service/backends@2024-06-01-preview' = {
  parent: apim
  name: functionApiName
  properties: {
    description: functionApiName
    url: 'https://${functionApiName}.azurewebsites.net/api'
    protocol: 'http'
    resourceId: '${environment().resourceManager}${substring(resourceId('Microsoft.Web/sites', functionApiName), 1)}'
  }
}

resource productApiHaste 'Microsoft.ApiManagement/service/products/apis@2024-06-01-preview' = {
  parent: swaProduct
  name: functionApiName
  dependsOn: [ apiHaste ]
}

// API-level policy: route every operation of this API to the function backend.
// Operations added by the postdeploy op-sync hook inherit this via <base/>, so
// the hook only needs to create operations — no per-operation policy.
resource apiPolicyHaste 'Microsoft.ApiManagement/service/apis/policies@2024-06-01-preview' = {
  parent: apiHaste
  name: 'policy'
  properties: {
    format: 'xml'
    value: replace('''<policies>
  <inbound>
    <base />
    <set-backend-service id="apim-generated-policy" backend-id="__BID__" />
  </inbound>
  <backend><base /></backend>
  <outbound><base /></outbound>
  <on-error><base /></on-error>
</policies>''', '__BID__', functionApiName)
  }
  dependsOn: [ backendHaste ]
}

// ---------------------------------------------------------------------------
// titiler — path api/titiler, backend -> <titiler> (root), + get-tiles op
// ---------------------------------------------------------------------------
resource apiTitiler 'Microsoft.ApiManagement/service/apis@2024-06-01-preview' = {
  parent: apim
  name: functionTitilerName
  properties: {
    displayName: functionTitilerName
    apiRevision: '1'
    description: 'Import from "${functionTitilerName}" Function App'
    subscriptionRequired: true
    path: 'api/titiler'
    protocols: [ 'https' ]
    subscriptionKeyParameterNames: subscriptionKeyParameterNames
    isCurrent: true
  }
}

resource backendTitiler 'Microsoft.ApiManagement/service/backends@2024-06-01-preview' = {
  parent: apim
  name: functionTitilerName
  properties: {
    description: functionTitilerName
    url: 'https://${functionTitilerName}.azurewebsites.net'
    protocol: 'http'
    resourceId: '${environment().resourceManager}${substring(resourceId('Microsoft.Web/sites', functionTitilerName), 1)}'
  }
}

resource productApiTitiler 'Microsoft.ApiManagement/service/products/apis@2024-06-01-preview' = {
  parent: swaProduct
  name: functionTitilerName
  dependsOn: [ apiTitiler ]
}

// API-level policy routes all titiler operations (get-tiles + the hook-synced
// ones) to the titiler backend.
resource apiPolicyTitiler 'Microsoft.ApiManagement/service/apis/policies@2024-06-01-preview' = {
  parent: apiTitiler
  name: 'policy'
  properties: {
    format: 'xml'
    value: replace('''<policies>
  <inbound>
    <base />
    <set-backend-service id="apim-generated-policy" backend-id="__BID__" />
  </inbound>
  <backend><base /></backend>
  <outbound><base /></outbound>
  <on-error><base /></on-error>
</policies>''', '__BID__', functionTitilerName)
  }
  dependsOn: [ backendTitiler ]
}

resource tilesOp 'Microsoft.ApiManagement/service/apis/operations@2024-06-01-preview' = {
  parent: apiTitiler
  name: 'get-tiles'
  properties: {
    displayName: 'get-tiles'
    method: 'GET'
    urlTemplate: '/cog/tiles/WebMercatorQuad/{z}/{x}/{y}'
    templateParameters: [
      { name: 'z', required: true, type: 'string' }
      { name: 'x', required: true, type: 'string' }
      { name: 'y', required: true, type: 'string' }
    ]
  }
}

// ---------------------------------------------------------------------------
// hastestorageapi — path api/haste/storage, no backend; managed-identity blob proxy
// ---------------------------------------------------------------------------
resource apiStorage 'Microsoft.ApiManagement/service/apis@2024-06-01-preview' = {
  parent: apim
  name: 'hastestorageapi'
  properties: {
    displayName: 'hastestorageapi'
    apiRevision: '1'
    description: 'Storage artifact proxy (managed identity).'
    subscriptionRequired: true
    path: 'api/haste/storage'
    protocols: [ 'https' ]
    subscriptionKeyParameterNames: subscriptionKeyParameterNames
    isCurrent: true
  }
}

resource productApiStorage 'Microsoft.ApiManagement/service/products/apis@2024-06-01-preview' = {
  parent: swaProduct
  name: 'hastestorageapi'
  dependsOn: [ apiStorage ]
}

resource getArtifactsOp 'Microsoft.ApiManagement/service/apis/operations@2024-06-01-preview' = {
  parent: apiStorage
  name: 'get-artifacts'
  properties: {
    displayName: 'get-artifacts'
    method: 'GET'
    urlTemplate: '/get-artifacts/{container}/{projectDir}/{modelDir}/{fileName}'
    templateParameters: [
      { name: 'container', required: true, type: 'string' }
      { name: 'projectDir', required: true, type: 'string' }
      { name: 'modelDir', required: true, type: 'string' }
      { name: 'fileName', required: true, type: 'string' }
    ]
  }
}

resource getArtifactsPolicy 'Microsoft.ApiManagement/service/apis/operations/policies@2024-06-01-preview' = {
  parent: getArtifactsOp
  name: 'policy'
  properties: {
    format: 'xml'
    value: replace('''<policies>
  <inbound>
    <send-request mode="new" timeout="20" response-variable-name="blobdata" ignore-error="false">
      <set-url>@{ return "https://__SA__.blob.core.windows.net/" + (string)context.Request.MatchedParameters["container"] + "/" + (string)context.Request.MatchedParameters["projectDir"] + "/" + (string)context.Request.MatchedParameters["modelDir"]+ "/" + (string)context.Request.MatchedParameters["fileName"]; }</set-url>
      <set-method>GET</set-method>
      <set-header name="x-ms-version" exists-action="override">
        <value>2019-07-07</value>
      </set-header>
      <authentication-managed-identity resource="https://storage.azure.com" />
    </send-request>
    <return-response response-variable-name="blobdata" />
    <base />
  </inbound>
  <backend><base /></backend>
  <outbound><base /></outbound>
  <on-error><base /></on-error>
</policies>''', '__SA__', storageAccountName)
  }
}

resource getProjectArtifactsOp 'Microsoft.ApiManagement/service/apis/operations@2024-06-01-preview' = {
  parent: apiStorage
  name: 'get-project-artifacts'
  properties: {
    displayName: 'get-project-artifacts'
    method: 'GET'
    urlTemplate: '/get-project-artifacts/{container}/{projectDir}/{fileName}'
    templateParameters: [
      { name: 'container', required: true, type: 'string' }
      { name: 'projectDir', required: true, type: 'string' }
      { name: 'fileName', required: true, type: 'string' }
    ]
  }
}

resource getProjectArtifactsPolicy 'Microsoft.ApiManagement/service/apis/operations/policies@2024-06-01-preview' = {
  parent: getProjectArtifactsOp
  name: 'policy'
  properties: {
    format: 'xml'
    value: replace('''<policies>
  <inbound>
    <send-request mode="new" timeout="20" response-variable-name="blobdata" ignore-error="false">
      <set-url>@{ return "https://__SA__.blob.core.windows.net/" + (string)context.Request.MatchedParameters["container"] + "/" + (string)context.Request.MatchedParameters["projectDir"] + "/" + (string)context.Request.MatchedParameters["fileName"]; }</set-url>
      <set-method>GET</set-method>
      <set-header name="x-ms-version" exists-action="override">
        <value>2019-07-07</value>
      </set-header>
      <authentication-managed-identity resource="https://storage.azure.com" />
    </send-request>
    <return-response response-variable-name="blobdata" />
    <base />
  </inbound>
  <backend><base /></backend>
  <outbound><base /></outbound>
  <on-error><base /></on-error>
</policies>''', '__SA__', storageAccountName)
  }
}
