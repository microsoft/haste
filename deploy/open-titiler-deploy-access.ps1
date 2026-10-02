#!/usr/bin/env pwsh
# azd predeploy for titiler: let this machine publish through TiTiler's locked
# main and SCM sites. close-titiler-deploy-access.ps1 removes the rule again.
& (Join-Path $PSScriptRoot 'function-deploy-access.ps1') -Action Open
