#Requires -Version 7.0
<#
.SYNOPSIS
    Provisions the Entra Agent ID objects for the Biotrackr solution. Idempotent.

.DESCRIPTION
    Creates (or reuses) the Agent Identity Blueprint and BlueprintPrincipal, the chat and report agent
    identities, the health MCP and report API app registrations, the demo CLI public client, the
    delegated and app-role grants, a Blueprint dev secret for the local sidecar, the test users alice
    and bob, and optionally a federated credential for the Azure managed identity.

    Non-secret typed IDs go to stdout (and to the azd environment with -AzdEnvSet). Secrets and test
    user passwords go only to solution/.secrets/ (gitignored, owner-only ACL).

    Agent ID APIs reject Azure CLI tokens, so this uses Connect-MgGraph with explicit delegated scopes
    (Microsoft Graph Command Line Tools, tenant-wide admin consent granted in S0).

.EXAMPLE
    ./scripts/provision_agent_id.ps1 -TenantId <tenant> -WriteDotEnv

.EXAMPLE
    # azd postprovision hook: federated credential only.
    ./scripts/provision_agent_id.ps1 -ManagedIdentityPrincipalId <oid> -FederatedCredentialOnly
#>
[CmdletBinding()]
param(
    [string]$TenantId = $env:AZURE_TENANT_ID,
    [string]$Prefix = 'biotrackr',
    [string]$UserDomain,
    [string]$ManagedIdentityPrincipalId,
    [switch]$FederatedCredentialOnly,
    [switch]$RemoveFederatedCredential,
    [switch]$RotateSecret,
    [switch]$AzdEnvSet,
    [switch]$WriteDotEnv,
    [switch]$UseDeviceCode
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

$RequiredScopes = @(
    'AgentIdentityBlueprint.Create',
    'AgentIdentityBlueprint.ReadWrite.All',
    'AgentIdentityBlueprintPrincipal.Create',
    'AgentIdentity.Create.All',
    'Application.ReadWrite.All',
    'DelegatedPermissionGrant.ReadWrite.All',
    'AppRoleAssignment.ReadWrite.All',
    'User.ReadWrite.All'
)
$Graph = 'https://graph.microsoft.com/v1.0'
$SolutionRoot = Split-Path -Parent $PSScriptRoot
$SecretsDir = Join-Path $SolutionRoot '.secrets'
$Names = @{
    Blueprint   = "$Prefix-blueprint"
    # A production biotrackr-chat-agent exists under another Blueprint in the demo tenant; keep names distinct.
    ChatAgent   = "$Prefix-owasp-chat-agent"
    ReportAgent = "$Prefix-report-agent"
    HealthMcp   = "$Prefix-health-mcp"
    ReportApi   = "$Prefix-report-api"
    Cli         = "$Prefix-demo-cli"
}

function Write-Step([string]$Message) { Write-Host "==> $Message" -ForegroundColor Cyan }

function Invoke-Graph {
    param(
        [Parameter(Mandatory)][string]$Method,
        [Parameter(Mandatory)][string]$Uri,
        [object]$Body,
        [int]$MaxAttempts = 6
    )
    $url = if ($Uri.StartsWith('http')) { $Uri } else { "$Graph$Uri" }
    for ($attempt = 1; ; $attempt++) {
        try {
            $params = @{ Method = $Method; Uri = $url; Headers = @{ 'OData-Version' = '4.0'; ConsistencyLevel = 'eventual' }; OutputType = 'PSObject' }
            if ($null -ne $Body) { $params.Body = ($Body | ConvertTo-Json -Depth 10); $params.ContentType = 'application/json' }
            return Invoke-MgGraphRequest @params
        }
        catch {
            $status = $null
            try { $status = [int]$_.Exception.Response.StatusCode } catch { $status = $null }
            $message = if ($_.ErrorDetails -and $_.ErrorDetails.Message) { $_.ErrorDetails.Message } else { $_.Exception.Message }
            # Agent ID objects replicate slowly: Blueprint -> Principal -> Identity in quick succession can 400/404/403.
            $transient = $status -in 400, 403, 404, 409, 429, 500, 502, 503 -and
                ($status -ne 400 -or $message -match 'does not exist|not found|cannot be found|Principal')
            if (-not $transient -or $attempt -ge $MaxAttempts) { throw "Graph $Method $Uri failed ($status): $message" }
            $delay = [Math]::Min(60, [Math]::Pow(2, $attempt) * 2)
            Write-Verbose "Graph $Method $Uri returned $status; retrying in $delay s"
            Start-Sleep -Seconds $delay
        }
    }
}

function Get-Single([string]$Uri) {
    $result = Invoke-Graph -Method GET -Uri $Uri
    $items = @($result.value)
    if ($items.Count -gt 1) { throw "Expected at most one result for $Uri, found $($items.Count)" }
    if ($items.Count -eq 1) { return $items[0] }
    return $null
}

function Get-OrCreateServicePrincipal([string]$AppId) {
    $sp = Get-Single "/servicePrincipals?`$filter=appId eq '$AppId'"
    if ($sp) { return $sp }
    return Invoke-Graph -Method POST -Uri '/servicePrincipals' -Body @{ appId = $AppId }
}

function Get-OrCreateApplication([string]$DisplayName, [hashtable]$Body) {
    $app = Get-Single "/applications?`$filter=displayName eq '$DisplayName'"
    if (-not $app) {
        Write-Step "Creating application $DisplayName"
        $app = Invoke-Graph -Method POST -Uri '/applications' -Body (@{ displayName = $DisplayName } + $Body)
    }
    return $app
}

function Get-ScopeId($App, [string]$Value) {
    $existing = @($App.api.oauth2PermissionScopes | Where-Object { $_.value -eq $Value })
    if ($existing.Count -gt 0) { return $existing[0].id }
    return [guid]::NewGuid().ToString()
}

function Protect-SecretsDir {
    if (-not (Test-Path $SecretsDir)) { New-Item -ItemType Directory -Path $SecretsDir | Out-Null }
    if ($IsWindows) {
        icacls $SecretsDir /inheritance:r /grant:r "$($env:USERNAME):(OI)(CI)F" | Out-Null
    }
    else {
        chmod 700 $SecretsDir
    }
}

function Set-AzdValue([string]$Name, [string]$Value) {
    azd env set $Name $Value | Out-Null
    if ($LASTEXITCODE -ne 0) { throw "azd env set $Name failed" }
}

# --- Sign in and preflight -------------------------------------------------------------------

# Microsoft Graph Command Line Tools: the client the S0 tenant-wide consent was granted to.
$GraphCliClientId = '14d82eec-204b-4c2f-b7e8-296a70dab67e'
$TokenCache = Join-Path $SecretsDir 'graph-token.json'

function Get-DeviceCodeToken([string]$Tenant) {
    # Plain OAuth device code flow. Graph PowerShell's DeviceCodeCredential can fail with a null reference
    # after sign-in, so the token is acquired here and handed to Connect-MgGraph -AccessToken.
    $authority = "https://login.microsoftonline.com/$Tenant/oauth2/v2.0"
    $scope = (($RequiredScopes | ForEach-Object { "https://graph.microsoft.com/$_" }) + 'offline_access') -join ' '
    if (Test-Path $TokenCache) {
        $cached = Get-Content $TokenCache -Raw | ConvertFrom-Json
        try {
            $refreshed = Invoke-RestMethod -Method POST -Uri "$authority/token" -Body @{
                client_id = $GraphCliClientId; grant_type = 'refresh_token'; refresh_token = $cached.refresh_token; scope = $scope
            }
            Save-Token $refreshed
            return $refreshed.access_token
        }
        catch { Write-Verbose 'Cached refresh token rejected; starting device code sign-in' }
    }
    $code = Invoke-RestMethod -Method POST -Uri "$authority/devicecode" -Body @{ client_id = $GraphCliClientId; scope = $scope }
    Write-Host $code.message -ForegroundColor Yellow
    $deadline = (Get-Date).AddSeconds([int]$code.expires_in)
    while ((Get-Date) -lt $deadline) {
        Start-Sleep -Seconds ([int]$code.interval)
        try {
            $token = Invoke-RestMethod -Method POST -Uri "$authority/token" -Body @{
                client_id = $GraphCliClientId; grant_type = 'urn:ietf:params:oauth:grant-type:device_code'; device_code = $code.device_code
            }
            Save-Token $token
            return $token.access_token
        }
        catch {
            $err = $null
            try { $err = ($_.ErrorDetails.Message | ConvertFrom-Json).error } catch { $err = $null }
            if ($err -notin 'authorization_pending', 'slow_down') { throw }
        }
    }
    throw 'Device code sign-in timed out.'
}

function Save-Token($Token) {
    Protect-SecretsDir
    @{ refresh_token = $Token.refresh_token } | ConvertTo-Json | Set-Content -Path $TokenCache
}

function Get-TokenScopes([string]$AccessToken) {
    $payload = $AccessToken.Split('.')[1].Replace('-', '+').Replace('_', '/')
    $payload += '=' * ((4 - $payload.Length % 4) % 4)
    $claims = [Text.Encoding]::UTF8.GetString([Convert]::FromBase64String($payload)) | ConvertFrom-Json
    return @($claims.scp -split ' ')
}

if ($UseDeviceCode) {
    if (-not $TenantId) { throw '-TenantId is required with -UseDeviceCode.' }
    $accessToken = Get-DeviceCodeToken $TenantId
    Connect-MgGraph -AccessToken (ConvertTo-SecureString $accessToken -AsPlainText -Force) -NoWelcome
    $grantedScopes = Get-TokenScopes $accessToken
}
else {
    $connect = @{ Scopes = $RequiredScopes; NoWelcome = $true }
    if ($TenantId) { $connect.TenantId = $TenantId }
    Connect-MgGraph @connect
    $grantedScopes = @((Get-MgContext).Scopes)
}
$TenantId = (Get-MgContext).TenantId
$missing = @($RequiredScopes | Where-Object { $_ -notin $grantedScopes })
if ($missing.Count -gt 0) {
    Write-Error ("Missing delegated scopes: {0}. A Global Administrator or Privileged Role Administrator must grant " +
        "tenant-wide admin consent for Microsoft Graph Command Line Tools (see scripts/README.md)." -f ($missing -join ', '))
    exit 1
}
if ('Directory.AccessAsUser.All' -in $grantedScopes) {
    Write-Error 'Token carries Directory.AccessAsUser.All; Agent ID APIs reject it. Remove that consent and retry.'
    exit 1
}

$blueprint = Get-Single "/applications/microsoft.graph.agentIdentityBlueprint?`$filter=displayName eq '$($Names.Blueprint)'"

# --- Federated credential only (azd postprovision, verification teardown) -------------------

if ($FederatedCredentialOnly -or $RemoveFederatedCredential) {
    if (-not $blueprint) { throw "Blueprint $($Names.Blueprint) not found; run the full provisioning first." }
    if (-not $ManagedIdentityPrincipalId) { throw '-ManagedIdentityPrincipalId is required.' }
    $ficName = "aca-$ManagedIdentityPrincipalId"
    $ficBase = "/applications/$($blueprint.id)/microsoft.graph.agentIdentityBlueprint/federatedIdentityCredentials"
    $fic = @((Invoke-Graph -Method GET -Uri $ficBase).value | Where-Object { $_.name -eq $ficName })
    if ($RemoveFederatedCredential) {
        if ($fic.Count -gt 0) {
            Write-Step "Removing federated credential $ficName"
            Invoke-Graph -Method DELETE -Uri "$ficBase/$($fic[0].id)" | Out-Null
        }
        else { Write-Step "Federated credential $ficName not present" }
        return
    }
    if ($fic.Count -eq 0) {
        Write-Step "Adding federated credential $ficName"
        Invoke-Graph -Method POST -Uri $ficBase -Body @{
            name      = $ficName
            issuer    = "https://login.microsoftonline.com/$TenantId/v2.0"
            subject   = $ManagedIdentityPrincipalId
            audiences = @('api://AzureADTokenExchange')
        } | Out-Null
    }
    else { Write-Step "Federated credential $ficName already present" }
    return
}

# --- Full provisioning ---------------------------------------------------------------------

$me = Invoke-Graph -Method GET -Uri '/me?$select=id,userPrincipalName'
$sponsor = @("$Graph/users/$($me.id)")
if (-not $UserDomain) {
    # Guest admins have UPNs like name#EXT#@tenant.onmicrosoft.com; the part after @ is a tenant domain.
    $UserDomain = $me.userPrincipalName.Split('@')[-1]
}

if (-not $blueprint) {
    Write-Step "Creating Agent Identity Blueprint $($Names.Blueprint)"
    $blueprint = Invoke-Graph -Method POST -Uri '/applications/microsoft.graph.agentIdentityBlueprint' -Body @{
        displayName           = $Names.Blueprint
        'sponsors@odata.bind' = $sponsor
    }
}
$blueprintPrincipal = Get-Single "/servicePrincipals?`$filter=appId eq '$($blueprint.appId)'"
if (-not $blueprintPrincipal) {
    Write-Step 'Creating BlueprintPrincipal'
    $blueprintPrincipal = Invoke-Graph -Method POST -Uri '/servicePrincipals/microsoft.graph.agentIdentityBlueprintPrincipal' -Body @{
        appId = $blueprint.appId
    }
}

# Health MCP API: delegated scope Health.Read, v2 tokens (aud = appId).
$healthMcp = Get-OrCreateApplication $Names.HealthMcp @{ signInAudience = 'AzureADMyOrg' }
$healthScopeId = Get-ScopeId $healthMcp 'Health.Read'
Invoke-Graph -Method PATCH -Uri "/applications/$($healthMcp.id)" -Body @{
    identifierUris = @("api://$($healthMcp.appId)")
    api            = @{
        requestedAccessTokenVersion = 2
        oauth2PermissionScopes      = @(@{
                id                      = $healthScopeId
                value                   = 'Health.Read'
                type                    = 'User'
                isEnabled               = $true
                adminConsentDisplayName = 'Read health data'
                adminConsentDescription = "Read the signed-in user's Biotrackr health data."
                userConsentDisplayName  = 'Read your health data'
                userConsentDescription  = 'Read your Biotrackr health data.'
            })
    }
} | Out-Null
$healthMcpSp = Get-OrCreateServicePrincipal $healthMcp.appId

# Report API (used from S3): app role Report.Generate.
$reportApi = Get-OrCreateApplication $Names.ReportApi @{ signInAudience = 'AzureADMyOrg' }
$roleIds = @($reportApi.appRoles | Where-Object { $_.value -eq 'Report.Generate' } | ForEach-Object { $_.id })
$reportRoleId = if ($roleIds.Count -gt 0) { $roleIds[0] } else { [guid]::NewGuid().ToString() }
Invoke-Graph -Method PATCH -Uri "/applications/$($reportApi.id)" -Body @{
    identifierUris = @("api://$($reportApi.appId)")
    api            = @{ requestedAccessTokenVersion = 2 }
    appRoles       = @(@{
            id                 = $reportRoleId
            value              = 'Report.Generate'
            displayName        = 'Generate reports'
            description        = 'Generate Biotrackr health reports.'
            allowedMemberTypes = @('Application')
            isEnabled          = $true
        })
} | Out-Null
$reportApiSp = Get-OrCreateServicePrincipal $reportApi.appId

# Demo CLI: public client for device code sign-in.
$cli = Get-OrCreateApplication $Names.Cli @{ signInAudience = 'AzureADMyOrg'; isFallbackPublicClient = $true }
Invoke-Graph -Method PATCH -Uri "/applications/$($cli.id)" -Body @{
    isFallbackPublicClient = $true
    publicClient           = @{ redirectUris = @('http://localhost') }
} | Out-Null
$cliSp = Get-OrCreateServicePrincipal $cli.appId

# Blueprint as an OAuth2 API for OBO: access_as_user, CLI pre-authorized, idtyp claim.
$blueprint = Invoke-Graph -Method GET -Uri "/applications/$($blueprint.id)"
$accessScopeId = Get-ScopeId $blueprint 'access_as_user'
Write-Verbose "access_as_user scope id: $accessScopeId"
Write-Step 'Configuring Blueprint API (access_as_user, pre-authorized CLI)'
$blueprintApi = @{
    requestedAccessTokenVersion = 2
    oauth2PermissionScopes      = @(@{
            id                      = $accessScopeId
            value                   = 'access_as_user'
            type                    = 'User'
            isEnabled               = $true
            adminConsentDisplayName = 'Access Biotrackr chat'
            adminConsentDescription = 'Allow the app to call the Biotrackr chat agent on behalf of the user.'
            userConsentDisplayName  = 'Access Biotrackr chat'
            userConsentDescription  = 'Call the Biotrackr chat agent on your behalf.'
        })
}
Invoke-Graph -Method PATCH -Uri "/applications/$($blueprint.id)" -Body @{
    identifierUris = @("api://$($blueprint.appId)")
    api            = $blueprintApi
    optionalClaims = @{
        accessToken = @(@{ name = 'idtyp'; source = $null; essential = $false; additionalProperties = @('include_user_token') })
    }
} | Out-Null
# The scope must exist before a pre-authorization can reference it; resend the whole api object.
$blueprintApi.preAuthorizedApplications = @(@{ appId = $cli.appId; delegatedPermissionIds = @($accessScopeId) })
Invoke-Graph -Method PATCH -Uri "/applications/$($blueprint.id)" -Body @{ api = $blueprintApi } | Out-Null

# Agent identities under the Blueprint.
function Get-OrCreateAgentIdentity([string]$DisplayName) {
    # Only ever reuse an identity whose parent is this Blueprint; never touch identities of other Blueprints.
    $children = @((Invoke-Graph -Method GET -Uri "/servicePrincipals/microsoft.graph.agentIdentity?`$filter=agentIdentityBlueprintId eq '$($blueprint.appId)'").value |
        Where-Object { $_.displayName -eq $DisplayName })
    if ($children.Count -gt 1) { throw "More than one agent identity named $DisplayName under $($Names.Blueprint)" }
    if ($children.Count -eq 1) { return $children[0] }
    $sameName = @((Invoke-Graph -Method GET -Uri "/servicePrincipals?`$filter=displayName eq '$DisplayName'").value)
    if ($sameName.Count -gt 0) { Write-Warning "$DisplayName also exists outside $($Names.Blueprint); leaving it untouched." }
    Write-Step "Creating agent identity $DisplayName"
    return Invoke-Graph -Method POST -Uri '/servicePrincipals/microsoft.graph.agentIdentity' -Body @{
        displayName              = $DisplayName
        agentIdentityBlueprintId = $blueprint.appId
        'sponsors@odata.bind'    = $sponsor
    }
}
# Agent identities' client id equals their object id; the typed endpoint omits appId.
function Get-AgentClientId($Agent) { if ($Agent.PSObject.Properties['appId'] -and $Agent.appId) { $Agent.appId } else { $Agent.id } }
$chatAgent = Get-OrCreateAgentIdentity $Names.ChatAgent
$reportAgent = Get-OrCreateAgentIdentity $Names.ReportAgent

# Delegated grant: chat agent may call the MCP API as the user with Health.Read only.
$grant = Get-Single "/oauth2PermissionGrants?`$filter=clientId eq '$($chatAgent.id)' and resourceId eq '$($healthMcpSp.id)'"
$expiry = (Get-Date).ToUniversalTime().AddYears(1).ToString('yyyy-MM-ddTHH:mm:ssZ')
if (-not $grant) {
    Write-Step 'Granting chat agent Health.Read (delegated, all principals)'
    Invoke-Graph -Method POST -Uri '/oauth2PermissionGrants' -Body @{
        clientId    = $chatAgent.id
        consentType = 'AllPrincipals'
        resourceId  = $healthMcpSp.id
        scope       = 'Health.Read'
        expiryTime  = $expiry
    } | Out-Null
}
elseif ($grant.scope.Trim() -ne 'Health.Read') {
    Invoke-Graph -Method PATCH -Uri "/oauth2PermissionGrants/$($grant.id)" -Body @{ scope = 'Health.Read' } | Out-Null
}

# App role: chat agent may call the report API (S3).
$assignments = @((Invoke-Graph -Method GET -Uri "/servicePrincipals/$($chatAgent.id)/appRoleAssignments").value |
    Where-Object { $_.resourceId -eq $reportApiSp.id -and $_.appRoleId -eq $reportRoleId })
if ($assignments.Count -eq 0) {
    Write-Step 'Assigning chat agent Report.Generate'
    Invoke-Graph -Method POST -Uri "/servicePrincipals/$($chatAgent.id)/appRoleAssignments" -Body @{
        principalId = $chatAgent.id
        resourceId  = $reportApiSp.id
        appRoleId   = $reportRoleId
    } | Out-Null
}

# Blueprint dev secret for the local sidecar only (Azure uses a federated credential).
Protect-SecretsDir
$sidecarEnv = Join-Path $SecretsDir 'sidecar.env'
if ($RotateSecret -or -not (Test-Path $sidecarEnv)) {
    Write-Step 'Adding Blueprint dev secret (written to .secrets/sidecar.env)'
    $password = Invoke-Graph -Method POST -Uri "/applications/$($blueprint.id)/addPassword" -Body @{
        passwordCredential = @{ displayName = 'local-sidecar-dev'; endDateTime = (Get-Date).ToUniversalTime().AddDays(90).ToString('o') }
    }
    Set-Content -Path $sidecarEnv -Value "AzureAd__ClientCredentials__0__ClientSecret=$($password.secretText)" -NoNewline
}

if ($ManagedIdentityPrincipalId) {
    & $PSCommandPath -TenantId $TenantId -Prefix $Prefix -ManagedIdentityPrincipalId $ManagedIdentityPrincipalId -FederatedCredentialOnly -UseDeviceCode:$UseDeviceCode
}

# Test users.
$usersFile = Join-Path $SecretsDir 'test-users.txt'
function Get-OrCreateUser([string]$Nickname, [string]$DisplayName) {
    $upn = "$Nickname@$UserDomain"
    $user = Get-Single "/users?`$filter=userPrincipalName eq '$upn'&`$select=id,userPrincipalName"
    if ($user) { return $user }
    Write-Step "Creating test user $upn (password in .secrets/test-users.txt)"
    $password = -join ((48..57) + (65..90) + (97..122) | Get-Random -Count 20 | ForEach-Object { [char]$_ }) + '!a1'
    $user = Invoke-Graph -Method POST -Uri '/users' -Body @{
        accountEnabled    = $true
        displayName       = $DisplayName
        mailNickname      = $Nickname
        userPrincipalName = $upn
        passwordProfile   = @{ password = $password; forceChangePasswordNextSignIn = $false }
    }
    Add-Content -Path $usersFile -Value "$upn`t$password"
    return $user
}
$alice = Get-OrCreateUser "$Prefix-alice" 'Alice Example'
$bob = Get-OrCreateUser "$Prefix-bob" 'Bob Example'

# --- Output (non-secret IDs only) ----------------------------------------------------------

$ids = [ordered]@{
    TENANT_ID                 = $TenantId
    BLUEPRINT_APP_ID          = $blueprint.appId
    BLUEPRINT_OBJECT_ID       = $blueprint.id
    CHAT_AGENT_APP_ID         = (Get-AgentClientId $chatAgent)
    CHAT_AGENT_SP_OBJECT_ID   = $chatAgent.id
    REPORT_AGENT_APP_ID       = (Get-AgentClientId $reportAgent)
    REPORT_AGENT_SP_OBJECT_ID = $reportAgent.id
    HEALTH_MCP_APP_ID         = $healthMcp.appId
    REPORT_API_APP_ID         = $reportApi.appId
    CLI_APP_ID                = $cli.appId
    ALICE_OID                 = $alice.id
    BOB_OID                   = $bob.id
    ALICE_UPN                 = $alice.userPrincipalName
    BOB_UPN                   = $bob.userPrincipalName
}
$null = $cliSp, $blueprintPrincipal

foreach ($key in $ids.Keys) { Write-Output "$key=$($ids[$key])" }

if ($AzdEnvSet) {
    Write-Step 'Writing IDs to the azd environment'
    foreach ($key in $ids.Keys) { Set-AzdValue $key $ids[$key] }
}

if ($WriteDotEnv) {
    $dotEnv = Join-Path $SolutionRoot '.env'
    if (-not (Test-Path $dotEnv)) { Copy-Item (Join-Path $SolutionRoot '.env.example') $dotEnv }
    $lines = [System.Collections.Generic.List[string]](Get-Content $dotEnv)
    foreach ($key in $ids.Keys) {
        $index = $lines.FindIndex({ param($l) $l -match "^$key=" })
        if ($index -ge 0) { $lines[$index] = "$key=$($ids[$key])" } else { $lines.Add("$key=$($ids[$key])") }
    }
    Set-Content -Path $dotEnv -Value $lines
    Write-Step "Updated $dotEnv"
}
