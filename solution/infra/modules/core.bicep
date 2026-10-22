// Shared resources: monitoring, registry, managed identity, Container Apps environment, Cosmos DB, Foundry.

param location string
param tags object
param resourceToken string
param principalId string
param principalType string
param modelName string
param modelVersion string
param modelCapacity int

var roles = {
  acrPull: '7f951dda-4ed3-4680-a7ca-43fe172d538d'
  cognitiveServicesOpenAIUser: '5e0bd9bd-7b93-4f28-af87-19fc36ad61bd'
  azureAIUser: '53ca6127-db72-4b80-b1b0-d745d6d5456d'
}
// Cosmos DB Built-in Data Contributor (data plane).
var cosmosDataContributor = '00000000-0000-0000-0000-000000000002'

resource logs 'Microsoft.OperationalInsights/workspaces@2023-09-01' = {
  name: 'log-${resourceToken}'
  location: location
  tags: tags
  properties: {
    sku: { name: 'PerGB2018' }
    retentionInDays: 30
  }
}

resource appInsights 'Microsoft.Insights/components@2020-02-02' = {
  name: 'appi-${resourceToken}'
  location: location
  tags: tags
  kind: 'web'
  properties: {
    Application_Type: 'web'
    WorkspaceResourceId: logs.id
    DisableLocalAuth: true
  }
}

resource identity 'Microsoft.ManagedIdentity/userAssignedIdentities@2023-01-31' = {
  name: 'id-${resourceToken}'
  location: location
  tags: tags
}

// ASI05: the report agent's own identity (image pull, Foundry, and Session Executor on the chart pool only). It has
// no Cosmos DB access and no federated credential on the Blueprint, so it can never read health data.
resource reportIdentity 'Microsoft.ManagedIdentity/userAssignedIdentities@2023-01-31' = {
  name: 'id-report-${resourceToken}'
  location: location
  tags: tags
}

// ASI03: the browser UI's own identity, used only to pull its image (AcrPull). It has no data-plane roles and no
// federated credential, so the static nginx container never holds credentials it does not need.
resource uiIdentity 'Microsoft.ManagedIdentity/userAssignedIdentities@2023-01-31' = {
  name: 'id-ui-${resourceToken}'
  location: location
  tags: tags
}

resource registry 'Microsoft.ContainerRegistry/registries@2023-07-01' = {
  name: 'cr${resourceToken}'
  location: location
  tags: tags
  sku: { name: 'Basic' }
  properties: {
    adminUserEnabled: false
  }
}

resource acrPull 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(registry.id, identity.id, roles.acrPull)
  scope: registry
  properties: {
    principalId: identity.properties.principalId
    principalType: 'ServicePrincipal'
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', roles.acrPull)
  }
}

resource reportAcrPull 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(registry.id, reportIdentity.id, roles.acrPull)
  scope: registry
  properties: {
    principalId: reportIdentity.properties.principalId
    principalType: 'ServicePrincipal'
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', roles.acrPull)
  }
}

resource uiAcrPull 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(registry.id, uiIdentity.id, roles.acrPull)
  scope: registry
  properties: {
    principalId: uiIdentity.properties.principalId
    principalType: 'ServicePrincipal'
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', roles.acrPull)
  }
}

resource environment 'Microsoft.App/managedEnvironments@2024-03-01' = {
  name: 'cae-${resourceToken}'
  location: location
  tags: tags
  properties: {
    // Workload profiles are required by the Dynamic Sessions custom-container pool (ASI05).
    workloadProfiles: [{ name: 'Consumption', workloadProfileType: 'Consumption' }]
    appLogsConfiguration: {
      destination: 'log-analytics'
      logAnalyticsConfiguration: {
        customerId: logs.properties.customerId
        sharedKey: logs.listKeys().primarySharedKey
      }
    }
  }
}

// ASI03: Entra only. Account keys are disabled, so the services use the managed identity.
resource cosmos 'Microsoft.DocumentDB/databaseAccounts@2024-11-15' = {
  name: 'cosmos-${resourceToken}'
  location: location
  tags: tags
  kind: 'GlobalDocumentDB'
  properties: {
    databaseAccountOfferType: 'Standard'
    disableLocalAuth: true
    capabilities: [{ name: 'EnableServerless' }]
    consistencyPolicy: { defaultConsistencyLevel: 'Session' }
    locations: [{ locationName: location, failoverPriority: 0, isZoneRedundant: false }]
    minimalTlsVersion: 'Tls12'
  }
}

resource database 'Microsoft.DocumentDB/databaseAccounts/sqlDatabases@2024-11-15' = {
  parent: cosmos
  name: 'biotrackr'
  properties: { resource: { id: 'biotrackr' } }
}

resource healthContainer 'Microsoft.DocumentDB/databaseAccounts/sqlDatabases/containers@2024-11-15' = {
  parent: database
  name: 'health'
  properties: {
    resource: {
      id: 'health'
      partitionKey: { paths: ['/userId'], kind: 'Hash' }
    }
  }
}

