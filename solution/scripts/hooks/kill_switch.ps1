#Requires -Version 7.0
# ASI10: create the agent kill switch in App Configuration with `off`, only if it does not exist yet. Re-running never
# resets a switch an operator engaged. chat-api treats a missing key as engaged (fail closed), so until this has run
# every chat run is refused.
#
# Flip it:  az appconfig kv set --endpoint <APP_CONFIG_ENDPOINT> --auth-mode login --key agent-kill-switch --value on --yes
$ErrorActionPreference = 'Stop'

$endpoint = azd env get-value APP_CONFIG_ENDPOINT 2>$null
if (-not $endpoint) { throw 'APP_CONFIG_ENDPOINT is not set; did provisioning succeed?' }
$key = 'agent-kill-switch'

# The developer's App Configuration Data Owner assignment comes from the same deployment and can take a few minutes
# to reach the data plane.
for ($attempt = 1; $attempt -le 20; $attempt++) {
    $existing = az appconfig kv list --endpoint $endpoint --auth-mode login --key $key --query '[0].value' -o tsv 2>$null
    if ($LASTEXITCODE -eq 0) {
        if ($existing) {
            Write-Host "==> kill switch already set ($key = $existing); left unchanged"
            exit 0
        }
        az appconfig kv set --endpoint $endpoint --auth-mode login --key $key --value off --content-type 'text/plain' --yes --only-show-errors | Out-Null
        if ($LASTEXITCODE -eq 0) {
            Write-Host "==> kill switch created ($key = off)"
            exit 0
        }
    }
    Write-Host "    waiting for App Configuration data-plane access (attempt $attempt)..."
    Start-Sleep -Seconds 15
}
throw "could not read or create $key in $endpoint"
