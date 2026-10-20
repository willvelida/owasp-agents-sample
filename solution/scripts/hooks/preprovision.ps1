#Requires -Version 7.0
# azd preprovision hook: create or reuse the Agent ID objects and write their typed IDs into the azd environment.
$ErrorActionPreference = 'Stop'
$scripts = Split-Path -Parent $PSScriptRoot
$tenant = $env:AZURE_TENANT_ID
if (-not $tenant) { $tenant = (az account show --query tenantId -o tsv) }
& (Join-Path $scripts 'provision_agent_id.ps1') -TenantId $tenant -AzdEnvSet -WriteDotEnv -UseDeviceCode
if (-not $?) { exit 1 }

# ASI05: build the chart runner image first when the registry already exists, so Bicep gives the pool the real image.
& (Join-Path $PSScriptRoot 'build_chart_runner.ps1') -BuildOnly
if (-not $?) { exit 1 }
