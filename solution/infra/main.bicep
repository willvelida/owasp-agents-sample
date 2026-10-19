targetScope = 'subscription'

@minLength(1)
@maxLength(64)
@description('azd environment name; the resource group is rg-<name>.')
param environmentName string

@description('Primary location for all resources.')
param location string = 'australiaeast'

@description('Object id of the developer running azd, for local Entra access to Foundry and Cosmos DB.')
param principalId string = ''

@description('Developer principal type.')
@allowed(['User', 'ServicePrincipal'])
param principalType string = 'User'

// Typed non-secret IDs written by the preprovision hook (scripts/provision_agent_id.ps1 -AzdEnvSet). They default to empty
// in main.parameters.json because azd checks inputs before hooks run; minLength makes a missing value fail the deployment.
@minLength(36)
param tenantId string
@minLength(36)
param blueprintAppId string
@minLength(36)
param chatAgentAppId string
@minLength(36)
param healthMcpAppId string
@minLength(36)
param cliAppId string

// azd sets these after the first deploy so re-provisioning keeps the deployed images.
param chatApiExists bool = false
param healthMcpExists bool = false

param modelName string = 'gpt-4.1'
param modelVersion string = '2025-04-14'
param modelCapacity int = 100

var tags = { 'azd-env-name': environmentName }
var resourceToken = toLower(uniqueString(subscription().id, environmentName, location))

resource rg 'Microsoft.Resources/resourceGroups@2024-03-01' = {
  name: 'rg-${environmentName}'
  location: location
  tags: tags
}

module core 'modules/core.bicep' = {
  scope: rg
  name: 'core'
  params: {
    location: location
    tags: tags
    resourceToken: resourceToken
    principalId: principalId
    principalType: principalType
    modelName: modelName
    modelVersion: modelVersion
    modelCapacity: modelCapacity
  }
}

module healthMcp 'modules/health_mcp.bicep' = {
  scope: rg
  name: 'health-mcp'
  params: {
    location: location
    tags: tags
    environmentId: core.outputs.containerAppsEnvironmentId
    environmentDomain: core.outputs.containerAppsEnvironmentDomain
    identityId: core.outputs.managedIdentityId
    identityClientId: core.outputs.managedIdentityClientId
    registryServer: core.outputs.registryLoginServer
    exists: healthMcpExists
    tenantId: tenantId
    healthMcpAppId: healthMcpAppId
    chatAgentAppId: chatAgentAppId
    cosmosEndpoint: core.outputs.cosmosEndpoint
  }
}

module chatApi 'modules/chat_api.bicep' = {
  scope: rg
  name: 'chat-api'
  params: {
    location: location
    tags: tags
    environmentId: core.outputs.containerAppsEnvironmentId
    identityId: core.outputs.managedIdentityId
    identityClientId: core.outputs.managedIdentityClientId
    registryServer: core.outputs.registryLoginServer
    exists: chatApiExists
    tenantId: tenantId
    blueprintAppId: blueprintAppId
    chatAgentAppId: chatAgentAppId
    healthMcpAppId: healthMcpAppId
    cliAppId: cliAppId
    healthMcpUrl: healthMcp.outputs.url
    foundryProjectEndpoint: core.outputs.foundryProjectEndpoint
    modelName: modelName
    cosmosEndpoint: core.outputs.cosmosEndpoint
    appInsightsConnectionString: core.outputs.appInsightsConnectionString
  }
}

output AZURE_LOCATION string = location
output AZURE_TENANT_ID string = tenant().tenantId
output AZURE_RESOURCE_GROUP string = rg.name
output AZURE_CONTAINER_REGISTRY_ENDPOINT string = core.outputs.registryLoginServer
output MANAGED_IDENTITY_PRINCIPAL_ID string = core.outputs.managedIdentityPrincipalId
output MANAGED_IDENTITY_CLIENT_ID string = core.outputs.managedIdentityClientId
output FOUNDRY_PROJECT_ENDPOINT string = core.outputs.foundryProjectEndpoint
output FOUNDRY_MODEL string = modelName
output COSMOS_ENDPOINT string = core.outputs.cosmosEndpoint
output CHAT_API_URL string = chatApi.outputs.url
output HEALTH_MCP_INTERNAL_URL string = healthMcp.outputs.url
