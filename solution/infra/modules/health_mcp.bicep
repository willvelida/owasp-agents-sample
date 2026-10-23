// Health MCP server: internal ingress only, managed identity for Cosmos DB, OBO bearer required on every call.
param location string
param tags object
param environmentId string
param environmentDomain string
param identityId string
param identityClientId string
param registryServer string
param exists bool
param tenantId string
param healthMcpAppId string
param chatAgentAppId string
param cosmosEndpoint string
@description('App Insights connection string for Entra-only telemetry ingestion.')
param appInsightsConnectionString string

var name = 'health-mcp'
var fqdn = '${name}.internal.${environmentDomain}'

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
      // ASI03: not reachable from outside the Container Apps environment.
      ingress: {
        external: false
        targetPort: 8001
        transport: 'auto'
        allowInsecure: false
      }
      registries: [{ server: registryServer, identity: identityId }]
    }
    template: {
      containers: [
        {
          name: 'app'
          image: exists ? fetchImage.outputs.image : 'mcr.microsoft.com/k8se/quickstart:latest'
          command: ['python', '-m', 'health_mcp']
          resources: { cpu: json('0.5'), memory: '1Gi' }
          env: [
            { name: 'IDENTITY_MODE', value: 'entra' }
            { name: 'TENANT_ID', value: tenantId }
            { name: 'HEALTH_MCP_APP_ID', value: healthMcpAppId }
            { name: 'CHAT_AGENT_APP_ID', value: chatAgentAppId }
            { name: 'AZURE_CLIENT_ID', value: identityClientId }
            { name: 'APPLICATIONINSIGHTS_CONNECTION_STRING', value: appInsightsConnectionString }
            { name: 'COSMOS_ENDPOINT', value: cosmosEndpoint }
            { name: 'COSMOS_DATABASE', value: 'biotrackr' }
            { name: 'MCP_ALLOWED_HOSTS', value: '${fqdn},${fqdn}:443' }
            { name: 'MCP_RESOURCE_URL', value: 'https://${fqdn}/mcp' }
          ]
        }
      ]
      scale: { minReplicas: 1, maxReplicas: 1 }
    }
  }
}

output url string = 'https://${fqdn}'
