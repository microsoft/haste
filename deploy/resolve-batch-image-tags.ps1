#!/usr/bin/env pwsh
# azd preprovision: make the immutable Batch-pool image tags transparent.
#
# When an environment reuses an existing (shared) Batch pool
# (HASTE_BATCH_POOL_MODE=Existing), the pool's container image tags are fixed at
# pool-creation time and can't be changed (deploymentConfiguration is immutable).
# The api/queues app settings must run tasks with a tag the shared ACR actually
# has, so they need to match the pool. Rather than making the operator hand-match
# HASTE_TRAINING_IMAGE / HASTE_IMAGERYPREP_IMAGE, read the pool's
# containerImageNames off the management plane and set them automatically — unless
# the operator has already provided an explicit override.
#
# No-op unless HASTE_BATCH_POOL_MODE=Existing and HASTE_EXISTING_BATCH_POOL_ID is
# a Batch pool ARM resource id. Best-effort: any failure logs and continues so the
# committed defaults / explicit overrides still apply.
#
# Inputs (azd environment): HASTE_BATCH_POOL_MODE, HASTE_EXISTING_BATCH_POOL_ID,
# HASTE_TRAINING_IMAGE (optional override), HASTE_IMAGERYPREP_IMAGE (optional
# override).

param(
    [string]$PoolMode = $env:HASTE_BATCH_POOL_MODE,
    [string]$PoolId = $env:HASTE_EXISTING_BATCH_POOL_ID
)

$ErrorActionPreference = 'Stop'

if ($PoolMode -ne 'Existing') {
    Write-Host "resolve-batch-images: HASTE_BATCH_POOL_MODE is '$PoolMode' (not 'Existing') — nothing to resolve."
    return
}
if ([string]::IsNullOrWhiteSpace($PoolId) -or $PoolId -notlike '/subscriptions/*') {
    Write-Warning "resolve-batch-images: HASTE_EXISTING_BATCH_POOL_ID is not a Batch pool resource id — skipping (got: '$PoolId')."
    return
}

# Persist an azd env var only when the operator hasn't already set an explicit
# override, so a deliberate override is never clobbered.
function Set-IfUnset([string]$Name, [string]$Value) {
    $current = [Environment]::GetEnvironmentVariable($Name)
    if (-not [string]::IsNullOrWhiteSpace($current)) {
        Write-Host "resolve-batch-images: $Name already set to '$current' — keeping the override."
        return
    }
    azd env set $Name $Value | Out-Null
    if ($LASTEXITCODE -eq 0) {
        Write-Host "resolve-batch-images: set $Name = '$Value' from the shared pool."
    } else {
        Write-Warning "resolve-batch-images: 'azd env set $Name' failed."
    }
}

try {
    $poolJson = az rest --method get `
        --uri "https://management.azure.com$($PoolId)?api-version=2024-07-01" -o json 2>$null
    if ($LASTEXITCODE -ne 0 -or [string]::IsNullOrWhiteSpace($poolJson)) {
        Write-Warning "resolve-batch-images: could not read the pool ($PoolId). Leaving image tags as configured."
        return
    }

    $images = ($poolJson | ConvertFrom-Json).properties.deploymentConfiguration.virtualMachineConfiguration.containerConfiguration.containerImageNames
    if (-not $images) {
        Write-Warning "resolve-batch-images: the pool declares no containerImageNames. Leaving image tags as configured."
        return
    }

    # Pool images are '<registry>/<repo>:<tag>'; the app-settings convention is
    # '<repo>:<tag>'. Strip the registry/path and classify by repo name.
    $training = $null
    $imageryprep = $null
    foreach ($img in $images) {
        $repoTag = ($img -split '/')[-1]
        if ($repoTag -match 'imageryprep') { $imageryprep = $repoTag }
        elseif ($repoTag -match 'training') { $training = $repoTag }
    }

    if ($training) { Set-IfUnset 'HASTE_TRAINING_IMAGE' $training }
    else { Write-Warning "resolve-batch-images: no training image found on the pool." }
    if ($imageryprep) { Set-IfUnset 'HASTE_IMAGERYPREP_IMAGE' $imageryprep }
    else { Write-Warning "resolve-batch-images: no imageryprep image found on the pool." }
}
catch {
    Write-Warning "resolve-batch-images: failed to resolve image tags (continuing): $($_.Exception.Message)"
}
