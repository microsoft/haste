#!/usr/bin/env pwsh
# azd postdeploy orchestrator. Runs after the function apps are published:
#   1. deploy-web             — build + publish the SWA to production (critical)
#   2. sync-apim-operations   — add APIM operations for newly deployed endpoints
#   3. seed-storage-defaults  — seed admin settings + the first admin user (once)
#   4. invite-user            — invite the deployer to the SWA so they can sign in
# Steps 2-4 are best-effort: a failure is logged but does not fail `azd up`, since
# they can be re-run and shouldn't block a successful infra + app deploy.

$ErrorActionPreference = 'Stop'
$here = $PSScriptRoot

# 1. SWA publish — critical (let it propagate / fail the deploy).
& (Join-Path $here 'deploy-web.ps1')

# 2-4. Best-effort app wiring.
foreach ($step in @('sync-apim-operations.ps1', 'seed-storage-defaults.ps1', 'invite-user.ps1')) {
    Write-Host ""
    Write-Host "=== postdeploy: $step ==="
    try {
        & (Join-Path $here $step)
    } catch {
        Write-Warning "postdeploy: $step failed (continuing): $($_.Exception.Message)"
    }
}

Write-Host ""
Write-Host "postdeploy: complete."
