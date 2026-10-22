#Requires -Version 7.0
# azd postprovision hook: let the Blueprint trust the managed identity (federated credential), point the local .env at
# the solution Foundry project, seed data, build the chart runner, create the kill switch, and set the SPA redirect URIs.
$ErrorActionPreference = 'Stop'
$scripts = Split-Path -Parent $PSScriptRoot
$solution = Split-Path -Parent $scripts

$principalId = azd env get-value MANAGED_IDENTITY_PRINCIPAL_ID
$tenant = azd env get-value TENANT_ID
if (-not $principalId) { throw 'MANAGED_IDENTITY_PRINCIPAL_ID is not set; did provisioning succeed?' }
& (Join-Path $scripts 'provision_agent_id.ps1') -TenantId $tenant -ManagedIdentityPrincipalId $principalId -FederatedCredentialOnly -UseDeviceCode
if (-not $?) { exit 1 }

$dotEnv = Join-Path $solution '.env'
if (Test-Path $dotEnv) {
    $endpoint = azd env get-value FOUNDRY_PROJECT_ENDPOINT
    $lines = Get-Content $dotEnv | ForEach-Object { $_ -replace '^FOUNDRY_PROJECT_ENDPOINT=.*', "FOUNDRY_PROJECT_ENDPOINT=$endpoint" }
    Set-Content -Path $dotEnv -Value $lines
    Write-Host "==> FOUNDRY_PROJECT_ENDPOINT set in $dotEnv"
}

# Seed Azure Cosmos DB here rather than in postdeploy: seeding needs only the provisioned account, and azd 1.34's
# overlapped `azd up` flow does not run the project-level postdeploy hook.
& (Join-Path $scripts 'seed.ps1')
if (-not $?) { exit 1 }

# ASI05: the chart runner is not an azd service (it runs in a session pool, not a container app), so its image is
# built in ACR and set on the pool here.
& (Join-Path $PSScriptRoot 'build_chart_runner.ps1')
if (-not $?) { exit 1 }

# ASI10: create the kill switch (off) if it is missing; never reset an engaged one.
& (Join-Path $PSScriptRoot 'kill_switch.ps1')
if (-not $?) { exit 1 }

# Browser client: add the deployed chat-ui URL to the SPA redirect URIs (the hostname exists only after Bicep). Last on
# purpose, so a failure here never skips the steps above. Warns and continues when SPA_APP_ID or CHAT_UI_URL is unset.
& (Join-Path $scripts 'provision_agent_id.ps1') -TenantId $tenant -SpaRedirectUri -UseDeviceCode
if (-not $?) { exit 1 }
