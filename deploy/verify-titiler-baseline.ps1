#!/usr/bin/env pwsh
#Requires -Version 7.0
# Verify a deployed environment's TiTiler hardening and print PASS/FAIL per check.
#
#   pwsh deploy/verify-titiler-baseline.ps1 -EnvName dev1
#   pwsh deploy/verify-titiler-baseline.ps1 -EnvName dev1 -SwaCookie '<StaticWebAppsAuthCookie value>'
#   pwsh deploy/verify-titiler-baseline.ps1 -EnvName dev1 -ReportPath .\titiler-dev1.json
#
# Names come from .azure/<EnvName>/.env (azd writes main.bicep outputs there).
# Run it before `azd up` too: the failures then show the old state.
#
# What it touches: read-only az/ARM calls, plus one APIM listSecrets call for the
# built-in all-APIs ("master") subscription key, kept in memory and never
# printed. The UI's own product key can't be used directly: that product
# validates an X-MS-AUTH-TOKEN only the Static Web App can mint. The master key
# skips product policies but still runs the TiTiler API policy, where the limits
# live. One request also goes to TiTiler's own hostname (expected to be refused).
#
# -SwaCookie runs the per-user rate-limit test. It sends ~1,250 requests through
# the Static Web App, which uses up this machine's per-client allowance for up to
# a minute. If the limit turns out to be shared, every dev user is throttled for
# that minute, so run it on a dev environment only. Get the cookie from the
# browser after signing in to the environment's UI: DevTools > Application >
# Cookies > StaticWebAppsAuthCookie (value only).
#
# Exit code: 0 when nothing failed, 1 otherwise.

param(
    [string]$EnvName = 'dev1',
    [string]$SwaCookie,
    [string]$ReportPath,
    # Any approved public COG and a point inside it, for the rendering check.
    [string]$PublicCogUrl = 'https://vantor-opendata.s3.amazonaws.com/events/Nepal-Flooding-Aug-2026/B160001101ECBD10.tif',
    [double]$PublicCogLon = 85.52,
    [double]$PublicCogLat = 28.2
)

$ErrorActionPreference = 'Stop'
$repoRoot = Split-Path -Parent $PSScriptRoot

# --- Environment --------------------------------------------------------------
$envFile = Join-Path $repoRoot ".azure/$EnvName/.env"
if (-not (Test-Path $envFile)) { throw "No azd environment file at $envFile." }
$cfg = @{}
foreach ($line in Get-Content $envFile) {
    if ($line -match '^\s*([A-Za-z0-9_]+)\s*=\s*"?(.*?)"?\s*$') { $cfg[$Matches[1]] = $Matches[2] }
}
foreach ($key in 'AZURE_SUBSCRIPTION_ID', 'AZURE_RESOURCE_GROUP', 'FUNCTION_TITILER_NAME', 'APIM_NAME', 'STORAGE_ACCOUNT_NAME', 'STATIC_WEB_APP_NAME') {
    if (-not $cfg[$key]) { throw "$key is missing from $envFile." }
}
$sub = $cfg.AZURE_SUBSCRIPTION_ID
$rg = $cfg.AZURE_RESOURCE_GROUP
$titiler = $cfg.FUNCTION_TITILER_NAME
$apim = $cfg.APIM_NAME
$sharedSa = $cfg.STORAGE_ACCOUNT_NAME
# Written by azd after the first provision with the isolated host storage.
$titilerSa = $cfg.TITILER_STORAGE_ACCOUNT_NAME
if (-not $titilerSa) { $titilerSa = "$($cfg.HASTE_RESOURCE_PREFIX)hastetiler$($cfg.HASTE_RANDOM_SUFFIX)sa" }

function Invoke-Az {
    $out = az @args --subscription $sub 2>$null
    if ($LASTEXITCODE -ne 0) { throw "az $($args[0..2] -join ' ') failed." }
    return $out
}
function Invoke-AzJson { return (Invoke-Az @args -o json | Out-String | ConvertFrom-Json) }

$armToken = Invoke-Az account get-access-token --resource https://management.azure.com --query accessToken -o tsv
$apimBase = "https://management.azure.com/subscriptions/$sub/resourceGroups/$rg/providers/Microsoft.ApiManagement/service/$apim"
$apiVersion = 'api-version=2024-06-01-preview'
function Invoke-Arm([string]$Method, [string]$Url) {
    return Invoke-RestMethod -Method $Method -Uri $Url -Headers @{ Authorization = "Bearer $armToken" }
}

