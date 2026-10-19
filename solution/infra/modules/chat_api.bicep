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
param healthMcpUrl string
param foundryProjectEndpoint string
param modelName string
param cosmosEndpoint string
param appInsightsConnectionString string

param sidecarImage string = 'mcr.microsoft.com/entra-sdk/auth-sidecar:1.0.0-azurelinux3.0-distroless'

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
            { name: 'SIDECAR_URL', value: 'http://localhost:5000' }
            { name: 'MCP_URL', value: '${healthMcpUrl}/mcp' }
            { name: 'FOUNDRY_PROJECT_ENDPOINT', value: foundryProjectEndpoint }
            { name: 'FOUNDRY_MODEL', value: modelName }
            { name: 'COSMOS_ENDPOINT', value: cosmosEndpoint }
            { name: 'COSMOS_DATABASE', value: 'biotrackr' }
            // ASI03: managed identity for Foundry and Cosmos DB; no keys anywhere.
            { name: 'AZURE_CLIENT_ID', value: identityClientId }
            { name: 'APPLICATIONINSIGHTS_CONNECTION_STRING', value: appInsightsConnectionString }
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
            { name: 'Logging__LogLevel__Default', value: 'Warning' }
            { name: 'Logging__LogLevel__Microsoft.Identity.Web', value: 'Information' }
          ]
        }
      ]
      scale: { minReplicas: 1, maxReplicas: 2 }
    }
  }
}

output url string = 'https://${app.properties.configuration.ingress.fqdn}'
