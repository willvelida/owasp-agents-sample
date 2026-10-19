#Requires -Version 7.0
<#
.SYNOPSIS
    Seeds Azure Cosmos DB with data/seed, keyed by the alice and bob object ids. Called by the azd postprovision hook.

.DESCRIPTION
    Uses the developer's Entra identity (az login; the Cosmos DB Built-in Data Contributor role is assigned by
    Bicep). The account has local auth disabled, so no key is involved. Local Compose seeds the emulator with
    the `seed` service instead.
#>
$ErrorActionPreference = 'Stop'
$solution = Split-Path -Parent $PSScriptRoot

$values = @{}
foreach ($line in (azd env get-values --cwd $solution)) {
    if ($line -match '^([A-Z0-9_]+)="?(.*?)"?$') { $values[$Matches[1]] = $Matches[2] }
}
foreach ($name in 'COSMOS_ENDPOINT', 'ALICE_OID', 'BOB_OID') {
    if (-not $values[$name]) { throw "$name is missing from the azd environment" }
}

$env:COSMOS_ENDPOINT = $values.COSMOS_ENDPOINT
$env:COSMOS_DATABASE = 'biotrackr'
$env:ALICE_OID = $values.ALICE_OID
$env:BOB_OID = $values.BOB_OID
$env:SEED_DIR = (Resolve-Path (Join-Path $solution '..' 'data' 'seed')).Path
Remove-Item Env:COSMOS_KEY -ErrorAction SilentlyContinue

Push-Location $solution
try {
    uv run --no-dev python -m seed
    if ($LASTEXITCODE -ne 0) { throw 'seeding failed' }
}
finally { Pop-Location }