# --- Results ------------------------------------------------------------------
$results = [System.Collections.Generic.List[object]]::new()
function Test-Check([string]$Id, [string]$Name, [scriptblock]$Body) {
    try {
        $r = & $Body
        $status = if ($r.Skip) { 'SKIP' } elseif ($r.Ok) { 'PASS' } else { 'FAIL' }
        $detail = $r.Detail
    } catch {
        $status = 'FAIL'
        $detail = "error: $($_.Exception.Message)"
    }
    $results.Add([pscustomobject]@{ Id = $Id; Check = $Name; Result = $status; Detail = $detail })
    $color = @{ PASS = 'Green'; FAIL = 'Red'; SKIP = 'Yellow' }[$status]
    Write-Host ("[{0}] {1,-4} {2}" -f $status, $Id, $Name) -ForegroundColor $color
    if ($detail) { Write-Host "         $detail" }
}
function Result([bool]$Ok, [string]$Detail = '') { return @{ Ok = $Ok; Detail = $Detail } }
function Skip([string]$Detail) { return @{ Skip = $true; Detail = $Detail } }

# --- HTTP ---------------------------------------------------------------------
$handler = [System.Net.Http.SocketsHttpHandler]::new()
$handler.AllowAutoRedirect = $false
$http = [System.Net.Http.HttpClient]::new($handler)
$http.Timeout = [TimeSpan]::FromSeconds(90)
function Send-Http([string]$Method, [string]$Url, [hashtable]$Headers = @{}, [string]$Body) {
    $request = [System.Net.Http.HttpRequestMessage]::new([System.Net.Http.HttpMethod]::new($Method), $Url)
    foreach ($k in $Headers.Keys) { [void]$request.Headers.TryAddWithoutValidation($k, $Headers[$k]) }
    if ($Body) { $request.Content = [System.Net.Http.StringContent]::new($Body) }
    $response = $http.SendAsync($request).GetAwaiter().GetResult()
    $bytes = $response.Content.ReadAsByteArrayAsync().GetAwaiter().GetResult()
    return [pscustomobject]@{
        Status = [int]$response.StatusCode
        Type   = $response.Content.Headers.ContentType.MediaType
        Length = $bytes.Length
    }
}

Write-Host "Verifying TiTiler baseline for '$EnvName' ($rg)" -ForegroundColor Cyan

# --- A. TiTiler app, identity and storage -------------------------------------
$site = Invoke-AzJson functionapp show --name $titiler --resource-group $rg
$settings = @{}
foreach ($s in (Invoke-AzJson functionapp config appsettings list --name $titiler --resource-group $rg)) { $settings[$s.name] = $s.value }

Test-Check 'A1' 'TiTiler has only its system-assigned identity' {
    $identity = $site.identity
    $uami = @($identity.userAssignedIdentities.PSObject.Properties).Count
    Result ($identity.type -eq 'SystemAssigned' -and $uami -eq 0) "type=$($identity.type); user-assigned=$uami"
}

Test-Check 'A2' 'No /data file-share mount' {
    $mounts = @(Invoke-AzJson webapp config storage-account list --name $titiler --resource-group $rg)
    Result ($mounts.Count -eq 0) "mounts=$($mounts.Count)"
}

Test-Check 'A3' 'Host state and deployment package use the TiTiler storage account' {
    $deploy = Invoke-Az resource show --ids $site.id --api-version 2023-12-01 --query properties.functionAppConfig.deployment.storage.value -o tsv
    $hostAccount = $settings['AzureWebJobsStorage__accountName']
    $ok = ($hostAccount -eq $titilerSa) -and ($deploy -like "https://$titilerSa.blob.*")
    Result $ok "AzureWebJobsStorage__accountName=$hostAccount; deployment=$deploy"
}

# Null until the isolated storage has been provisioned.
$titilerSaJson = az storage account show --name $titilerSa --resource-group $rg --subscription $sub -o json 2>$null
$titilerSaInfo = if ($LASTEXITCODE -eq 0) { $titilerSaJson | Out-String | ConvertFrom-Json } else { $null }
$missingSa = "storage account '$titilerSa' not found (not provisioned yet?)"

