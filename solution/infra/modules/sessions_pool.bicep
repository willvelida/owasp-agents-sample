// ASI05: isolated chart runner on Azure. A Dynamic Sessions custom-container pool with egress disabled: each chart
// job gets a fresh Hyper-V isolated session with no network, no secrets, and no managed identity inside it. Only the
// report agent's identity holds Session Executor on the pool.
param location string
param tags object
param environmentId string
param registryServer string
@description('Report agent identity: pulls the runner image and is the only caller allowed to run sessions.')
param reportIdentityId string
param reportIdentityPrincipalId string
@description('Runner image (linux/amd64, built in ACR by the postprovision hook). Empty on a fresh environment.')
param image string = ''

// Azure ContainerApps Session Executor.
var sessionExecutorRole = '0fb8eba5-a2bb-4abe-b1c1-49dfad359bb0'

resource pool 'Microsoft.App/sessionPools@2025-07-01' = {
  name: 'chartrunner'
  location: location
  tags: tags
  identity: {
    type: 'UserAssigned'
    userAssignedIdentities: { '${reportIdentityId}': {} }
  }
  properties: {
    environmentId: environmentId
    poolManagementType: 'Dynamic'
    containerType: 'CustomContainer'
    scaleConfiguration: {
      maxConcurrentSessions: 10
      // No warm sessions while the placeholder image is set (it would crash-loop on the runner port).
      readySessionInstances: empty(image) ? 0 : 1
    }
    dynamicPoolConfiguration: {
      lifecycleConfiguration: {
        lifecycleType: 'Timed'
        cooldownPeriodInSeconds: 300
      }
    }
    customContainerTemplate: {
      registryCredentials: {
        server: registryServer
        identity: reportIdentityId
      }
      containers: [
        {
          name: 'chart-runner'
          // The placeholder only exists until the postprovision hook has built and set the runner image.
          image: empty(image) ? 'mcr.microsoft.com/k8se/quickstart:latest' : image
          command: ['python', '-m', 'chart_runner', '--port', '8080']
          resources: { cpu: json('0.5'), memory: '1Gi' }
          // No env: the runner holds no secrets (REPORT_AGENT_CANARY lives only in the report agent).
        }
      ]
      ingress: { targetPort: 8080 }
    }
    // ASI05: no outbound network from any session.
    sessionNetworkConfiguration: { status: 'EgressDisabled' }
    // The identity is for the image pull only; its token is never available inside a session.
    managedIdentitySettings: [{ identity: reportIdentityId, lifecycle: 'None' }]
  }
}

resource executor 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(pool.id, reportIdentityId, sessionExecutorRole)
  scope: pool
  properties: {
    principalId: reportIdentityPrincipalId
    principalType: 'ServicePrincipal'
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', sessionExecutorRole)
  }
}

output name string = pool.name
output poolManagementEndpoint string = pool.properties.poolManagementEndpoint
