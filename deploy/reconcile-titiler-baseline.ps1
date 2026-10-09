#!/usr/bin/env pwsh
# azd postprovision: remove TiTiler access that Bicep no longer grants.
#
# Bicep deployments are incremental, so dropping a role assignment or an APIM
# operation from the template leaves the live one in place. This script brings
# the live state down to what infra declares:
#
#   1. TiTiler's system identity keeps data roles only on its own host storage
#      account (TITILER_STORAGE_ACCOUNT_NAME). Every other assignment, e.g. the
#      Blob Data Owner it used to hold on the shared account, is deleted.
#   2. TiTiler's APIM API keeps only the get-tiles operation. Anything else,
#      e.g. the catch-all operation an older op-sync hook created, is deleted.
#
# The shared user-assigned identity, the /data mount and the host storage move
# are handled by Bicep itself (infra/modules/functionApp.bicep).
#
# Safe to re-run. Fails (non-zero) if anything it should remove is still there.
# The decisions are made by .github/scripts/titiler_baseline.py (unit tested).

param(
    [string]$FunctionName = $env:FUNCTION_TITILER_NAME,
    [string]$ResourceGroup = $env:AZURE_RESOURCE_GROUP,
    [string]$StorageAccountName = $env:TITILER_STORAGE_ACCOUNT_NAME,
    [string]$ApimName = $env:APIM_NAME
)

$ErrorActionPreference = 'Stop'

foreach ($pair in @(
        @('FUNCTION_TITILER_NAME', $FunctionName),
        @('AZURE_RESOURCE_GROUP', $ResourceGroup),
        @('TITILER_STORAGE_ACCOUNT_NAME', $StorageAccountName),
        @('APIM_NAME', $ApimName))) {
    if ([string]::IsNullOrWhiteSpace($pair[1])) {
        throw "reconcile-titiler-baseline: $($pair[0]) is required (azd provides it from main.bicep outputs)."
    }
}

$helper = Join-Path (Split-Path -Parent $PSScriptRoot) '.github/scripts/titiler_baseline.py'
$python = (Get-Command python -ErrorAction SilentlyContinue) ?? (Get-Command python3 -ErrorAction SilentlyContinue)
if (-not $python) { throw 'reconcile-titiler-baseline: python is required.' }

function Invoke-Az {
    $output = az @args
    if ($LASTEXITCODE -ne 0) { throw "az $($args -join ' ') failed." }
    return $output
}

function Get-StaleRoles([string]$PrincipalId, [string]$AllowedScope) {
    # --all plus a local principal filter rather than --assignee, which
    # resolves through Microsoft Graph that deploy identities often can't read.
    $json = Invoke-Az role assignment list --all -o json
    $stale = $json | & $python.Source $helper stale-roles --principal-id $PrincipalId --allowed-scope $AllowedScope
    if ($LASTEXITCODE -ne 0) { throw 'titiler_baseline.py stale-roles failed.' }
    return @($stale | Where-Object { $_ })
}

function Get-StaleOperations {
    $json = Invoke-Az apim api operation list --resource-group $ResourceGroup `
        --service-name $ApimName --api-id $FunctionName -o json
    $stale = $json | & $python.Source $helper stale-operations
    if ($LASTEXITCODE -ne 0) { throw 'titiler_baseline.py stale-operations failed.' }
    return @($stale | Where-Object { $_ })
}

# --- 1. Role assignments ------------------------------------------------------
$principalId = Invoke-Az functionapp identity show --name $FunctionName `
    --resource-group $ResourceGroup --query principalId -o tsv
if ([string]::IsNullOrWhiteSpace($principalId)) {
    throw "reconcile-titiler-baseline: '$FunctionName' has no system-assigned identity."
}
$allowedScope = Invoke-Az storage account show --name $StorageAccountName `
    --resource-group $ResourceGroup --query id -o tsv

foreach ($id in Get-StaleRoles $principalId $allowedScope) {
    Write-Host "  removing TiTiler role assignment $id"
    Invoke-Az role assignment delete --ids $id -o none | Out-Null
}
$left = Get-StaleRoles $principalId $allowedScope
if ($left.Count -gt 0) {
    throw "reconcile-titiler-baseline: role assignments still present: $($left -join ', ')"
}
Write-Host "✔ TiTiler identity holds roles only on '$StorageAccountName'."

# --- 2. APIM operations -------------------------------------------------------
foreach ($name in Get-StaleOperations) {
    Write-Host "  removing APIM operation '$name' from '$FunctionName'"
    Invoke-Az apim api operation delete --resource-group $ResourceGroup `
        --service-name $ApimName --api-id $FunctionName --operation-id $name --yes -o none | Out-Null
}
$left = Get-StaleOperations
if ($left.Count -gt 0) {
    throw "reconcile-titiler-baseline: APIM operations still present: $($left -join ', ')"
}
Write-Host "✔ TiTiler APIM API exposes only get-tiles."