Test-Check 'A4' 'TiTiler identity holds roles only on its own storage account' {
    $saId = if ($titilerSaInfo) { $titilerSaInfo.id.ToLower() } else { '<none>' }
    $principal = $site.identity.principalId
    $mine = @(Invoke-AzJson role assignment list --all | Where-Object { $_.principalId -eq $principal })
    $outside = @($mine | Where-Object { -not ($_.scope.TrimEnd('/').ToLower() -eq $saId -or $_.scope.ToLower().StartsWith($saId + '/')) })
    $detail = "assignments=$($mine.Count); outside own account=$($outside.Count)"
    if ($outside.Count) { $detail += ' -> ' + (($outside | ForEach-Object { "$($_.roleDefinitionName) @ $($_.scope.Split('/')[-1])" }) -join '; ') }
    if (-not $titilerSaInfo) { $detail = "$missingSa; $detail" }
    Result ($mine.Count -gt 0 -and $outside.Count -eq 0) $detail
}

Test-Check 'A5' 'TiTiler storage account: identity-only, private, functions subnet only' {
    if (-not $titilerSaInfo) { return Result $false $missingSa }
    $sa = $titilerSaInfo
    $rules = @($sa.networkRuleSet.virtualNetworkRules)
    $subnetOk = $rules.Count -eq 1 -and $rules[0].virtualNetworkResourceId.ToLower() -eq $site.virtualNetworkSubnetId.ToLower()
    $ok = ($sa.allowSharedKeyAccess -eq $false) -and ($sa.allowBlobPublicAccess -eq $false) -and ($sa.networkRuleSet.defaultAction -eq 'Deny') -and $subnetOk
    Result $ok "sharedKey=$($sa.allowSharedKeyAccess); publicBlob=$($sa.allowBlobPublicAccess); default=$($sa.networkRuleSet.defaultAction); vnetRules=$($rules.Count) (functions subnet: $subnetOk)"
}

Test-Check 'A6' 'Allowed-host setting present, no relaxing GDAL or dev settings' {
    $expected = "$sharedSa.blob.core.windows.net"
    $unsafe = @('GDAL_VRT_RAWRASTERBAND_ALLOWED_SOURCE', 'GDAL_VRT_PYTHON_TRUSTED_MODULES', 'GDAL_HTTP_HEADER_FILE', 'GDAL_HTTP_HEADERS', 'GDAL_HTTP_COOKIEFILE', 'GDAL_HTTP_UNSAFESSL', 'TITILER_DEV_ALLOWED_ORIGINS') |
        Where-Object { $settings.ContainsKey($_) }
    $ok = ($settings['TITILER_ALLOWED_HOSTS'] -eq $expected) -and (@($unsafe).Count -eq 0)
    Result $ok "TITILER_ALLOWED_HOSTS=$($settings['TITILER_ALLOWED_HOSTS']) (expected $expected); relaxing settings: $(if (@($unsafe).Count) { $unsafe -join ', ' } else { 'none' })"
}

Test-Check 'A7' 'Inbound baseline: main and SCM sites deny by default' {
    $config = Invoke-AzJson functionapp config show --name $titiler --resource-group $rg
    $ok = $config.ipSecurityRestrictionsDefaultAction -eq 'Deny' -and $config.scmIpSecurityRestrictionsDefaultAction -eq 'Deny' -and -not $config.scmIpSecurityRestrictionsUseMain
    Result $ok "main=$($config.ipSecurityRestrictionsDefaultAction); scm=$($config.scmIpSecurityRestrictionsDefaultAction); scmUsesMain=$($config.scmIpSecurityRestrictionsUseMain)"
}

Test-Check 'A8' 'Deployed function accepts GET only' {
    $functions = @(Invoke-AzJson functionapp function list --name $titiler --resource-group $rg)
    $methods = @($functions | ForEach-Object { $_.config.bindings | Where-Object { $_.methods } | ForEach-Object { $_.methods } }) | Sort-Object -Unique
    Result ($functions.Count -eq 1 -and ($methods -join ',') -eq 'get') "functions=$($functions.Count); methods=$($methods -join ',')"
}

# --- B. APIM ------------------------------------------------------------------
Test-Check 'B1' 'APIM TiTiler API has only get-tiles' {
    $ops = @(Invoke-AzJson apim api operation list --resource-group $rg --service-name $apim --api-id $titiler)
    $names = @($ops | ForEach-Object { $_.name }) | Sort-Object
    Result (($names -join ',') -eq 'get-tiles') "operations: $($names -join ', ')"
}

