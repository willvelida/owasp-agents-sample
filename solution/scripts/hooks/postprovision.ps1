#Requires -Version 7.0
# azd postprovision hook: let the Blueprint trust the managed identity (federated credential), and point the
# local .env at the solution Foundry project.
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
