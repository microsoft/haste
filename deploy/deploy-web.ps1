#!/usr/bin/env pwsh
# azd postdeploy hook: build the HASTE UI and publish it to the Static Web App's
# PRODUCTION environment.
#
# Why a hook instead of an azd `web` service: azd only passes
# `swa deploy --env production` when no swa-cli.config.json exists in the service
# path. We keep ui/swa-cli.config.json for local `swa start`, so azd's native SWA
# deploy would target a *preview* environment. This hook calls the SWA CLI
# directly with `--env production`, preserving one-command `azd up`.
#
# Inputs (all provided by azd from the environment's .env, i.e. Bicep outputs):
#   VITE_AZURE_MAPS_CLIENT_ID  per-environment Azure Maps client id
#   STATIC_WEB_APP_NAME        SWA resource name
#   AZURE_RESOURCE_GROUP       resource group
# No secret is committed: the static build config lives in ui/.env.production and
# the Maps client id is injected here into Vite's highest-precedence env file.

$ErrorActionPreference = 'Stop'
$repoRoot = Split-Path -Parent $PSScriptRoot
$ui = Join-Path $repoRoot 'ui'

Push-Location $ui
try {
    # 1. Inject the per-environment Maps client id into Vite's highest-precedence,
    #    gitignored env file (merged over the committed ui/.env.production).
    if ([string]::IsNullOrWhiteSpace($env:VITE_AZURE_MAPS_CLIENT_ID)) {
        Write-Warning "VITE_AZURE_MAPS_CLIENT_ID is unset; the map will fall back to placeholder auth."
    }
    Set-Content -Path '.env.production.local' -Encoding utf8 `
        -Value "VITE_AZURE_MAPS_CLIENT_ID=$($env:VITE_AZURE_MAPS_CLIENT_ID)"

    # 2. Ensure dependencies, then run the production build (loads .env.production
    #    + .env.production.local).
    if (-not (Test-Path 'node_modules')) {
        Write-Host "deploy-web: installing npm dependencies (npm ci)..."
        npm ci
        if ($LASTEXITCODE -ne 0) { throw "npm ci failed" }
    }
    Write-Host "deploy-web: building UI (npm run build)..."
    npm run build
    if ($LASTEXITCODE -ne 0) { throw "npm run build failed" }

    # 3. Retrieve the SWA deployment token (uses the current az login / CI identity).
    if ([string]::IsNullOrWhiteSpace($env:STATIC_WEB_APP_NAME) -or
        [string]::IsNullOrWhiteSpace($env:AZURE_RESOURCE_GROUP)) {
        throw "STATIC_WEB_APP_NAME / AZURE_RESOURCE_GROUP not set; run 'azd provision' first."
    }
    $token = az staticwebapp secrets list `
        --name $env:STATIC_WEB_APP_NAME `
        --resource-group $env:AZURE_RESOURCE_GROUP `
        --query 'properties.apiKey' -o tsv
    if ([string]::IsNullOrWhiteSpace($token)) {
        throw "could not retrieve deployment token for SWA '$env:STATIC_WEB_APP_NAME'"
    }

    # 4. Publish the built app to the PRODUCTION environment.
    Write-Host "deploy-web: deploying ./dist to '$env:STATIC_WEB_APP_NAME' (production)..."
    npx -y "@azure/static-web-apps-cli@latest" deploy ./dist `
        --deployment-token $token `
        --env production `
        --no-use-keychain
    if ($LASTEXITCODE -ne 0) { throw "swa deploy failed" }

    Write-Host "deploy-web: SWA '$env:STATIC_WEB_APP_NAME' published to production."
}
finally {
    Pop-Location
}