Test-Check 'B2' 'APIM TiTiler policy has the limits' {
    $policy = (Invoke-Arm GET "$apimBase/apis/$titiler/policies/policy?$apiVersion&format=rawxml").properties.value
    $limits = ([regex]::Matches($policy, '<rate-limit-by-key ')).Count
    $ok = $limits -eq 2 -and $policy -match 'code="413"' -and $policy -match 'code="414"' -and $policy -match 'X-Forwarded-For'
    Result $ok "rate-limit-by-key=$limits; 413=$($policy -match 'code="413"'); 414=$($policy -match 'code="414"')"
}

# Gateway and the built-in all-APIs subscription key (see header).
$gateway = (Invoke-Az apim show --name $apim --resource-group $rg --query gatewayUrl -o tsv).TrimEnd('/')
$swaHost = Invoke-Az staticwebapp show --name $cfg.STATIC_WEB_APP_NAME --resource-group $rg --query defaultHostname -o tsv
$apimKey = $null
try {
    $apimKey = (Invoke-Arm POST "$apimBase/subscriptions/master/listSecrets?$apiVersion").primaryKey
} catch {
    Write-Host "Could not get the APIM master subscription key: $($_.Exception.Message)" -ForegroundColor Yellow
}
$keyHeader = @{ 'Ocp-Apim-Subscription-Key' = $apimKey }

function Get-TileXY([double]$Lon, [double]$Lat, [int]$Z) {
    $n = [math]::Pow(2, $Z)
    $latRad = $Lat * [math]::PI / 180
    $x = [math]::Floor(($Lon + 180) / 360 * $n)
    $y = [math]::Floor((1 - [math]::Log([math]::Tan($latRad) + 1 / [math]::Cos($latRad)) / [math]::PI) / 2 * $n)
    return $x, $y
}
function Get-TileUrl([string]$DatasetUrl, [string]$Tile = '1/0/0', [string]$Base = "$gateway/api/titiler") {
    return "$Base/cog/tiles/WebMercatorQuad/$Tile`?scale=1&url=$([uri]::EscapeDataString($DatasetUrl))"
}

# --- C. Live behaviour through APIM -------------------------------------------
# Benign targets: the checks only need the request refused, and an
# unpatched environment will actually try to open them.
$live = [ordered]@{
    'C2' = @('Inline VRT is rejected', '<VRTDataset rasterXSize="1" rasterYSize="1"></VRTDataset>', 400)
    'C3' = @('file: URL is rejected', 'file:///etc/hostname', 400)
    'C4' = @('Local path is rejected', '/etc/hostname', 400)
    'C5' = @('GDAL virtual file system path is rejected', '/vsicurl/https://example.com/a.tif', 400)
    'C6' = @('Unapproved storage account is rejected', 'https://example.blob.core.windows.net/c/a.tif', 400)
    'C7' = @('Embedded credentials are rejected', 'https://user:pass@data.source.coop/a.tif', 400)  # pragma: allowlist secret
}

if (-not $apimKey) {
    Test-Check 'C*' 'Live checks through APIM' { Skip 'no APIM subscription key' }
} else {
    Test-Check 'C1' 'Approved public COG renders through APIM' {
        $x, $y = Get-TileXY $PublicCogLon $PublicCogLat 15
        $r = Send-Http GET (Get-TileUrl $PublicCogUrl "15/$x/$y") $keyHeader
        Result ($r.Status -eq 200 -and $r.Type -like 'image/*' -and $r.Length -gt 0) "status=$($r.Status); type=$($r.Type); bytes=$($r.Length)"
    }
    foreach ($id in $live.Keys) {
        $name, $dataset, $expected = $live[$id]
        Test-Check $id $name {
            $r = Send-Http GET (Get-TileUrl $dataset) $keyHeader
            Result ($r.Status -eq $expected) "status=$($r.Status) (expected $expected)"
        }
    }
    Test-Check 'C8' 'Other TiTiler routes are not reachable' {
        $statuses = foreach ($path in '/cog/info', '/cog/preview.png', '/stac/info', '/mosaicjson/info', '/healthz', '/docs', '/openapi.json') {
            (Send-Http GET "$gateway/api/titiler$path`?url=$([uri]::EscapeDataString($PublicCogUrl))" $keyHeader).Status
        }
        $ok = @($statuses | Where-Object { $_ -lt 400 }).Count -eq 0
        Result $ok "statuses: $($statuses -join ', ')"
    }
    Test-Check 'C9' 'POST is refused' {
        $r = Send-Http POST (Get-TileUrl $PublicCogUrl) $keyHeader
        Result ($r.Status -ge 400 -and $r.Status -ne 429) "status=$($r.Status)"
    }
    Test-Check 'C10' 'Request body is refused (413)' {
        $r = Send-Http GET (Get-TileUrl $PublicCogUrl) $keyHeader 'x'
        Result ($r.Status -eq 413) "status=$($r.Status)"
    }
    Test-Check 'C11' 'Overlong URL is refused (414)' {
        $r = Send-Http GET ((Get-TileUrl $PublicCogUrl) + '&pad=' + ('a' * 7000)) $keyHeader
        Result ($r.Status -eq 414) "status=$($r.Status)"
    }
}

