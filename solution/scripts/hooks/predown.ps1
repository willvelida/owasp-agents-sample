#Requires -Version 7.0
# azd predown hook: remove the Blueprint's federated credential for this environment's managed identity before the
# identity is deleted, so the shared Blueprint never keeps trusting a deleted identity. Entra objects are kept on
# purpose: the next `azd up` reuses them and adds a credential for the new identity.
$ErrorActionPreference = 'Stop'
$scripts = Split-Path -Parent $PSScriptRoot

# azd prints "key not found" on stdout with exit code 1, so the exit code decides.
$principalId = azd env get-value MANAGED_IDENTITY_PRINCIPAL_ID 2>$null
if ($LASTEXITCODE -ne 0 -or -not $principalId) {
    Write-Host '==> MANAGED_IDENTITY_PRINCIPAL_ID is not set; no federated credential to remove'
    exit 0
}
$tenant = azd env get-value TENANT_ID 2>$null
if ($LASTEXITCODE -ne 0 -or -not $tenant) { $tenant = $env:AZURE_TENANT_ID }
if (-not $tenant) { $tenant = (az account show --query tenantId -o tsv) }

# A failure stops `azd down`, which keeps the identity and its credential consistent. Fix the cause and run it again.
& (Join-Path $scripts 'provision_agent_id.ps1') -TenantId $tenant -ManagedIdentityPrincipalId $principalId -RemoveFederatedCredential -UseDeviceCode
if (-not $?) { exit 1 }
