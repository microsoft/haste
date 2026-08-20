#!/usr/bin/env pwsh
# azd postpackage: restore the Function App requirements after
# deploy/pin-hastegeo-wheel.ps1 pinned the published hastegeo wheel.
#
# Runs immediately after packaging, so the deployment artifact already carries the
# pinned wheel — reverting here is safe and keeps the working tree clean even if the
# subsequent deploy fails.
#
# Restores each file from the verbatim backup the pin hook took, so the round trip
# is byte-for-byte. Falls back to `set_hastegeo_source.py --mode editable` when no
# backup exists (e.g. this hook ran without a preceding pin); that restores the
# correct install source but also rewrites the commented reference URL to the last
# pinned version, leaving a harmless one-line diff.
#
# Best-effort by design: the package is already built, so a failure here is a dirty
# working tree (visible in `git status`, one command to undo), not a bad deploy. It
# must not fail an otherwise good `azd up`.

$ErrorActionPreference = 'Continue'

$repoRoot = Split-Path -Parent $PSScriptRoot
$setter = Join-Path $repoRoot '.github/scripts/set_hastegeo_source.py'

$requirementFiles = @(
    (Join-Path $repoRoot 'api/hastefuncapi/requirements.txt'),
    (Join-Path $repoRoot 'api/hastefuncqueues/requirements.txt')
)

# Must match the path computed by pin-hastegeo-wheel.ps1.
$backupDir = Join-Path ([System.IO.Path]::GetTempPath()) 'haste-azd-hastegeo-pin'
function Get-BackupPath([string]$RequirementsPath) {
    $key = Split-Path -Leaf (Split-Path -Parent $RequirementsPath)
    return (Join-Path $backupDir "$key.bak")
}

$targets = @($requirementFiles | Where-Object { Test-Path $_ })
if ($targets.Count -eq 0) {
    Write-Warning "unpin-hastegeo: no Function App requirements.txt found."
    return
}

$restored = @()
$needFallback = @()
foreach ($target in $targets) {
    $backup = Get-BackupPath $target
    if (Test-Path $backup) {
        try {
            Copy-Item -LiteralPath $backup -Destination $target -Force
            Remove-Item -LiteralPath $backup -Force -ErrorAction SilentlyContinue
            $restored += $target
        }
        catch {
            Write-Warning "unpin-hastegeo: could not restore $target from backup: $($_.Exception.Message)"
            $needFallback += $target
        }
    }
    else {
        $needFallback += $target
    }
}

if ($needFallback.Count -gt 0) {
    $python = $null
    foreach ($candidate in @('python', 'python3')) {
        $cmd = Get-Command $candidate -ErrorAction SilentlyContinue
        if ($cmd) { $python = $cmd.Source; break }
    }

    if (-not $python -or -not (Test-Path $setter)) {
        Write-Warning "unpin-hastegeo: no backup and no usable setter — requirements may still be pinned. Revert with: python .github/scripts/set_hastegeo_source.py --mode editable api/hastefuncapi/requirements.txt api/hastefuncqueues/requirements.txt"
    }
    else {
        Write-Host "unpin-hastegeo: no backup for $($needFallback.Count) file(s) — falling back to --mode editable."
        & $python $setter --mode editable @needFallback
        if ($LASTEXITCODE -ne 0) {
            Write-Warning "unpin-hastegeo: failed to restore the editable source — check 'git status'."
        }
        else {
            $restored += $needFallback
        }
    }
}

if ($restored.Count -gt 0) {
    Write-Host "unpin-hastegeo: restored the editable hastegeo source in $($restored.Count) requirements file(s)."
}
