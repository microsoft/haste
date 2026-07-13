#!/usr/bin/env pwsh
# Invite the first admin to the Static Web App as administrator+contributor so
# they can sign in immediately after `azd up`. The invitee is
# HASTE_FIRST_ADMIN_EMAIL when set (non-interactive / CI deploys), else the
# signed-in deployer. Idempotent: skips if the user is already a SWA user. Prints
# the invitation URL (SWA invitations can't be emailed automatically without the
# wider invitation flow).
#
# Inputs (azd environment): STATIC_WEB_APP_NAME, AZURE_RESOURCE_GROUP,
# AZURE_SUBSCRIPTION_ID, HASTE_FIRST_ADMIN_EMAIL (optional).

param(
    [string]$StaticWebApp = $env:STATIC_WEB_APP_NAME,
    [string]$ResourceGroup = $env:AZURE_RESOURCE_GROUP,
    [string]$SubscriptionId = $env:AZURE_SUBSCRIPTION_ID,
    [string]$FirstAdminEmail = $env:HASTE_FIRST_ADMIN_EMAIL,
    [int]$HoursToExpiration = 168
)

$ErrorActionPreference = 'Stop'

if ([string]::IsNullOrWhiteSpace($StaticWebApp)) {
    Write-Warning "invite-user: STATIC_WEB_APP_NAME unset; run 'azd provision' first. Skipping."
    return
}

$email = $FirstAdminEmail
if ([string]::IsNullOrWhiteSpace($email)) {
    $email = az ad signed-in-user show --query mail -o tsv 2>$null
}
if ([string]::IsNullOrWhiteSpace($email)) {
    Write-Warning "invite-user: no HASTE_FIRST_ADMIN_EMAIL and could not resolve the signed-in user's email (service principal / no mail attribute?). Skipping invite. Set HASTE_FIRST_ADMIN_EMAIL for non-interactive deploys."
    return
}

$base = "https://management.azure.com/subscriptions/$SubscriptionId/resourceGroups/$ResourceGroup/providers/Microsoft.Web/staticSites/$StaticWebApp"
$host_ = az staticwebapp show --name $StaticWebApp --resource-group $ResourceGroup --query defaultHostname -o tsv 2>$null

# Dedup: skip if the user already exists on the SWA.
$usersJson = az rest --method post --uri "$base/authproviders/all/listUsers?api-version=2024-04-01" -o json 2>$null
if ($LASTEXITCODE -eq 0 -and $usersJson) {
    $existing = ($usersJson | ConvertFrom-Json).value |
        Where-Object { $_.properties.userDetails -eq $email }
    if ($existing) {
        Write-Host "invite-user: '$email' is already a user of $StaticWebApp — skip."
        return
    }
}

$body = @{
    properties = @{
        domain               = $host_
        provider             = 'aad'
        userDetails          = $email
        roles                = 'administrators,contributors'
        numHoursToExpiration = $HoursToExpiration
    }
} | ConvertTo-Json -Depth 5
$tmp = New-TemporaryFile
# UTF-8 without BOM — az rest rejects a BOM in the request body.
[System.IO.File]::WriteAllText($tmp.FullName, $body)

$resp = az rest --method post --uri "$base/createUserInvitation?api-version=2024-04-01" --body "@$($tmp.FullName)" -o json 2>$null
Remove-Item $tmp -ErrorAction SilentlyContinue

if ($LASTEXITCODE -eq 0 -and $resp) {
    $url = ($resp | ConvertFrom-Json).properties.invitationUrl
    Write-Host "invite-user: invitation created for '$email' (admin+contributor, ${HoursToExpiration}h)."
    Write-Host "  Sign in at https://$host_/ using this one-time invitation URL:"
    Write-Host "  $url"
} else {
    Write-Warning "invite-user: createUserInvitation failed for '$email'."
}