Test-Check 'C12' "TiTiler's own hostname is refused" {
    # Flex Consumption apps report the hostname under properties.
    $hostName = $site.defaultHostName ?? $site.properties.defaultHostName
    $r = Send-Http GET "https://$hostName/healthz"
    Result ($r.Status -eq 403) "status=$($r.Status) (expected 403)"
}

# --- D. Per-user rate limit ---------------------------------------------------
# Exhaust this machine's per-client allowance through the Static Web App (the
# UI path), then call APIM directly naming this machine's address in
# X-Forwarded-For. A 429 there means the SWA forwards the real client address
# and the limit is per user.
Test-Check 'D1' 'Per-client rate limit is keyed on the real user address' {
    if (-not $SwaCookie) { return Skip 'pass -SwaCookie to run (see header)' }
    if (-not $apimKey) { return Skip 'no APIM subscription key' }
    $swaUrl = Get-TileUrl 'not-a-url' '1/0/0' "https://$swaHost/api/titiler"
    $cookie = "StaticWebAppsAuthCookie=$SwaCookie"
    $statuses = 1..1250 | ForEach-Object -ThrottleLimit 32 -Parallel {
        $client = $using:http
        $request = [System.Net.Http.HttpRequestMessage]::new([System.Net.Http.HttpMethod]::Get, $using:swaUrl)
        [void]$request.Headers.TryAddWithoutValidation('Cookie', $using:cookie)
        # New connection per request, so a client port in the forwarded
        # address would change between requests and show up as no 429s.
        $request.Headers.ConnectionClose = $true
        [int]$client.SendAsync($request).GetAwaiter().GetResult().StatusCode
    }
    $counts = $statuses | Group-Object | Sort-Object Name | ForEach-Object { "$($_.Name)x$($_.Count)" }
    $throttled = @($statuses | Where-Object { $_ -eq 429 }).Count
    if (@($statuses | Where-Object { $_ -in 401, 302, 403 }).Count -gt 0) {
        return Result $false "SWA refused the cookie ($($counts -join ' ')); sign in again and copy a fresh value"
    }
    if ($throttled -eq 0) {
        return Result $false "no 429 after 1,250 requests ($($counts -join ' ')): the per-client key changes between requests (e.g. includes a port), so the per-client limit is not effective"
    }
    $myIp = (Invoke-RestMethod https://api.ipify.org).Trim()
    $direct = Send-Http GET (Get-TileUrl 'not-a-url') ($keyHeader + @{ 'X-Forwarded-For' = $myIp })
    if ($direct.Status -eq 429) {
        return Result $true "SWA path throttled ($($counts -join ' ')); direct call as $myIp also 429, so the key is this user's address"
    }
    return Result $false "SWA path throttled ($($counts -join ' ')) but a direct call as $myIp got $($direct.Status): the SWA path is keyed on something shared (likely the SWA egress address), so all users share one allowance"
}

# --- Summary ------------------------------------------------------------------
$failed = @($results | Where-Object Result -eq 'FAIL').Count
$passed = @($results | Where-Object Result -eq 'PASS').Count
$skipped = @($results | Where-Object Result -eq 'SKIP').Count
Write-Host ''
Write-Host "PASS $passed  FAIL $failed  SKIP $skipped" -ForegroundColor ($failed ? 'Red' : 'Green')

if ($ReportPath) {
    [ordered]@{
        environment = $EnvName
        resourceGroup = $rg
        titiler = $titiler
        checkedAtUtc = (Get-Date).ToUniversalTime().ToString('o')
        checkedBy = (az account show --query user.name -o tsv 2>$null)
        results = $results
    } | ConvertTo-Json -Depth 5 | Set-Content -Path $ReportPath -Encoding utf8
    Write-Host "Report written to $ReportPath"
}

exit ($failed ? 1 : 0)
