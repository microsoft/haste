#!/usr/bin/env pwsh
# azd postdeploy for titiler: remove the temporary deploy rule that
# open-titiler-deploy-access.ps1 added.
& (Join-Path $PSScriptRoot 'function-deploy-access.ps1') -Action Close
