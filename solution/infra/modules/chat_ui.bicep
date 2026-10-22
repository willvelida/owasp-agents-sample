// Browser chat UI: static Vue client on non-root nginx (8080), external ingress, strict headers set by the image.
// Its only identity can pull from ACR; it holds no secrets and no data-plane roles.
param location string
param tags object
param environmentId string
@description('User-assigned identity with AcrPull only.')
param identityId string
param registryServer string
param exists bool
param tenantId string
param spaAppId string
param blueprintAppId string
@description('chat-api origin (https://host, no path); rendered into /config.json and the CSP connect-src.')
param chatApiUrl string

var name = 'chat-ui'

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
      ingress: {
        external: true
        targetPort: 8080
        transport: 'auto'
        allowInsecure: false
      }
      registries: [{ server: registryServer, identity: identityId }]
    }
    template: {
      containers: [
        {
          name: 'app'
          // The quickstart image listens on 80, so chat-ui answers only after the first azd deploy of its own image.
          image: exists ? fetchImage.outputs.image : 'mcr.microsoft.com/k8se/quickstart:latest'
          resources: { cpu: json('0.25'), memory: '0.5Gi' }
          env: [
            { name: 'TENANT_ID', value: tenantId }
            { name: 'SPA_APP_ID', value: spaAppId }
            { name: 'BLUEPRINT_APP_ID', value: blueprintAppId }
            { name: 'CHAT_API_URL', value: chatApiUrl }
          ]
        }
      ]
      scale: { minReplicas: 1, maxReplicas: 1 }
    }
  }
}

output url string = 'https://${app.properties.configuration.ingress.fqdn}'
