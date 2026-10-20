// Report agent: internal ingress only. A2A calls need an app-only token for the report API from the chat agent
// identity (ASI07 baseline). Generated chart code runs only in the Dynamic Sessions pool (ASI05).
param location string
param tags object
param environmentId string
param environmentDomain string
param reportIdentityId string
param reportIdentityClientId string
param registryServer string
param exists bool
param tenantId string
param chatAgentAppId string
param reportApiAppId string
param foundryProjectEndpoint string
param modelName string
param sessionsEndpoint string
param appInsightsConnectionString string
@secure()
@description('ASI05 red-team canary: a stand-in secret held only by this app, as a Container Apps secret.')
param canary string

var name = 'report-agent'
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
    userAssignedIdentities: { '${reportIdentityId}': {} }
  }
  properties: {
    managedEnvironmentId: environmentId
    configuration: {
      // Not reachable from outside the Container Apps environment.
      ingress: {
        external: false
        targetPort: 8002
        transport: 'auto'
        allowInsecure: false
      }
      registries: [{ server: registryServer, identity: reportIdentityId }]
      secrets: [{ name: 'report-agent-canary', value: canary }]
    }
    template: {
      containers: [
        {
          name: 'app'
          image: exists ? fetchImage.outputs.image : 'mcr.microsoft.com/k8se/quickstart:latest'
          command: ['python', '-m', 'report_agent']
          resources: { cpu: json('0.5'), memory: '1Gi' }
          env: [
            { name: 'IDENTITY_MODE', value: 'entra' }
            { name: 'TENANT_ID', value: tenantId }
            { name: 'CHAT_AGENT_APP_ID', value: chatAgentAppId }
            { name: 'REPORT_API_APP_ID', value: reportApiAppId }
            { name: 'REPORT_AGENT_URL', value: 'https://${fqdn}/' }
            { name: 'FOUNDRY_PROJECT_ENDPOINT', value: foundryProjectEndpoint }
            { name: 'FOUNDRY_MODEL', value: modelName }
            { name: 'CHART_SESSIONS_ENDPOINT', value: sessionsEndpoint }
            // ASI03: the report agent's own managed identity (Foundry and the chart pool only).
            { name: 'AZURE_CLIENT_ID', value: reportIdentityClientId }
            { name: 'APPLICATIONINSIGHTS_CONNECTION_STRING', value: appInsightsConnectionString }
            { name: 'REPORT_AGENT_CANARY', secretRef: 'report-agent-canary' }
          ]
        }
      ]
      scale: { minReplicas: 1, maxReplicas: 1 }
    }
  }
}

output url string = 'https://${fqdn}'
