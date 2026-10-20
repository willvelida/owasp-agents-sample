#Requires -Version 7.0
# ASI05: build the isolated chart runner image in ACR (linux/amd64, remote build) and point the Dynamic Sessions pool
# at it. The tag is a content hash of the runner sources, so an unchanged runner is neither rebuilt nor re-pointed,
# and a changed one always gets a new tag (session pools cache images by tag).
#
# -BuildOnly (preprovision): build and record CHART_RUNNER_IMAGE before Bicep runs, when the registry already exists,
# so the pool is created or updated with the real image. On a fresh environment the pool starts with a placeholder
# and no warm sessions, and postprovision (without -BuildOnly) builds the image and patches the pool.
param([switch]$BuildOnly)
$ErrorActionPreference = 'Stop'
$scripts = Split-Path -Parent $PSScriptRoot
$solution = Split-Path -Parent $scripts

function Get-AzdValue([string]$Name) {
    $value = azd env get-value $Name 2>$null
    if ($LASTEXITCODE -ne 0) { return $null }
    return $value
}

$registry = Get-AzdValue AZURE_CONTAINER_REGISTRY_NAME
$loginServer = Get-AzdValue AZURE_CONTAINER_REGISTRY_ENDPOINT
if (-not $registry -and $loginServer) { $registry = $loginServer.Split('.')[0] }
if ($BuildOnly -and -not ($registry -and $loginServer)) {
    Write-Host '==> No container registry yet; postprovision builds the chart runner image'
    exit 0
}
$group = Get-AzdValue AZURE_RESOURCE_GROUP
$pool = Get-AzdValue CHART_SESSION_POOL_NAME
$subscription = Get-AzdValue AZURE_SUBSCRIPTION_ID
if (-not ($registry -and $loginServer -and $subscription)) {
    throw 'Registry or subscription outputs are missing; did provisioning succeed?'
}

$inputs = @('chart_runner.Containerfile', 'pyproject.toml', 'uv.lock') + (
    Get-ChildItem (Join-Path $solution 'src/chart_runner') -Filter *.py | Sort-Object Name | ForEach-Object { "src/chart_runner/$($_.Name)" }
)
$hasher = [System.Security.Cryptography.SHA256]::Create()
$bytes = foreach ($relative in $inputs) {
    $text = [IO.File]::ReadAllText((Join-Path $solution $relative)).Replace("`r`n", "`n")
    [Text.Encoding]::UTF8.GetBytes("$relative`n$text")
}
$tag = -join ($hasher.ComputeHash([byte[]]$bytes) | Select-Object -First 6 | ForEach-Object { $_.ToString('x2') })
$image = "$loginServer/chart-runner:$tag"

$existing = az acr repository show-tags --name $registry --repository chart-runner --query "[?@=='$tag']" -o tsv 2>$null
if ($existing -ne $tag) {
    Write-Host "==> Building $image in ACR (linux/amd64)"
    az acr build --registry $registry --image "chart-runner:$tag" --file (Join-Path $solution 'chart_runner.Containerfile') `
        --platform linux/amd64 $solution --no-logs --output none
    if ($LASTEXITCODE -ne 0) { throw 'az acr build failed' }
} else {
    Write-Host "==> $image already in ACR"
}

if ($BuildOnly) {
    azd env set CHART_RUNNER_IMAGE $image | Out-Null
    Write-Host "==> CHART_RUNNER_IMAGE=$image (Bicep sets it on the pool)"
    exit 0
}
if (-not ($group -and $pool)) { throw 'Resource group or chart session pool outputs are missing' }

$uri = "https://management.azure.com/subscriptions/$subscription/resourceGroups/$group/providers/Microsoft.App/sessionPools/$pool`?api-version=2025-07-01"
$current = az rest --method GET --uri $uri | ConvertFrom-Json
$template = $current.properties.customContainerTemplate
$scale = $current.properties.scaleConfiguration
if ($template.containers[0].image -ne $image -or $scale.readySessionInstances -lt 1) {
    Write-Host "==> Pointing session pool $pool at $image"
    $template.containers[0].image = $image
    $scale.readySessionInstances = 1
    $body = @{ properties = @{ customContainerTemplate = $template; scaleConfiguration = $scale } } | ConvertTo-Json -Depth 20 -Compress
    $file = New-TemporaryFile
    try {
        Set-Content -Path $file -Value $body -NoNewline
        az rest --method PATCH --uri $uri --body "@$file" --headers 'Content-Type=application/json' | Out-Null
        if ($LASTEXITCODE -ne 0) { throw 'session pool update failed' }
    } finally {
        Remove-Item $file -Force
    }
}
# Re-provisioning passes this back to Bicep, so the pool keeps the runner image instead of the placeholder.
azd env set CHART_RUNNER_IMAGE $image | Out-Null
Write-Host "==> CHART_RUNNER_IMAGE=$image"
