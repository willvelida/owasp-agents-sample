// Chat API: external ingress, plus the Entra SDK for AgentID sidecar as a second container on localhost.
param location string
param tags object
param environmentId string
param identityId string
param identityClientId string
param registryServer string
param exists bool
param tenantId string
param blueprintAppId string
param chatAgentAppId string
param healthMcpAppId string
param cliAppId string
@description('Browser client app id; its tokens are accepted next to the CLI\'s.')
param spaAppId string
@description('Exact browser origins (comma-separated) allowed by chat-api\'s CORS middleware.')
param corsAllowedOrigins string
param healthMcpUrl string
param reportApiAppId string
param reportAgentUrl string
param foundryProjectEndpoint string
param modelName string
param cosmosEndpoint string
param appInsightsConnectionString string
param appConfigEndpoint string
@secure()
@description('ASI07: Ed25519 A2A signing key (base64 raw), held only by this app as a Container Apps secret.')
param a2aSigningKey string

// WI-10: pinned by digest (1.1.2-azurelinux3.0-distroless, multi-arch index; amd64 only today). Dependabot's docker
// ecosystem does not see Bicep, so bump this by hand: `podman manifest inspect` the new tag and copy its digest.
param sidecarImage string = 'mcr.microsoft.com/entra-sdk/auth-sidecar@sha256:73a8763100c93c3da1a3ed1ba3af2c6122c0517687354dceded30537a1aee97f'

var name = 'chat-api'

module fetchImage 'fetch_image.bicep' = {
  name: '${name}-image'
  params: { name: name, exists: exists }
}

resource app 'Microsoft.App/containerApps@2024-03-01' = {
  name: name
  location: location
  tags: union(tags, { 'azd-service-name': name })
  identity: {
    type: 'UserAssigned'
    userAssignedIdentities: { '${identityId}': {} }
  }
  properties: {
    managedEnvironmentId: environmentId
    configuration: {
      // Only port 8000 (the app) is exposed; the sidecar listens on 127.0.0.1 inside the replica.
      ingress: {
        external: true
        targetPort: 8000
        transport: 'auto'
        allowInsecure: false
      }
      registries: [{ server: registryServer, identity: identityId }]
      secrets: [{ name: 'a2a-signing-key', value: a2aSigningKey }]
    }
    template: {
      // azd deploy replaces the first container's image, so the app container must stay first.
      containers: [
        {
          name: 'app'
          image: exists ? fetchImage.outputs.image : 'mcr.microsoft.com/k8se/quickstart:latest'
          command: ['python', '-m', 'chat_api']
          resources: { cpu: json('1.0'), memory: '2Gi' }
          env: [
            { name: 'IDENTITY_MODE', value: 'entra' }
            { name: 'TENANT_ID', value: tenantId }
            { name: 'BLUEPRINT_APP_ID', value: blueprintAppId }
            { name: 'CHAT_AGENT_APP_ID', value: chatAgentAppId }
            { name: 'HEALTH_MCP_APP_ID', value: healthMcpAppId }
            { name: 'CLI_APP_ID', value: cliAppId }
            // ASI03: only these two clients' tokens (azp) are accepted; CORS lets only the chat-ui origin read
            // responses and never bypasses the bearer check.
            { name: 'ALLOWED_CLIENT_APP_IDS', value: '${cliAppId},${spaAppId}' }
            { name: 'CORS_ALLOWED_ORIGINS', value: corsAllowedOrigins }
            { name: 'SIDECAR_URL', value: 'http://localhost:5000' }
            { name: 'MCP_URL', value: '${healthMcpUrl}/mcp' }
            { name: 'REPORT_AGENT_URL', value: '${reportAgentUrl}/' }
            { name: 'FOUNDRY_PROJECT_ENDPOINT', value: foundryProjectEndpoint }
            { name: 'FOUNDRY_MODEL', value: modelName }
            { name: 'COSMOS_ENDPOINT', value: cosmosEndpoint }
            { name: 'COSMOS_DATABASE', value: 'biotrackr' }
            // ASI03: managed identity for Foundry and Cosmos DB; no keys anywhere.
            { name: 'AZURE_CLIENT_ID', value: identityClientId }
            { name: 'APPLICATIONINSIGHTS_CONNECTION_STRING', value: appInsightsConnectionString }
            // ASI10: kill switch in App Configuration, read with the managed identity on every run (10 s cache).
            { name: 'APP_CONFIG_ENDPOINT', value: appConfigEndpoint }
            // ASI07: signs every A2A request to the report agent; without it no report request is sent.
            { name: 'A2A_SIGNING_KEY', secretRef: 'a2a-signing-key' }
          ]
        }
        {
          // ASI03: OBO as the chat agent identity. The Blueprint trusts this managed identity through a
          // federated credential (added by the postprovision hook), so there is no secret in Azure.
          name: 'entra-sidecar'
          image: sidecarImage
          resources: { cpu: json('0.25'), memory: '0.5Gi' }
          env: [
            // Bound to loopback inside the replica; that binding is the network control. (The 1.0.0 image's
            // host filter rejects 127.0.0.1 even when listed in AllowedHosts, so it is left at its default.)
            { name: 'ASPNETCORE_URLS', value: 'http://127.0.0.1:5000' }
            { name: 'AzureAd__Instance', value: environment().authentication.loginEndpoint }
            { name: 'AzureAd__TenantId', value: tenantId }
            { name: 'AzureAd__ClientId', value: blueprintAppId }
            { name: 'AzureAd__Audience', value: blueprintAppId }
            { name: 'AzureAd__Scopes', value: 'access_as_user' }
            { name: 'AzureAd__ClientCredentials__0__SourceType', value: 'SignedAssertionFromManagedIdentity' }
            { name: 'AzureAd__ClientCredentials__0__ManagedIdentityClientId', value: identityClientId }
            { name: 'DownstreamApis__HealthMcp__BaseUrl', value: '${healthMcpUrl}/' }
            { name: 'DownstreamApis__HealthMcp__Scopes__0', value: 'api://${healthMcpAppId}/.default' }
            { name: 'DownstreamApis__HealthMcp__RequestAppToken', value: 'false' }
            // ASI07 baseline: app-only token for the report agent as the chat agent identity (autonomous route).
            { name: 'DownstreamApis__ReportApi__BaseUrl', value: '${reportAgentUrl}/' }
            { name: 'DownstreamApis__ReportApi__Scopes__0', value: 'api://${reportApiAppId}/.default' }
            { name: 'DownstreamApis__ReportApi__RequestAppToken', value: 'true' }
            // Newer sidecar builds ignore AgentIdentity on the unauthenticated route unless this is set; only the
            // chat-api container shares this loopback. WI-22: still needed in 1.1.2 (upstream defaults it to false).
            { name: 'Sidecar__AllowOverrides__GetAuthorizationHeaderUnauthenticated', value: 'true' }
            { name: 'Logging__LogLevel__Default', value: 'Warning' }
            { name: 'Logging__LogLevel__Microsoft.Identity.Web', value: 'Information' }
          ]
        }
      ]
      // One replica: the tool and token budgets, rogue-detection quarantines, and circuit breakers are in-process
      // (DD-35). Scaling out needs them in a shared store first (WI-13).
      scale: { minReplicas: 1, maxReplicas: 1 }
    }
  }
}

output url string = 'https://${app.properties.configuration.ingress.fqdn}'
