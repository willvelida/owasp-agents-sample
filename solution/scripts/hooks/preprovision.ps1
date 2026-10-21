#Requires -Version 7.0
# azd preprovision hook: create or reuse the Agent ID objects and write their typed IDs into the azd environment.
$ErrorActionPreference = 'Stop'
$scripts = Split-Path -Parent $PSScriptRoot
$tenant = $env:AZURE_TENANT_ID
if (-not $tenant) { $tenant = (az account show --query tenantId -o tsv) }
& (Join-Path $scripts 'provision_agent_id.ps1') -TenantId $tenant -AzdEnvSet -WriteDotEnv -UseDeviceCode
if (-not $?) { exit 1 }

# ASI07: the chat agent's A2A signing key pair, generated once per azd environment. The private key reaches Azure only
# as a Container Apps secret on chat-api; the report agent gets the public key. Rotate by clearing both values.
$existing = azd env get-value A2A_SIGNING_KEY 2>$null
$hasSigning = $LASTEXITCODE -eq 0 -and $existing
$verify = azd env get-value A2A_VERIFY_KEY 2>$null
$hasVerify = $LASTEXITCODE -eq 0 -and $verify
# azd prints "key not found" on stdout with exit code 1, so the exit code decides.
if (-not $hasSigning -or -not $hasVerify) {
    $pair = uv run --quiet --project (Split-Path -Parent $scripts) python -m report_agent.a2a_security keygen --format env
    if ($LASTEXITCODE -ne 0) { throw 'A2A key generation failed' }
    foreach ($line in $pair) {
        $name, $value = $line -split '=', 2
        if ($name -in 'A2A_SIGNING_KEY', 'A2A_VERIFY_KEY') {
            azd env set $name $value | Out-Null
            if ($LASTEXITCODE -ne 0) { throw "azd env set $name failed" }
        }
    }
    Write-Host 'A2A signing key pair generated and stored in the azd environment.'
}
Remove-Variable existing, verify, hasSigning, hasVerify, pair -ErrorAction SilentlyContinue

# ASI05: build the chart runner image first when the registry already exists, so Bicep gives the pool the real image.
& (Join-Path $PSScriptRoot 'build_chart_runner.ps1') -BuildOnly
if (-not $?) { exit 1 }