// ASI06: conversations live in the caller's own partition (every read names the oid) and expire 90 days after their
// last write. Partition keys are immutable, so this replaces the S1 `conversations` container (partition /sessionId).
resource chatHistoryContainer 'Microsoft.DocumentDB/databaseAccounts/sqlDatabases/containers@2024-11-15' = {
  parent: database
  name: 'chat_history'
  properties: {
    resource: {
      id: 'chat_history'
      partitionKey: { paths: ['/userId'], kind: 'Hash' }
      defaultTtl: 7776000
    }
  }
}

// ASI10: hash-chained audit trail written by chat-api, one chain per process.
resource auditContainer 'Microsoft.DocumentDB/databaseAccounts/sqlDatabases/containers@2024-11-15' = {
  parent: database
  name: 'audit'
  properties: {
    resource: {
      id: 'audit'
      partitionKey: { paths: ['/chainId'], kind: 'Hash' }
    }
  }
}

resource cosmosIdentityRole 'Microsoft.DocumentDB/databaseAccounts/sqlRoleAssignments@2024-11-15' = {
  parent: cosmos
  name: guid(cosmos.id, identity.id, cosmosDataContributor)
  properties: {
    principalId: identity.properties.principalId
    roleDefinitionId: '${cosmos.id}/sqlRoleDefinitions/${cosmosDataContributor}'
    scope: cosmos.id
  }
}

resource cosmosDeveloperRole 'Microsoft.DocumentDB/databaseAccounts/sqlRoleAssignments@2024-11-15' = if (!empty(principalId)) {
  parent: cosmos
  name: guid(cosmos.id, principalId, cosmosDataContributor)
  properties: {
    principalId: principalId
    roleDefinitionId: '${cosmos.id}/sqlRoleDefinitions/${cosmosDataContributor}'
    scope: cosmos.id
  }
}

// ASI03: solution Foundry resource with key auth disabled (the starter's model lives elsewhere, with keys).
resource foundry 'Microsoft.CognitiveServices/accounts@2025-06-01' = {
  name: 'aif-${resourceToken}'
  location: location
  tags: tags
  kind: 'AIServices'
  sku: { name: 'S0' }
  identity: { type: 'SystemAssigned' }
  properties: {
    customSubDomainName: 'aif-${resourceToken}'
    allowProjectManagement: true
    disableLocalAuth: true
    publicNetworkAccess: 'Enabled'
  }
}

resource project 'Microsoft.CognitiveServices/accounts/projects@2025-06-01' = {
  parent: foundry
  name: 'biotrackr'
  location: location
  identity: { type: 'SystemAssigned' }
  properties: {
    displayName: 'Biotrackr solution'
  }
}

resource deployment 'Microsoft.CognitiveServices/accounts/deployments@2025-06-01' = {
  parent: foundry
  name: modelName
  sku: { name: 'GlobalStandard', capacity: modelCapacity }
  properties: {
    model: { format: 'OpenAI', name: modelName, version: modelVersion }
  }
  dependsOn: [project]
}

var foundryRoles = [roles.cognitiveServicesOpenAIUser, roles.azureAIUser]

resource foundryIdentityRoles 'Microsoft.Authorization/roleAssignments@2022-04-01' = [
  for role in foundryRoles: {
    name: guid(foundry.id, identity.id, role)
    scope: foundry
    properties: {
      principalId: identity.properties.principalId
      principalType: 'ServicePrincipal'
      roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', role)
    }
  }
]

resource foundryReportRoles 'Microsoft.Authorization/roleAssignments@2022-04-01' = [
  for role in foundryRoles: {
    name: guid(foundry.id, reportIdentity.id, role)
    scope: foundry
    properties: {
      principalId: reportIdentity.properties.principalId
      principalType: 'ServicePrincipal'
      roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', role)
    }
  }
]

resource foundryDeveloperRoles 'Microsoft.Authorization/roleAssignments@2022-04-01' = [
  for role in foundryRoles: if (!empty(principalId)) {
    name: guid(foundry.id, principalId, role)
    scope: foundry
    properties: {
      principalId: principalId
      principalType: principalType
      roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', role)
    }
  }
]

output containerAppsEnvironmentId string = environment.id
output containerAppsEnvironmentDomain string = environment.properties.defaultDomain
output managedIdentityId string = identity.id
output managedIdentityClientId string = identity.properties.clientId
output managedIdentityPrincipalId string = identity.properties.principalId
output reportIdentityId string = reportIdentity.id
output reportIdentityClientId string = reportIdentity.properties.clientId
output reportIdentityPrincipalId string = reportIdentity.properties.principalId
output uiIdentityId string = uiIdentity.id
output registryName string = registry.name
output registryLoginServer string = registry.properties.loginServer
output cosmosEndpoint string = cosmos.properties.documentEndpoint
output foundryProjectEndpoint string = 'https://${foundry.properties.customSubDomainName}.services.ai.azure.com/api/projects/${project.name}'
output appInsightsConnectionString string = appInsights.properties.ConnectionString
