#!/usr/bin/env pwsh
# Additively sync APIM operations from a function app's *deployed* HTTP endpoints.
# For each HTTP-triggered function that has no matching APIM operation yet, create
# the operation and a set-backend-service policy routing it to the function's
# backend. Existing operations are left untouched, so this is safe to run every
# deploy. Port of .github/scripts/deploy_apps.sh:sync_apim_operations.
#
# Runs in postdeploy (after the function code is published), because it enumerates
# the live function list. The base APIs + backends are provisioned by
# infra/modules/apimApis.bicep; this only adds per-endpoint operations.
#
# Inputs (azd environment): APIM_NAME, AZURE_RESOURCE_GROUP, and the function app
# names to sync (api + titiler).

param(
    [string]$ApimName = $env:APIM_NAME,
    [string]$ResourceGroup = $env:AZURE_RESOURCE_GROUP,
    [string[]]$FunctionApps = @($env:FUNCTION_API_NAME, $env:FUNCTION_TITILER_NAME)
)

$ErrorActionPreference = 'Stop'
$subId = $env:AZURE_SUBSCRIPTION_ID

function Sync-One([string]$FunctionName) {
    if ([string]::IsNullOrWhiteSpace($FunctionName)) { return }
    Write-Host "── Syncing APIM operations for '$FunctionName' ──"

    # APIM service must exist.
    az apim show --name $ApimName --resource-group $ResourceGroup -o none 2>$null
    if ($LASTEXITCODE -ne 0) {
        Write-Warning "APIM '$ApimName' not found; skipping operation sync for $FunctionName."
        return
    }
    # Base API (api-id == function app name) must exist (created by apimApis.bicep).
    az apim api show --resource-group $ResourceGroup --service-name $ApimName --api-id $FunctionName -o none 2>$null
    if ($LASTEXITCODE -ne 0) {
        Write-Warning "APIM API '$FunctionName' not found; run provision (apimApis.bicep) first. Skipping."
        return
    }

    $functionsJson = az functionapp function list --name $FunctionName --resource-group $ResourceGroup -o json 2>$null
    if ($LASTEXITCODE -ne 0 -or [string]::IsNullOrWhiteSpace($functionsJson)) {
        Write-Warning "Could not list functions for '$FunctionName'; skipping."
        return
    }

    foreach ($fn in ($functionsJson | ConvertFrom-Json)) {
        $cfg = $fn.config
        $opName = if ($cfg.name) { $cfg.name } else { ($fn.id -split '/')[-1] }
        $binding = $cfg.bindings | Where-Object { $_.methods } | Select-Object -First 1
        $method = if ($binding) { ($binding.methods | Select-Object -First 1) } else { $null }
        $route = if ($binding -and $binding.route) { $binding.route } else { $opName }

        if ([string]::IsNullOrWhiteSpace($method)) {
            Write-Host "  skip '$opName' (no HTTP method — not an HTTP trigger)"
            continue
        }

        # Translate route template params (e.g. options/{*path}) to APIM's {path}.
        $templateParam = $null
        if ($route -match '{.*}') {
            $route = $route -replace '\*', ''
            if ($route -match '{([^}]*)}') { $templateParam = $Matches[1] }
        }

        # Create the operation if it doesn't exist (idempotent). Backend routing is
        # handled by the API-level set-backend-service policy in apimApis.bicep,
        # which every operation inherits via <base/> — so no per-operation policy
        # is set here (and it avoids az rest, which can't decode APIM's BOM'd
        # policy responses on Windows).
        az apim api operation show --resource-group $ResourceGroup --service-name $ApimName `
            --api-id $FunctionName --operation-id $opName -o none 2>$null
        if ($LASTEXITCODE -eq 0) {
            Write-Host "  '$opName' already exists — skip"
            continue
        }

        Write-Host "  creating operation '$opName' [$($method.ToUpper()) /$route]"
        $createArgs = @(
            'apim', 'api', 'operation', 'create',
            '--resource-group', $ResourceGroup, '--service-name', $ApimName,
            '--api-id', $FunctionName, '--operation-id', $opName,
            '--display-name', $opName, '--method', $method.ToUpper(),
            '--url-template', "/$route"
        )
        if ($templateParam) {
            $createArgs += @('--template-parameters', "name=$templateParam", 'required=true', 'type=string')
        }
        az @createArgs -o none
        if ($LASTEXITCODE -eq 0) {
            Write-Host "  ✔ '$opName' created"
        } else {
            Write-Warning "  failed to create '$opName'; continuing."
        }
    }
}

# Inject the func host master key into the APIM backend so APIM can call
# key-protected functions. Done here (postdeploy) rather than in Bicep because the
# key isn't available at provision time — the host runtime isn't running until code
# is deployed (listKeys returns InternalServerError). Under DEVELOPMENT_MODE the
# functions are anonymous, so this is a harmless no-op. Uses an inline Bicep deploy
# (not az rest, which can't decode APIM's BOM'd responses on Windows).
function Set-BackendKey([string]$FunctionName, [string]$BackendUrl) {
    if ([string]::IsNullOrWhiteSpace($FunctionName)) { return }
    $mk = az functionapp keys list --name $FunctionName --resource-group $ResourceGroup --query masterKey -o tsv 2>$null
    if ([string]::IsNullOrWhiteSpace($mk)) {
        Write-Warning "  no master key for '$FunctionName' yet; backend left credential-less."
        return
    }
    $resId = "https://management.azure.com/subscriptions/$($env:AZURE_SUBSCRIPTION_ID)/resourceGroups/$ResourceGroup/providers/Microsoft.Web/sites/$FunctionName"
    $bicep = @"
resource backend 'Microsoft.ApiManagement/service/backends@2024-06-01-preview' = {
  name: '$ApimName/$FunctionName'
  properties: {
    description: '$FunctionName'
    url: '$BackendUrl'
    protocol: 'http'
    resourceId: '$resId'
    credentials: { header: { 'x-functions-key': [ '$mk' ] } }
  }
}
"@
    $bicepFile = (New-TemporaryFile).FullName + '.bicep'
    [System.IO.File]::WriteAllText($bicepFile, $bicep)
    az deployment group create --resource-group $ResourceGroup --template-file $bicepFile --no-prompt -o none 2>$null
    if ($LASTEXITCODE -eq 0) { Write-Host "  ✔ backend key set for '$FunctionName'" }
    else { Write-Warning "  backend key deploy failed for '$FunctionName'" }
    Remove-Item $bicepFile -ErrorAction SilentlyContinue
}

foreach ($app in $FunctionApps) { Sync-One $app }

# Backend credentials (api + titiler; the storage API has no backend).
Set-BackendKey $env:FUNCTION_API_NAME "https://$($env:FUNCTION_API_NAME).azurewebsites.net/api"
Set-BackendKey $env:FUNCTION_TITILER_NAME "https://$($env:FUNCTION_TITILER_NAME).azurewebsites.net"

Write-Host "sync-apim-operations: done."
