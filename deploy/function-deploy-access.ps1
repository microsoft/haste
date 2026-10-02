#!/usr/bin/env pwsh
# Temporarily let this machine publish to a function app whose main or SCM site
# denies traffic by default (TiTiler; see infra/modules/functions.bicep).
#
#   -Action Open   allow this machine's public IPv4 address (/32) on each site
#                  that denies by default, after clearing deploy rules that a
#                  failed deployment left behind
#   -Action Close  remove every temporary deploy rule (haste-ci-*) again
#
# azd runs Open as the titiler predeploy hook and Close as its postdeploy hook.
# If `azd deploy` fails in between, run this script with -Action Close.
#
# The address is looked up from https://api.ipify.org unless -SourceAddress or
# HASTE_DEPLOY_SOURCE_IP names it, for networks where Azure sees a different
# egress address than the public internet does.
#
# Requires: az (logged in) and python. The rule evaluation is shared with
# .github/scripts/deploy_apps.sh through .github/scripts/function_network_baseline.py.

param(
    [Parameter(Mandatory)]
    [ValidateSet('Open', 'Close')]
    [string]$Action,
    [string]$FunctionName = $env:FUNCTION_TITILER_NAME,
    [string]$ResourceGroup = $env:AZURE_RESOURCE_GROUP,
    [string]$SourceAddress = $env:HASTE_DEPLOY_SOURCE_IP
)

$ErrorActionPreference = 'Stop'
$rulePrefix = 'haste-ci-'
$ruleName = "${rulePrefix}azd"

if ([string]::IsNullOrWhiteSpace($FunctionName) -or [string]::IsNullOrWhiteSpace($ResourceGroup)) {
    throw "deploy-access: FunctionName and ResourceGroup are required (azd provides FUNCTION_TITILER_NAME and AZURE_RESOURCE_GROUP)."
}

$helper = Join-Path (Split-Path -Parent $PSScriptRoot) '.github/scripts/function_network_baseline.py'
$python = $null
foreach ($candidate in @('python', 'python3')) {
    $cmd = Get-Command $candidate -ErrorAction SilentlyContinue
    if ($cmd) { $python = $cmd.Source; break }
}
if (-not $python) {
    throw "deploy-access: no python interpreter found on PATH (tried 'python', 'python3')."
}

function Invoke-Az {
    $output = & az @args
    if ($LASTEXITCODE -ne 0) { throw "deploy-access: 'az $($args -join ' ')' failed." }
    $output
}

function Invoke-Helper([string]$Json, [string[]]$Arguments) {
    $output = $Json | & $python $helper @Arguments
    if ($LASTEXITCODE -ne 0) { throw "deploy-access: function_network_baseline.py $($Arguments -join ' ') failed." }
    @($output | Where-Object { $_ })
}

function Get-SiteConfig {
    (Invoke-Az functionapp config show --name $FunctionName --resource-group $ResourceGroup --output json) -join "`n"
}

function Get-ScmFlag([string]$Site) {
    if ($Site -eq 'scm') { 'true' } else { 'false' }
}

function Remove-DeployRules {
    foreach ($line in (Invoke-Helper (Get-SiteConfig) @('rules', '--prefix', $rulePrefix))) {
        $site, $name = $line -split "`t", 2
        Write-Host "deploy-access: removing '$name' from the $site site of $FunctionName"
        Invoke-Az functionapp config access-restriction remove `
            --name $FunctionName --resource-group $ResourceGroup `
            --rule-name $name --scm-site (Get-ScmFlag $site) --output none | Out-Null
    }
}

if ($Action -eq 'Close') {
    Remove-DeployRules
    return
}

$sites = Invoke-Helper (Get-SiteConfig) @('deny-sites')
if (-not $sites) {
    Write-Host "deploy-access: $FunctionName allows traffic by default; nothing to open."
    return
}
if ([string]::IsNullOrWhiteSpace($SourceAddress)) {
    $SourceAddress = "$(Invoke-RestMethod -Uri 'https://api.ipify.org' -TimeoutSec 30)".Trim()
}
& $python $helper public-ipv4 $SourceAddress
if ($LASTEXITCODE -ne 0) {
    throw "deploy-access: '$SourceAddress' is not a public IPv4 address; set HASTE_DEPLOY_SOURCE_IP."
}
Remove-DeployRules
foreach ($site in $sites) {
    Write-Host "deploy-access: allowing this machine on the $site site of $FunctionName"
    Invoke-Az functionapp config access-restriction add `
        --name $FunctionName --resource-group $ResourceGroup `
        --rule-name $ruleName --action Allow --ip-address "$SourceAddress/32" `
        --priority 90 --scm-site (Get-ScmFlag $site) --output none | Out-Null
}
