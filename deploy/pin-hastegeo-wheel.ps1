#!/usr/bin/env pwsh
# azd prepackage: pin the published hastegeo wheel into the Function App requirements.
#
# api/*/requirements.txt commit `-e ../../hastelib` as the default install source so
# docker-compose and local Function builds work straight from the checked-out tree
# with no wheel publish. That relative path does NOT resolve inside an azd
# deployment package — only api/<app> is uploaded — so a deployed app would fail to
# install hastegeo at all.
#
# CI already handles this in .github/scripts/deploy_apps.sh, which rewrites the line
# to the published wheel before `func azure functionapp publish`. azd had no
# equivalent, so `azd up` silently shipped the unresolvable editable path from
# 2026-07-24 (PR #75 inverted the committed default) onward. This hook restores
# parity: pin before packaging; deploy/unpin-hastegeo-wheel.ps1 reverts afterwards.
#
# Fails the deploy on error, deliberately. A missing or mis-resolved wheel produces
# an app that deploys "successfully" and only breaks at runtime.
#
# Each file is backed up verbatim to a deterministic temp path before rewriting so
# unpin-hastegeo-wheel.ps1 can restore it byte-for-byte. That matters because
# set_hastegeo_source.py --mode editable round-trips the pinned URL into the
# commented reference line, which would otherwise leave a diff in the working tree
# after every deploy.
#
# Inputs (azd environment): HASTE_HASTEGEO_VERSION — an exact X.Y.Z or X.Y.ZrcN.
# Blank (the default) resolves the latest stable release from haste-binaries.
# Requires: python, and the `gh` CLI authenticated (the resolver lists release assets).

param(
    [string]$Version = $env:HASTE_HASTEGEO_VERSION
)

$ErrorActionPreference = 'Stop'

$repoRoot = Split-Path -Parent $PSScriptRoot
$resolver = Join-Path $repoRoot '.github/scripts/resolve_hastegeo_deploy.py'
$setter = Join-Path $repoRoot '.github/scripts/set_hastegeo_source.py'

# Only the apps that actually depend on hastegeo. titiler has no hastegeo line and
# is intentionally excluded; set_hastegeo_source would no-op on it anyway.
$requirementFiles = @(
    (Join-Path $repoRoot 'api/hastefuncapi/requirements.txt'),
    (Join-Path $repoRoot 'api/hastefuncqueues/requirements.txt')
)

# Must match the path computed by unpin-hastegeo-wheel.ps1.
function Get-BackupDir {
    return (Join-Path ([System.IO.Path]::GetTempPath()) 'haste-azd-hastegeo-pin')
}

function Get-BackupPath([string]$RequirementsPath) {
    $key = Split-Path -Leaf (Split-Path -Parent $RequirementsPath)
    return (Join-Path (Get-BackupDir) "$key.bak")
}

function Get-PythonExe {
    foreach ($candidate in @('python', 'python3')) {
        $cmd = Get-Command $candidate -ErrorAction SilentlyContinue
        if ($cmd) { return $cmd.Source }
    }
    throw "pin-hastegeo: no python interpreter found on PATH (tried 'python', 'python3')."
}

$python = Get-PythonExe

foreach ($path in @($resolver, $setter)) {
    if (-not (Test-Path $path)) {
        throw "pin-hastegeo: required script not found: $path"
    }
}

$targets = @($requirementFiles | Where-Object { Test-Path $_ })
if ($targets.Count -eq 0) {
    throw "pin-hastegeo: no Function App requirements.txt found to pin."
}

if ([string]::IsNullOrWhiteSpace($Version)) {
    Write-Host "pin-hastegeo: HASTE_HASTEGEO_VERSION unset — resolving the latest stable release."
} else {
    Write-Host "pin-hastegeo: resolving hastegeo $Version."
}

$resolved = & $python $resolver --version "$Version" 2>&1
if ($LASTEXITCODE -ne 0) {
    throw "pin-hastegeo: could not resolve the hastegeo wheel.`n$resolved"
}

# The resolver prints `key=value` lines: version, wheel_name, url.
$url = ($resolved | Select-String -Pattern '^url=' | Select-Object -First 1) -replace '^url=', ''
$resolvedVersion = ($resolved | Select-String -Pattern '^version=' | Select-Object -First 1) -replace '^version=', ''

if ([string]::IsNullOrWhiteSpace($url)) {
    throw "pin-hastegeo: resolver returned no wheel url.`n$resolved"
}

Write-Host "pin-hastegeo: pinning hastegeo $resolvedVersion"
Write-Host "pin-hastegeo:   $url"

$backupDir = Get-BackupDir
New-Item -ItemType Directory -Force -Path $backupDir | Out-Null
foreach ($target in $targets) {
    $backup = Get-BackupPath $target
    if (Test-Path $backup) {
        Write-Host "pin-hastegeo: backup already exists for $(Split-Path -Leaf (Split-Path -Parent $target)) — keeping the original."
    }
    else {
        Copy-Item -LiteralPath $target -Destination $backup -Force
    }
}

& $python $setter --mode wheel --url "$url" @targets
if ($LASTEXITCODE -ne 0) {
    throw "pin-hastegeo: failed to rewrite the requirements files."
}

foreach ($target in $targets) {
    Write-Host "pin-hastegeo: pinned $(Resolve-Path -Relative $target)"
}
